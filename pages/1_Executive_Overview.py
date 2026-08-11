"""Page 1 — Executive Overview.

Primary message: where is distributed solar growing beyond what the utility
may currently see in its internal records?
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_folium import st_folium

from src.config import load_config
from src.models import REVIEW_END_STATE_VALUES, ChangeType, Priority
from src.pipeline import get_pipeline_result
from src.review_store import apply_decisions_to_alerts
from src.ui_components import (
    CHANGE_TYPE_COLORS,
    CHANGE_TYPE_EMPHASIS,
    PRIORITY_COLORS,
    add_polygon_layer,
    kpi_row,
    make_base_map,
    render_app_header,
    render_disclaimer,
    render_footer,
    render_map_legend,
    section_title,
    size_class,
)

st.set_page_config(page_title="PV Watch — Executive Overview", page_icon="☀️", layout="wide")
config = load_config()
render_app_header(config, "Executive Overview")

result = get_pipeline_result()
if result is None:
    st.info("Choose a data source on the main **PV Watch** page first (demo data or upload two KMZ files).")
    st.stop()

change_df = result.change_df
installations_2025 = result.installations_2025
installations_2020 = result.installations_2020
alerts_df = apply_decisions_to_alerts(result.alerts_df)

n_2020 = len(installations_2020)
n_2025 = len(installations_2025)
n_new = int((change_df["change_type"] == ChangeType.NEWLY_OBSERVED.value).sum())
pct_growth = ((n_2025 - n_2020) / n_2020 * 100) if n_2020 else 0.0
new_area_m2 = change_df.loc[change_df["change_type"] == ChangeType.NEWLY_OBSERVED.value, "area_2025_m2"].sum()
new_capacity_kw = new_area_m2 * config.capacity_estimation.kw_per_m2
unresolved_high_priority = int(
    (
        (alerts_df["priority"].isin([Priority.P1.value, Priority.P2.value]))
        & (~alerts_df["review_status"].isin(REVIEW_END_STATE_VALUES))
    ).sum()
) if not alerts_df.empty else 0

top_zone = "—"
if not installations_2025.empty and "barangay" in installations_2025.columns:
    new_ids = set(change_df.loc[change_df["change_type"] == ChangeType.NEWLY_OBSERVED.value, "installation_id_2025"])
    new_installs = installations_2025[installations_2025["installation_id"].isin(new_ids)]
    if not new_installs.empty:
        counts = new_installs.groupby("barangay").size().sort_values(ascending=False)
        if len(counts):
            top_zone = f"{counts.index[0]} ({int(counts.iloc[0])} new)"

section_title("Where is distributed solar growing beyond what the utility may currently see in its records?")

tab_overview, tab_map, tab_trends = st.tabs(["Overview", "Map", "Trends"])

with tab_overview:
    # Kept to four cards, each a genuine insight or a direct call to action —
    # raw installation counts and duplicate area/capacity figures live on the
    # Map/Trends tabs and the Sustainable PV Reporting page instead.
    kpi_row(
        [
            ("Newly observed", f"{n_new:,}", "First observed in the latest imagery with no credible match in the baseline."),
            ("Installation count growth", f"{pct_growth:+.0f}%", "(2025 count − 2020 count) / 2020 count."),
            ("Estimated new capacity", f"{new_capacity_kw:,.1f} kW (est.)", "Area × configurable kW/m² factor — an estimate, not utility-confirmed."),
            ("Unresolved P1/P2 alerts", f"{unresolved_high_priority:,}", "Priority 1 or 2 alerts whose case is still open (not Registered or False positive)."),
        ]
    )
    st.caption(f"Zone with the most newly observed installations: **{top_zone}**")

    render_disclaimer(
        "Newly observed installations were first observed in the "
        f"{config.app.observation_year_latest} imagery, with a possible installation window between the "
        f"{config.app.observation_year_baseline} and {config.app.observation_year_latest} observation dates. "
        "This does not imply the system was installed in 2025, nor does it determine registration status — "
        "verify registration and grid-interconnection status before taking action."
    )

    if unresolved_high_priority > 0:
        st.warning(
            f"**{unresolved_high_priority} Priority 1/2 alert(s)** are unresolved — open the "
            "**Dark Solar Alerts** page to review and decide on them."
        )

with tab_map:
    section_title("Change-classification map", "Every installation, colored by how it changed between the two observation years.")
    change_types_in_order = [
        ChangeType.EXISTING.value, ChangeType.POTENTIALLY_REMOVED.value, ChangeType.UNCERTAIN.value,
        ChangeType.EXPANDED.value, ChangeType.NEWLY_OBSERVED.value,
    ]
    render_map_legend([(ct, CHANGE_TYPE_COLORS[ct]) for ct in change_types_in_order], title="Change type:")
    m = make_base_map(result.center_lat, result.center_lon, zoom=15)
    for ct in change_types_in_order:
        if ct == ChangeType.POTENTIALLY_REMOVED.value:
            ids = change_df.loc[change_df["change_type"] == ct, "installation_id_2020"]
            subset = installations_2020[installations_2020["installation_id"].isin(ids)]
        else:
            ids = change_df.loc[change_df["change_type"] == ct, "installation_id_2025"]
            subset = installations_2025[installations_2025["installation_id"].isin(ids)]
        weight, fill_opacity = CHANGE_TYPE_EMPHASIS.get(ct, (1.5, 0.55))
        add_polygon_layer(
            m, subset, CHANGE_TYPE_COLORS[ct], ct,
            tooltip_fields=["installation_id", "barangay", "area_m2", "estimated_capacity_kw"],
            tooltip_aliases=["Installation ID", "Barangay", "Area (m²)", "Est. capacity (kW)"],
            weight=weight, fill_opacity=fill_opacity,
        )
    from folium import LayerControl

    LayerControl(collapsed=False).add_to(m)
    st_folium(m, use_container_width=True, height=560, key="exec_overview_map", returned_objects=[])
    st.caption("Use the layer control (top right) to isolate a single change type, or the fullscreen icon to expand the map.")

with tab_trends:
    col_a, col_b = st.columns(2)
    with col_a:
        section_title("Growth by barangay")
        if not installations_2025.empty:
            g2020 = installations_2020.groupby("barangay").size().rename("2020")
            g2025 = installations_2025.groupby("barangay").size().rename("2025")
            growth_df = pd.concat([g2020, g2025], axis=1).fillna(0).reset_index()
            growth_melt = growth_df.melt(id_vars="barangay", var_name="Year", value_name="Installations")
            fig = px.bar(growth_melt, x="barangay", y="Installations", color="Year", barmode="group")
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=340)
            st.plotly_chart(fig, use_container_width=True)

    with col_b:
        section_title("Change-type distribution")
        dist = change_df["change_type"].value_counts().reset_index()
        dist.columns = ["change_type", "count"]
        fig = px.bar(
            dist, x="change_type", y="count", color="change_type", color_discrete_map=CHANGE_TYPE_COLORS
        )
        fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=10, b=10), height=340)
        st.plotly_chart(fig, use_container_width=True)

    col_c, col_d = st.columns(2)
    with col_c:
        section_title("New installations by size class")
        new_ids = change_df.loc[change_df["change_type"] == ChangeType.NEWLY_OBSERVED.value, "installation_id_2025"]
        new_installs = installations_2025[installations_2025["installation_id"].isin(new_ids)].copy()
        if not new_installs.empty:
            new_installs["size_class"] = new_installs["area_m2"].apply(size_class)
            counts = new_installs["size_class"].value_counts().reset_index()
            counts.columns = ["size_class", "count"]
            fig = px.bar(counts, x="size_class", y="count")
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=320)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No newly observed installations in this dataset.")

    with col_d:
        section_title("Alerts by priority")
        if not alerts_df.empty:
            counts = alerts_df["priority"].value_counts().reindex([p.value for p in Priority]).fillna(0).reset_index()
            counts.columns = ["priority", "count"]
            fig = px.bar(counts, x="priority", y="count", color="priority", color_discrete_map=PRIORITY_COLORS)
            fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=10, b=10), height=320)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No alerts were generated for this dataset.")

    col_e, col_f = st.columns(2)
    with col_e:
        section_title("Alerts by review status")
        if not alerts_df.empty:
            counts = alerts_df["review_status"].value_counts().reset_index()
            counts.columns = ["review_status", "count"]
            fig = px.bar(counts, x="review_status", y="count")
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=320)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No alerts were generated for this dataset.")

    with col_f:
        section_title("Top PV-growth hotspots")
        if not installations_2025.empty:
            new_ids = change_df.loc[change_df["change_type"] == ChangeType.NEWLY_OBSERVED.value, "installation_id_2025"]
            new_installs = installations_2025[installations_2025["installation_id"].isin(new_ids)]
            if not new_installs.empty:
                hotspots = (
                    new_installs.groupby("barangay")
                    .agg(new_installations=("installation_id", "count"), new_area_m2=("area_m2", "sum"))
                    .sort_values("new_installations", ascending=False)
                    .head(5)
                    .reset_index()
                )
                hotspots["new_area_m2"] = hotspots["new_area_m2"].round(0)
                st.dataframe(hotspots, use_container_width=True, hide_index=True)
            else:
                st.caption("No newly observed installations in this dataset.")

render_footer(config)
