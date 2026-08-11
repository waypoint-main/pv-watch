"""Unit tests for the (heuristic) installation-grouping logic."""

from __future__ import annotations

import geopandas as gpd

from src.config import InstallationGroupingConfig, AppConfig, AppMeta, CrsConfig, ChangeDetectionConfig, \
    CapacityEstimationConfig, AlertEngineConfig, RegistryMatchingConfig, SyntheticDemoConfig
from src.installation_grouping import group_into_installations

from tests.geo_helpers import box_m


def _config(grouping_distance_m: float = 5.0, use_parcel_id: bool = True) -> AppConfig:
    return AppConfig(
        app=AppMeta(),
        crs=CrsConfig(),
        installation_grouping=InstallationGroupingConfig(
            grouping_distance_m=grouping_distance_m, use_parcel_id_when_available=use_parcel_id
        ),
        change_detection=ChangeDetectionConfig(),
        capacity_estimation=CapacityEstimationConfig(),
        alert_engine=AlertEngineConfig(weights={}),
        registry_matching=RegistryMatchingConfig(),
        synthetic_demo=SyntheticDemoConfig(),
    )


def _observations(rows: list[dict]) -> gpd.GeoDataFrame:
    defaults = {"annotation_confidence": "High", "parcel_id": None, "raw_name": None, "observation_id": None}
    return gpd.GeoDataFrame([{**defaults, **r} for r in rows], geometry="geometry", crs="EPSG:4326")


def test_nearby_arrays_are_merged_into_one_installation():
    # Two small arrays 2 m apart on the same "roof" -> should merge (grouping distance 5 m).
    obs = _observations(
        [
            {"observation_id": "OBS-1", "geometry": box_m(0, 0, 4, 4)},
            {"observation_id": "OBS-2", "geometry": box_m(6, 0, 10, 4)},
        ]
    )
    installations, _ = group_into_installations(obs, 2025, _config(grouping_distance_m=5.0))

    assert len(installations) == 1
    assert installations.iloc[0]["array_count"] == 2


def test_distant_arrays_remain_separate_installations():
    obs = _observations(
        [
            {"observation_id": "OBS-1", "geometry": box_m(0, 0, 4, 4)},
            {"observation_id": "OBS-2", "geometry": box_m(200, 200, 204, 204)},
        ]
    )
    installations, _ = group_into_installations(obs, 2025, _config(grouping_distance_m=5.0))

    assert len(installations) == 2
    assert set(installations["array_count"]) == {1}


def test_shared_parcel_id_forces_grouping_even_when_far_apart():
    obs = _observations(
        [
            {"observation_id": "OBS-1", "geometry": box_m(0, 0, 4, 4), "parcel_id": "PARCEL-1"},
            {"observation_id": "OBS-2", "geometry": box_m(500, 500, 504, 504), "parcel_id": "PARCEL-1"},
        ]
    )
    installations, _ = group_into_installations(obs, 2025, _config(grouping_distance_m=5.0, use_parcel_id=True))

    assert len(installations) == 1
    assert installations.iloc[0]["array_count"] == 2
    assert installations.iloc[0]["parcel_id"] == "PARCEL-1"


def test_empty_observations_return_empty_installations():
    obs = gpd.GeoDataFrame({"observation_id": [], "geometry": [], "annotation_confidence": []}, geometry="geometry", crs="EPSG:4326")
    installations, _ = group_into_installations(obs, 2025, _config())
    assert installations.empty
