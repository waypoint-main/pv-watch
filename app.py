"""PV Watch — entrypoint / navigation router.

This file no longer holds page content (that moved to ``pages/0_Home.py``).
It now only does two things, per Streamlit's ``st.navigation`` pattern
("your entrypoint file acts like a router or frame of common elements
around each of your pages"):

1. Declares every page via ``st.Page`` and registers them with
   ``st.navigation`` (``position="hidden"`` — Streamlit's own auto-generated
   nav list can't be reordered, grouped, or selectively styled, so it's
   turned off in favor of the fully custom sidebar built below).
2. Renders the sidebar chrome that's common to every page: a hand-built
   nav list using ``st.page_link`` — grouped, spaced, and labeled exactly
   as requested, which ``st.page_link`` supports because its ``label``
   accepts GitHub-flavored Markdown (bold, etc.) — followed by the
   PV Watch / Waypoint brand credit block, anchored to the bottom of the
   sidebar rather than the top.

Requires Streamlit >= 1.36 (``st.navigation``/``st.Page`` — see
requirements.txt).
"""

from __future__ import annotations

import streamlit as st

from src.config import load_config
from src.ui_components import render_sidebar_brand, render_sidebar_html

config = load_config()

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

# Company/product brand credit — anchored to the bottom of the sidebar
# (lower-left of the screen), below all navigation, not above it.
render_sidebar_brand(config)

pg.run()
