"""Group individual PV array polygons into PV installations (sites).

A single rooftop or property may have several separate panel-array polygons
digitized on it (e.g. two arrays on different roof planes). For change
detection and alerting, the more useful unit is usually the *installation*
(one PV system / one site) rather than the raw array polygon.

IMPORTANT — this is a heuristic, not ground truth
--------------------------------------------------
Without authoritative building footprints or parcel boundaries, grouping
nearby array polygons into one installation is inherently approximate. It can:

* Over-merge: two genuinely separate customers' rooftops that happen to sit
  close together could be merged into a single "installation".
* Under-merge: a single customer's arrays spread across a roof in a way the
  proximity threshold does not capture could be split into multiple
  "installations".

When a ``parcel_id`` (or building ID) attribute IS available on the source
data, it takes priority over pure distance-based grouping, since it reflects
an actual property boundary rather than a guessed one. Grouped results should
always be treated as a starting point for human review, not a final
determination of "how many PV systems" exist at a location.
"""

from __future__ import annotations

import logging
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from src.config import AppConfig
from src.geometry_utils import to_projected

logger = logging.getLogger("pv_watch.installation_grouping")

_CONFIDENCE_ORDER = {"Low": 0, "Not recorded": 0, "Medium": 1, "High": 2}


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _most_conservative_confidence(values: list[str]) -> str:
    """Return the lowest (most cautious) confidence among grouped members."""
    cleaned = [v if v in _CONFIDENCE_ORDER else "Not recorded" for v in values]
    return min(cleaned, key=lambda v: _CONFIDENCE_ORDER[v])


def group_into_installations(
    observations: gpd.GeoDataFrame,
    source_year: int,
    config: AppConfig,
    projected_crs: Optional[str] = None,
) -> tuple[gpd.GeoDataFrame, str]:
    """Merge nearby/related array polygons into installation-level records.

    Returns (installations_gdf, projected_crs_used). ``installations_gdf`` is
    in the same geographic CRS as the input (EPSG:4326 by convention), with
    ``area_m2`` computed on the merged geometry in the projected CRS.
    """
    if observations.empty:
        empty = observations.iloc[0:0].copy()
        for col in ["installation_id", "array_count", "member_observation_ids"]:
            empty[col] = pd.Series(dtype=object)
        return empty, projected_crs or "EPSG:32651"

    projected, crs_used = to_projected(observations, projected_crs)
    projected = projected.reset_index(drop=True)
    n = len(projected)
    uf = _UnionFind(n)

    grouping_distance = config.installation_grouping.grouping_distance_m
    use_parcel = config.installation_grouping.use_parcel_id_when_available
    parcel_col = config.installation_grouping.parcel_id_field if config.installation_grouping.parcel_id_field in projected.columns else "parcel_id"

    # Proximity-based grouping via spatial index: buffer each geometry by the
    # grouping distance and find intersecting neighbors (equivalent to
    # "distance <= grouping_distance_m" without an O(n^2) distance matrix).
    buffered = projected.geometry.buffer(grouping_distance)
    sindex = gpd.GeoSeries(buffered, crs=projected.crs).sindex
    for i, geom in enumerate(buffered):
        candidate_idx = list(sindex.query(geom, predicate="intersects"))
        for j in candidate_idx:
            if j > i:
                uf.union(i, j)

    # Parcel/building-ID-based grouping takes priority when available.
    if use_parcel and parcel_col in projected.columns:
        parcel_groups: dict[str, list[int]] = {}
        for i, val in enumerate(projected[parcel_col]):
            if val is not None and str(val).strip():
                parcel_groups.setdefault(str(val), []).append(i)
        for idxs in parcel_groups.values():
            for k in idxs[1:]:
                uf.union(idxs[0], k)

    components: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        components.setdefault(root, []).append(i)

    records = []
    for comp_idx, members in enumerate(components.values()):
        member_rows = projected.iloc[members]
        merged_geom_proj = unary_union(member_rows.geometry.values)
        area_m2 = merged_geom_proj.area

        confidences = member_rows.get("annotation_confidence", pd.Series(["Not recorded"] * len(members))).tolist()
        parcel_vals = set(v for v in member_rows.get(parcel_col, pd.Series([None] * len(members))).tolist() if v)
        obs_ids = member_rows.get("observation_id", pd.Series([f"row{k}" for k in members])).astype(str).tolist()
        raw_names = member_rows.get("raw_name", pd.Series([None] * len(members))).tolist()

        record = {
            "installation_id": f"INST-{source_year}-{comp_idx:05d}",
            "source_year": source_year,
            "array_count": len(members),
            "member_observation_ids": ",".join(obs_ids),
            "member_raw_names": ",".join([str(r) for r in raw_names if r]),
            "parcel_id": next(iter(parcel_vals)) if len(parcel_vals) == 1 else (None if not parcel_vals else "MULTIPLE"),
            "annotation_confidence": _most_conservative_confidence(confidences),
            "area_m2": area_m2,
            "_geom_projected": merged_geom_proj,
        }
        # Carry through a real, filename/attribute-derived barangay/municipality
        # when the source data provided one (e.g. a local per-barangay KMZ
        # folder) — more accurate than a synthetic spatial-zone join, and the
        # pipeline uses it directly instead of that join when present.
        for zone_col in ("barangay", "municipality"):
            if zone_col in member_rows.columns:
                vals = [v for v in member_rows[zone_col].tolist() if v]
                record[zone_col] = vals[0] if vals else None
        records.append(record)

    result_proj = gpd.GeoDataFrame(records, geometry="_geom_projected", crs=crs_used).rename_geometry("geometry")
    result = result_proj.to_crs(observations.crs or "EPSG:4326")

    multi_array_installations = sum(1 for r in records if r["array_count"] > 1)
    if multi_array_installations:
        logger.info(
            "Grouped %d array polygon(s) into %d installation(s) for year %s (%d installations have >1 array).",
            n,
            len(records),
            source_year,
            multi_array_installations,
        )

    return result, crs_used
