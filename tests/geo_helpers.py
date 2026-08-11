"""Small shared helpers for building test geometries.

Tests author simple axis-aligned rectangles in local meters near a fixed
Philippine reference point (so UTM-zone auto-selection is deterministic),
converted to WGS84 lon/lat with the same small-area equirectangular
approximation used by ``src.synthetic_data``.
"""

from __future__ import annotations

import math

import geopandas as gpd
from shapely.geometry import Polygon

BASE_LAT = 14.30
BASE_LON = 121.10
EARTH_RADIUS_M = 6_371_000.0


def meters_to_lonlat(dx: float, dy: float) -> tuple[float, float]:
    lat_rad = math.radians(BASE_LAT)
    dlon = dx / (EARTH_RADIUS_M * math.cos(lat_rad))
    dlat = dy / EARTH_RADIUS_M
    return BASE_LON + math.degrees(dlon), BASE_LAT + math.degrees(dlat)


def box_m(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    """An axis-aligned rectangle defined by local meter offsets (x0,y0)-(x1,y1)."""
    corners_m = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return Polygon([meters_to_lonlat(x, y) for x, y in corners_m])


def make_installations_gdf(rows: list[dict]) -> gpd.GeoDataFrame:
    """Build a minimal installations-shaped GeoDataFrame for tests.

    Each row dict should include at least 'installation_id' and 'geometry';
    other expected columns (area_m2, annotation_confidence, etc.) get sane
    defaults if omitted.
    """
    defaults = {
        "source_year": 2020,
        "array_count": 1,
        "member_observation_ids": "",
        "member_raw_names": "",
        "parcel_id": None,
        "annotation_confidence": "High",
    }
    full_rows = []
    for row in rows:
        merged = {**defaults, **row}
        full_rows.append(merged)
    return gpd.GeoDataFrame(full_rows, geometry="geometry", crs="EPSG:4326")


def empty_installations_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "installation_id": [],
            "source_year": [],
            "array_count": [],
            "annotation_confidence": [],
            "geometry": [],
        },
        geometry="geometry",
        crs="EPSG:4326",
    )
