"""Synthetic demonstration data generator.

Everything produced by this module is FICTIONAL and exists only so PV Watch
can be explored immediately after cloning, without requiring real utility or
customer data. Geometries approximate a small Philippine urban area (in the
general vicinity of Santa Rosa, Laguna) purely for visual realism; they do
not represent actual PV installations, actual parcels, or actual utility
infrastructure.

Design notes
------------
* Geometry is authored in local planar meters around a configurable center
  point and converted to WGS84 (EPSG:4326) with a small-area equirectangular
  approximation. This keeps polygon shapes/areas realistic without needing a
  real projected CRS during authoring (the application's normal CRS pipeline
  is still exercised afterwards, exactly as it would be for uploaded KMZ).
* The generator deliberately constructs distinct spatial "scenarios"
  (existing / expanded / removed / newly observed / uncertain) so that the
  real ``change_detection`` module classifies them correctly through its own
  rules — classifications are never hard-coded here.
* Barangay/municipality admin zones are generated once and reused both to
  place synthetic installations AND to spatially assign a barangay/
  municipality to *any* dataset (including future uploaded KMZ data) via a
  simple spatial join, so the rest of the app has one consistent code path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon, box

from src.config import AppConfig
from src.models import OBSERVATION_SCHEMA_FIELDS

EARTH_RADIUS_M = 6_371_000.0

# Real Philippine barangay names (Santa Rosa, Laguna area) are reused purely
# as realistic place-name labels for synthetic zones. No real boundaries,
# parcels, or customer data are associated with them.
BARANGAY_NAMES_A = ["Sinalhan", "Tagapo", "Balibago", "Dita"]
BARANGAY_NAMES_B = ["Caingin", "Pooc"]
MUNICIPALITY_A = "Santa Rosa (synthetic demo)"
MUNICIPALITY_B = "Cabuyao (synthetic demo)"


def _meters_to_lonlat(center_lat: float, center_lon: float, dx: float, dy: float) -> tuple[float, float]:
    """Convert a local (dx, dy) meter offset to (lon, lat) near a center point."""
    lat_rad = math.radians(center_lat)
    dlat = dy / EARTH_RADIUS_M
    dlon = dx / (EARTH_RADIUS_M * math.cos(lat_rad))
    return center_lon + math.degrees(dlon), center_lat + math.degrees(dlat)


def _rect_polygon(center_lat, center_lon, cx, cy, width, height, rotation_deg=0.0) -> Polygon:
    """Build a (optionally rotated) rectangle in local meters, return as WGS84 Polygon."""
    hw, hh = width / 2, height / 2
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    lonlat_corners = []
    for lx, ly in corners:
        rx = lx * cos_t - ly * sin_t
        ry = lx * sin_t + ly * cos_t
        lonlat_corners.append(_meters_to_lonlat(center_lat, center_lon, cx + rx, cy + ry))
    return Polygon(lonlat_corners)


@dataclass
class ZoneSlot:
    zone_index: int
    municipality: str
    barangay: str
    origin_dx: float
    origin_dy: float
    size_m: float


def _build_zone_grid(config: AppConfig) -> list[ZoneSlot]:
    """Lay out 6 barangay-sized zones in a loose 3x2 grid, ~380m apart."""
    names = [(MUNICIPALITY_A, b) for b in BARANGAY_NAMES_A] + [(MUNICIPALITY_B, b) for b in BARANGAY_NAMES_B]
    zones = []
    spacing = 380.0
    cols = 3
    for i, (muni, brgy) in enumerate(names):
        row, col = divmod(i, cols)
        origin_dx = (col - 1) * spacing
        origin_dy = (row - 0.5) * spacing
        zones.append(ZoneSlot(i, muni, brgy, origin_dx, origin_dy, size_m=260.0))
    return zones


def generate_admin_zones(config: AppConfig) -> gpd.GeoDataFrame:
    """Generate synthetic barangay/municipality service-area polygons.

    Used both to place synthetic installations and to spatially label ANY
    installation set (demo or uploaded) with a municipality/barangay via
    spatial join, since real KMZ uploads typically do not carry admin-zone
    attributes.
    """
    center_lat, center_lon = config.synthetic_demo.center_lat, config.synthetic_demo.center_lon
    zones = _build_zone_grid(config)
    records = []
    for z in zones:
        poly = _rect_polygon(center_lat, center_lon, z.origin_dx, z.origin_dy, z.size_m, z.size_m)
        records.append(
            {
                "zone_id": f"ZONE-{z.zone_index:02d}",
                "municipality": z.municipality,
                "barangay": z.barangay,
                "geometry": poly,
            }
        )
    return gpd.GeoDataFrame(records, crs="EPSG:4326")


def assign_admin_zone(gdf: gpd.GeoDataFrame, zones_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Spatially join installations/observations to municipality & barangay.

    Falls back to "Unclassified area" for geometries outside all synthetic
    zones (expected for real-world uploaded data outside the demo extent).
    """
    if gdf.empty:
        out = gdf.copy()
        out["municipality"] = pd.Series(dtype=object)
        out["barangay"] = pd.Series(dtype=object)
        return out

    left = gdf.copy()
    left["_centroid"] = left.geometry.centroid
    centroid_gdf = gpd.GeoDataFrame(left.drop(columns="geometry"), geometry=left["_centroid"], crs=gdf.crs)
    joined = gpd.sjoin(centroid_gdf, zones_gdf[["municipality", "barangay", "geometry"]], how="left", predicate="within")
    joined = joined.drop(columns=[c for c in ["index_right", "_centroid"] if c in joined.columns])
    joined["municipality"] = joined["municipality"].fillna("Unclassified area")
    joined["barangay"] = joined["barangay"].fillna("Unclassified area")
    result = gdf.copy()
    result["municipality"] = joined["municipality"].values
    result["barangay"] = joined["barangay"].values
    return result


def _rng(config: AppConfig) -> np.random.Generator:
    return np.random.default_rng(config.synthetic_demo.seed)


def generate_raw_observations(config: AppConfig) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Generate synthetic 2020 and 2025 raw PV array observations.

    Returns two GeoDataFrames shaped like freshly-parsed KMZ output (i.e.
    *before* schema normalization / area calculation), so they flow through
    exactly the same ``data_loader`` normalization path as an uploaded file.
    """
    rng = _rng(config)
    center_lat, center_lon = config.synthetic_demo.center_lat, config.synthetic_demo.center_lon
    zones = _build_zone_grid(config)

    rows_2020: list[dict] = []
    rows_2025: list[dict] = []
    placed_points: list[tuple[float, float]] = []
    counter = {"n": 0}

    def next_site(zone: ZoneSlot, min_spacing=18.0, tries=30) -> tuple[float, float]:
        half = zone.size_m / 2 - 12
        for _ in range(tries):
            dx = zone.origin_dx + rng.uniform(-half, half)
            dy = zone.origin_dy + rng.uniform(-half, half)
            if all(math.hypot(dx - px, dy - py) >= min_spacing for px, py in placed_points):
                placed_points.append((dx, dy))
                return dx, dy
        placed_points.append((dx, dy))
        return dx, dy

    def make_array(cx, cy, area_m2, rotation, confidence, parcel_id, zone_idx, name_prefix):
        counter["n"] += 1
        side = math.sqrt(area_m2)
        width = side * rng.uniform(0.85, 1.15)
        height = area_m2 / width
        poly = _rect_polygon(center_lat, center_lon, cx, cy, width, height, rotation)
        return {
            "raw_name": f"{name_prefix}_{zone_idx:02d}_{counter['n']:03d}",
            "parcel_id": parcel_id,
            "annotation_confidence": confidence,
            "geometry": poly,
            "_zone_idx": zone_idx,
        }

    confidences = ["High", "High", "Medium", "Medium", "Low"]

    def pick_confidence(low_bias=False):
        if low_bias:
            return rng.choice(["Medium", "Low", "Low"])
        return rng.choice(confidences)

    zone_cycle = list(range(len(zones)))

    # --- Existing (19): stable location + stable area between 2020 & 2025 ---
    for i in range(19):
        z = zones[zone_cycle[i % len(zones)]]
        cx, cy = next_site(z)
        area = rng.uniform(18, 55)
        rot = rng.uniform(0, 89)
        parcel = f"PARCEL-{z.barangay[:3].upper()}-{i:03d}" if rng.random() < 0.4 else None
        conf = pick_confidence()
        rows_2020.append(make_array(cx, cy, area, rot, conf, parcel, z.zone_index, "PV2020_EXIST"))
        # small jitter + small area change (<20%) to avoid requiring exact equality
        jitter = rng.uniform(-1.5, 1.5)
        area_2025 = area * rng.uniform(0.92, 1.15)
        rows_2025.append(
            make_array(cx + jitter, cy + jitter, area_2025, rot, pick_confidence(), parcel, z.zone_index, "PV2025_EXIST")
        )

    # --- Expanded (6): same location, area grows well beyond 30% ---
    for i in range(6):
        z = zones[zone_cycle[i % len(zones)]]
        cx, cy = next_site(z)
        area = rng.uniform(20, 40)
        rot = rng.uniform(0, 89)
        parcel = f"PARCEL-{z.barangay[:3].upper()}-EXP{i:02d}" if rng.random() < 0.4 else None
        rows_2020.append(make_array(cx, cy, area, rot, pick_confidence(), parcel, z.zone_index, "PV2020_EXP"))
        area_2025 = area * rng.uniform(1.6, 2.4)
        rows_2025.append(make_array(cx, cy, area_2025, rot, pick_confidence(), parcel, z.zone_index, "PV2025_EXP"))

    # --- Potentially removed (5): 2020 only ---
    for i in range(5):
        z = zones[zone_cycle[i % len(zones)]]
        cx, cy = next_site(z)
        area = rng.uniform(15, 45)
        rot = rng.uniform(0, 89)
        rows_2020.append(make_array(cx, cy, area, rot, pick_confidence(), None, z.zone_index, "PV2020_REM"))

    # --- Uncertain (4 scenarios): ambiguous multi-match geometry ---
    for i in range(4):
        z = zones[zone_cycle[i % len(zones)]]
        cx, cy = next_site(z, min_spacing=22)
        area = rng.uniform(40, 60)
        rot = rng.uniform(0, 89)
        rows_2020.append(make_array(cx, cy, area, rot, pick_confidence(low_bias=True), None, z.zone_index, "PV2020_UNC"))
        # One 2020 array is split into two smaller, adjacent 2025 arrays
        # (simulates a roof re-annotated as two sub-arrays) -> ambiguous
        # overlap against a single 2020 match, well below full coverage.
        half_area = area * 0.5
        offset = math.sqrt(area) * 0.55
        rows_2025.append(
            make_array(cx - offset, cy, half_area, rot, pick_confidence(low_bias=True), None, z.zone_index, "PV2025_UNC")
        )
        rows_2025.append(
            make_array(cx + offset, cy, half_area, rot, pick_confidence(low_bias=True), None, z.zone_index, "PV2025_UNC")
        )

    # --- Newly observed (23): 2025 only, incl. a clustered group near one
    # transformer location to trigger the transformer-cluster alert rule,
    # and a couple of large installations to trigger the large-system rule.
    cluster_zone = zones[0]
    cluster_anchor = next_site(cluster_zone, min_spacing=10)
    for i in range(23):
        if i < 6:
            # Tight cluster around one anchor point within the same zone.
            cx = cluster_anchor[0] + rng.uniform(-25, 25)
            cy = cluster_anchor[1] + rng.uniform(-25, 25)
            zone_index = cluster_zone.zone_index
            placed_points.append((cx, cy))
        else:
            z = zones[zone_cycle[i % len(zones)]]
            cx, cy = next_site(z)
            zone_index = z.zone_index
        rot = rng.uniform(0, 89)
        area = rng.uniform(95, 140) if i in (6, 7) else rng.uniform(12, 70)  # a couple of "large" systems
        conf = pick_confidence(low_bias=(i % 5 == 0))
        rows_2025.append(make_array(cx, cy, area, rot, conf, None, zone_index, "PV2025_NEW"))

    def to_gdf(rows: list[dict], source_year: int, observation_date: str, imagery_source: str) -> gpd.GeoDataFrame:
        for r in rows:
            r["source_year"] = source_year
            r["observation_date"] = observation_date
            r["imagery_source"] = imagery_source
            r.pop("_zone_idx", None)
        return gpd.GeoDataFrame(rows, crs="EPSG:4326")

    gdf_2020 = to_gdf(
        rows_2020,
        config.app.observation_year_baseline,
        config.app.observation_date_baseline,
        "Synthetic demo imagery (2020 baseline annotation)",
    )
    gdf_2025 = to_gdf(
        rows_2025,
        config.app.observation_year_latest,
        config.app.observation_date_latest,
        "Synthetic demo imagery (2025 latest annotation)",
    )
    return gdf_2020, gdf_2025


def generate_transformers_and_feeders(config: AppConfig) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Generate synthetic feeder service areas and transformer point locations."""
    rng = _rng(config)
    center_lat, center_lon = config.synthetic_demo.center_lat, config.synthetic_demo.center_lon
    zones = _build_zone_grid(config)

    feeder_defs = [
        {"feeder_id": "FDR-A1", "feeder_name": "Feeder A1 (synthetic)", "zone_indices": [0, 1, 3]},
        {"feeder_id": "FDR-B2", "feeder_name": "Feeder B2 (synthetic)", "zone_indices": [2, 4, 5]},
    ]
    feeder_rows = []
    for fd in feeder_defs:
        member_zones = [zones[i] for i in fd["zone_indices"]]
        min_dx = min(z.origin_dx for z in member_zones) - 150
        max_dx = max(z.origin_dx for z in member_zones) + 150
        min_dy = min(z.origin_dy for z in member_zones) - 150
        max_dy = max(z.origin_dy for z in member_zones) + 150
        corners = [
            _meters_to_lonlat(center_lat, center_lon, min_dx, min_dy),
            _meters_to_lonlat(center_lat, center_lon, max_dx, min_dy),
            _meters_to_lonlat(center_lat, center_lon, max_dx, max_dy),
            _meters_to_lonlat(center_lat, center_lon, min_dx, max_dy),
        ]
        feeder_rows.append(
            {
                "feeder_id": fd["feeder_id"],
                "feeder_name": fd["feeder_name"],
                "geometry": Polygon(corners),
            }
        )
    feeders_gdf = gpd.GeoDataFrame(feeder_rows, crs="EPSG:4326")

    transformer_defs = [
        ("TX-101", "FDR-A1", 0, 500),
        ("TX-102", "FDR-A1", 1, 300),
        ("TX-103", "FDR-A1", 3, 300),
        ("TX-104", "FDR-B2", 2, 500),
        ("TX-105", "FDR-B2", 4, 300),
        ("TX-106", "FDR-B2", 5, 300),
    ]
    tx_rows = []
    for tx_id, feeder_id, zone_idx, rated_kva in transformer_defs:
        z = zones[zone_idx]
        dx = z.origin_dx + rng.uniform(-40, 40)
        dy = z.origin_dy + rng.uniform(-40, 40)
        lon, lat = _meters_to_lonlat(center_lat, center_lon, dx, dy)
        tx_rows.append(
            {
                "transformer_id": tx_id,
                "feeder_id": feeder_id,
                "rated_capacity_kva": rated_kva,
                "recorded_pv_capacity_kw": float(rng.uniform(2, 12)),
                "geometry": Point(lon, lat),
            }
        )
    transformers_gdf = gpd.GeoDataFrame(tx_rows, crs="EPSG:4326")
    return transformers_gdf, feeders_gdf


def generate_synthetic_registry(config: AppConfig, installations_2025: gpd.GeoDataFrame) -> pd.DataFrame:
    """Generate a synthetic utility registry with a mix of match outcomes.

    All customer references, application statuses, and dates are fictional.
    The registry deliberately includes exact/near/no-match cases so that
    ``registry_matching.py`` has realistic ambiguity to resolve.
    """
    rng = _rng(config)
    if installations_2025.empty:
        return pd.DataFrame(
            columns=[
                "registry_id",
                "installation_id",
                "customer_reference",
                "municipality",
                "barangay",
                "registered_capacity_kw",
                "application_status",
                "net_metering_status",
                "meter_status",
                "commissioning_date",
            ]
        )

    installs = installations_2025.reset_index(drop=True)
    n = len(installs)
    rows = []
    reg_counter = 0

    # Deterministic cycling of outcome archetypes across installations so the
    # demo always contains every registry_match_status the app supports.
    for i, inst in installs.iterrows():
        outcome = i % 7
        area = inst.get("area_m2", 25.0) or 25.0
        est_kw = area * config.capacity_estimation.kw_per_m2
        reg_counter += 1
        registry_id = f"REG-{reg_counter:05d}"
        customer_ref = f"CUST-{2000 + reg_counter}"
        muni = inst.get("municipality", "Unclassified area")
        brgy = inst.get("barangay", "Unclassified area")

        if outcome == 0:
            # Exact match: registered near the installation, capacity close.
            rows.append(
                dict(
                    registry_id=registry_id,
                    installation_id=inst["installation_id"],
                    customer_reference=customer_ref,
                    municipality=muni,
                    barangay=brgy,
                    registered_capacity_kw=round(est_kw * rng.uniform(0.95, 1.05), 1),
                    application_status="Approved",
                    net_metering_status="Net metering active",
                    meter_status="Bi-directional meter installed",
                    commissioning_date="2019-11-15",
                    _offset_m=0.0,
                )
            )
        elif outcome == 1:
            # Probable match: registered nearby but not exactly co-located.
            rows.append(
                dict(
                    registry_id=registry_id,
                    installation_id=None,
                    customer_reference=customer_ref,
                    municipality=muni,
                    barangay=brgy,
                    registered_capacity_kw=round(est_kw * rng.uniform(0.9, 1.1), 1),
                    application_status="Approved",
                    net_metering_status="Net metering active",
                    meter_status="Bi-directional meter installed",
                    commissioning_date="2020-03-02",
                    _offset_m=25.0,
                    _near_installation_id=inst["installation_id"],
                )
            )
        elif outcome == 2:
            # No registry match at all.
            continue
        elif outcome == 3:
            # Registration pending.
            rows.append(
                dict(
                    registry_id=registry_id,
                    installation_id=inst["installation_id"],
                    customer_reference=customer_ref,
                    municipality=muni,
                    barangay=brgy,
                    registered_capacity_kw=round(est_kw * rng.uniform(0.9, 1.0), 1),
                    application_status="Pending",
                    net_metering_status="Application submitted",
                    meter_status="Meter not yet upgraded",
                    commissioning_date="",
                    _offset_m=0.0,
                )
            )
        elif outcome == 4:
            # Registered but with materially lower recorded capacity than observed.
            rows.append(
                dict(
                    registry_id=registry_id,
                    installation_id=inst["installation_id"],
                    customer_reference=customer_ref,
                    municipality=muni,
                    barangay=brgy,
                    registered_capacity_kw=round(est_kw * rng.uniform(0.35, 0.6), 1),
                    application_status="Approved",
                    net_metering_status="Net metering active",
                    meter_status="Bi-directional meter installed",
                    commissioning_date="2018-07-20",
                    _offset_m=0.0,
                )
            )
        elif outcome == 5:
            # Off-grid / non-exporting system.
            rows.append(
                dict(
                    registry_id=registry_id,
                    installation_id=inst["installation_id"],
                    customer_reference=customer_ref,
                    municipality=muni,
                    barangay=brgy,
                    registered_capacity_kw=round(est_kw * rng.uniform(0.8, 1.0), 1),
                    application_status="Not applicable (off-grid)",
                    net_metering_status="Non-exporting / off-grid",
                    meter_status="Standard meter (no export metering)",
                    commissioning_date="2021-01-10",
                    _offset_m=0.0,
                )
            )
        else:
            # Ambiguous: two registry candidates near the same installation.
            rows.append(
                dict(
                    registry_id=registry_id,
                    installation_id=None,
                    customer_reference=customer_ref,
                    municipality=muni,
                    barangay=brgy,
                    registered_capacity_kw=round(est_kw * rng.uniform(0.7, 1.3), 1),
                    application_status="Approved",
                    net_metering_status="Net metering active",
                    meter_status="Bi-directional meter installed",
                    commissioning_date="2020-09-05",
                    _offset_m=8.0,
                    _near_installation_id=inst["installation_id"],
                )
            )
            reg_counter += 1
            rows.append(
                dict(
                    registry_id=f"REG-{reg_counter:05d}",
                    installation_id=None,
                    customer_reference=f"CUST-{2000 + reg_counter}",
                    municipality=muni,
                    barangay=brgy,
                    registered_capacity_kw=round(est_kw * rng.uniform(0.7, 1.3), 1),
                    application_status="Approved",
                    net_metering_status="Net metering active",
                    meter_status="Bi-directional meter installed",
                    commissioning_date="2020-09-05",
                    _offset_m=-8.0,
                    _near_installation_id=inst["installation_id"],
                )
            )

    df = pd.DataFrame(rows)
    return df
