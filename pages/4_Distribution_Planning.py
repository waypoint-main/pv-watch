"""Page 4 — Distribution Planning (formerly "Grid Planning").

Aggregates observed and newly observed PV by transformer, feeder,
municipality, and barangay for planning intelligence. All network data
(transformers, feeders, rated/recorded capacities) and the hosting-capacity
indicator are SYNTHETIC and illustrative only — they do not replace a formal
distribution-impact study or power-flow analysis. Tabs separate the three
planning levels a reviewer works at: transformer (most granular, drives a
"verify/monitor" call), feeder (rollup for prioritizing field visits), and
municipality/barangay (geographic rollup for coordination with local units).

Note on scope: this page supports *distribution planning* (where is new PV
concentrating, which transformers/feeders need a closer look). It does not
do *load forecasting* — that requires a time series of observations, and
Solance currently only has two snapshots (baseline and latest). See the
caption below the header for the honest version of that limitation.
"""

from __future__ import annotations

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src import network_context
from src.region import active_config
from src.export_utils import build_export_metadata, dataframe_to_csv_bytes
from src.models import ChangeType, HostingCapacityStatus
from src.network_context import MONITOR_RATIO, REVIEW_RECOMMENDED_ALERT_COUNT, REVIEW_RECOMMENDED_RATIO
from src.pipeline import get_pipeline_result
from src.review_store import apply_decisions_to_alerts
from src.ui_components import (
    HOSTING_STATUS_COLORS,
    NEUTRAL_BLUE,
    NEUTRAL_BLUE_LIGHT,
    add_polygon_layer,
    factsheet_popup_html,
    make_base_map,
    render_app_header,
    render_disclaimer,
    render_footer,
    render_html,
    render_map_legend,
    render_synthetic_data_notice,
    section_title,
    transformer_marker_icon,
)

# Discrete marker-size tiers (px) by rated capacity — a few fixed steps
# rather than continuous scaling, so markers stay compact instead of
# growing into large blobs for bigger transformers.
_TRANSFORMER_MARKER_TIERS = [(300, 22), (600, 28), (float("inf"), 34)]


def _transformer_marker_size(rated_kva: float) -> int:
    for max_kva, size in _TRANSFORMER_MARKER_TIERS:
        if rated_kva <= max_kva:
            return size
    return _TRANSFORMER_MARKER_TIERS[-1][1]

st.set_page_config(page_title="Solance — Distribution Planning", page_icon="☀️", layout="wide")
config = active_config()
render_app_header(config, "Distribution Planning")

result = get_pipeline_result()
if result is None:
    st.info("Choose a data source on the main **Solance** page first (demo data or upload two KMZ files).")
    st.stop()

render_synthetic_data_notice("feeder, transformer, and registered-capacity")
render_disclaimer(
    "The hosting-capacity indicators below are simple illustrative ratios of observed + estimated PV capacity "
    "to transformer rated capacity. They do NOT replace a formal distribution-impact study or power-flow analysis."
)
st.caption(
    "This page supports **distribution planning** (where new PV is concentrating, by transformer_id / feeder_id / "
    "installation_id). It does not do **load forecasting** — Solance currently compares two snapshots "
    f"({config.app.observation_year_baseline} and {config.app.observation_year_latest}), which isn't enough "
    "history to project future load. A production deployment ingesting imagery on a regular cadence could add "
    "true trend-based forecasting; this demo doesn't overstate what two data points can support."
)

live_alerts = apply_decisions_to_alerts(result.alerts_df)
transformer_summary = network_context.compute_transformer_summary(result.installations_2025, result.transformers, alerts=live_alerts)
transformer_summary = transformer_summary.merge(
    result.transformers[["transformer_id", "feeder_id"]].drop_duplicates(), on=["transformer_id"], suffixes=("", "_dup"), how="left"
) if "feeder_id" not in transformer_summary.columns else transformer_summary

STATUS_RANK = {
    HostingCapacityStatus.REVIEW_RECOMMENDED.value: 3,
    HostingCapacityStatus.MONITOR.value: 2,
    HostingCapacityStatus.DATA_INCOMPLETE.value: 1,
    HostingCapacityStatus.LOW_CONCERN.value: 0,
}

tab_tx, tab_feeder, tab_zone = st.tabs(["Transformers", "Feeders", "Municipality & Barangay"])

with tab_tx:
    review_count = int((transformer_summary["hosting_capacity_status"] == HostingCapacityStatus.REVIEW_RECOMMENDED.value).sum())
    if review_count:
        st.warning(f"**{review_count} transformer(s)** are flagged **Review recommended** — prioritize these for field/registry verification.")

    section_title(
        "Transformer network map",
        f"Each badge is a transformer. Larger badges are bigger transformers (rated capacity, in a few size "
        f"steps, not continuous). Color shows how much of that capacity rooftop PV already uses, as a share of "
        f"rated capacity: green is under {MONITOR_RATIO:.0%}, gold is {MONITOR_RATIO:.0%}–{REVIEW_RECOMMENDED_RATIO:.0%}, "
        f"and red is {REVIEW_RECOMMENDED_RATIO:.0%} or more (or {REVIEW_RECOMMENDED_ALERT_COUNT}+ unresolved alerts "
        "on that transformer) — click a badge to see its exact PV load percentage.",
    )
    render_map_legend([(label, color) for label, color in HOSTING_STATUS_COLORS.items()])
    tx_geo = result.transformers[["transformer_id", "geometry"]].merge(transformer_summary, on="transformer_id", how="left")
    tx_geo = gpd.GeoDataFrame(tx_geo, geometry="geometry", crs=result.transformers.crs)

    m = make_base_map(result.center_lat, result.center_lon, zoom=15)
    add_polygon_layer(m, result.feeders, NEUTRAL_BLUE_LIGHT, "Feeder service areas", tooltip_fields=["feeder_id", "feeder_name"], show=True)
    for _, row in tx_geo.iterrows():
        status = row.get("hosting_capacity_status", HostingCapacityStatus.DATA_INCOMPLETE.value)
        color = HOSTING_STATUS_COLORS.get(status, NEUTRAL_BLUE)
        rated = row.get("rated_capacity_kva") or 0
        marker_size = _transformer_marker_size(rated)
        # Review-recommended transformers get a colored glow ring so they
        # pop against the calmer low-concern/monitor badges on the same map.
        is_urgent = status == HostingCapacityStatus.REVIEW_RECOMMENDED.value
        ratio = row.get("pv_load_ratio")
        ratio_display = f"{ratio * 100:.0f}% of rated capacity" if pd.notna(ratio) else "Unknown — rated capacity missing"
        popup_html = factsheet_popup_html(
            [
                ("Feeder", row.get("feeder_id", "—")),
                ("Status", status),
                ("PV load vs. rated capacity", ratio_display),
                ("Rated capacity", f"{rated:.0f} kVA"),
                ("Recorded PV", f"{row.get('recorded_pv_capacity_kw', 0):.1f} kW"),
                ("New/expanded PV (est.)", f"{row.get('estimated_new_pv_capacity_kw', 0):.1f} kW"),
                ("Unresolved alerts", f"{int(row.get('unresolved_alert_count', 0) or 0)}"),
            ],
            title=row["transformer_id"],
        )
        folium.Marker(
            location=[row.geometry.y, row.geometry.x],
            icon=transformer_marker_icon(color, size=marker_size, urgent=is_urgent),
            popup=folium.Popup(popup_html, max_width=280),
            tooltip=row["transformer_id"],
        ).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, use_container_width=True, height=520, key="grid_planning_map", returned_objects=[])

    section_title(
        "By transformer",
        "Same story as the map, in table form — sorted so transformers most worth a look come first. "
        "\"PV load vs. rated capacity\" is the number the status/color is based on.",
    )
    tx_display_cols = [
        "transformer_id", "feeder_id", "rated_capacity_kva", "recorded_pv_capacity_kw", "installation_count",
        "new_installation_count", "estimated_new_pv_capacity_kw", "existing_estimated_capacity_kw",
        "unresolved_alert_count", "pv_load_ratio", "hosting_capacity_status",
    ]
    tx_display_cols = [c for c in tx_display_cols if c in transformer_summary.columns]
    tx_table = transformer_summary[tx_display_cols].sort_values(
        "hosting_capacity_status", key=lambda s: s.map(STATUS_RANK), ascending=False
    ).copy()
    if "pv_load_ratio" in tx_table.columns:
        tx_table["pv_load_ratio"] = (tx_table["pv_load_ratio"] * 100).round(1)
    st.dataframe(
        tx_table, use_container_width=True, hide_index=True,
        column_config={
            "pv_load_ratio": st.column_config.ProgressColumn(
                "PV load vs. rated capacity",
                help="Recorded + newly observed PV capacity as a share of this transformer's rated capacity.",
                format="%.0f%%", min_value=0, max_value=100,
            ),
        },
    )

    metadata = build_export_metadata(config, result.is_synthetic)
    st.download_button(
        "Transformer summaries (CSV)", data=dataframe_to_csv_bytes(transformer_summary[tx_display_cols], metadata),
        file_name="pv_watch_transformer_summary.csv", mime="text/csv",
    )

    notable = transformer_summary[transformer_summary["new_installation_count"] > 0].sort_values("new_installation_count", ascending=False)
    if not notable.empty:
        top = notable.iloc[0]
        top_ratio = top.get("pv_load_ratio")
        ratio_clause = f" — now at <b>{top_ratio * 100:.0f}%</b> of rated capacity" if pd.notna(top_ratio) else ""
        render_html(
            f"""
            <div class="pv-card" style="border-left:4px solid #F2A93B;">
                Transformer <b>{top['transformer_id']}</b> has <b>{int(top['new_installation_count'])} newly observed</b>
                systems representing an estimated <b>{top['estimated_new_pv_capacity_kw']:.0f} kW</b> of additional
                rooftop PV{ratio_clause}. <b>{int(top['unresolved_alert_count'])}</b> related alert(s) are still unresolved and
                require verification.
            </div>
            """
        )

with tab_feeder:
    section_title(
        "By feeder",
        "Feeder boundaries are colored by their single worst transformer's status (same color scale as the "
        "Transformers map). The table below also shows each feeder's overall PV load: total PV capacity across "
        "all its transformers, as a share of their combined rated capacity.",
    )
    if not transformer_summary.empty and "feeder_id" in transformer_summary.columns:
        feeder_summary = (
            transformer_summary.groupby("feeder_id")
            .agg(
                transformer_count=("transformer_id", "count"),
                rated_capacity_kva=("rated_capacity_kva", "sum"),
                recorded_pv_capacity_kw=("recorded_pv_capacity_kw", "sum"),
                installation_count=("installation_count", "sum"),
                new_installation_count=("new_installation_count", "sum"),
                estimated_new_pv_capacity_kw=("estimated_new_pv_capacity_kw", "sum"),
                unresolved_alert_count=("unresolved_alert_count", "sum"),
            )
            .reset_index()
        )
        total_feeder_pv = feeder_summary["recorded_pv_capacity_kw"] + feeder_summary["estimated_new_pv_capacity_kw"]
        feeder_summary["pv_load_ratio"] = total_feeder_pv / feeder_summary["rated_capacity_kva"].mask(
            feeder_summary["rated_capacity_kva"] <= 0
        )
        worst_status = (
            transformer_summary.assign(_rank=transformer_summary["hosting_capacity_status"].map(STATUS_RANK))
            .sort_values("_rank", ascending=False)
            .drop_duplicates(subset="feeder_id")
            .set_index("feeder_id")["hosting_capacity_status"]
        )
        feeder_summary["worst_hosting_status"] = feeder_summary["feeder_id"].map(worst_status)

        render_map_legend([(label, color) for label, color in HOSTING_STATUS_COLORS.items()])
        m2 = make_base_map(result.center_lat, result.center_lon, zoom=14)
        feeders_colored = result.feeders.merge(
            feeder_summary[["feeder_id", "worst_hosting_status", "pv_load_ratio"]], on="feeder_id", how="left"
        )
        feeders_colored = gpd.GeoDataFrame(feeders_colored, geometry="geometry", crs=result.feeders.crs)
        for idx in feeders_colored.index:
            row = feeders_colored.loc[idx]
            status = row.get("worst_hosting_status") or HostingCapacityStatus.DATA_INCOMPLETE.value
            color = HOSTING_STATUS_COLORS.get(status, NEUTRAL_BLUE)
            single = feeders_colored.loc[[idx]]
            # A feeder whose worst transformer needs review pops with a
            # heavier outline and denser fill; calmer feeders stay light so
            # they don't compete for attention.
            is_urgent = status == HostingCapacityStatus.REVIEW_RECOMMENDED.value
            weight, fill_opacity = (3, 0.55) if is_urgent else (1.5, 0.3)
            ratio = row.get("pv_load_ratio")
            ratio_txt = f" — {ratio * 100:.0f}% PV load" if pd.notna(ratio) else ""
            folium.GeoJson(
                single.to_json(),
                name=row["feeder_id"],
                style_function=lambda _f, c=color, w=weight, fo=fill_opacity: {"fillColor": c, "color": c, "weight": w, "fillOpacity": fo},
                tooltip=f"{row['feeder_id']} — {status}{ratio_txt}",
            ).add_to(m2)
        st_folium(m2, use_container_width=True, height=420, key="feeder_map", returned_objects=[])

        feeder_table = feeder_summary.copy()
        feeder_table["pv_load_ratio"] = (feeder_table["pv_load_ratio"] * 100).round(1)
        st.dataframe(
            feeder_table, use_container_width=True, hide_index=True,
            column_config={
                "pv_load_ratio": st.column_config.ProgressColumn(
                    "PV load vs. rated capacity",
                    help="Total recorded + newly observed PV capacity across this feeder's transformers, as a "
                    "share of their combined rated capacity.",
                    format="%.0f%%", min_value=0, max_value=100,
                ),
            },
        )
    else:
        st.info("No feeder-level data available for the current dataset.")

with tab_zone:
    section_title("By municipality and barangay")
    # `installations_2025` already carries each installation's own change_type
    # (merged in by the pipeline) — no extra join needed here.
    installs = result.installations_2025.copy()
    installs["change_type"] = installs["change_type"].fillna(ChangeType.EXISTING.value)
    zone_summary = (
        installs.groupby(["municipality", "barangay"])
        .apply(
            lambda g: pd.Series(
                {
                    "existing_systems": int((g["change_type"] != ChangeType.NEWLY_OBSERVED.value).sum()),
                    "newly_observed_systems": int((g["change_type"] == ChangeType.NEWLY_OBSERVED.value).sum()),
                    "estimated_existing_capacity_kw": round(g.loc[g["change_type"] != ChangeType.NEWLY_OBSERVED.value, "estimated_capacity_kw"].sum(), 1),
                    "estimated_new_capacity_kw": round(g.loc[g["change_type"] == ChangeType.NEWLY_OBSERVED.value, "estimated_capacity_kw"].sum(), 1),
                }
            )
        )
        .reset_index()
    )
    st.dataframe(zone_summary, use_container_width=True, hide_index=True)
    st.caption(
        "An optional grid-cell aggregation (independent of administrative boundaries) is planned for a future phase — "
        "see the Methodology page's roadmap."
    )

render_footer(config)
