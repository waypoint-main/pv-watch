"""Centralized configuration loading for PV Watch.

All analytical thresholds, capacity assumptions, and scoring weights live in
``config/settings.yaml`` rather than being hard-coded throughout the
application. This module loads that file into small, typed dataclasses so the
rest of the codebase can rely on attribute access (with IDE support and type
checking) instead of dictionary lookups scattered across modules.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"


@dataclass(frozen=True)
class AppMeta:
    name: str = "PV Watch"
    tagline: str = "Distributed Solar Change Intelligence"
    version: str = "0.1.0-mvp"
    observation_year_baseline: int = 2020
    observation_year_latest: int = 2025
    observation_date_baseline: str = "2020-06-30"
    observation_date_latest: str = "2025-06-30"


@dataclass(frozen=True)
class CrsConfig:
    geographic_crs: str = "EPSG:4326"
    default_projected_crs: Optional[str] = None
    fallback_projected_crs: str = "EPSG:32651"


@dataclass(frozen=True)
class InstallationGroupingConfig:
    grouping_distance_m: float = 5.0
    use_parcel_id_when_available: bool = True
    parcel_id_field: str = "parcel_id"


@dataclass(frozen=True)
class ChangeDetectionConfig:
    minimum_iou_match: float = 0.30
    minimum_overlap_ratio: float = 0.50
    maximum_centroid_distance_m: float = 10.0
    stable_area_change_ratio: float = 0.20
    expansion_area_change_ratio: float = 0.30
    grouping_distance_m: float = 5.0
    uncertainty_margin: float = 0.08
    ambiguous_secondary_match_margin: float = 0.10


@dataclass(frozen=True)
class CapacityEstimationConfig:
    kw_per_m2: float = 0.17
    large_system_capacity_kw: float = 15.0


@dataclass(frozen=True)
class AlertEngineConfig:
    weights: dict = field(default_factory=dict)
    large_installation_area_m2: float = 90.0
    cluster_new_installation_count: int = 3
    priority_1_min_score: int = 7
    priority_2_min_score: int = 5
    priority_3_min_score: int = 3


@dataclass(frozen=True)
class RegistryMatchingConfig:
    spatial_match_distance_m: float = 15.0
    probable_match_distance_m: float = 40.0


@dataclass(frozen=True)
class SyntheticDemoConfig:
    seed: int = 42
    baseline_installation_count: int = 34
    latest_installation_count: int = 52
    town_name: str = "Synthetic demo area"
    center_lat: float = 14.2856
    center_lon: float = 121.0997


@dataclass(frozen=True)
class LocalDataSourcesConfig:
    """Optional local folders of real, per-barangay KMZ files.

    When these folders exist, PV Watch can load and merge every ``.kmz`` file
    in them into one baseline/latest inventory automatically — no upload
    step required. Paths are relative to the project root.
    """

    local_kmz_2020_dir: str = "output-kmz/2020"
    local_kmz_2025_dir: str = "output-kmz/2025"
    default_municipality: str = "Santa Rosa, Laguna"
    # Static regional label for the PV Reporting page's province-level rollup.
    # This demo only ever covers a single municipality, so "province level"
    # reporting is illustrated with one province, not fabricated multi-province
    # geodata.
    province: str = "Laguna"


@dataclass(frozen=True)
class AppConfig:
    app: AppMeta
    crs: CrsConfig
    installation_grouping: InstallationGroupingConfig
    change_detection: ChangeDetectionConfig
    capacity_estimation: CapacityEstimationConfig
    alert_engine: AlertEngineConfig
    registry_matching: RegistryMatchingConfig
    synthetic_demo: SyntheticDemoConfig
    data_sources: LocalDataSourcesConfig
    raw: dict = field(default_factory=dict, repr=False)

    def as_flat_dict(self) -> dict[str, Any]:
        """Return a flattened view suitable for display on the methodology page."""
        return self.raw


def _get(d: dict, key: str, default: dict) -> dict:
    value = d.get(key)
    return value if isinstance(value, dict) else default


@functools.lru_cache(maxsize=4)
def load_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load and cache the application configuration from YAML.

    Cached with ``lru_cache`` (keyed by path) rather than
    ``st.cache_resource`` so this module has no Streamlit dependency and can
    be reused from unit tests or future non-Streamlit entry points.
    """
    path = Path(config_path)
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    return AppConfig(
        app=AppMeta(**_get(raw, "app", {})),
        crs=CrsConfig(**_get(raw, "crs", {})),
        installation_grouping=InstallationGroupingConfig(**_get(raw, "installation_grouping", {})),
        change_detection=ChangeDetectionConfig(**_get(raw, "change_detection", {})),
        capacity_estimation=CapacityEstimationConfig(**_get(raw, "capacity_estimation", {})),
        alert_engine=AlertEngineConfig(**_get(raw, "alert_engine", {})),
        registry_matching=RegistryMatchingConfig(**_get(raw, "registry_matching", {})),
        synthetic_demo=SyntheticDemoConfig(**_get(raw, "synthetic_demo", {})),
        data_sources=LocalDataSourcesConfig(**_get(raw, "data_sources", {})),
        raw=raw,
    )
