"""Geometry validation, CRS handling, and area calculation utilities.

Geospatial assumptions made explicit here:

* Area must never be computed in a geographic CRS (e.g. EPSG:4326) because
  degrees are not a unit of length/area. We always reproject to a local
  projected CRS (UTM, meters) before measuring area or distance.
* When no projected CRS is supplied, we pick the UTM zone that contains the
  dataset's centroid. This is a reasonable default for a single town/city
  extent but would need to change for datasets spanning multiple UTM zones.
* Invalid geometries are repaired with a zero-width buffer (``buffer(0)``),
  a standard Shapely trick that fixes many self-intersections. Geometries
  that remain invalid after repair are dropped and reported, not silently
  ignored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import geopandas as gpd
import pyproj
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid

logger = logging.getLogger("pv_watch.geometry_utils")

SUPPORTED_GEOM_TYPES = {"Polygon", "MultiPolygon"}


@dataclass
class GeometryQualityReport:
    """Summary of issues encountered while normalizing a set of geometries."""

    total_input_features: int = 0
    repaired_count: int = 0
    dropped_invalid_count: int = 0
    dropped_empty_count: int = 0
    dropped_unsupported_type_count: int = 0
    dropped_duplicate_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        logger.warning(message)

    @property
    def total_dropped(self) -> int:
        return (
            self.dropped_invalid_count
            + self.dropped_empty_count
            + self.dropped_unsupported_type_count
            + self.dropped_duplicate_count
        )

    @property
    def has_issues(self) -> bool:
        return self.total_dropped > 0 or self.repaired_count > 0


def estimate_utm_crs(gdf: gpd.GeoDataFrame) -> str:
    """Pick an appropriate UTM CRS (meters) from the dataset centroid.

    GeoPandas/PyProj expose ``estimate_utm_crs`` which inspects the data's
    bounding box; we wrap it so callers get a plain EPSG string and a
    guaranteed fallback if estimation fails (e.g. empty GeoDataFrame).
    """
    try:
        crs = gdf.estimate_utm_crs()
        if crs is not None:
            return f"EPSG:{crs.to_epsg()}"
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("UTM auto-estimation failed (%s); using fallback CRS.", exc)
    return "EPSG:32651"  # UTM 51N — covers most of the Philippines


def repair_geometry(geom: Optional[BaseGeometry]) -> tuple[Optional[BaseGeometry], bool]:
    """Attempt to repair an invalid geometry.

    Returns (possibly repaired geometry, was_repaired). Returns (None, False)
    if the geometry cannot be salvaged.
    """
    if geom is None or geom.is_empty:
        return None, False
    if geom.is_valid:
        return geom, False
    try:
        repaired = make_valid(geom)
        if repaired is not None and not repaired.is_empty and repaired.is_valid:
            return repaired, True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("make_valid failed (%s); trying buffer(0).", exc)
    try:
        repaired = geom.buffer(0)
        if repaired is not None and not repaired.is_empty and repaired.is_valid:
            return repaired, True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("buffer(0) repair failed: %s", exc)
    return None, False


def normalize_geometries(
    gdf: gpd.GeoDataFrame, report: Optional[GeometryQualityReport] = None
) -> tuple[gpd.GeoDataFrame, GeometryQualityReport]:
    """Validate, repair, and filter geometries in-place.

    Keeps only Polygon/MultiPolygon features. Repairs invalid geometries
    where possible, drops empty/unsupported/unrepairable ones, and removes
    exact-duplicate geometries (common when a KMZ has overlapping folders).
    Every drop/repair is recorded in the returned :class:`GeometryQualityReport`.
    """
    report = report or GeometryQualityReport()
    report.total_input_features += len(gdf)

    if gdf.empty:
        return gdf, report

    keep_rows = []
    seen_wkb: set[bytes] = set()

    for idx, row in gdf.iterrows():
        geom = row.geometry

        if geom is None or geom.is_empty:
            report.dropped_empty_count += 1
            continue

        geom_type = geom.geom_type
        if geom_type not in SUPPORTED_GEOM_TYPES:
            # Attempt to salvage a GeometryCollection by extracting polygons.
            if geom_type == "GeometryCollection":
                polys = [g for g in geom.geoms if g.geom_type in SUPPORTED_GEOM_TYPES]
                if polys:
                    from shapely.ops import unary_union

                    geom = unary_union(polys)
                    geom_type = geom.geom_type

            if geom_type not in SUPPORTED_GEOM_TYPES:
                report.dropped_unsupported_type_count += 1
                report.add_warning(
                    f"Record {row.get('observation_id', idx)} has unsupported geometry "
                    f"type '{geom_type}' and was skipped."
                )
                continue

        if not geom.is_valid:
            repaired, was_repaired = repair_geometry(geom)
            if repaired is None:
                report.dropped_invalid_count += 1
                report.add_warning(
                    f"Record {row.get('observation_id', idx)} has an invalid geometry "
                    f"that could not be repaired and was skipped."
                )
                continue
            if was_repaired:
                report.repaired_count += 1
            geom = repaired

        if geom is None or geom.is_empty:
            report.dropped_empty_count += 1
            continue

        wkb = geom.wkb
        if wkb in seen_wkb:
            report.dropped_duplicate_count += 1
            continue
        seen_wkb.add(wkb)

        row = row.copy()
        row.geometry = geom
        keep_rows.append(row)

    if not keep_rows:
        cleaned = gdf.iloc[0:0].copy()
    else:
        cleaned = gpd.GeoDataFrame(keep_rows, columns=gdf.columns, crs=gdf.crs)

    return cleaned, report


def to_projected(gdf: gpd.GeoDataFrame, projected_crs: Optional[str] = None) -> tuple[gpd.GeoDataFrame, str]:
    """Reproject a GeoDataFrame to a projected (meters) CRS for measurement.

    If ``projected_crs`` is not supplied, a UTM zone is auto-selected from
    the data's centroid and returned alongside the reprojected frame so the
    caller can display which CRS was chosen.
    """
    if gdf.crs is None:
        logger.warning("Input GeoDataFrame has no CRS; assuming EPSG:4326 (WGS84).")
        gdf = gdf.set_crs("EPSG:4326")

    crs = projected_crs or estimate_utm_crs(gdf)
    projected = gdf.to_crs(crs)
    return projected, crs


def compute_area_m2(gdf: gpd.GeoDataFrame, projected_crs: Optional[str] = None) -> tuple[gpd.GeoDataFrame, str]:
    """Compute polygon area in square meters using a projected CRS.

    Never computes area directly on geographic (lat/lon) coordinates. Returns
    the original GeoDataFrame (in its original CRS) with an ``area_m2`` column
    added, plus the projected CRS string that was used for the calculation.
    """
    projected, crs_used = to_projected(gdf, projected_crs)
    areas = projected.geometry.area
    result = gdf.copy()
    result["area_m2"] = areas.values
    return result, crs_used


def reproject_to_geographic(gdf: gpd.GeoDataFrame, geographic_crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    """Reproject to the geographic CRS used for map display and export."""
    if gdf.crs is None:
        return gdf.set_crs(geographic_crs)
    if str(gdf.crs).upper() != geographic_crs.upper():
        return gdf.to_crs(geographic_crs)
    return gdf


def centroid_distance_m(geom_a: BaseGeometry, geom_b: BaseGeometry) -> float:
    """Euclidean centroid distance; geometries must already be in a projected CRS."""
    return geom_a.centroid.distance(geom_b.centroid)


def safe_crs_string(crs: pyproj.CRS | str | None) -> str:
    if crs is None:
        return "unknown"
    if isinstance(crs, str):
        return crs
    try:
        epsg = crs.to_epsg()
        return f"EPSG:{epsg}" if epsg else str(crs)
    except Exception:  # pragma: no cover - defensive
        return str(crs)
