"""Unit tests for geometry validation/repair and area calculation."""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Polygon

from src.geometry_utils import compute_area_m2, normalize_geometries

from tests.geo_helpers import box_m


def test_invalid_self_intersecting_geometry_is_repaired():
    # A classic "bowtie" self-intersecting polygon (invalid).
    bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])
    assert not bowtie.is_valid

    gdf = gpd.GeoDataFrame({"observation_id": ["OBS-1"], "geometry": [bowtie]}, crs="EPSG:4326")
    cleaned, report = normalize_geometries(gdf)

    assert len(cleaned) == 1
    assert report.repaired_count == 1
    assert cleaned.iloc[0].geometry.is_valid


def test_degenerate_zero_area_geometry_is_rejected_gracefully():
    # A zero-area, degenerate "polygon" (all points collapse to a line) —
    # should be dropped, not crash the pipeline.
    degenerate = Polygon([(0, 0), (0, 0), (0, 0)])
    valid = box_m(0, 0, 10, 10)

    gdf = gpd.GeoDataFrame({"observation_id": ["OBS-1", "OBS-2"], "geometry": [degenerate, valid]}, crs="EPSG:4326")
    cleaned, report = normalize_geometries(gdf)

    assert len(cleaned) == 1
    assert cleaned.iloc[0]["observation_id"] == "OBS-2"
    assert report.total_dropped >= 1


def test_unsupported_geometry_type_is_skipped_with_warning():
    from shapely.geometry import LineString

    line = LineString([(0, 0), (1, 1)])
    poly = box_m(0, 0, 10, 10)
    gdf = gpd.GeoDataFrame({"observation_id": ["OBS-1", "OBS-2"], "geometry": [line, poly]}, crs="EPSG:4326")

    cleaned, report = normalize_geometries(gdf)

    assert len(cleaned) == 1
    assert report.dropped_unsupported_type_count == 1
    assert any("unsupported geometry type" in w for w in report.warnings)


def test_area_is_computed_in_projected_crs_not_degrees():
    gdf = gpd.GeoDataFrame({"observation_id": ["OBS-1"], "geometry": [box_m(0, 0, 10, 10)]}, crs="EPSG:4326")
    result, crs_used = compute_area_m2(gdf)

    # A 10x10 m square should be ~100 m^2 once correctly reprojected — never
    # the (meaningless, tiny) figure you'd get by measuring degrees directly.
    assert 90 < result.iloc[0]["area_m2"] < 110
    assert crs_used.upper().startswith("EPSG:")
    assert crs_used.upper() != "EPSG:4326"
