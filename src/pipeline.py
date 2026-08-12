"""End-to-end orchestration: raw inventories -> alerts, cached for Streamlit.

Every page calls :func:`run_pipeline` (via :func:`get_pipeline_result`), which
is wrapped in ``st.cache_data`` so expensive spatial operations (geometry
normalization, installation grouping, change detection, registry/network
joins) only re-run when the *inputs* actually change — not on every UI filter
interaction. Pages then filter/aggregate the already-computed tables, which
is cheap.

This module intentionally contains no Streamlit *widgets* — only data
orchestration — so it stays testable and reusable outside the UI layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import streamlit as st

from src import alert_engine, change_detection, installation_grouping, network_context, registry_matching, synthetic_data
from src.capacity_estimation import add_estimated_capacity
from src.config import AppConfig, load_config
from src.data_loader import (
    KmzLoadError,
    LoadResult,
    finalize_raw_observations,
    load_kmz_folder_observations,
    load_kmz_observations,
)
from src.geometry_utils import GeometryQualityReport, estimate_utm_crs
from src.models import ChangeType


@dataclass
class PipelineWarnings:
    baseline: list[str] = field(default_factory=list)
    latest: list[str] = field(default_factory=list)

    @property
    def has_any(self) -> bool:
        return bool(self.baseline or self.latest)


@dataclass
class PipelineResult:
    is_synthetic: bool
    observations_2020: gpd.GeoDataFrame
    observations_2025: gpd.GeoDataFrame
    installations_2020: gpd.GeoDataFrame
    installations_2025: gpd.GeoDataFrame
    change_df: pd.DataFrame
    registry_df: pd.DataFrame
    registry_match_df: pd.DataFrame
    transformers: gpd.GeoDataFrame
    feeders: gpd.GeoDataFrame
    zones: gpd.GeoDataFrame
    transformer_summary: pd.DataFrame
    alerts_df: pd.DataFrame
    warnings: PipelineWarnings
    projected_crs_used: str
    center_lat: float
    center_lon: float


def _center_from_zones(config: AppConfig) -> tuple[float, float]:
    return config.synthetic_demo.center_lat, config.synthetic_demo.center_lon


def _apply_admin_zone(installations: gpd.GeoDataFrame, zones: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Assign municipality/barangay, preferring a real source attribute.

    If installation_grouping already carried through a real ``barangay``
    value (present on most rows), keep it as-is. Otherwise fall back to the
    synthetic spatial-zone join used for the demo dataset and generic
    uploads with no admin-boundary attribute of their own.
    """
    if installations.empty:
        return synthetic_data.assign_admin_zone(installations, zones)

    has_real_barangay = "barangay" in installations.columns and installations["barangay"].notna().mean() > 0.5
    if has_real_barangay:
        result = installations.copy()
        result["barangay"] = result["barangay"].fillna("Unclassified area")
        if "municipality" not in result.columns:
            result["municipality"] = "Unclassified area"
        else:
            result["municipality"] = result["municipality"].fillna("Unclassified area")
        return result

    return synthetic_data.assign_admin_zone(installations, zones)


def _build_from_observations(
    gdf_2020: gpd.GeoDataFrame,
    gdf_2025: gpd.GeoDataFrame,
    config: AppConfig,
    is_synthetic: bool,
    projected_crs_override: Optional[str],
    warnings: PipelineWarnings,
) -> PipelineResult:
    """Shared tail of the pipeline once both years' raw observations exist."""
    combined = gpd.GeoDataFrame(
        pd.concat(
            [g[["geometry"]] for g in (gdf_2020, gdf_2025) if not g.empty],
            ignore_index=True,
        ),
        crs="EPSG:4326",
    ) if not (gdf_2020.empty and gdf_2025.empty) else gpd.GeoDataFrame({"geometry": []}, crs="EPSG:4326")

    shared_crs = projected_crs_override or (estimate_utm_crs(combined) if not combined.empty else "EPSG:32651")

    installations_2020, _ = installation_grouping.group_into_installations(gdf_2020, 2020, config, shared_crs)
    installations_2025, _ = installation_grouping.group_into_installations(gdf_2025, 2025, config, shared_crs)

    installations_2020 = add_estimated_capacity(installations_2020, "area_m2", config.capacity_estimation)
    installations_2025 = add_estimated_capacity(installations_2025, "area_m2", config.capacity_estimation)

    zones = synthetic_data.generate_admin_zones(config)
    # When the source data already carries a real, filename/attribute-derived
    # barangay (e.g. loaded from a local per-barangay KMZ folder), use it
    # directly instead of the synthetic spatial-zone join, which is only a
    # stand-in for datasets with no real admin-boundary attribute at all.
    installations_2020 = _apply_admin_zone(installations_2020, zones)
    installations_2025 = _apply_admin_zone(installations_2025, zones)

    transformers, feeders = synthetic_data.generate_transformers_and_feeders(config)
    installations_2020 = network_context.assign_transformer_context(installations_2020, transformers)
    installations_2025 = network_context.assign_transformer_context(installations_2025, transformers)

    change_df = change_detection.classify_changes(installations_2020, installations_2025, config.change_detection, shared_crs)

    registry_raw = synthetic_data.generate_synthetic_registry(config, installations_2025)
    registry_gdf = registry_matching.attach_synthetic_registry_geometry(registry_raw, installations_2025)
    registry_match_df = registry_matching.match_installations_to_registry(
        installations_2025, registry_gdf, config.registry_matching, capacity_col="estimated_capacity_kw"
    )
    registry_clean = registry_raw.drop(columns=[c for c in ["_offset_m", "_near_installation_id"] if c in registry_raw.columns])

    installations_2025_full = installations_2025.merge(
        registry_match_df.drop(columns=["installation_id"]).set_index(registry_match_df["installation_id"]),
        left_on="installation_id",
        right_index=True,
        how="left",
    ) if not installations_2025.empty else installations_2025

    # Every 2025 installation has exactly one change_df row (its own change_type);
    # carry it onto the installation table so downstream aggregation (grid-planning
    # transformer summaries) can group by change_type without a separate join.
    if not installations_2025_full.empty and not change_df.empty:
        change_type_by_2025_id = (
            change_df.dropna(subset=["installation_id_2025"])
            .drop_duplicates(subset=["installation_id_2025"])
            .set_index("installation_id_2025")["change_type"]
        )
        installations_2025_full = installations_2025_full.merge(
            change_type_by_2025_id.rename("change_type"),
            left_on="installation_id",
            right_index=True,
            how="left",
        )
        installations_2025_full["change_type"] = installations_2025_full["change_type"].fillna(ChangeType.EXISTING.value)
    else:
        installations_2025_full["change_type"] = ChangeType.EXISTING.value

    transformer_summary_pass1 = network_context.compute_transformer_summary(installations_2025_full, transformers, alerts=None)

    alerts_df = alert_engine.generate_alerts(
        change_df,
        installations_2025_full,
        installations_2020,
        registry_match_df,
        transformer_summary_pass1,
        config.alert_engine,
        config.capacity_estimation,
    )

    transformer_summary = network_context.compute_transformer_summary(installations_2025_full, transformers, alerts=alerts_df)

    center_lat, center_lon = _center_from_zones(config)
    if not combined.empty:
        c = combined.geometry.unary_union.centroid
        center_lat, center_lon = c.y, c.x

    return PipelineResult(
        is_synthetic=is_synthetic,
        observations_2020=gdf_2020,
        observations_2025=gdf_2025,
        installations_2020=installations_2020,
        installations_2025=installations_2025_full,
        change_df=change_df,
        registry_df=registry_clean,
        registry_match_df=registry_match_df,
        transformers=transformers,
        feeders=feeders,
        zones=zones,
        transformer_summary=transformer_summary,
        alerts_df=alerts_df,
        warnings=warnings,
        projected_crs_used=shared_crs,
        center_lat=center_lat,
        center_lon=center_lon,
    )


def _run_pipeline_uncached(
    mode: str,
    kmz_2020_bytes: Optional[bytes],
    kmz_2025_bytes: Optional[bytes],
    filename_2020: str,
    filename_2025: str,
    projected_crs_override: Optional[str],
    config_path: str,
) -> PipelineResult:
    config = load_config(config_path)
    warnings = PipelineWarnings()

    if mode == "demo":
        gdf_2020_raw, gdf_2025_raw = synthetic_data.generate_raw_observations(config)
        gdf_2020, crs_2020, q2020 = finalize_raw_observations(
            gdf_2020_raw,
            config.app.observation_year_baseline,
            config.app.observation_date_baseline,
            "Synthetic demo imagery (2020 baseline annotation)",
            projected_crs_override,
        )
        gdf_2025, crs_2025, q2025 = finalize_raw_observations(
            gdf_2025_raw,
            config.app.observation_year_latest,
            config.app.observation_date_latest,
            "Synthetic demo imagery (2025 latest annotation)",
            projected_crs_override,
        )
        warnings.baseline = q2020.warnings
        warnings.latest = q2025.warnings
        return _build_from_observations(gdf_2020, gdf_2025, config, True, projected_crs_override, warnings)

    if mode == "local_folder":
        project_root = Path(__file__).resolve().parent.parent
        dir_2020 = project_root / config.data_sources.local_kmz_2020_dir
        dir_2025 = project_root / config.data_sources.local_kmz_2025_dir

        result_2020: LoadResult = load_kmz_folder_observations(
            dir_2020,
            config.app.observation_year_baseline,
            config.app.observation_date_baseline,
            "Local KMZ folder (2020 baseline annotation)",
            config.data_sources.default_municipality,
            projected_crs_override,
        )
        result_2025: LoadResult = load_kmz_folder_observations(
            dir_2025,
            config.app.observation_year_latest,
            config.app.observation_date_latest,
            "Local KMZ folder (2025 latest annotation)",
            config.data_sources.default_municipality,
            projected_crs_override,
        )
        warnings.baseline = result_2020.quality.warnings
        warnings.latest = result_2025.quality.warnings
        return _build_from_observations(
            result_2020.gdf, result_2025.gdf, config, False, projected_crs_override, warnings
        )

    if mode == "upload":
        if not kmz_2020_bytes or not kmz_2025_bytes:
            raise KmzLoadError("Both a 2020 and a 2025 KMZ file are required to run the comparison.")

        result_2020: LoadResult = load_kmz_observations(
            kmz_2020_bytes,
            config.app.observation_year_baseline,
            config.app.observation_date_baseline,
            "Uploaded KMZ (2020 baseline annotation)",
            config,
            filename_2020,
            projected_crs_override,
        )
        result_2025: LoadResult = load_kmz_observations(
            kmz_2025_bytes,
            config.app.observation_year_latest,
            config.app.observation_date_latest,
            "Uploaded KMZ (2025 latest annotation)",
            config,
            filename_2025,
            projected_crs_override,
        )
        warnings.baseline = result_2020.quality.warnings
        warnings.latest = result_2025.quality.warnings
        return _build_from_observations(
            result_2020.gdf, result_2025.gdf, config, False, projected_crs_override, warnings
        )

    raise ValueError(f"Unknown pipeline mode: {mode}")


@st.cache_data(show_spinner="Running the Solance analysis pipeline (geometry, grouping, change detection, alerts)...")
def run_pipeline(
    mode: str,
    kmz_2020_bytes: Optional[bytes],
    kmz_2025_bytes: Optional[bytes],
    filename_2020: str = "",
    filename_2025: str = "",
    projected_crs_override: Optional[str] = None,
    config_path: str = "config/settings.yaml",
) -> PipelineResult:
    """Cached pipeline entry point. See ``_run_pipeline_uncached`` for logic."""
    return _run_pipeline_uncached(
        mode, kmz_2020_bytes, kmz_2025_bytes, filename_2020, filename_2025, projected_crs_override, config_path
    )


def build_explorer_table(result: PipelineResult, alerts_df: Optional[pd.DataFrame] = None) -> gpd.GeoDataFrame:
    """Build one unified, map-ready table covering every change case.

    Each row represents one change record, carrying whichever geometry is
    "current" for display (the 2025 installation geometry when one exists,
    otherwise the 2020 geometry for a potentially-removed case), plus
    registry match status, network context, and alert priority/review
    status when an alert was generated for that case. Used by the PV Change
    Explorer and Alert Inbox pages so filtering logic only needs to be
    written once.

    Pass a live, review-decision-overlaid ``alerts_df`` (e.g. from
    ``src.review_store.apply_decisions_to_alerts``) to reflect in-session
    reviewer actions; defaults to the pipeline's cached alerts otherwise.
    """
    alerts_df = alerts_df if alerts_df is not None else result.alerts_df
    change_df = result.change_df
    if change_df.empty:
        return gpd.GeoDataFrame(columns=["change_id", "geometry"], geometry="geometry", crs="EPSG:4326")

    # change_df's own change_type is authoritative here (and covers the
    # 2020-only "potentially removed" rows installations_2025 has no opinion
    # on); drop any change_type already carried on the installation tables
    # so the merge doesn't produce change_type_x/change_type_y.
    installations_2025_for_merge = result.installations_2025.drop(columns=["change_type"], errors="ignore")
    installations_2020_for_merge = result.installations_2020.drop(columns=["change_type"], errors="ignore")

    has_2025 = change_df["installation_id_2025"].notna()
    rows_2025 = change_df[has_2025].merge(
        installations_2025_for_merge, left_on="installation_id_2025", right_on="installation_id", how="left"
    )
    rows_2020_only = change_df[~has_2025].merge(
        installations_2020_for_merge, left_on="installation_id_2020", right_on="installation_id", how="left"
    )
    combined = pd.concat([rows_2025, rows_2020_only], ignore_index=True, sort=False)
    combined["display_installation_id"] = combined["installation_id_2025"].fillna(combined["installation_id_2020"])

    alerts_slim = alerts_df[
        ["change_id", "alert_id", "priority", "priority_reason", "priority_score", "review_status", "assigned_to", "reviewer_notes"]
    ] if not alerts_df.empty else pd.DataFrame(
        columns=["change_id", "alert_id", "priority", "priority_reason", "priority_score", "review_status", "assigned_to", "reviewer_notes"]
    )
    combined = combined.merge(alerts_slim, on="change_id", how="left")
    combined["priority"] = combined["priority"].fillna("No alert generated")
    combined["review_status"] = combined["review_status"].fillna("No alert generated")
    if "registry_match_status" not in combined.columns:
        combined["registry_match_status"] = "Not applicable (2020-only record)"
    else:
        combined["registry_match_status"] = combined["registry_match_status"].fillna("Not applicable (2020-only record)")

    return gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:4326")


def get_pipeline_result() -> Optional[PipelineResult]:
    """Fetch the pipeline result for the mode/files currently in session state.

    Every page calls this at the top so navigating directly to any page (not
    just the landing page) still produces a consistent, cached result.
    """
    mode = st.session_state.get("pv_watch_mode", "demo")
    kmz_2020 = st.session_state.get("pv_watch_kmz_2020_bytes")
    kmz_2025 = st.session_state.get("pv_watch_kmz_2025_bytes")
    name_2020 = st.session_state.get("pv_watch_kmz_2020_name", "")
    name_2025 = st.session_state.get("pv_watch_kmz_2025_name", "")
    crs_override = st.session_state.get("pv_watch_crs_override")

    if mode == "upload" and (not kmz_2020 or not kmz_2025):
        return None

    try:
        return run_pipeline(mode, kmz_2020, kmz_2025, name_2020, name_2025, crs_override)
    except KmzLoadError as exc:
        st.error(f"Could not process the uploaded KMZ file(s): {exc}")
        return None
