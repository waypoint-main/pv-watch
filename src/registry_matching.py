"""Compare observed PV installations against a (synthetic) utility registry.

The matching logic here is purely spatial-proximity based and is agnostic to
where the registry data came from — it does not depend on any "ground truth"
hints baked into the synthetic generator. This keeps the logic testable and
reusable if a real utility registry (with real customer coordinates) is
substituted later.

Matching rule (transparent, distance-based):

1. Build the set of registry points within ``probable_match_distance_m`` of
   an installation's centroid.
2. If none exist -> "No registry match".
3. If the closest candidate is within ``spatial_match_distance_m`` AND is
   unambiguously the closest registry point to this installation (and this
   installation is the closest installation to that registry point) -> a
   confident match, refined into "Exact match", "Registration pending",
   "Off-grid / non-exporting", or the capacity-discrepancy variant based on
   the registry record's own fields.
4. If the closest candidate is within ``probable_match_distance_m`` but
   farther than the exact-match distance -> "Probable match".
5. If two candidates are nearly equidistant (within a small margin), or a
   registry point is the closest candidate for more than one installation
   -> "Ambiguous match" (requires human review either way).

All results are clearly synthetic/demo data and must be labeled as such in
the UI — this module makes no claim about real registration status.
"""

from __future__ import annotations

from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from src.config import RegistryMatchingConfig
from src.models import RegistryMatchStatus

AMBIGUOUS_DISTANCE_MARGIN_M = 5.0
CAPACITY_DISCREPANCY_RATIO = 0.7


def offset_point_north(point, offset_m: float):
    """Shift a lon/lat Point north/south by ``offset_m`` meters (small-area approx).

    Used only to place synthetic registry records near a synthetic
    installation for demonstration purposes.
    """
    lat_deg_per_m = 1 / 111_320.0
    return type(point)(point.x, point.y + offset_m * lat_deg_per_m)


def attach_synthetic_registry_geometry(
    registry_df: pd.DataFrame, installations_2025: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """Give each synthetic registry row a plausible point location.

    Rows with an explicit ``installation_id`` are placed at that
    installation's centroid. Rows with a ``_near_installation_id`` +
    ``_offset_m`` hint (representing a nearby-but-not-exact self-reported
    address) are placed at an offset from that installation's centroid.
    Rows with neither are dropped (they carry no usable location).
    """
    if registry_df.empty:
        return gpd.GeoDataFrame(registry_df, geometry=gpd.GeoSeries([], dtype="geometry"), crs="EPSG:4326")

    centroid_by_id = {row["installation_id"]: row.geometry.centroid for _, row in installations_2025.iterrows()}

    geoms = []
    keep_mask = []
    for _, row in registry_df.iterrows():
        inst_id = row.get("installation_id")
        near_id = row.get("_near_installation_id")
        offset_m = row.get("_offset_m", 0.0) or 0.0
        if inst_id and inst_id in centroid_by_id:
            geoms.append(centroid_by_id[inst_id])
            keep_mask.append(True)
        elif near_id and near_id in centroid_by_id:
            geoms.append(offset_point_north(centroid_by_id[near_id], offset_m))
            keep_mask.append(True)
        else:
            geoms.append(None)
            keep_mask.append(False)

    result = registry_df.loc[keep_mask].copy()
    result_geoms = [g for g, k in zip(geoms, keep_mask) if k]
    gdf = gpd.GeoDataFrame(result, geometry=result_geoms, crs="EPSG:4326")
    return gdf.drop(columns=[c for c in ["_offset_m", "_near_installation_id"] if c in gdf.columns])


def match_installations_to_registry(
    installations: gpd.GeoDataFrame,
    registry: gpd.GeoDataFrame,
    config: RegistryMatchingConfig,
    capacity_col: str = "estimated_capacity_kw",
) -> pd.DataFrame:
    """Return one row per installation describing its registry match outcome."""
    if installations.empty:
        return pd.DataFrame(
            columns=[
                "installation_id", "registry_match_status", "registry_id", "customer_reference",
                "registered_capacity_kw", "application_status", "net_metering_status", "meter_status",
                "commissioning_date", "capacity_discrepancy_kw",
            ]
        )

    installs = installations.reset_index(drop=True)

    if registry.empty:
        return pd.DataFrame(
            [
                {
                    "installation_id": row["installation_id"],
                    "registry_match_status": RegistryMatchStatus.NO_MATCH.value,
                    "registry_id": None,
                    "customer_reference": None,
                    "registered_capacity_kw": None,
                    "application_status": None,
                    "net_metering_status": None,
                    "meter_status": None,
                    "commissioning_date": None,
                    "capacity_discrepancy_kw": None,
                }
                for _, row in installs.iterrows()
            ]
        )

    reg = registry.reset_index(drop=True)

    # Project both layers to meters for accurate distance thresholds.
    from src.geometry_utils import estimate_utm_crs

    combined_for_crs = gpd.GeoDataFrame(
        pd.concat([installs[["geometry"]], reg[["geometry"]]], ignore_index=True), crs="EPSG:4326"
    )
    utm = estimate_utm_crs(combined_for_crs)
    # Reproject full geometries to meters *before* taking centroids (more
    # accurate than centroiding in degrees), then use the projected centroid.
    installs_utm_full = installs.to_crs(utm)
    installs_proj = installs.set_geometry(installs_utm_full.geometry.centroid, crs=utm)
    reg_proj = reg.to_crs(utm)

    n_inst, n_reg = len(installs_proj), len(reg_proj)
    # Small-scale distance matrix (demo-sized data); for larger deployments
    # this should be replaced with a KD-tree / sjoin_nearest-based approach.
    dist_matrix = np.zeros((n_inst, n_reg))
    inst_coords = np.array([(g.x, g.y) for g in installs_proj.geometry])
    reg_coords = np.array([(g.x, g.y) for g in reg_proj.geometry])
    for i in range(n_inst):
        dist_matrix[i, :] = np.sqrt(((reg_coords - inst_coords[i]) ** 2).sum(axis=1))

    closest_reg_for_inst = dist_matrix.argmin(axis=1) if n_reg > 0 else np.array([])
    closest_inst_for_reg = dist_matrix.argmin(axis=0) if n_inst > 0 else np.array([])

    results = []
    for i in range(n_inst):
        inst_row = installs.iloc[i]
        est_capacity = inst_row.get(capacity_col, 0.0) or 0.0
        distances = dist_matrix[i, :]
        within_probable = np.where(distances <= config.probable_match_distance_m)[0]

        if len(within_probable) == 0:
            results.append(_no_match_row(inst_row))
            continue

        order = within_probable[np.argsort(distances[within_probable])]
        best_j = order[0]
        best_dist = distances[best_j]
        second_dist = distances[order[1]] if len(order) > 1 else None

        reciprocal_ok = closest_inst_for_reg[best_j] == i
        locally_ambiguous = second_dist is not None and (second_dist - best_dist) <= AMBIGUOUS_DISTANCE_MARGIN_M

        if not reciprocal_ok or locally_ambiguous:
            results.append(_status_row(inst_row, reg.iloc[best_j], RegistryMatchStatus.AMBIGUOUS, est_capacity))
            continue

        reg_row = reg.iloc[best_j]
        if best_dist <= config.spatial_match_distance_m:
            status = _refine_confident_status(reg_row, est_capacity)
        else:
            status = RegistryMatchStatus.PROBABLE_MATCH

        results.append(_status_row(inst_row, reg_row, status, est_capacity))

    return pd.DataFrame(results)


def _refine_confident_status(reg_row: pd.Series, est_capacity: float) -> RegistryMatchStatus:
    app_status = str(reg_row.get("application_status", "")).lower()
    net_status = str(reg_row.get("net_metering_status", "")).lower()
    registered_kw = reg_row.get("registered_capacity_kw") or 0.0

    if "pending" in app_status:
        return RegistryMatchStatus.PENDING
    if "off-grid" in net_status or "non-exporting" in net_status:
        return RegistryMatchStatus.OFF_GRID
    if est_capacity > 0 and registered_kw < est_capacity * CAPACITY_DISCREPANCY_RATIO:
        return RegistryMatchStatus.CAPACITY_DISCREPANCY
    return RegistryMatchStatus.EXACT_MATCH


def _no_match_row(inst_row: pd.Series) -> dict:
    return {
        "installation_id": inst_row["installation_id"],
        "registry_match_status": RegistryMatchStatus.NO_MATCH.value,
        "registry_id": None,
        "customer_reference": None,
        "registered_capacity_kw": None,
        "application_status": None,
        "net_metering_status": None,
        "meter_status": None,
        "commissioning_date": None,
        "capacity_discrepancy_kw": None,
    }


def _status_row(inst_row: pd.Series, reg_row: pd.Series, status: RegistryMatchStatus, est_capacity: float) -> dict:
    registered_kw = reg_row.get("registered_capacity_kw")
    discrepancy = (registered_kw - est_capacity) if registered_kw is not None else None
    return {
        "installation_id": inst_row["installation_id"],
        "registry_match_status": status.value,
        "registry_id": reg_row.get("registry_id"),
        "customer_reference": reg_row.get("customer_reference"),
        "registered_capacity_kw": registered_kw,
        "application_status": reg_row.get("application_status"),
        "net_metering_status": reg_row.get("net_metering_status"),
        "meter_status": reg_row.get("meter_status"),
        "commissioning_date": reg_row.get("commissioning_date"),
        "capacity_discrepancy_kw": round(discrepancy, 2) if discrepancy is not None else None,
    }
