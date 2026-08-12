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

from src.config import load_config
from src.pipeline import get_pipeline_result
from src.ui_components import (
    _icon_svg,
    kpi_row,
    render_app_header,
    render_disclaimer,
    render_footer,
    render_html,
    section_title,
)

st.set_page_config(page_title="Solance", page_icon="☀️", layout="wide")

config = load_config()
render_app_header(config)

render_disclaimer(
    "This demonstration identifies geospatial changes that may warrant utility verification. "
    "It does not determine legal, permitting, registration, ownership, export, safety, or "
    "interconnection status."
)

# --- What Solance delivers (3-pillar value story) -----------------------------
# Mirrors the utility's own inputs -> Solance -> outcomes workflow: this is
# the first thing a reviewer sees, before picking a data source.
section_title("What Solance delivers", "Three inputs — registration records, satellite imagery, feeder/transformer data — feed one workflow with three outcomes.")
pillar1, pillar2, pillar3 = st.columns(3)

with pillar1:
    render_html(
        f"""
        <div class="pv-card" style="min-height:190px;">
            <div class="pv-kpi-icon" style="margin-bottom:0.5rem;">{_icon_svg("bell", size=18)}</div>
            <b>Dark solar alerting & registration tracking</b>
            <p style="color:#5B6B76;font-size:0.85rem;margin-top:0.4rem;">
                Surface PV systems visible in imagery but not yet confirmed registered ("dark solar"), and track
                each one from field validation through application to registration — closing the loop back into
                your registration inventory.
            </p>
        </div>
        """
    )

with pillar2:
    render_html(
        f"""
        <div class="pv-card" style="min-height:190px;">
            <div class="pv-kpi-icon" style="margin-bottom:0.5rem;">{_icon_svg("building", size=18)}</div>
            <b>Distribution planning intelligence</b>
            <p style="color:#5B6B76;font-size:0.85rem;margin-top:0.4rem;">
                See new and existing PV by transformer_id / feeder_id / installation_id to support distribution
                planning decisions. (Load <i>forecasting</i> needs a time series Solance doesn't have yet with
                only two observation years — see Distribution Planning for details.)
            </p>
        </div>
        """
    )

with pillar3:
    render_html(
        f"""
        <div class="pv-card" style="min-height:190px;">
            <div class="pv-kpi-icon" style="margin-bottom:0.5rem;">{_icon_svg("layers", size=18)}</div>
            <b>Sustainable PV reporting</b>
            <p style="color:#5B6B76;font-size:0.85rem;margin-top:0.4rem;">
                Barangay- and province-level solar PV capacity estimates, rolled up into a summary ready to
                share with management or a regulator.
            </p>
        </div>
        """
    )

st.divider()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIR_2020 = PROJECT_ROOT / config.data_sources.local_kmz_2020_dir
DIR_2025 = PROJECT_ROOT / config.data_sources.local_kmz_2025_dir
local_folder_available = (
    DIR_2020.is_dir() and DIR_2025.is_dir() and any(DIR_2020.glob("*.kmz")) and any(DIR_2025.glob("*.kmz"))
)

if "pv_watch_mode" not in st.session_state:
    st.session_state["pv_watch_mode"] = "local_folder" if local_folder_available else "demo"

section_title("Data source")

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
    st.caption(
        f"Automatically loading and merging **{n_2020}** {config.app.observation_year_baseline} KMZ file(s) from "
        f"`{config.data_sources.local_kmz_2020_dir}` and **{n_2025}** {config.app.observation_year_latest} KMZ file(s) "
        f"from `{config.data_sources.local_kmz_2025_dir}` — each file's barangay name comes from its filename."
    )
    st.session_state.pop("pv_watch_kmz_2020_bytes", None)
    st.session_state.pop("pv_watch_kmz_2025_bytes", None)
    st.session_state["pv_watch_crs_override"] = None

elif mode == "demo":
    st.session_state.pop("pv_watch_kmz_2020_bytes", None)
    st.session_state.pop("pv_watch_kmz_2025_bytes", None)
    st.session_state["pv_watch_crs_override"] = None
    st.caption(
        f"Using synthetic demonstration data resembling a small Philippine urban area "
        f"({config.synthetic_demo.town_name}). These geometries are fictional and do not represent real PV installations."
    )

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

    with st.expander("Advanced: projected CRS for area calculation"):
        st.caption(
            "Solance auto-selects an appropriate UTM zone from your data's centroid for area/distance "
            "calculations. Override it here only if you need a specific projected CRS (e.g. a local grid)."
        )
        crs_input = st.text_input("Projected CRS (e.g. EPSG:32651)", value="", key="crs_override_input")
        st.session_state["pv_watch_crs_override"] = crs_input.strip() or None

    ready = bool(st.session_state.get("pv_watch_kmz_2020_bytes")) and bool(st.session_state.get("pv_watch_kmz_2025_bytes"))
    if not ready:
        st.info("Upload both a 2020 and a 2025 KMZ file to run the comparison, or switch to another data source above.")

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
    section_title("Snapshot", f"Projected CRS used for area/distance calculations: `{result.projected_crs_used}`")
    n_new = int((result.change_df["change_type"] == "Newly observed").sum())
    n_alerts = len(result.alerts_df)
    kpi_row(
        [
            (f"{config.app.observation_year_latest} installations", f"{len(result.installations_2025):,}", "Total installations in the latest inventory."),
            ("Newly observed", f"{n_new:,}", "First observed in the latest imagery — the headline change signal."),
            ("Alerts generated", f"{n_alerts:,}", "Cases requiring reviewer verification — see Dark Solar Alerts."),
        ]
    )

    st.success(
        "Analysis complete. Use the sidebar to open **Overview**, **PV Change Explorer**, "
        "**Dark Solar Alerts**, **Distribution Planning**, **Sustainable Reporting**, or **Methodology** — "
        "or use the cards above."
    )

    if st.button("Re-run pipeline (clear cache)"):
        st.cache_data.clear()
        st.rerun()

    render_footer(config)
else:
    st.stop()
