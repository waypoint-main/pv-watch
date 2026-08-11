"""Page 3 — Dark Solar Alerts (Alert Inbox).

This page is where PV Watch's "dark solar" outcome lives: a PV system is
called **dark solar** when it's visible in imagery but not yet confirmed
registered with the utility. Two tabs drive the two distinct actions here:
**Queue** (triage — filter, sort, scan, export) and **Review & Decide**
(pick a case-management state, pick an alert within it, and record a
reviewer decision).  Filters live in a top filter bar, not the sidebar, and
apply to both tabs.

Reviewer dispositions follow a fixed, two-branch case-management workflow
(``src.models.ReviewAction`` / ``REVIEW_STATE_TRANSITIONS``) that mirrors
field validation through to registration:

    For inspection -> For registration -> Ongoing registration -> Registered (end state)
    For inspection -> False positive (end state)

A case that reaches **Registered** is, conceptually, fed back into the
utility's own registration inventory — closing the loop from "observed in
imagery" to "on the books." Every state change is timestamped and logged to
a per-alert history so the Review & Decide tab can show a full audit trail,
not just the current state. Decisions are stored via ``src.review_store``
(session state + a lightweight local JSON file for this MVP), structured so
a real database can replace the storage layer later without touching this
page.
"""

from __future__ import annotations

import folium
import streamlit as st
from streamlit_folium import st_folium

from src.config import load_config
from src.export_utils import build_export_metadata, dataframe_to_csv_bytes
from src.models import REVIEW_END_STATE_VALUES, REVIEW_STATE_TRANSITIONS, ReviewAction
from src.pipeline import get_pipeline_result
from src.review_store import all_decisions_df, apply_decisions_to_alerts, get_decision, save_decision
from src.ui_components import (
    CHANGE_TYPE_COLORS,
    CHANGE_TYPE_EMPHASIS,
    REVIEW_STATE_COLORS,
    add_polygon_layer,
    kpi_row,
    make_base_map,
    priority_badge_html,
    render_app_header,
    render_factsheet_sections,
    render_footer,
    render_html,
    render_map_legend,
    review_state_badge_html,
    safe_number,
    section_title,
)

st.set_page_config(page_title="PV Watch — Dark Solar Alerts", page_icon="☀️", layout="wide")
config = load_config()
render_app_header(config, "Dark Solar Alerts")

result = get_pipeline_result()
if result is None:
    st.info("Choose a data source on the main **PV Watch** page first (demo data or upload two KMZ files).")
    st.stop()

alerts_df = apply_decisions_to_alerts(result.alerts_df)
if alerts_df.empty:
    st.success("No alerts were generated for the current dataset and thresholds.")
    st.stop()

st.caption(
    "**\"Dark solar\"** = a PV system visible in imagery but not yet confirmed registered with the utility. "
    "Case states below are seeded with **illustrative synthetic starting points** so this queue reads as an "
    "actively managed inbox — no real registration action has occurred. Reviewer actions you take from here are real."
)

STATE_ORDER = [
    ReviewAction.FOR_INSPECTION, ReviewAction.FOR_REGISTRATION, ReviewAction.ONGOING_REGISTRATION,
    ReviewAction.REGISTERED, ReviewAction.FALSE_POSITIVE,
]

# --- Filters (top bar, not sidebar) --------------------------------------------
with st.expander("Filters", expanded=False):
    f1, f2, f3 = st.columns(3)
    sel_priority = f1.multiselect("Priority", sorted(alerts_df["priority"].unique()), default=sorted(alerts_df["priority"].unique()))
    sel_change = f2.multiselect("Change type", sorted(alerts_df["change_type"].unique()), default=sorted(alerts_df["change_type"].unique()))
    sel_review = f3.multiselect("Case state", sorted(alerts_df["review_status"].unique()), default=sorted(alerts_df["review_status"].unique()))
    f4, f5 = st.columns(2)
    sel_registry = f4.multiselect("Registry status", sorted(alerts_df["registry_match_status"].unique()), default=sorted(alerts_df["registry_match_status"].unique()))
    sel_muni = f5.multiselect("Municipality", sorted(alerts_df["municipality"].unique()), default=sorted(alerts_df["municipality"].unique()))

filtered = alerts_df[
    alerts_df["priority"].isin(sel_priority)
    & alerts_df["change_type"].isin(sel_change)
    & alerts_df["review_status"].isin(sel_review)
    & alerts_df["registry_match_status"].isin(sel_registry)
    & alerts_df["municipality"].isin(sel_muni)
].sort_values(["priority", "priority_score"], ascending=[True, False])

state_counts = filtered["review_status"].value_counts()
kpi_row([(s.value, f"{int(state_counts.get(s.value, 0)):,}", None) for s in STATE_ORDER])

p1p2_open = int(
    (
        filtered["priority"].isin([p for p in filtered["priority"].unique() if p.startswith("Priority 1") or p.startswith("Priority 2")])
        & (~filtered["review_status"].isin(REVIEW_END_STATE_VALUES))
    ).sum()
)
registered_mask = filtered["review_status"] == ReviewAction.REGISTERED.value
registered_count = int(registered_mask.sum())
registered_capacity_kw = float(filtered.loc[registered_mask, "estimated_capacity_kw"].sum())
# Just the two numbers not already visible in the state-breakdown row above:
# urgency (still open + high priority) and the registration-loop payoff.
kpi_row(
    [
        ("Priority 1 / 2 open", f"{p1p2_open:,}", "Immediate verification or registry reconciliation, still open."),
        ("Fed back to registration inventory", f"{registered_count:,} ({registered_capacity_kw:,.0f} kW)", "Cases reaching Registered — see Sustainable PV Reporting for the capacity rollup."),
    ]
)
st.caption(
    "In a production deployment, every case reaching **Registered** would be written back to the utility's own "
    "registration inventory — closing the loop shown in the PV Watch workflow, from paper-based registration "
    "records through to a confirmed, geo-located entry."
)

tab_queue, tab_review = st.tabs(["Queue", "Review & Decide"])

display_cols = [
    "alert_id", "change_type", "municipality", "barangay", "area_m2", "estimated_capacity_kw",
    "registry_match_status", "transformer_id", "priority", "detection_confidence", "review_status", "assigned_to",
]

with tab_queue:
    section_title(f"Alerts ({len(filtered):,} of {len(alerts_df):,})", "Sorted by priority, then priority score. Open the Review & Decide tab to act on one.")
    st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True, height=420)

    metadata = build_export_metadata(config, result.is_synthetic)
    exp1, exp2 = st.columns(2)
    with exp1:
        st.download_button(
            "Filtered alerts (CSV)", data=dataframe_to_csv_bytes(filtered[display_cols], metadata),
            file_name="pv_watch_alerts.csv", mime="text/csv",
        )
    with exp2:
        decisions_df = all_decisions_df()
        st.download_button(
            "Review decisions (CSV)", data=dataframe_to_csv_bytes(decisions_df, metadata),
            file_name="pv_watch_review_decisions.csv", mime="text/csv", disabled=decisions_df.empty,
        )

with tab_review:
    section_title("Choose a state to review", "Group the queue by case state, then pick one alert within it.")
    state_labels = [f"{s.value} ({int(state_counts.get(s.value, 0))})" for s in STATE_ORDER]
    label_to_state = {label: s for label, s in zip(state_labels, STATE_ORDER)}
    # Default to the first state group that actually has alerts in view.
    default_idx = next((i for i, s in enumerate(STATE_ORDER) if state_counts.get(s.value, 0) > 0), 0)
    chosen_label = st.radio("Case state", state_labels, index=default_idx, horizontal=True, label_visibility="collapsed")
    chosen_state = label_to_state[chosen_label]

    state_filtered = filtered[filtered["review_status"] == chosen_state.value]
    alert_ids = state_filtered["alert_id"].tolist()
    if not alert_ids:
        st.info(f"No alerts are currently in **{chosen_state.value}**. Pick another state above, or adjust the filters.")
        st.stop()

    selected_alert_id = st.selectbox(f"Select an alert to review ({len(alert_ids)} in this state)", alert_ids)
    alert_row = alerts_df[alerts_df["alert_id"] == selected_alert_id].iloc[0]
    change_row = result.change_df[result.change_df["change_id"] == alert_row["change_id"]].iloc[0]
    current_decision = get_decision(selected_alert_id)

    col_map, col_detail = st.columns([1.1, 1])

    with col_map:
        render_map_legend(
            [
                (f"{config.app.observation_year_baseline} geometry", CHANGE_TYPE_COLORS["Existing"]),
                (f"{config.app.observation_year_latest} geometry", CHANGE_TYPE_COLORS["Newly observed"]),
            ]
        )
        inst_2020 = result.installations_2020[result.installations_2020["installation_id"] == change_row["installation_id_2020"]]
        inst_2025 = result.installations_2025[result.installations_2025["installation_id"] == change_row["installation_id_2025"]]

        anchor = inst_2025 if not inst_2025.empty else inst_2020
        if not anchor.empty:
            centroid = anchor.geometry.centroid.iloc[0]
            m = make_base_map(centroid.y, centroid.x, zoom=19)
        else:
            m = make_base_map(result.center_lat, result.center_lon, zoom=17)

        # The 2020 baseline geometry is context; the 2025 geometry is the
        # flagged installation this reviewer is actually being asked to act
        # on — give it the same "pop" weight/opacity used for Newly observed
        # everywhere else so it visually dominates the comparison.
        w2020, fo2020 = CHANGE_TYPE_EMPHASIS["Existing"]
        w2025, fo2025 = CHANGE_TYPE_EMPHASIS["Newly observed"]
        add_polygon_layer(
            m, inst_2020, CHANGE_TYPE_COLORS["Existing"], f"{config.app.observation_year_baseline} geometry",
            tooltip_fields=["installation_id", "area_m2", "estimated_capacity_kw"],
            tooltip_aliases=["Installation ID", "Area (m²)", "Est. capacity (kW)"],
            weight=w2020, fill_opacity=fo2020,
        )
        add_polygon_layer(
            m, inst_2025, CHANGE_TYPE_COLORS["Newly observed"], f"{config.app.observation_year_latest} geometry",
            tooltip_fields=["installation_id", "area_m2", "estimated_capacity_kw"],
            tooltip_aliases=["Installation ID", "Area (m²)", "Est. capacity (kW)"],
            weight=w2025, fill_opacity=fo2025,
        )
        folium.LayerControl(collapsed=False).add_to(m)
        st_folium(m, use_container_width=True, height=400, key=f"alert_map_{selected_alert_id}", returned_objects=[])

    with col_detail:
        st.markdown(f"#### {alert_row['alert_id']} — {alert_row['change_type']}", unsafe_allow_html=True)
        badge_row = f"{priority_badge_html(alert_row['priority'])} {review_state_badge_html(chosen_state.value)}"
        st.markdown(badge_row, unsafe_allow_html=True)
        st.markdown(
            f"**Detection window:** {config.app.observation_date_baseline} → {config.app.observation_date_latest} "
            "(possible installation window; not a construction date)"
        )
        area_2020 = safe_number(change_row.get("area_2020_m2"))
        area_2025 = safe_number(change_row.get("area_2025_m2"))
        area_change_pct = safe_number(change_row.get("area_change_percent"))
        kpi_row(
            [
                (f"{config.app.observation_year_baseline} area", f"{area_2020:,.0f} m²", None),
                (f"{config.app.observation_year_latest} area", f"{area_2025:,.0f} m²", None),
                ("Area change", f"{area_change_pct:+.0f}%", None),
                ("Estimated capacity (est. only)", f"{alert_row['estimated_capacity_kw']:,.1f} kW", "Demo estimate — not utility-confirmed."),
            ]
        )
        st.caption(f"Detection confidence: **{alert_row['detection_confidence']}** (separate from operational priority)")

        render_factsheet_sections(
            [
                ("Registry comparison (synthetic demo data)", [("Status", alert_row["registry_match_status"])]),
                (
                    "Network context (synthetic demo data)",
                    [("Transformer", alert_row["transformer_id"]), ("Feeder", alert_row["feeder_id"])],
                ),
            ]
        )

        st.markdown("**Classification reason**")
        st.info(change_row["classification_reason"])

        st.markdown("**Priority reason**")
        st.info(alert_row["priority_reason"])

    st.divider()
    col_history, col_action = st.columns([1, 1])

    with col_history:
        section_title("Case history", "Every state change is logged with the date and time it happened.")
        history = current_decision.history
        if not history:
            st.caption("No state changes logged yet.")
        else:
            rows = "".join(
                f"""
                <div style="display:flex;justify-content:space-between;gap:0.75rem;padding:0.4rem 0;
                            border-bottom:1px solid #E1E8ED;font-size:0.85rem;">
                    <span>{review_state_badge_html(h['state'])}</span>
                    <span style="color:#5B6B76;white-space:nowrap;">{h['changed_at'][:16].replace('T', ' ')}</span>
                </div>
                """
                for h in history
            )
            render_html(f'<div class="pv-card">{rows}</div>')
            if current_decision.state_changed_at:
                st.caption(f"Current state entered: **{current_decision.state_changed_at.strftime('%Y-%m-%d %H:%M')}**")

    with col_action:
        section_title("Reviewer action", "Record the outcome of your verification.")
        current_state = current_decision.state
        allowed_next = REVIEW_STATE_TRANSITIONS.get(current_state, [])
        state_options = [current_state] + [s for s in allowed_next if s != current_state]
        is_end_state = current_state.value in REVIEW_END_STATE_VALUES

        if is_end_state:
            st.caption(f"This case is **closed** ({current_state.value}) — an end state of the workflow. Notes/assignment can still be updated.")

        with st.form(key=f"review_form_{selected_alert_id}"):
            new_state_value = st.selectbox(
                "Case state", [s.value for s in state_options],
                index=0, disabled=is_end_state,
                help="Only the current state and its valid next step(s) are selectable.",
            )
            notes = st.text_area("Reviewer notes", value=current_decision.notes)
            assigned_to = st.text_input("Assigned to", value=current_decision.assigned_to or alert_row.get("assigned_to", ""))
            submitted = st.form_submit_button("Save review decision")
            if submitted:
                save_decision(selected_alert_id, new_state_value, notes, assigned_to)
                st.success(f"Saved: {selected_alert_id} → {new_state_value}.")
                st.rerun()

render_footer(config)
