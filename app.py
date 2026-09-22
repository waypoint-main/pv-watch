"""Solance — entrypoint / navigation router.

This file no longer holds page content (that moved to ``pages/0_Home.py``).
It now does three things, per Streamlit's ``st.navigation`` pattern
("your entrypoint file acts like a router or frame of common elements
around each of your pages"):

1. Gates the whole app behind a simple region picker (see
   ``_render_region_gate`` below) — Solance now serves two independently-
   scoped datasets, Santa Rosa/Laguna and Makati City, from one deployment,
   and a reviewer should only ever see the one they're working with. This
   is a lightweight split, not real authentication.
2. Declares every page via ``st.Page`` and registers them with
   ``st.navigation`` (``position="hidden"`` — Streamlit's own auto-generated
   nav list can't be reordered, grouped, or selectively styled, so it's
   turned off in favor of the fully custom sidebar built below).
3. Renders the sidebar chrome that's common to every page: a hand-built
   nav list using ``st.page_link`` — grouped, spaced, and labeled exactly
   as requested, which ``st.page_link`` supports because its ``label``
   accepts GitHub-flavored Markdown (bold, etc.) — followed by the active
   region indicator and the Solance / Waypoint brand credit block, both
   anchored to the bottom of the sidebar rather than the top.

Requires Streamlit >= 1.36 (``st.navigation``/``st.Page`` — see
requirements.txt).
"""

from __future__ import annotations

import streamlit as st

from src.region import REGION_LABELS, active_config, active_region, log_out, set_region
from src.ui_components import inject_base_style, render_sidebar_brand, render_sidebar_html


def _render_region_gate() -> None:
    """Simple region gate: type "makati" or "laguna" to pick which region's
    dataset to view for the rest of the session.

    This is intentionally NOT real authentication (no accounts, no
    passwords, nothing sensitive gated) — it exists only so a Makati
    reviewer doesn't land in Laguna's data (or vice versa) by accident, and
    so each region's data source / upload state stays scoped to itself.
    """
    st.set_page_config(page_title="Solance — Region Access", page_icon="☀️", layout="centered")
    inject_base_style()  # shared fonts/button styling, so the gate matches the rest of the app
    st.markdown("<div style='height:10vh;'></div>", unsafe_allow_html=True)
    st.markdown("## ☀️ Solance")
    st.caption("Distributed Solar Change Intelligence")
    st.write("")
    st.markdown("**Enter your region to continue.**")
    with st.form("region_gate_form", clear_on_submit=False):
        code = st.text_input(
            "Region code", placeholder="makati or laguna", label_visibility="collapsed"
        )
        submitted = st.form_submit_button("Continue", use_container_width=True)
    if submitted:
        if set_region(code):
            st.rerun()
        else:
            st.error("Unrecognized region. Enter **makati** or **laguna**.")


if active_region() is None:
    _render_region_gate()
    st.stop()

config = active_config()

home_page = st.Page("pages/0_Home.py", title="Home", default=True)
overview_page = st.Page("pages/1_Executive_Overview.py", title="Overview")
explorer_page = st.Page("pages/2_PV_Change_Explorer.py", title="PV Change Explorer")
alerts_page = st.Page("pages/3_Dark_Solar_Alerts.py", title="Dark Solar Alerts")
planning_page = st.Page("pages/4_Distribution_Planning.py", title="Distribution Planning")
reporting_page = st.Page("pages/5_Sustainable_PV_Reporting.py", title="Sustainable Reporting")
methodology_page = st.Page("pages/6_Methodology.py", title="Methodology")

pg = st.navigation(
    [home_page, overview_page, explorer_page, alerts_page, planning_page, reporting_page, methodology_page],
    position="hidden",
)

# --- Sidebar chrome (rendered on every page, since this router script runs
# on every app rerun regardless of which page is active) -------------------
st.sidebar.page_link(overview_page, label="**Overview**")
render_sidebar_html('<div style="height:0.9rem;"></div>')  # space Overview apart from the group below

render_sidebar_html('<div class="pv-nav-section-title">Explore, Alert & Report</div>')
_chevron = ":material/chevron_right:"
st.sidebar.page_link(explorer_page, label="PV Change Explorer", icon=_chevron)
st.sidebar.page_link(alerts_page, label="Dark Solar Alerts", icon=_chevron)
st.sidebar.page_link(planning_page, label="Distribution Planning", icon=_chevron)
st.sidebar.page_link(reporting_page, label="Sustainable Reporting", icon=_chevron)

render_sidebar_html('<div class="pv-nav-divider"></div>')
st.sidebar.page_link(home_page, label="Home")
st.sidebar.page_link(methodology_page, label="Methodology")

# --- Active region indicator + switcher -------------------------------------
render_sidebar_html('<div class="pv-nav-divider"></div>')
_region_key = active_region()
st.sidebar.caption(f"Region: **{REGION_LABELS.get(_region_key, _region_key)}**")
if st.sidebar.button("Switch region", use_container_width=True):
    log_out()
    st.rerun()

# Company/product brand credit — anchored to the bottom of the sidebar
# (lower-left of the screen), below all navigation, not above it.
render_sidebar_brand(config)

pg.run()
