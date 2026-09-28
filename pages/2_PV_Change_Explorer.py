"""Page 2 — PV Change Explorer.

Map-first exploration of the 2020 vs 2025 inventories. Filters live in a
single collapsible bar at the top of the page (not the sidebar) and apply
across every tab; each tab drives one specific exploration action: view the
current map mode, compare years side by side, or browse the case table.

No bulk-export tab is exposed here by design (client-shared builds should
not let a viewer download the underlying proprietary geometry/data).
"""

from __future__ import annotations

import folium
import streamlit as st
from streamlit_folium import st_folium

from src.region import active_config
from src.models import ChangeType, DetectionConfidence
from src.pipeline import build_explorer_table, get_pipeline_result
from src.review_store import apply_decisions_to_alerts
from src.ui_components import (
    BASELINE_HIGHLIGHT_BLUE,
    CHANGE_TYPE_COLORS,
    CHANGE_TYPE_EMPHASIS,
    GEOJSON_DETAIL_CLASS,
    GEOJSON_POPUP_STYLE,
    add_polygon_layer,
    make_base_map,
    render_app_header,
    render_footer,
    render_map_legend,
    section_title,
    size_class,
)

st.set_page_config(page_title="Solance — PV Change Explorer", layout="wide")
config = active_config()
render_app_header(config, "PV Change Explorer")

result = get_pipeline_result()
if result is None:
    st.info("Choose a data source on the main **Solance** page first (demo data or upload two KMZ files).")
    st.stop()

explorer = build_explorer_table(result, apply_decisions_to_alerts(result.alerts_df))
explorer["size_class"] = explorer["area_m2"].apply(size_class)

# --- Filters (top bar, not sidebar) --------------------------------------------
with st.expander("Filters", expanded=False):
    row1 = st.columns(3)
    municipalities = sorted(explorer["municipality"].dropna().unique().tolist())
    sel_muni = row1[0].multiselect("Municipality", municipalities, default=municipalities)
    barangay_options = sorted(explorer.loc[explorer["municipality"].isin(sel_muni), "barangay"].dropna().unique().tolist())
    sel_brgy = row1[1].multiselect("Barangay", barangay_options, default=barangay_options)
    sel_change_type = row1[2].multiselect("Change type", [c.value for c in ChangeType], default=[c.value for c in ChangeType])

    row2 = st.columns(3)
    review_options = sorted(explorer["review_status"].dropna().unique().tolist())
    sel_review = row2[0].multiselect("Review status", review_options, default=review_options)
    sel_size = row2[1].multiselect(
        "Size class", ["Small (<20 m²)", "Medium (20–50 m²)", "Large (50–90 m²)", "Very large (90+ m²)"],
        default=["Small (<20 m²)", "Medium (20–50 m²)", "Large (50–90 m²)", "Very large (90+ m²)"],
    )
    sel_confidence = row2[2].multiselect(
        "Detection confidence", [c.value for c in DetectionConfidence], default=[c.value for c in DetectionConfidence]
    )
    max_capacity = float(explorer["estimated_capacity_kw"].max()) if not explorer.empty else 20.0
    sel_capacity = st.slider("Estimated capacity (kW)", 0.0, max(max_capacity, 1.0), (0.0, max(max_capacity, 1.0)))

filtered = explorer[
    explorer["municipality"].isin(sel_muni)
    & explorer["barangay"].isin(sel_brgy)
    & explorer["change_type"].isin(sel_change_type)
    & explorer["size_class"].isin(sel_size)
    & explorer["estimated_capacity_kw"].fillna(0).between(sel_capacity[0], sel_capacity[1])
    & explorer["detection_confidence"].isin(sel_confidence)
    & explorer["review_status"].isin(sel_review)
]
st.caption(f"**{len(filtered):,}** of {len(explorer):,} cases match the current filters.")

tab_map, tab_compare, tab_table = st.tabs(["Map", "Compare 2020 → 2025", "Case table"])


# Kept intentionally short — this is a scan-at-a-glance popup, not the full
# case record. Click through to the Case table tab, or open the alert on
# Dark Solar Alerts, for area/network/classification detail.
popup_fields = [
    "display_installation_id", "change_type", "area_2025_m2", "estimated_capacity_kw",
]
popup_aliases = [
    "Installation ID", "Change type", "2025 area (m²)", "Est. capacity (kW)",
]
available_fields = [f for f in popup_fields if f in filtered.columns]
available_aliases = [a for a, f in zip(popup_aliases, popup_fields) if f in filtered.columns]

with tab_map:
    mode = st.radio(
        "Map mode",
        ["2020 inventory", "2025 inventory", "Newly observed", "Change classification"],
        horizontal=True,
    )

    m = make_base_map(result.center_lat, result.center_lon, zoom=15)

    if mode == "2020 inventory":
        layer = result.installations_2020.copy()
        layer["size_class"] = layer["area_m2"].apply(size_class)
        layer = layer[layer["barangay"].isin(sel_brgy) & layer["municipality"].isin(sel_muni)]
        add_polygon_layer(m, layer, BASELINE_HIGHLIGHT_BLUE, f"{config.app.observation_year_baseline} inventory",
                           tooltip_fields=["installation_id", "barangay", "area_m2", "estimated_capacity_kw"],
                           tooltip_aliases=["Installation ID", "Barangay", "Area (m²)", "Est. capacity (kW)"])
        render_map_legend([(f"{config.app.observation_year_baseline} installation", BASELINE_HIGHLIGHT_BLUE)])
    elif mode == "2025 inventory":
        layer = result.installations_2025.copy()
        layer = layer[layer["barangay"].isin(sel_brgy) & layer["municipality"].isin(sel_muni)]
        add_polygon_layer(m, layer, CHANGE_TYPE_COLORS[ChangeType.EXISTING.value], f"{config.app.observation_year_latest} inventory",
                           tooltip_fields=["installation_id", "barangay", "area_m2", "estimated_capacity_kw"],
                           tooltip_aliases=["Installation ID", "Barangay", "Area (m²)", "Est. capacity (kW)"])
        render_map_legend([(f"{config.app.observation_year_latest} installation", CHANGE_TYPE_COLORS[ChangeType.EXISTING.value])])
    elif mode == "Newly observed":
        layer = filtered[filtered["change_type"] == ChangeType.NEWLY_OBSERVED.value]
        if not layer.empty:
            nw, nfo = CHANGE_TYPE_EMPHASIS[ChangeType.NEWLY_OBSERVED.value]
            folium.GeoJson(
                layer.to_json(),
                name="Newly observed",
                style_function=lambda _f, c=CHANGE_TYPE_COLORS[ChangeType.NEWLY_OBSERVED.value], w=nw, fo=nfo: {"fillColor": c, "color": c, "weight": w, "fillOpacity": fo},
                popup=folium.GeoJsonPopup(
                    fields=available_fields, aliases=available_aliases, max_width=320,
                    style=GEOJSON_POPUP_STYLE, class_name=GEOJSON_DETAIL_CLASS,
                ),
            ).add_to(m)
        render_map_legend([("Newly observed", CHANGE_TYPE_COLORS[ChangeType.NEWLY_OBSERVED.value])])
    else:  # Change classification
        change_types_in_order = [
            ChangeType.EXISTING.value, ChangeType.POTENTIALLY_REMOVED.value, ChangeType.UNCERTAIN.value,
            ChangeType.EXPANDED.value, ChangeType.NEWLY_OBSERVED.value,
        ]
        for ct in change_types_in_order:
            layer = filtered[filtered["change_type"] == ct]
            if layer.empty:
                continue
            weight, fill_opacity = CHANGE_TYPE_EMPHASIS.get(ct, (1.5, 0.55))
            folium.GeoJson(
                layer.to_json(),
                name=ct,
                style_function=lambda _f, c=CHANGE_TYPE_COLORS[ct], w=weight, fo=fill_opacity: {"fillColor": c, "color": c, "weight": w, "fillOpacity": fo},
                popup=folium.GeoJsonPopup(
                    fields=available_fields, aliases=available_aliases, max_width=320,
                    style=GEOJSON_POPUP_STYLE, class_name=GEOJSON_DETAIL_CLASS,
                ),
            ).add_to(m)
        folium.LayerControl(collapsed=False).add_to(m)
        render_map_legend([(ct, CHANGE_TYPE_COLORS[ct]) for ct in change_types_in_order])

    st_folium(m, use_container_width=True, height=560, key="explorer_map", returned_objects=[])
    st.caption("Click any installation for full case detail.")

with tab_compare:
    section_title("2020 vs 2025 Side by Side")
    side1, side2 = st.columns(2)
    with side1:
        st.caption(f"{config.app.observation_year_baseline} baseline")
        m1 = make_base_map(result.center_lat, result.center_lon, zoom=14)
        layer_2020 = result.installations_2020[
            result.installations_2020["barangay"].isin(sel_brgy) & result.installations_2020["municipality"].isin(sel_muni)
        ]
        w2020, fo2020 = CHANGE_TYPE_EMPHASIS[ChangeType.EXISTING.value]
        add_polygon_layer(
            m1, layer_2020, BASELINE_HIGHLIGHT_BLUE, "2020",
            tooltip_fields=["installation_id", "area_m2", "estimated_capacity_kw"],
            tooltip_aliases=["Installation ID", "Area (m²)", "Est. capacity (kW)"],
            weight=w2020, fill_opacity=fo2020,
        )
        st_folium(m1, use_container_width=True, height=380, key="side_2020", returned_objects=[])
    with side2:
        st.caption(f"{config.app.observation_year_latest} latest")
        m2 = make_base_map(result.center_lat, result.center_lon, zoom=14)
        layer_2025 = result.installations_2025[
            result.installations_2025["barangay"].isin(sel_brgy) & result.installations_2025["municipality"].isin(sel_muni)
        ]
        w2025, fo2025 = CHANGE_TYPE_EMPHASIS[ChangeType.NEWLY_OBSERVED.value]
        add_polygon_layer(
            m2, layer_2025, CHANGE_TYPE_COLORS[ChangeType.NEWLY_OBSERVED.value], "2025",
            tooltip_fields=["installation_id", "area_m2", "estimated_capacity_kw"],
            tooltip_aliases=["Installation ID", "Area (m²)", "Est. capacity (kW)"],
            weight=w2025, fill_opacity=fo2025,
        )
        st_folium(m2, use_container_width=True, height=380, key="side_2025", returned_objects=[])

with tab_table:
    section_title(f"Filtered Cases ({len(filtered):,})")
    display_cols = [c for c in [
        "display_installation_id", "change_type", "municipality", "barangay", "area_2020_m2", "area_2025_m2",
        "area_change_percent", "estimated_capacity_kw", "detection_confidence",
        "transformer_id", "feeder_id", "review_status",
    ] if c in filtered.columns]
    st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True, height=460)

render_footer(config)
