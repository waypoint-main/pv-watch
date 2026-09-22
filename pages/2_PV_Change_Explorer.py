"""Page 2 — PV Change Explorer.

Map-first exploration of the 2020 vs 2025 inventories. Filters live in a
single collapsible bar at the top of the page (not the sidebar) and apply
across every tab; each tab drives one specific exploration action: view the
current map mode, compare years side by side, browse the case table, or
export the filtered data.
"""

from __future__ import annotations

import folium
import streamlit as st
from streamlit_folium import st_folium

from src.region import active_config
from src.export_utils import build_export_metadata, geodataframe_to_geojson_bytes
from src.models import ChangeType, DetectionConfidence, Priority, RegistryMatchStatus
from src.pipeline import build_explorer_table, get_pipeline_result
from src.review_store import apply_decisions_to_alerts
from src.ui_components import (
    CHANGE_TYPE_COLORS,
    CHANGE_TYPE_EMPHASIS,
    GEOJSON_DETAIL_CLASS,
    GEOJSON_POPUP_STYLE,
    NEUTRAL_BLUE,
    NEUTRAL_BLUE_LIGHT,
    NEUTRAL_TAUPE,
    PRIORITY_COLORS,
    PRIORITY_EMPHASIS,
    add_polygon_layer,
    make_base_map,
    render_app_header,
    render_footer,
    render_map_legend,
    section_title,
    size_class,
)

st.set_page_config(page_title="Solance — PV Change Explorer", page_icon="☀️", layout="wide")
config = active_config()
render_app_header(config, "PV Change Explorer")

result = get_pipeline_result()
if result is None:
    st.info("Choose a data source on the main **Solance** page first (demo data or upload two KMZ files).")
    st.stop()

explorer = build_explorer_table(result, apply_decisions_to_alerts(result.alerts_df))
explorer["size_class"] = explorer["area_m2"].apply(size_class)

# Same "muted context vs. pop accent" system as CHANGE_TYPE_COLORS: matched
# records recede since there's nothing to do, while NO_MATCH — an
# installation visible in imagery with zero registry record, the prime
# dark-solar suspect — gets the same urgent red used everywhere else in the
# app for "act now." The three "nothing to do" statuses use NEUTRAL_BLUE /
# NEUTRAL_BLUE_LIGHT / NEUTRAL_TAUPE rather than grey, since the basemap
# tile itself is greyscale and a grey fill would disappear into it.
REG_COLORS = {
    RegistryMatchStatus.EXACT_MATCH.value: "#2E7D32",
    RegistryMatchStatus.PROBABLE_MATCH.value: "#7FB37F",
    RegistryMatchStatus.PENDING.value: "#F2A93B",
    RegistryMatchStatus.CAPACITY_DISCREPANCY.value: "#E07B00",
    RegistryMatchStatus.OFF_GRID.value: NEUTRAL_BLUE,
    RegistryMatchStatus.AMBIGUOUS.value: NEUTRAL_TAUPE,
    RegistryMatchStatus.NO_MATCH.value: "#C4291C",
    "Not applicable (2020-only record)": NEUTRAL_BLUE_LIGHT,
}
REG_EMPHASIS = {
    RegistryMatchStatus.EXACT_MATCH.value: (1.2, 0.4),
    RegistryMatchStatus.PROBABLE_MATCH.value: (1.2, 0.4),
    RegistryMatchStatus.PENDING.value: (1.8, 0.6),
    RegistryMatchStatus.CAPACITY_DISCREPANCY.value: (2.0, 0.65),
    RegistryMatchStatus.OFF_GRID.value: (1.0, 0.35),
    RegistryMatchStatus.AMBIGUOUS.value: (1.2, 0.4),
    RegistryMatchStatus.NO_MATCH.value: (2.5, 0.78),
    "Not applicable (2020-only record)": (0.8, 0.25),
}

# --- Filters (top bar, not sidebar) --------------------------------------------
with st.expander("Filters", expanded=False):
    row1 = st.columns(3)
    municipalities = sorted(explorer["municipality"].dropna().unique().tolist())
    sel_muni = row1[0].multiselect("Municipality", municipalities, default=municipalities)
    barangay_options = sorted(explorer.loc[explorer["municipality"].isin(sel_muni), "barangay"].dropna().unique().tolist())
    sel_brgy = row1[1].multiselect("Barangay", barangay_options, default=barangay_options)
    sel_change_type = row1[2].multiselect("Change type", [c.value for c in ChangeType], default=[c.value for c in ChangeType])

    row2 = st.columns(3)
    registry_options = sorted(explorer["registry_match_status"].dropna().unique().tolist())
    sel_registry = row2[0].multiselect("Registry status", registry_options, default=registry_options)
    priority_options = sorted(explorer["priority"].dropna().unique().tolist())
    sel_priority = row2[1].multiselect("Alert priority", priority_options, default=priority_options)
    review_options = sorted(explorer["review_status"].dropna().unique().tolist())
    sel_review = row2[2].multiselect("Review status", review_options, default=review_options)

    row3 = st.columns(3)
    sel_size = row3[0].multiselect(
        "Size class", ["Small (<20 m²)", "Medium (20–50 m²)", "Large (50–90 m²)", "Very large (90+ m²)"],
        default=["Small (<20 m²)", "Medium (20–50 m²)", "Large (50–90 m²)", "Very large (90+ m²)"],
    )
    sel_confidence = row3[1].multiselect(
        "Detection confidence", [c.value for c in DetectionConfidence], default=[c.value for c in DetectionConfidence]
    )
    max_capacity = float(explorer["estimated_capacity_kw"].max()) if not explorer.empty else 20.0
    sel_capacity = row3[2].slider("Estimated capacity (kW)", 0.0, max(max_capacity, 1.0), (0.0, max(max_capacity, 1.0)))

filtered = explorer[
    explorer["municipality"].isin(sel_muni)
    & explorer["barangay"].isin(sel_brgy)
    & explorer["change_type"].isin(sel_change_type)
    & explorer["size_class"].isin(sel_size)
    & explorer["estimated_capacity_kw"].fillna(0).between(sel_capacity[0], sel_capacity[1])
    & explorer["detection_confidence"].isin(sel_confidence)
    & explorer["registry_match_status"].isin(sel_registry)
    & explorer["priority"].isin(sel_priority)
    & explorer["review_status"].isin(sel_review)
]
st.caption(f"**{len(filtered):,}** of {len(explorer):,} cases match the current filters.")

tab_map, tab_compare, tab_table, tab_export = st.tabs(["Map", "Compare 2020 → 2025", "Case table", "Exports"])


# Kept intentionally short (6 fields) — this is a scan-at-a-glance popup, not
# the full case record. Click through to the Case table tab, or open the
# alert on Dark Solar Alerts, for area/registry/network/classification detail.
popup_fields = [
    "display_installation_id", "change_type", "area_2025_m2", "estimated_capacity_kw", "registry_match_status", "priority",
]
popup_aliases = [
    "Installation ID", "Change type", "2025 area (m²)", "Est. capacity (kW)", "Registry status", "Alert priority",
]
available_fields = [f for f in popup_fields if f in filtered.columns]
available_aliases = [a for a, f in zip(popup_aliases, popup_fields) if f in filtered.columns]

with tab_map:
    mode = st.radio(
        "Map mode",
        ["2020 inventory", "2025 inventory", "Newly observed", "Change classification", "Registry-match status", "Alert priority"],
        horizontal=True,
    )

    m = make_base_map(result.center_lat, result.center_lon, zoom=15)

    if mode == "2020 inventory":
        layer = result.installations_2020.copy()
        layer["size_class"] = layer["area_m2"].apply(size_class)
        layer = layer[layer["barangay"].isin(sel_brgy) & layer["municipality"].isin(sel_muni)]
        add_polygon_layer(m, layer, CHANGE_TYPE_COLORS[ChangeType.EXISTING.value], f"{config.app.observation_year_baseline} inventory",
                           tooltip_fields=["installation_id", "barangay", "area_m2", "estimated_capacity_kw"],
                           tooltip_aliases=["Installation ID", "Barangay", "Area (m²)", "Est. capacity (kW)"])
        render_map_legend([(f"{config.app.observation_year_baseline} installation", CHANGE_TYPE_COLORS[ChangeType.EXISTING.value])])
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
    elif mode == "Change classification":
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
    elif mode == "Registry-match status":
        for status, color in REG_COLORS.items():
            layer = filtered[filtered["registry_match_status"] == status]
            if layer.empty:
                continue
            weight, fill_opacity = REG_EMPHASIS.get(status, (1.5, 0.55))
            folium.GeoJson(
                layer.to_json(),
                name=status,
                style_function=lambda _f, c=color, w=weight, fo=fill_opacity: {"fillColor": c, "color": c, "weight": w, "fillOpacity": fo},
                popup=folium.GeoJsonPopup(
                    fields=available_fields, aliases=available_aliases, max_width=320,
                    style=GEOJSON_POPUP_STYLE, class_name=GEOJSON_DETAIL_CLASS,
                ),
            ).add_to(m)
        folium.LayerControl(collapsed=False).add_to(m)
        render_map_legend([(status, color) for status, color in REG_COLORS.items()])
    else:  # Alert priority
        for p, color in PRIORITY_COLORS.items():
            layer = filtered[filtered["priority"] == p]
            if layer.empty:
                continue
            weight, fill_opacity = PRIORITY_EMPHASIS.get(p, (1.5, 0.55))
            folium.GeoJson(
                layer.to_json(),
                name=p,
                style_function=lambda _f, c=color, w=weight, fo=fill_opacity: {"fillColor": c, "color": c, "weight": w, "fillOpacity": fo},
                popup=folium.GeoJsonPopup(
                    fields=available_fields, aliases=available_aliases, max_width=320,
                    style=GEOJSON_POPUP_STYLE, class_name=GEOJSON_DETAIL_CLASS,
                ),
            ).add_to(m)
        folium.LayerControl(collapsed=False).add_to(m)
        render_map_legend([(p, color) for p, color in PRIORITY_COLORS.items()])

    st_folium(m, use_container_width=True, height=560, key="explorer_map", returned_objects=[])
    st.caption("Click a shaded installation to see its full case details (IDs, areas, capacity, registry, network, and classification reason).")

with tab_compare:
    section_title("2020 vs 2025 side-by-side view", "Same municipality/barangay filters and extent, shown for both observation years.")
    side1, side2 = st.columns(2)
    with side1:
        st.caption(f"{config.app.observation_year_baseline} baseline")
        m1 = make_base_map(result.center_lat, result.center_lon, zoom=14)
        layer_2020 = result.installations_2020[
            result.installations_2020["barangay"].isin(sel_brgy) & result.installations_2020["municipality"].isin(sel_muni)
        ]
        w2020, fo2020 = CHANGE_TYPE_EMPHASIS[ChangeType.EXISTING.value]
        add_polygon_layer(
            m1, layer_2020, CHANGE_TYPE_COLORS[ChangeType.EXISTING.value], "2020",
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
    section_title(f"Filtered cases ({len(filtered):,})")
    display_cols = [c for c in [
        "display_installation_id", "change_type", "municipality", "barangay", "area_2020_m2", "area_2025_m2",
        "area_change_percent", "estimated_capacity_kw", "detection_confidence", "registry_match_status",
        "transformer_id", "feeder_id", "priority", "review_status",
    ] if c in filtered.columns]
    st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True, height=460)

with tab_export:
    section_title("Exports", "EPSG:4326, with source years / thresholds / synthetic-data flag / app version embedded.")
    metadata = build_export_metadata(config, result.is_synthetic)
    exp1, exp2 = st.columns(2)
    with exp1:
        change_geojson = geodataframe_to_geojson_bytes(filtered.drop(columns=["size_class"], errors="ignore"), metadata)
        st.download_button(
            "Change inventory (GeoJSON)", data=change_geojson, file_name="pv_watch_change_inventory.geojson",
            mime="application/geo+json",
        )
    with exp2:
        new_only = filtered[filtered["change_type"] == ChangeType.NEWLY_OBSERVED.value].drop(columns=["size_class"], errors="ignore")
        new_geojson = geodataframe_to_geojson_bytes(new_only, metadata)
        st.download_button(
            "Newly observed installations (GeoJSON)", data=new_geojson, file_name="pv_watch_newly_observed.geojson",
            mime="application/geo+json",
        )

render_footer(config)
