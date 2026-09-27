"""Page 5 — Sustainable PV Reporting.

The client-facing deliverable for the third outcome in Solance's value
story: "Solar PV capacity estimation (barangay, province level) ->
Sustainable PV reporting." Where Executive Overview and Distribution
Planning are built for exploration, this page is built to be *handed to
someone* — management, a regulator, a planning office — as a summary of
observed and newly observed distributed PV capacity, with an export to
back it up.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.region import active_config
from src.export_utils import build_export_metadata, dataframe_to_csv_bytes
from src.models import ChangeType, ReviewAction
from src.pipeline import get_pipeline_result
from src.review_store import apply_decisions_to_alerts
from src.ui_components import (
    ACCENT,
    CHANGE_TYPE_COLORS,
    kpi_row,
    render_app_header,
    render_factsheet_sections,
    render_footer,
    section_title,
)

st.set_page_config(page_title="Solance — Sustainable PV Reporting", layout="wide")
config = active_config()
render_app_header(config, "Sustainable PV Reporting")

result = get_pipeline_result()
if result is None:
    st.info("Choose a data source on the main **Solance** page first (demo data or upload two KMZ files).")
    st.stop()

installs_2025 = result.installations_2025.copy()
installs_2025["change_type"] = installs_2025["change_type"].fillna(ChangeType.EXISTING.value)
installs_2020 = result.installations_2020

municipalities = sorted(installs_2025["municipality"].dropna().unique().tolist()) if not installs_2025.empty else []
province_label = config.data_sources.province
muni_label = ", ".join(municipalities) if municipalities else "—"

render_factsheet_sections(
    [
        (
            None,
            [
                ("Province", province_label),
                ("Municipality / municipalities covered", muni_label),
                ("Report window", f"{config.app.observation_year_baseline} → {config.app.observation_year_latest}"),
            ],
        )
    ]
)

capacity_2025 = float(installs_2025["estimated_capacity_kw"].sum()) if not installs_2025.empty else 0.0
capacity_2020 = float(installs_2020["estimated_capacity_kw"].sum()) if not installs_2020.empty else 0.0
capacity_growth_pct = ((capacity_2025 - capacity_2020) / capacity_2020 * 100) if capacity_2020 else 0.0
new_capacity_kw = (
    installs_2025.loc[installs_2025["change_type"] == ChangeType.NEWLY_OBSERVED.value, "estimated_capacity_kw"].sum()
    if not installs_2025.empty else 0.0
)

alerts_df = apply_decisions_to_alerts(result.alerts_df)
if not alerts_df.empty:
    registered_mask = alerts_df["review_status"] == ReviewAction.REGISTERED.value
    registered_capacity_kw = float(alerts_df.loc[registered_mask, "estimated_capacity_kw"].sum())
else:
    registered_capacity_kw = 0.0

section_title("Capacity Summary")
kpi_row(
    [
        (f"Total est. capacity, {config.app.observation_year_latest}", f"{capacity_2025:,.0f} kW", "Sum of estimated capacity across all installations observed."),
        ("Capacity growth", f"{capacity_growth_pct:+.0f}%", f"({config.app.observation_year_baseline} → {config.app.observation_year_latest})"),
        ("Newly observed capacity", f"{new_capacity_kw:,.0f} kW", "Estimated capacity of installations first seen in the latest imagery."),
        ("Confirmed & registered capacity", f"{registered_capacity_kw:,.0f} kW", "Estimated capacity of cases that reached the Registered end state in Dark Solar Alerts."),
    ]
)

st.divider()
section_title("Capacity Growth")
# Always meaningful regardless of barangay granularity (unlike the chart
# below, which needs a real per-barangay breakdown to say anything) — a
# plain baseline-vs-latest comparison of total capacity, the same story the
# "Capacity growth" KPI above states as a bare percentage.
growth_chart_df = pd.DataFrame(
    {
        "year": [str(config.app.observation_year_baseline), str(config.app.observation_year_latest)],
        "Estimated capacity (kW)": [capacity_2020, capacity_2025],
    }
)
fig_growth = px.bar(growth_chart_df, x="year", y="Estimated capacity (kW)", text="Estimated capacity (kW)")
fig_growth.update_traces(marker_color=ACCENT, texttemplate="%{text:,.0f} kW", textposition="outside")
fig_growth.update_layout(margin=dict(l=10, r=10, t=30, b=10), height=320, xaxis_title=None, showlegend=False)
st.plotly_chart(fig_growth, use_container_width=True)

st.divider()
section_title("Capacity by Barangay")
if not installs_2025.empty:
    barangay_report = (
        installs_2025.groupby(["municipality", "barangay"])
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
    barangay_report.insert(0, "province", province_label)
    barangay_report["total_estimated_capacity_kw"] = (
        barangay_report["estimated_existing_capacity_kw"] + barangay_report["estimated_new_capacity_kw"]
    )

    # Some regions (e.g. Makati City) only have a single citywide KMZ per
    # year rather than one file per barangay, so there's no real
    # barangay-level breakdown to chart — "barangay" collapses to one row
    # (the "—" placeholder). A bar chart with exactly one bar isn't a
    # takeaway, it's dead space, so skip straight to the summary in that
    # case rather than rendering a chart that has nothing to show.
    has_barangay_breakdown = barangay_report["barangay"].nunique() > 1 or (
        barangay_report["barangay"].nunique() == 1 and barangay_report["barangay"].iloc[0] != "—"
    )

    if has_barangay_breakdown:
        # Chart first, table underneath — the stacked bar is the at-a-glance
        # takeaway; the table is the detail a reader drills into afterward.
        chart_df = barangay_report.melt(
            id_vars="barangay",
            value_vars=["estimated_existing_capacity_kw", "estimated_new_capacity_kw"],
            var_name="Capacity type", value_name="Estimated capacity (kW)",
        )
        chart_df["Capacity type"] = chart_df["Capacity type"].map(
            {"estimated_existing_capacity_kw": "Existing", "estimated_new_capacity_kw": "Newly observed"}
        )
        # Reuse the app-wide semantic colors (blue = existing/context, red = newly
        # observed/act-now) rather than a one-off pair — a client who's just
        # learned "red means newly observed" from the maps elsewhere shouldn't
        # see it turn a different color here.
        fig = px.bar(
            chart_df, x="barangay", y="Estimated capacity (kW)", color="Capacity type", barmode="stack",
            color_discrete_map={
                "Existing": CHANGE_TYPE_COLORS[ChangeType.EXISTING.value],
                "Newly observed": CHANGE_TYPE_COLORS[ChangeType.NEWLY_OBSERVED.value],
            },
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=360)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Barangay-level breakdown isn't available for this dataset — see Capacity Summary above for totals.")

    st.dataframe(
        barangay_report if has_barangay_breakdown else barangay_report.drop(columns=["barangay"]),
        use_container_width=True, hide_index=True,
    )

    st.divider()
    section_title("Export")
    metadata = build_export_metadata(config, result.is_synthetic)
    st.download_button(
        "Sustainability report (CSV)", data=dataframe_to_csv_bytes(barangay_report, metadata),
        file_name="pv_watch_sustainability_report.csv", mime="text/csv",
    )
else:
    st.info("No installations available to report on for the current dataset.")

render_footer(config)
