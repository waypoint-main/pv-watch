"""Region selection — Solance serves two independently-scoped datasets
(Santa Rosa, Laguna and Makati City) from one deployment, gated behind a
simple region picker in ``app.py`` (see ``render_region_gate`` there).

This module is the single source of truth mapping the selected region to its
settings file and local KMZ inventory, so every page reads the correct,
region-scoped configuration without duplicating that mapping — and so the
underlying pipeline cache (keyed in part on ``config_path``, see
``src.pipeline.run_pipeline``) naturally keeps the two regions' analysis
results separate.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st

from src.config import AppConfig, load_config

SESSION_KEY = "pv_watch_region"

REGION_CONFIG_PATHS: dict[str, str] = {
    "laguna": "config/settings.yaml",
    "makati": "config/settings_makati.yaml",
}
REGION_LABELS: dict[str, str] = {
    "laguna": "Santa Rosa, Laguna",
    "makati": "Makati City",
}
DEFAULT_REGION = "laguna"

# Session-state keys scoped to a single region's data-source selection —
# cleared whenever the active region changes so an upload or mode choice
# made under one region can't leak into the other.
_DATA_SOURCE_SESSION_KEYS = (
    "pv_watch_mode",
    "pv_watch_kmz_2020_bytes",
    "pv_watch_kmz_2025_bytes",
    "pv_watch_kmz_2020_name",
    "pv_watch_kmz_2025_name",
    "pv_watch_crs_override",
)


def active_region() -> Optional[str]:
    """The currently logged-in region key ('laguna'/'makati'), or ``None``
    if no region has been selected yet (i.e. the login gate hasn't passed)."""
    return st.session_state.get(SESSION_KEY)


def active_config_path() -> str:
    """Settings YAML path for the active region (falls back to the default
    region if none is set yet, so pages behave sensibly even if opened
    directly before the gate normally runs)."""
    region = st.session_state.get(SESSION_KEY, DEFAULT_REGION)
    return REGION_CONFIG_PATHS.get(region, REGION_CONFIG_PATHS[DEFAULT_REGION])


def active_config() -> AppConfig:
    """Load the ``AppConfig`` for the active region."""
    return load_config(active_config_path())


def set_region(region: str) -> bool:
    """Log into ``region`` ('laguna' or 'makati', case-insensitive).

    Clears any data-source selection left over from a previous region so
    the new region starts fresh (defaulting to its own local KMZ folder).
    Returns ``True`` on success, ``False`` if ``region`` isn't recognized.
    """
    key = region.strip().lower()
    if key not in REGION_CONFIG_PATHS:
        return False
    if st.session_state.get(SESSION_KEY) != key:
        for k in _DATA_SOURCE_SESSION_KEYS:
            st.session_state.pop(k, None)
    st.session_state[SESSION_KEY] = key
    return True


def log_out() -> None:
    """Clear the active region and any region-scoped data-source state,
    returning the app to the login gate."""
    st.session_state.pop(SESSION_KEY, None)
    for k in _DATA_SOURCE_SESSION_KEYS:
        st.session_state.pop(k, None)
