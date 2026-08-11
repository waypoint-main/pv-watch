"""Structured data models shared across PV Watch modules.

Using small dataclasses/enums (rather than passing bare dicts or untyped
DataFrame rows between modules) keeps the pipeline self-documenting: every
stage's inputs and outputs are named and typed, which makes it easier to
extend the pipeline later (e.g. swapping the synthetic registry for a real
utility CRM feed) without hunting for implicit field names.

Bulk data (observations, installations, change records, alerts) is carried
through the pipeline as GeoDataFrames/DataFrames for vectorized spatial and
tabular operations; these dataclasses/enums define the *columns* and
*vocabulary* those tables must honor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class ChangeType(str, Enum):
    EXISTING = "Existing"
    EXPANDED = "Expanded"
    NEWLY_OBSERVED = "Newly observed"
    POTENTIALLY_REMOVED = "Potentially removed"
    UNCERTAIN = "Uncertain"


class DetectionConfidence(str, Enum):
    """How certain the geospatial observation or match is (NOT priority)."""

    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Priority(str, Enum):
    P1 = "Priority 1 — Immediate verification"
    P2 = "Priority 2 — Registry reconciliation"
    P3 = "Priority 3 — Planning intelligence"
    P4 = "Priority 4 — Human review required"

    @property
    def sort_key(self) -> int:
        return {"P1": 1, "P2": 2, "P3": 3, "P4": 4}[self.name]


class RegistryMatchStatus(str, Enum):
    EXACT_MATCH = "Exact match"
    PROBABLE_MATCH = "Probable match"
    NO_MATCH = "No registry match"
    PENDING = "Registration pending"
    CAPACITY_DISCREPANCY = "Registered — recorded capacity lower than observed estimate"
    OFF_GRID = "Off-grid / non-exporting"
    AMBIGUOUS = "Ambiguous match"


class HostingCapacityStatus(str, Enum):
    LOW_CONCERN = "Low concern"
    MONITOR = "Monitor"
    REVIEW_RECOMMENDED = "Review recommended"
    DATA_INCOMPLETE = "Data incomplete"


class ReviewAction(str, Enum):
    """The case-management state of an alert's reviewer disposition.

    A fixed, two-branch workflow. Every alert starts at ``FOR_INSPECTION``:

        FOR_INSPECTION -> FOR_REGISTRATION -> ONGOING_REGISTRATION -> REGISTERED (end state)
        FOR_INSPECTION -> FALSE_POSITIVE (end state)
    """

    FOR_INSPECTION = "For inspection"
    FOR_REGISTRATION = "For registration"
    ONGOING_REGISTRATION = "Ongoing registration"
    REGISTERED = "Registered"
    FALSE_POSITIVE = "False positive"


# Valid next state(s) from a given state — the two-branch workflow described
# above. Used to restrict the reviewer-action selector to legal transitions
# and to reconstruct a plausible history path for synthetic seed data.
REVIEW_STATE_TRANSITIONS: dict[ReviewAction, list[ReviewAction]] = {
    ReviewAction.FOR_INSPECTION: [ReviewAction.FOR_REGISTRATION, ReviewAction.FALSE_POSITIVE],
    ReviewAction.FOR_REGISTRATION: [ReviewAction.ONGOING_REGISTRATION],
    ReviewAction.ONGOING_REGISTRATION: [ReviewAction.REGISTERED],
    ReviewAction.REGISTERED: [],
    ReviewAction.FALSE_POSITIVE: [],
}

# The two terminal ("closed case") states.
REVIEW_END_STATES = (ReviewAction.REGISTERED, ReviewAction.FALSE_POSITIVE)
REVIEW_END_STATE_VALUES = {s.value for s in REVIEW_END_STATES}


class QaStatus(str, Enum):
    OK = "ok"
    REPAIRED = "repaired_invalid_geometry"
    EMPTY_REMOVED = "removed_empty_geometry"
    UNSUPPORTED_TYPE = "unsupported_geometry_type"


# Normalized observation schema field names (single source of truth used by
# data_loader.py, geometry_utils.py, and downstream modules).
OBSERVATION_SCHEMA_FIELDS = [
    "observation_id",
    "source_year",
    "observation_date",
    "geometry",
    "area_m2",
    "imagery_source",
    "annotation_confidence",
    "qa_status",
    "parcel_id",
    "raw_name",
]

CHANGE_RECORD_FIELDS = [
    "change_id",
    "installation_id_2020",
    "installation_id_2025",
    "change_type",
    "match_score",
    "iou",
    "overlap_ratio_2020",
    "overlap_ratio_2025",
    "centroid_distance_m",
    "area_2020_m2",
    "area_2025_m2",
    "area_change_m2",
    "area_change_percent",
    "classification_reason",
    "review_required",
    "detection_confidence",
]


@dataclass
class ReviewDecision:
    """A reviewer's current disposition of an alert, plus its state history.

    Persisted via ``src.review_store`` (session state today; file/DB later).
    ``history`` records every state the case has passed through, each with
    the date/time it was entered, so the Alert Inbox can show a full audit
    trail — not just the current state.
    """

    alert_id: str
    state: ReviewAction = ReviewAction.FOR_INSPECTION
    notes: str = ""
    assigned_to: str = ""
    state_changed_at: Optional[datetime] = None
    history: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "state": self.state.value if isinstance(self.state, ReviewAction) else self.state,
            "notes": self.notes,
            "assigned_to": self.assigned_to,
            "state_changed_at": self.state_changed_at.isoformat() if self.state_changed_at else "",
            "history": self.history,
        }

    @staticmethod
    def from_dict(d: dict) -> "ReviewDecision":
        state_changed_at = None
        if d.get("state_changed_at"):
            try:
                state_changed_at = datetime.fromisoformat(d["state_changed_at"])
            except ValueError:
                state_changed_at = None
        try:
            state = ReviewAction(d.get("state", ReviewAction.FOR_INSPECTION.value))
        except ValueError:
            state = ReviewAction.FOR_INSPECTION
        return ReviewDecision(
            alert_id=d["alert_id"],
            state=state,
            notes=d.get("notes", ""),
            assigned_to=d.get("assigned_to", ""),
            state_changed_at=state_changed_at,
            history=d.get("history", []),
        )


@dataclass
class ExportMetadata:
    """Metadata bundled with every export (CSV/GeoJSON)."""

    source_year_baseline: int
    source_year_latest: int
    processing_date: date
    is_synthetic: bool
    application_version: str
    threshold_config_summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source_year_baseline": self.source_year_baseline,
            "source_year_latest": self.source_year_latest,
            "processing_date": self.processing_date.isoformat(),
            "is_synthetic": self.is_synthetic,
            "application_version": self.application_version,
            "threshold_config": self.threshold_config_summary,
        }
