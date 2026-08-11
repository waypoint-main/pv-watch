"""Persistence for alert review decisions.

For this MVP, review decisions are stored in ``st.session_state`` (so the UI
updates instantly) and mirrored to a small local JSON file so decisions
survive an app restart during a demo. Both are wrapped behind the
``ReviewStore`` interface so a future phase can swap in a real database
(e.g. Postgres/SQLite) without touching any page code — pages only ever call
``get_review_store()``, ``get_decision()``, and ``save_decision()``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import streamlit as st

from src.models import ReviewAction, ReviewDecision

logger = logging.getLogger("pv_watch.review_store")

DEFAULT_REVIEW_FILE = Path(__file__).resolve().parent.parent / "data" / "processed" / "review_decisions.json"
SESSION_KEY = "pv_watch_review_decisions"


class ReviewStore(ABC):
    """Abstract interface for persisting alert review decisions.

    Swapping this MVP's session-state/file-backed implementation for a real
    database later only requires implementing this interface and updating
    ``get_review_store()``.
    """

    @abstractmethod
    def get(self, alert_id: str) -> ReviewDecision: ...

    @abstractmethod
    def set(self, decision: ReviewDecision) -> None: ...

    @abstractmethod
    def all(self) -> dict[str, ReviewDecision]: ...


class SessionFileReviewStore(ReviewStore):
    """Session-state-backed store with best-effort JSON file mirroring."""

    def __init__(self, file_path: Path = DEFAULT_REVIEW_FILE):
        self.file_path = file_path
        if SESSION_KEY not in st.session_state:
            st.session_state[SESSION_KEY] = self._load_from_file()

    def _load_from_file(self) -> dict[str, dict]:
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not read review decisions file (%s); starting fresh.", exc)
        return {}

    def _persist(self) -> None:
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as fh:
                json.dump(st.session_state[SESSION_KEY], fh, indent=2)
        except OSError as exc:  # pragma: no cover - defensive, non-fatal
            logger.warning("Could not persist review decisions to file (%s).", exc)

    def get(self, alert_id: str) -> ReviewDecision:
        raw = st.session_state[SESSION_KEY].get(alert_id)
        if raw is None:
            return ReviewDecision(alert_id=alert_id)
        return ReviewDecision.from_dict(raw)

    def set(self, decision: ReviewDecision) -> None:
        """Persist a decision, logging the date/time whenever its state changes.

        Editing only the notes/assignee on an unchanged state does not add a
        new history entry — only an actual state transition does, so the
        history stays a clean record of case progress.
        """
        previous_raw = st.session_state[SESSION_KEY].get(decision.alert_id)
        now = datetime.now()
        new_state_value = decision.state.value if isinstance(decision.state, ReviewAction) else decision.state

        if previous_raw is None or previous_raw.get("state") != new_state_value:
            history = list(previous_raw.get("history", [])) if previous_raw else []
            history.append({"state": new_state_value, "changed_at": now.isoformat()})
            decision.history = history
            decision.state_changed_at = now
        else:
            decision.history = previous_raw.get("history", [])
            prior_changed_at = previous_raw.get("state_changed_at")
            decision.state_changed_at = datetime.fromisoformat(prior_changed_at) if prior_changed_at else now

        st.session_state[SESSION_KEY][decision.alert_id] = decision.to_dict()
        self._persist()

    def all(self) -> dict[str, ReviewDecision]:
        return {aid: ReviewDecision.from_dict(d) for aid, d in st.session_state[SESSION_KEY].items()}


def get_review_store() -> ReviewStore:
    """Return the (session-scoped) review store instance for this app run."""
    return SessionFileReviewStore()


def get_decision(alert_id: str) -> ReviewDecision:
    return get_review_store().get(alert_id)


def save_decision(alert_id: str, state: ReviewAction | str, notes: str = "", assigned_to: str = "") -> None:
    if isinstance(state, str):
        state = ReviewAction(state)
    get_review_store().set(ReviewDecision(alert_id=alert_id, state=state, notes=notes, assigned_to=assigned_to))


# --- Synthetic case-state seeding (demonstration only) -------------------------
#
# A freshly generated alert list starts 100% "For inspection", which does not
# read as an actively managed queue. To demonstrate the case-management
# workflow (grouping by state, a state-change history log, etc.) with
# realistic-looking data, every alert that has no real reviewer decision yet
# is seeded with a deterministic — stable across reruns, but effectively
# random per alert — starting state, assigned reviewer, and backdated state
# history. This never overwrites an alert that already has a real decision
# recorded, so nothing a reviewer actually does is ever lost or altered.
_SYNTHETIC_STATE_WEIGHTS: list[tuple[ReviewAction, float]] = [
    (ReviewAction.FOR_INSPECTION, 0.34),
    (ReviewAction.FOR_REGISTRATION, 0.20),
    (ReviewAction.ONGOING_REGISTRATION, 0.16),
    (ReviewAction.REGISTERED, 0.20),
    (ReviewAction.FALSE_POSITIVE, 0.10),
]

_SYNTHETIC_STATE_PATH: dict[ReviewAction, list[ReviewAction]] = {
    ReviewAction.FOR_INSPECTION: [ReviewAction.FOR_INSPECTION],
    ReviewAction.FOR_REGISTRATION: [ReviewAction.FOR_INSPECTION, ReviewAction.FOR_REGISTRATION],
    ReviewAction.ONGOING_REGISTRATION: [ReviewAction.FOR_INSPECTION, ReviewAction.FOR_REGISTRATION, ReviewAction.ONGOING_REGISTRATION],
    ReviewAction.REGISTERED: [
        ReviewAction.FOR_INSPECTION, ReviewAction.FOR_REGISTRATION, ReviewAction.ONGOING_REGISTRATION, ReviewAction.REGISTERED,
    ],
    ReviewAction.FALSE_POSITIVE: [ReviewAction.FOR_INSPECTION, ReviewAction.FALSE_POSITIVE],
}

_SYNTHETIC_NOTES: dict[ReviewAction, str] = {
    ReviewAction.FOR_INSPECTION: "",
    ReviewAction.FOR_REGISTRATION: "Field inspection complete; registration application being prepared.",
    ReviewAction.ONGOING_REGISTRATION: "Application submitted to the registration desk; awaiting processing.",
    ReviewAction.REGISTERED: "Registration confirmed with the utility. Case closed.",
    ReviewAction.FALSE_POSITIVE: "Reviewed and determined not to be a valid new PV installation. Case closed.",
}

_SYNTHETIC_ASSIGNEES = ["J. Santos (Field Ops)", "M. Reyes (Registration Desk)", "A. Cruz (Technical Review)"]


def _deterministic_rng(seed_text: str) -> random.Random:
    """A Random instance seeded from a stable hash of ``seed_text``.

    Using a hash-derived seed (rather than the system clock) means the same
    alert_id always gets the same synthetic state across reruns within a
    demo, instead of visibly reshuffling every time the page refreshes.
    """
    digest = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def seed_synthetic_review_states(alerts_df) -> None:
    """Give every alert without a real decision yet a synthetic starting state.

    Safe to call on every rerun — alerts that already have a decision
    (synthetic or a real reviewer action) are left untouched.
    """
    if alerts_df is None or alerts_df.empty or "alert_id" not in alerts_df.columns:
        return
    existing = st.session_state.setdefault(SESSION_KEY, {})
    alert_ids = [aid for aid in alerts_df["alert_id"].tolist() if aid not in existing]
    if not alert_ids:
        return

    states = [s for s, _ in _SYNTHETIC_STATE_WEIGHTS]
    weights = [w for _, w in _SYNTHETIC_STATE_WEIGHTS]
    now = datetime.now()

    for alert_id in alert_ids:
        rng = _deterministic_rng(alert_id)
        target_state = rng.choices(states, weights=weights, k=1)[0]
        path = _SYNTHETIC_STATE_PATH[target_state]

        cursor = now - timedelta(days=rng.randint(14, 120))
        history = []
        for state in path:
            history.append({"state": state.value, "changed_at": cursor.isoformat()})
            cursor = cursor + timedelta(days=rng.randint(3, 18))
        state_changed_at = datetime.fromisoformat(history[-1]["changed_at"])

        decision = ReviewDecision(
            alert_id=alert_id,
            state=target_state,
            notes=_SYNTHETIC_NOTES.get(target_state, ""),
            assigned_to="" if target_state == ReviewAction.FOR_INSPECTION else rng.choice(_SYNTHETIC_ASSIGNEES),
            state_changed_at=state_changed_at,
            history=history,
        )
        existing[alert_id] = decision.to_dict()

    SessionFileReviewStore()._persist()


def apply_decisions_to_alerts(alerts_df):
    """Return a copy of ``alerts_df`` with live review decisions overlaid.

    The pipeline's cached ``alerts_df`` always starts every alert at "For
    inspection"; this first seeds any un-seeded alert with a synthetic
    starting state (see :func:`seed_synthetic_review_states`) so the queue
    looks actively managed, then overlays whatever the reviewer has since
    recorded — without ever invalidating/recomputing the underlying
    analytical pipeline.
    """
    if alerts_df is None or alerts_df.empty:
        return alerts_df
    seed_synthetic_review_states(alerts_df)
    decisions = get_review_store().all()
    if not decisions:
        return alerts_df
    df = alerts_df.copy()
    for alert_id, decision in decisions.items():
        mask = df["alert_id"] == alert_id
        if mask.any():
            df.loc[mask, "review_status"] = decision.state.value
            df.loc[mask, "assigned_to"] = decision.assigned_to or df.loc[mask, "assigned_to"]
            df.loc[mask, "reviewer_notes"] = decision.notes
            df.loc[mask, "state_changed_at"] = decision.state_changed_at.isoformat() if decision.state_changed_at else ""
    return df


def all_decisions_df():
    """Return all review decisions as a small DataFrame (for export)."""
    import pandas as pd

    decisions = get_review_store().all()
    if not decisions:
        return pd.DataFrame(columns=["alert_id", "state", "notes", "assigned_to", "state_changed_at"])
    rows = [
        {k: v for k, v in d.to_dict().items() if k != "history"}
        for d in decisions.values()
    ]
    return pd.DataFrame(rows)
