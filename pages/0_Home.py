"""Home — data source selection + pipeline kick-off.

Formerly the app's entrypoint (``app.py``); relocated here so ``app.py`` can
become a thin ``st.navigation`` router with full control over the sidebar
(custom labels, grouping, and ordering) instead of Streamlit's automatic
``pages/`` navigation. See ``app.py`` for the page list and sidebar chrome —
this file only handles data-source selection and pipeline kick-off. All
analytical logic lives in ``src/`` and all page-specific UI lives in
``pages/`` — see those modules for the actual Solance functionality.

Solance automatically loads the local ``output-kmz/2020`` and
``output-kmz/2025`` folders (every per-barangay .kmz file merged into one
inventory per year) if present — no upload required. Synthetic demo data and
manual KMZ upload remain available as alternatives.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.region import active_config
from src.pipeline import get_pipeline_result, local_kmz_folder_available
from src.ui_components import (
    INK_MUTED,
    _icon_svg,
    kpi_row,
    render_app_header,
    render_footer,
    render_html,
    section_title,
)

st.set_page_config(page_title="Solance", layout="wide")

config = active_config()
render_app_header(config)

# --- What Solance delivers (3-pillar value story) -----------------------------
# One short line per pillar, named to match the sidebar pages — a client
# should recognize where to click next, not read a paragraph to get there.
section_title("What Solance Delivers")
pillar1, pillar2, pillar3 = st.columns(3)

with pillar1:
    render_html(
        f"""
        <div class="pv-card" style="min-height:130px;">
            <div class="pv-kpi-icon" style="margin-bottom:0.5rem;">{_icon_svg("bell", size=18)}</div>
            <b>Dark Solar Alerts</b>
            <p style="color:{INK_MUTED};font-size:0.85rem;margin-top:0.4rem;">
                Every unregistered system, tracked to resolution.
            </p>
        </div>
        """
    )

with pillar2:
    render_html(
        f"""
        <div class="pv-card" style="min-height:130px;">
            <div class="pv-kpi-icon" style="margin-bottom:0.5rem;">{_icon_svg("building", size=18)}</div>
            <b>Distribution Planning</b>
            <p style="color:{INK_MUTED};font-size:0.85rem;margin-top:0.4rem;">
                PV load by transformer and feeder, ranked by exposure.
            </p>
        </div>
        """
    )

with pillar3:
    render_html(
        f"""
        <div class="pv-card" style="min-height:130px;">
            <div class="pv-kpi-icon" style="margin-bottom:0.5rem;">{_icon_svg("layers", size=18)}</div>
            <b>Sustainability Reporting</b>
            <p style="color:{INK_MUTED};font-size:0.85rem;margin-top:0.4rem;">
                Verified capacity, rolled up and export-ready.
            </p>
        </div>
        """
    )

st.divider()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIR_2020 = PROJECT_ROOT / config.data_sources.local_kmz_2020_dir
DIR_2025 = PROJECT_ROOT / config.data_sources.local_kmz_2025_dir
# Shared with get_pipeline_result()'s own default-mode fallback (src/pipeline.py)
# so the two checks can't drift apart again — that drift was the actual bug
# behind "sometimes it's demo data instead of local KMZ."
local_folder_available = local_kmz_folder_available(config)

if "pv_watch_mode" not in st.session_state:
    st.session_state["pv_watch_mode"] = "local_folder" if local_folder_available else "demo"

section_title("Data Source")

mode_options = (["Local KMZ folder (real data)"] if local_folder_available else []) + [
    "Synthetic demo data",
    "Upload my own KMZ files",
]
mode_key_by_label = {
    "Local KMZ folder (real data)": "local_folder",
    "Synthetic demo data": "demo",
    "Upload my own KMZ files": "upload",
}
label_by_mode_key = {v: k for k, v in mode_key_by_label.items()}
current_label = label_by_mode_key.get(st.session_state["pv_watch_mode"], mode_options[0])

mode_label = st.radio(
    "Data source", options=mode_options, horizontal=True, label_visibility="collapsed",
    index=mode_options.index(current_label) if current_label in mode_options else 0,
)
st.session_state["pv_watch_mode"] = mode_key_by_label[mode_label]
mode = st.session_state["pv_watch_mode"]

if mode == "local_folder":
    n_2020 = len(list(DIR_2020.glob("*.kmz")))
    n_2025 = len(list(DIR_2025.glob("*.kmz")))
    st.caption(f"**{n_2020 + n_2025}** verified imagery files loaded — {config.app.observation_year_baseline} vs. {config.app.observation_year_latest}.")
    st.session_state.pop("pv_watch_kmz_2020_bytes", None)
    st.session_state.pop("pv_watch_kmz_2025_bytes", None)
    st.session_state["pv_watch_crs_override"] = None

elif mode == "demo":
    st.session_state.pop("pv_watch_kmz_2020_bytes", None)
    st.session_state.pop("pv_watch_kmz_2025_bytes", None)
    st.session_state["pv_watch_crs_override"] = None
    st.caption("Synthetic demo dataset — not real installations.")

else:  # upload
    col1, col2 = st.columns(2)
    with col1:
        f2020 = st.file_uploader(f"{config.app.observation_year_baseline} baseline inventory (.kmz)", type=["kmz"], key="uploader_2020")
        if f2020 is not None:
            st.session_state["pv_watch_kmz_2020_bytes"] = f2020.getvalue()
            st.session_state["pv_watch_kmz_2020_name"] = f2020.name
    with col2:
        f2025 = st.file_uploader(f"{config.app.observation_year_latest} latest inventory (.kmz)", type=["kmz"], key="uploader_2025")
        if f2025 is not None:
            st.session_state["pv_watch_kmz_2025_bytes"] = f2025.getvalue()
            st.session_state["pv_watch_kmz_2025_name"] = f2025.name

    with st.expander("Advanced: projected CRS"):
        crs_input = st.text_input("Projected CRS (e.g. EPSG:32651)", value="", key="crs_override_input")
        st.session_state["pv_watch_crs_override"] = crs_input.strip() or None

    ready = bool(st.session_state.get("pv_watch_kmz_2020_bytes")) and bool(st.session_state.get("pv_watch_kmz_2025_bytes"))
    if not ready:
        st.info("Upload both a 2020 and a 2025 KMZ file to continue.")

result = get_pipeline_result()

if result is not None:
    if result.warnings.has_any:
        with st.expander(f"⚠️ Data quality warnings ({len(result.warnings.baseline) + len(result.warnings.latest)})", expanded=False):
            if result.warnings.baseline:
                st.markdown(f"**{config.app.observation_year_baseline} inventory:**")
                for w in result.warnings.baseline:
                    st.markdown(f"- {w}")
            if result.warnings.latest:
                st.markdown(f"**{config.app.observation_year_latest} inventory:**")
                for w in result.warnings.latest:
                    st.markdown(f"- {w}")

    st.divider()
    section_title("Snapshot")
    n_new = int((result.change_df["change_type"] == "Newly observed").sum())
    n_alerts = len(result.alerts_df)
    capacity_kw = float(result.installations_2025["estimated_capacity_kw"].sum()) if not result.installations_2025.empty else 0.0
    kpi_row(
        [
            (f"{config.app.observation_year_latest} installations", f"{len(result.installations_2025):,}", "Total installations in the latest inventory."),
            ("Newly observed", f"{n_new:,}", "First observed in the latest imagery — the headline change signal."),
            ("Estimated capacity", f"{capacity_kw:,.0f} kW", "Total estimated PV capacity in the latest inventory."),
            ("Alerts generated", f"{n_alerts:,}", "Cases requiring reviewer verification — see Dark Solar Alerts."),
        ]
    )

    if st.button("Re-run pipeline (clear cache)"):
        st.cache_data.clear()
        st.rerun()

    render_footer(config)
else:
    st.stop()
