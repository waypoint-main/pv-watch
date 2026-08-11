"""Unit tests for alert priority scoring.

Detection confidence and operational priority are deliberately different
concepts (see ``src/alert_engine.py``); these tests check that priority is
driven by the weighted combination of risk factors, not by confidence alone.
"""

from __future__ import annotations

from src.alert_engine import score_alert
from src.config import AlertEngineConfig
from src.models import ChangeType, HostingCapacityStatus, Priority, RegistryMatchStatus

WEIGHTS = {
    "newly_observed": 3,
    "expanded": 2,
    "uncertain": 1,
    "no_registry_match": 2,
    "capacity_exceeds_registered": 3,
    "large_installation": 2,
    "transformer_cluster": 2,
    "low_detection_confidence": 1,
    "network_review_recommended": 2,
}
CONFIG = AlertEngineConfig(
    weights=WEIGHTS, large_installation_area_m2=90.0, cluster_new_installation_count=3,
    priority_1_min_score=7, priority_2_min_score=5, priority_3_min_score=3,
)


def test_newly_observed_no_registry_large_and_cluster_is_priority_1():
    score, priority, reason = score_alert(
        change_type=ChangeType.NEWLY_OBSERVED.value,
        detection_confidence="High",
        area_m2=120.0,
        estimated_capacity_kw=20.0,
        registered_capacity_kw=None,
        registry_match_status=RegistryMatchStatus.NO_MATCH.value,
        transformer_cluster_flag=True,
        hosting_capacity_status=HostingCapacityStatus.REVIEW_RECOMMENDED.value,
        config=CONFIG,
        large_installation_area_m2=90.0,
    )
    # newly_observed(3) + no_registry_match(2) + large_installation(2) + transformer_cluster(2)
    # + network_review_recommended(2) = 11 -> well above priority_1_min_score(7)
    assert score == 11
    assert priority == Priority.P1
    assert "newly observed" in reason.lower()


def test_high_detection_confidence_does_not_by_itself_imply_high_priority():
    """A HIGH-confidence, otherwise unremarkable existing-installation case
    should NOT be priority 1 just because confidence is high — confidence and
    priority are independent concepts."""
    score, priority, reason = score_alert(
        change_type=ChangeType.EXISTING.value,
        detection_confidence="High",
        area_m2=25.0,
        estimated_capacity_kw=4.0,
        registered_capacity_kw=4.0,
        registry_match_status=RegistryMatchStatus.EXACT_MATCH.value,
        transformer_cluster_flag=False,
        hosting_capacity_status=HostingCapacityStatus.LOW_CONCERN.value,
        config=CONFIG,
        large_installation_area_m2=90.0,
    )
    assert score == 0
    assert priority == Priority.P4


def test_low_detection_confidence_alone_is_not_automatically_priority_1():
    score, priority, _ = score_alert(
        change_type=ChangeType.UNCERTAIN.value,
        detection_confidence="Low",
        area_m2=15.0,
        estimated_capacity_kw=2.0,
        registered_capacity_kw=None,
        registry_match_status="Not applicable (2020-only record)",
        transformer_cluster_flag=False,
        hosting_capacity_status=HostingCapacityStatus.LOW_CONCERN.value,
        config=CONFIG,
        large_installation_area_m2=90.0,
    )
    # uncertain(1) + low_detection_confidence(1) = 2 -> Priority 4, not 1.
    assert score == 2
    assert priority == Priority.P4


def test_capacity_exceeds_registered_contributes_to_score():
    score, priority, reason = score_alert(
        change_type=ChangeType.EXISTING.value,
        detection_confidence="Medium",
        area_m2=30.0,
        estimated_capacity_kw=10.0,
        registered_capacity_kw=4.0,  # estimated (10) clearly exceeds registered (4)
        registry_match_status=RegistryMatchStatus.CAPACITY_DISCREPANCY.value,
        transformer_cluster_flag=False,
        hosting_capacity_status=HostingCapacityStatus.MONITOR.value,
        config=CONFIG,
        large_installation_area_m2=90.0,
    )
    # no_registry_match-style flag (capacity discrepancy, 2) + capacity_exceeds_registered(3) = 5 -> Priority 2
    assert score == 5
    assert priority == Priority.P2
    assert "exceeds" in reason.lower()


def test_priority_tiers_are_monotonic_with_score():
    assert Priority.P1.sort_key < Priority.P2.sort_key < Priority.P3.sort_key < Priority.P4.sort_key
