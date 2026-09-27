"""Page 6 — Data & Methodology.

Documents inputs, processing, thresholds, assumptions, and limitations so a
utility reviewer can evaluate exactly how Solance produced its results.
Grouped into tabs by concern: how data was processed, the rules/thresholds
that drove classification, and what to keep in mind before acting on it.
"""

from __future__ import annotations

import streamlit as st

from src.region import active_config
from src.pipeline import get_pipeline_result
from src.ui_components import render_app_header, render_footer, section_title

st.set_page_config(page_title="Solance — Methodology", layout="wide")
config = active_config()
render_app_header(config, "Data & Methodology")

result = get_pipeline_result()

tab_data, tab_rules, tab_limits = st.tabs(["Data & Processing", "Rules & Thresholds", "Limitations & Review"])

with tab_data:
    section_title("Input Data & Observation Dates")
    st.markdown(
        f"""
- **Baseline:** {config.app.observation_year_baseline} (`{config.app.observation_date_baseline}`)
- **Latest:** {config.app.observation_year_latest} (`{config.app.observation_date_latest}`)
- Only two observation points exist, so Solance never claims an installation was *built* in
  {config.app.observation_year_latest} — only *first observed* then, with a possible installation window between
  the two dates.
- New systems are flagged for registration/interconnection **verification** — never labeled "illegal" or
  definitively "unregistered."
"""
    )

    section_title("KMZ Processing Workflow")
    st.markdown(
        """
1. Extract the KMZ archive and parse its KML document.
2. Parse `<Placemark>` polygon geometries; unsupported types (points, lines) are skipped with a warning.
3. Preserve `ExtendedData`/`SimpleData` attributes (e.g. parcel or building ID) when present.
4. Assign a source year and nominal observation date.
5. Validate and repair geometries where possible; drop empty, unrepairable, or duplicate geometries.
6. Compute polygon area in a projected CRS — never directly in EPSG:4326.
7. Assemble the normalized observation schema for downstream matching.
"""
    )

    section_title("CRS Handling")
    st.markdown(
        f"""
- KML/KMZ geometry is WGS84 (EPSG:4326) by spec; area/distance math reprojects to a projected (meters) CRS.
- Solance auto-selects the UTM zone via GeoPandas' `estimate_utm_crs()`, or uses a user override.
- Fallback CRS if auto-selection fails: `{config.crs.fallback_projected_crs}`.
"""
    )
    if result is not None:
        st.info(f"Selected for the current dataset: **{result.projected_crs_used}**.")

    section_title("Data Provenance")
    st.markdown(
        """
- Demo mode uses synthetic geometry placed near a real Philippine municipality for visual realism only — it does
  not represent actual installations, parcels, or utility infrastructure.
- Uploaded KMZ files are processed in-session and are not sent to any third party.
"""
    )

with tab_rules:
    section_title("Installation Grouping (Heuristic)")
    st.markdown(
        f"""
- Array polygons within **{config.installation_grouping.grouping_distance_m:.0f} m** of one another are merged; a
  shared parcel/building ID (when available) takes priority over pure distance.
- **This is a heuristic, not ground truth** — always validate grouped installations before operational use.
"""
    )

    section_title("Change-Matching Rules & Thresholds")
    cd = config.change_detection
    st.markdown(
        f"""
- For every {config.app.observation_year_latest} installation, Solance searches {config.app.observation_year_baseline}
  candidates nearby and computes intersection-over-union, coverage percentage, centroid displacement, and area
  change. Exact polygon equality is never required.

**Current thresholds (demonstration assumptions — not scientifically validated):**
"""
    )
    st.json(
        {
            "minimum_iou_match": cd.minimum_iou_match,
            "minimum_overlap_ratio": cd.minimum_overlap_ratio,
            "maximum_centroid_distance_m": cd.maximum_centroid_distance_m,
            "stable_area_change_ratio": cd.stable_area_change_ratio,
            "expansion_area_change_ratio": cd.expansion_area_change_ratio,
            "grouping_distance_m": cd.grouping_distance_m,
            "uncertainty_margin": cd.uncertainty_margin,
            "ambiguous_secondary_match_margin": cd.ambiguous_secondary_match_margin,
        }
    )
    st.markdown(
        """
**Classification rules:**

- **Existing** — a credible match with area change within the stable-area threshold.
- **Expanded** — a credible match whose area grew beyond the expansion threshold.
- **Newly observed** — no credible match in the baseline inventory.
- **Potentially removed** — a baseline installation with no credible match in the latest inventory.
- **Uncertain** — ambiguous or near-threshold matches; always flagged for human review.

Every change record stores a `classification_reason` (visible in PV Change Explorer and Dark Solar Alerts).
"""
    )

    section_title("Capacity Estimation Assumptions")
    ce = config.capacity_estimation
    st.markdown(
        f"""
- `estimated_capacity_kw = pv_area_m2 × {ce.kw_per_m2} kW/m²` — a **demo default factor only**; real capacity also
  depends on module efficiency, tilt, spacing, and technology type.
- Installations ≥ **{ce.large_system_capacity_kw:.0f} kW** (area ≥ **{config.alert_engine.large_installation_area_m2:.0f} m²**) are flagged "large."
- All capacity figures are estimates, never utility-confirmed nameplate capacity.
"""
    )

    section_title("Registry-Matching Logic (Synthetic Demo Registry)")
    rm = config.registry_matching
    st.markdown(
        f"""
- The registry is entirely **synthetic** — fictional references, no real names or account numbers.
- Matching is spatial-proximity based: within **{rm.spatial_match_distance_m:.0f} m** is a confident match; within
  **{rm.probable_match_distance_m:.0f} m** is probable; equally-close candidates are ambiguous; otherwise "no
  registry match."
"""
    )

    section_title("Alert-Priority Logic")
    st.markdown(
        """
- **Detection confidence** (how certain the match is) and **operational priority** (how important the case is) are
  kept separate.
- A weighted score combines change type, registry concerns, capacity discrepancy, large-installation status,
  transformer clustering, and confidence — mapping to Priority 1 (immediate) through Priority 4 (human review).
- Every alert stores a `priority_reason`.
"""
    )
    st.json({"weights": config.alert_engine.weights, "priority_1_min_score": config.alert_engine.priority_1_min_score,
             "priority_2_min_score": config.alert_engine.priority_2_min_score, "priority_3_min_score": config.alert_engine.priority_3_min_score})

with tab_limits:
    section_title("Known Limitations")
    st.markdown(
        """
- Grouping, classification, and registry/network matching are heuristic and demonstration-tuned — not
  scientifically validated or utility-certified.
- The registry, transformers, feeders, and their capacities are synthetic demonstration data.
- Hosting-capacity indicators are illustrative ratios, not a distribution-impact study or power-flow analysis.
- Two observation years give a plausible window, not a precise date, ownership, permitting, or interconnection status.
- KMZ ingestion assumes Polygon/MultiPolygon rooftop footprints; other KML feature types are skipped.
- This MVP excludes automated satellite-image download, ML-based PV detection, real-time notifications, load-flow
  simulation, customer identity lookup, and production authentication — see the project README for the roadmap.
"""
    )

    section_title("Human-Review Requirement")
    st.markdown(
        "Every newly observed, expanded, uncertain, or potentially-removed case is surfaced as an alert requiring "
        "human review before any outreach, registration, safety, or grid-planning decision. Solance accelerates "
        "that review; it does not replace it."
    )

render_footer(config)
