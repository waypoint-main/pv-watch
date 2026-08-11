"""Unit tests for spatial-proximity-based registry matching."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src.config import RegistryMatchingConfig
from src.models import RegistryMatchStatus
from src.registry_matching import match_installations_to_registry

from tests.geo_helpers import meters_to_lonlat

CONFIG = RegistryMatchingConfig()  # spatial_match=15m, probable_match=40m (defaults)


def _installation(inst_id: str, cx: float, cy: float, capacity_kw: float = 10.0) -> gpd.GeoDataFrame:
    lon, lat = meters_to_lonlat(cx, cy)
    return gpd.GeoDataFrame(
        [{"installation_id": inst_id, "geometry": Point(lon, lat), "estimated_capacity_kw": capacity_kw}],
        crs="EPSG:4326",
    )


def _registry(**kwargs) -> gpd.GeoDataFrame:
    defaults = dict(
        registry_id="REG-1",
        customer_reference="CUST-1000",
        registered_capacity_kw=10.0,
        application_status="Approved",
        net_metering_status="Net metering active",
        meter_status="Bi-directional meter installed",
        commissioning_date="2019-01-01",
    )
    defaults.update(kwargs)
    return gpd.GeoDataFrame([defaults], crs="EPSG:4326")


def test_exact_match_within_spatial_distance():
    installs = _installation("INST-2025-A", 0, 0, capacity_kw=10.0)
    lon, lat = meters_to_lonlat(2, 2)  # ~2.8 m away — well within the exact-match radius
    reg = _registry(geometry=[Point(lon, lat)], registered_capacity_kw=10.0)
    reg = gpd.GeoDataFrame(reg, crs="EPSG:4326")

    result = match_installations_to_registry(installs, reg, CONFIG)

    assert len(result) == 1
    assert result.iloc[0]["registry_match_status"] == RegistryMatchStatus.EXACT_MATCH.value


def test_probable_match_between_spatial_and_probable_distance():
    installs = _installation("INST-2025-A", 0, 0, capacity_kw=10.0)
    lon, lat = meters_to_lonlat(25, 0)  # 25 m — beyond exact (15m), within probable (40m)
    reg = gpd.GeoDataFrame(
        [
            dict(
                registry_id="REG-1", customer_reference="CUST-1000", registered_capacity_kw=10.0,
                application_status="Approved", net_metering_status="Net metering active",
                meter_status="Bi-directional meter installed", commissioning_date="2019-01-01",
                geometry=Point(lon, lat),
            )
        ],
        crs="EPSG:4326",
    )

    result = match_installations_to_registry(installs, reg, CONFIG)

    assert len(result) == 1
    assert result.iloc[0]["registry_match_status"] == RegistryMatchStatus.PROBABLE_MATCH.value


def test_no_registry_match_when_far_away():
    installs = _installation("INST-2025-A", 0, 0, capacity_kw=10.0)
    lon, lat = meters_to_lonlat(500, 500)  # far beyond the probable-match radius
    reg = gpd.GeoDataFrame(
        [
            dict(
                registry_id="REG-1", customer_reference="CUST-1000", registered_capacity_kw=10.0,
                application_status="Approved", net_metering_status="Net metering active",
                meter_status="Bi-directional meter installed", commissioning_date="2019-01-01",
                geometry=Point(lon, lat),
            )
        ],
        crs="EPSG:4326",
    )

    result = match_installations_to_registry(installs, reg, CONFIG)

    assert len(result) == 1
    assert result.iloc[0]["registry_match_status"] == RegistryMatchStatus.NO_MATCH.value


def test_no_registry_records_at_all_yields_no_match():
    installs = _installation("INST-2025-A", 0, 0, capacity_kw=10.0)
    empty_registry = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:4326")

    result = match_installations_to_registry(installs, empty_registry, CONFIG)

    assert len(result) == 1
    assert result.iloc[0]["registry_match_status"] == RegistryMatchStatus.NO_MATCH.value


def test_capacity_discrepancy_flagged_when_registered_much_lower_than_estimated():
    installs = _installation("INST-2025-A", 0, 0, capacity_kw=20.0)
    lon, lat = meters_to_lonlat(1, 1)
    reg = gpd.GeoDataFrame(
        [
            dict(
                registry_id="REG-1", customer_reference="CUST-1000", registered_capacity_kw=5.0,  # well below 70% of 20 kW
                application_status="Approved", net_metering_status="Net metering active",
                meter_status="Bi-directional meter installed", commissioning_date="2019-01-01",
                geometry=Point(lon, lat),
            )
        ],
        crs="EPSG:4326",
    )

    result = match_installations_to_registry(installs, reg, CONFIG)

    assert result.iloc[0]["registry_match_status"] == RegistryMatchStatus.CAPACITY_DISCREPANCY.value
