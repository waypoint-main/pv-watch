"""Turn change-detection + registry + network context into reviewable alerts.

Two concepts are deliberately kept separate throughout this module:

* **Detection confidence** — how certain the geospatial observation/match is
  (produced by ``change_detection.py``).
* **Operational priority** — how important the case may be to the utility,
  computed here from a configurable weighted score.

A newly observed installation with HIGH detection confidence is not
automatically high priority, and a LOW-confidence observation is not
automatically low priority (it may still need urgent human review). Priority
is driven by change type, capacity, registry status, and network context —
detection confidence contributes only a small, explicit weight of its own.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from src.capacity_estimation import is_large_installation
from src.config import AlertEngineConfig, CapacityEstimationConfig
from src.models import ChangeType, HostingCapacityStatus, Priority, RegistryMatchStatus, ReviewAction

ELIGIBLE_CHANGE_TYPES = {
    ChangeType.NEWLY_OBSERVED.value,
    ChangeType.EXPANDED.value,
    ChangeType.UNCERTAIN.value,
    ChangeType.POTENTIALLY_REMOVED.value,
}
REGISTRY_CONCERN_STATUSES = {
    RegistryMatchStatus.NO_MATCH.value,
    RegistryMatchStatus.CAPACITY_DISCREPANCY.value,
    RegistryMatchStatus.AMBIGUOUS.value,
}


def _priority_from_score(score: int, config: AlertEngineConfig) -> Priority:
    if score >= config.priority_1_min_score:
        return Priority.P1
    if score >= config.priority_2_min_score:
        return Priority.P2
    if score >= config.priority_3_min_score:
        return Priority.P3
    return Priority.P4


def _reason_phrase(flags: list[str]) -> str:
    if not flags:
        return "no specific risk factors were triggered"
    if len(flags) == 1:
        return flags[0]
    return ", ".join(flags[:-1]) + ", and " + flags[-1]


def score_alert(
    *,
    change_type: str,
    detection_confidence: str,
    area_m2: float,
    estimated_capacity_kw: float,
    registered_capacity_kw: Optional[float],
    registry_match_status: str,
    transformer_cluster_flag: bool,
    hosting_capacity_status: str,
    config: AlertEngineConfig,
    large_installation_area_m2: float,
) -> tuple[int, Priority, str]:
    """Compute a weighted priority score and human-readable reason for one case."""
    w = config.weights
    triggered: list[tuple[int, str]] = []

    if change_type == ChangeType.NEWLY_OBSERVED.value:
        triggered.append((w.get("newly_observed", 0), "the installation is newly observed"))
    if change_type == ChangeType.EXPANDED.value:
        triggered.append((w.get("expanded", 0), "the installation appears to have expanded"))
    if change_type == ChangeType.UNCERTAIN.value:
        triggered.append((w.get("uncertain", 0), "the spatial match is uncertain"))
    if change_type == ChangeType.POTENTIALLY_REMOVED.value:
        triggered.append((w.get("uncertain", 0), "the installation is potentially removed and needs confirmation"))

    if registry_match_status in REGISTRY_CONCERN_STATUSES:
        label = {
            RegistryMatchStatus.NO_MATCH.value: "has no registry match",
            RegistryMatchStatus.CAPACITY_DISCREPANCY.value: "has a registered capacity lower than the observed estimate",
            RegistryMatchStatus.AMBIGUOUS.value: "has an ambiguous registry match",
        }[registry_match_status]
        triggered.append((w.get("no_registry_match", 0), label))

    if registered_capacity_kw is not None and estimated_capacity_kw > registered_capacity_kw:
        triggered.append((w.get("capacity_exceeds_registered", 0), "the estimated capacity exceeds the registered capacity"))

    if is_large_installation(area_m2, config, large_installation_area_m2):
        triggered.append(
            (w.get("large_installation", 0), "has an estimated capacity above the large-system threshold")
        )

    if transformer_cluster_flag:
        triggered.append(
            (w.get("transformer_cluster", 0), "is part of a cluster of new PV installations on the same transformer")
        )

    if detection_confidence == "Low":
        triggered.append((w.get("low_detection_confidence", 0), "the geospatial detection confidence is low"))

    if hosting_capacity_status == HostingCapacityStatus.REVIEW_RECOMMENDED.value:
        triggered.append(
            (w.get("network_review_recommended", 0), "is associated with a transformer already marked for review")
        )

    score = sum(pts for pts, _ in triggered)
    priority = _priority_from_score(score, config)
    phrases = [phrase for _, phrase in triggered]
    reason = f"{priority.value.split('—')[0].strip()} because {_reason_phrase(phrases)}."
    return score, priority, reason


def generate_alerts(
    change_df: pd.DataFrame,
    installations_2025_ctx: pd.DataFrame,
    installations_2020_ctx: pd.DataFrame,
    registry_match_df: pd.DataFrame,
    transformer_summary_df: pd.DataFrame,
    alert_config: AlertEngineConfig,
    capacity_config: CapacityEstimationConfig,
) -> pd.DataFrame:
    """Build the full alert table from upstream pipeline outputs."""
    if change_df.empty:
        return _empty_alerts_frame()

    inst_2025_by_id = installations_2025_ctx.set_index("installation_id") if not installations_2025_ctx.empty else pd.DataFrame()
    inst_2020_by_id = installations_2020_ctx.set_index("installation_id") if not installations_2020_ctx.empty else pd.DataFrame()
    registry_by_inst = registry_match_df.set_index("installation_id") if not registry_match_df.empty else pd.DataFrame()
    hosting_by_tx = (
        transformer_summary_df.set_index("transformer_id")["hosting_capacity_status"]
        if not transformer_summary_df.empty and "hosting_capacity_status" in transformer_summary_df.columns
        else pd.Series(dtype=object)
    )

    # Transformer clustering: transformers with >= cluster_new_installation_count newly-observed installations.
    cluster_transformers: set = set()
    if not installations_2025_ctx.empty and "transformer_id" in installations_2025_ctx.columns:
        if "change_type" in installations_2025_ctx.columns:
            # Already carries its own change_type (the normal pipeline path) — no join needed.
            merged = installations_2025_ctx
        else:
            merged = installations_2025_ctx.merge(
                change_df[["installation_id_2025", "change_type"]], left_on="installation_id", right_on="installation_id_2025", how="left"
            )
        new_counts = (
            merged[merged["change_type"] == ChangeType.NEWLY_OBSERVED.value].groupby("transformer_id").size()
        )
        cluster_transformers = set(new_counts[new_counts >= alert_config.cluster_new_installation_count].index)

    rows = []
    alert_counter = 0
    for _, chg in change_df.iterrows():
        change_type = chg["change_type"]
        eligible = change_type in ELIGIBLE_CHANGE_TYPES

        inst_id = chg["installation_id_2025"] or chg["installation_id_2020"]
        is_2025_side = bool(chg["installation_id_2025"])

        inst_row = None
        if is_2025_side and not inst_2025_by_id.empty and inst_id in inst_2025_by_id.index:
            inst_row = inst_2025_by_id.loc[inst_id]
        elif not is_2025_side and not inst_2020_by_id.empty and inst_id in inst_2020_by_id.index:
            inst_row = inst_2020_by_id.loc[inst_id]

        if inst_row is None:
            continue

        area_m2 = inst_row.get("area_m2", 0.0) or 0.0
        estimated_capacity_kw = inst_row.get("estimated_capacity_kw", 0.0) or 0.0
        transformer_id = inst_row.get("transformer_id")
        feeder_id = inst_row.get("feeder_id")
        municipality = inst_row.get("municipality", "Unclassified area")
        barangay = inst_row.get("barangay", "Unclassified area")
        detection_confidence = chg.get("detection_confidence", "Medium")

        registry_status = RegistryMatchStatus.NO_MATCH.value
        registered_capacity_kw = None
        if is_2025_side and not registry_by_inst.empty and inst_id in registry_by_inst.index:
            reg_row = registry_by_inst.loc[inst_id]
            registry_status = reg_row.get("registry_match_status", RegistryMatchStatus.NO_MATCH.value)
            registered_capacity_kw = reg_row.get("registered_capacity_kw")
        elif not is_2025_side:
            registry_status = "Not applicable (2020-only record)"

        registry_flag_eligible = is_2025_side and registry_status in REGISTRY_CONCERN_STATUSES
        capacity_exceeds_eligible = (
            is_2025_side and registered_capacity_kw is not None and estimated_capacity_kw > registered_capacity_kw
        )
        large_eligible = is_large_installation(area_m2, alert_config, alert_config.large_installation_area_m2)
        low_conf_eligible = detection_confidence == "Low"

        if not (eligible or registry_flag_eligible or capacity_exceeds_eligible or large_eligible or low_conf_eligible):
            continue

        transformer_cluster_flag = transformer_id in cluster_transformers
        hosting_status = hosting_by_tx.get(transformer_id, HostingCapacityStatus.DATA_INCOMPLETE.value) if transformer_id else HostingCapacityStatus.DATA_INCOMPLETE.value

        score, priority, priority_reason = score_alert(
            change_type=change_type,
            detection_confidence=detection_confidence,
            area_m2=area_m2,
            estimated_capacity_kw=estimated_capacity_kw,
            registered_capacity_kw=registered_capacity_kw,
            registry_match_status=registry_status if is_2025_side else "Not applicable (2020-only record)",
            transformer_cluster_flag=transformer_cluster_flag,
            hosting_capacity_status=hosting_status,
            config=alert_config,
            large_installation_area_m2=alert_config.large_installation_area_m2,
        )

        alert_counter += 1
        rows.append(
            {
                "alert_id": f"ALERT-{alert_counter:05d}",
                "change_id": chg["change_id"],
                "installation_id": inst_id,
                "change_type": change_type,
                "municipality": municipality,
                "barangay": barangay,
                "area_m2": round(area_m2, 1),
                "estimated_capacity_kw": round(estimated_capacity_kw, 2),
                "registry_match_status": registry_status,
                "transformer_id": transformer_id,
                "feeder_id": feeder_id,
                "priority": priority.value,
                "priority_score": score,
                "priority_reason": priority_reason,
                "detection_confidence": detection_confidence,
                "classification_reason": chg.get("classification_reason", ""),
                "review_status": ReviewAction.FOR_INSPECTION.value,
                "assigned_to": "",
                "reviewer_notes": "",
            }
        )

    if not rows:
        return _empty_alerts_frame()

    return pd.DataFrame(rows)


def _empty_alerts_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "alert_id", "change_id", "installation_id", "change_type", "municipality", "barangay", "area_m2",
            "estimated_capacity_kw", "registry_match_status", "transformer_id", "feeder_id", "priority",
            "priority_score", "priority_reason", "detection_confidence", "classification_reason", "review_status",
            "assigned_to", "reviewer_notes",
        ]
    )
