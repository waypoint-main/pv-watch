"""Unit tests for the rule-based spatial change-classification logic."""

from __future__ import annotations

from src.change_detection import classify_changes
from src.config import ChangeDetectionConfig
from src.models import ChangeType

from tests.geo_helpers import box_m, empty_installations_gdf, make_installations_gdf

CONFIG = ChangeDetectionConfig()  # uses the same defaults as config/settings.yaml


def test_exact_spatial_match_is_existing():
    installs_2020 = make_installations_gdf(
        [{"installation_id": "INST-2020-00000", "geometry": box_m(0, 0, 10, 10), "area_m2": 100.0}]
    )
    installs_2025 = make_installations_gdf(
        [{"installation_id": "INST-2025-00000", "geometry": box_m(0, 0, 10, 10), "area_m2": 100.0}]
    )
    result = classify_changes(installs_2020, installs_2025, CONFIG)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["change_type"] == ChangeType.EXISTING.value
    assert row["iou"] > 0.95
    assert row["review_required"] is False


def test_similar_polygon_small_area_difference_is_existing():
    installs_2020 = make_installations_gdf(
        [{"installation_id": "INST-2020-00000", "geometry": box_m(0, 0, 10, 10), "area_m2": 100.0}]
    )
    # ~10% larger footprint, same footprint origin -> well within the stable-area threshold (20%).
    installs_2025 = make_installations_gdf(
        [{"installation_id": "INST-2025-00000", "geometry": box_m(0, 0, 10, 11), "area_m2": 110.0}]
    )
    result = classify_changes(installs_2020, installs_2025, CONFIG)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["change_type"] == ChangeType.EXISTING.value
    assert abs(row["area_change_percent"] - 10.0) < 2.0


def test_matched_polygon_with_major_area_increase_is_expanded():
    installs_2020 = make_installations_gdf(
        [{"installation_id": "INST-2020-00000", "geometry": box_m(0, 0, 10, 10), "area_m2": 100.0}]
    )
    # Nearly doubles in area (96% growth), well beyond the 30% expansion threshold.
    installs_2025 = make_installations_gdf(
        [{"installation_id": "INST-2025-00000", "geometry": box_m(0, 0, 14, 14), "area_m2": 196.0}]
    )
    result = classify_changes(installs_2020, installs_2025, CONFIG)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["change_type"] == ChangeType.EXPANDED.value
    assert row["area_change_percent"] > 30


def test_unmatched_2025_polygon_is_newly_observed():
    installs_2020 = empty_installations_gdf()
    installs_2025 = make_installations_gdf(
        [{"installation_id": "INST-2025-00000", "geometry": box_m(0, 0, 10, 10), "area_m2": 100.0}]
    )
    result = classify_changes(installs_2020, installs_2025, CONFIG)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["change_type"] == ChangeType.NEWLY_OBSERVED.value
    assert row["installation_id_2020"] is None
    assert row["review_required"] is True


def test_unmatched_2020_polygon_is_potentially_removed():
    installs_2020 = make_installations_gdf(
        [{"installation_id": "INST-2020-00000", "geometry": box_m(0, 0, 10, 10), "area_m2": 100.0}]
    )
    installs_2025 = empty_installations_gdf()
    result = classify_changes(installs_2020, installs_2025, CONFIG)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["change_type"] == ChangeType.POTENTIALLY_REMOVED.value
    assert row["installation_id_2025"] is None


def test_ambiguous_multi_match_is_uncertain():
    # Two adjacent 2020 installations, each overlapping one 2025 installation
    # by an equally strong (and individually credible) margin -> ambiguous.
    installs_2020 = make_installations_gdf(
        [
            {"installation_id": "INST-2020-A", "geometry": box_m(0, 0, 10, 10), "area_m2": 100.0},
            {"installation_id": "INST-2020-B", "geometry": box_m(10, 0, 20, 10), "area_m2": 100.0},
        ]
    )
    installs_2025 = make_installations_gdf(
        [{"installation_id": "INST-2025-00000", "geometry": box_m(5, 0, 15, 10), "area_m2": 100.0}]
    )
    result = classify_changes(installs_2020, installs_2025, CONFIG)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["change_type"] == ChangeType.UNCERTAIN.value
    assert row["review_required"] is True


def test_zero_overlap_between_datasets_handled_gracefully():
    """Two inventories with no spatial relationship should not crash and
    should classify everything as newly observed / potentially removed."""
    installs_2020 = make_installations_gdf(
        [{"installation_id": "INST-2020-00000", "geometry": box_m(0, 0, 10, 10), "area_m2": 100.0}]
    )
    installs_2025 = make_installations_gdf(
        [{"installation_id": "INST-2025-00000", "geometry": box_m(5000, 5000, 5010, 5010), "area_m2": 100.0}]
    )
    result = classify_changes(installs_2020, installs_2025, CONFIG)

    change_types = set(result["change_type"])
    assert change_types == {ChangeType.NEWLY_OBSERVED.value, ChangeType.POTENTIALLY_REMOVED.value}


def test_empty_inventories_return_empty_dataframe_without_error():
    result = classify_changes(empty_installations_gdf(), empty_installations_gdf(), CONFIG)
    assert result.empty
    assert list(result.columns)  # schema columns still present
