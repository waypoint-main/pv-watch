"""Page 6 — Data & Methodology.

Documents inputs, processing, thresholds, assumptions, and limitations so a
utility reviewer can evaluate exactly how PV Watch produced its results.
Grouped into tabs by concern: how data was processed, the rules/thresholds
that drove classification, and what to keep in mind before acting on it.
"""

from __future__ import annotations

import streamlit as st

from src.config import load_config
from src.pipeline import get_pipeline_result
from src.ui_components import render_app_header, render_disclaimer, render_footer, section_title

st.set_page_config(page_title="PV Watch — Methodology", page_icon="☀️", layout="wide")
config = load_config()
render_app_header(config, "Data & Methodology")

render_disclaimer(
    "This demonstration identifies geospatial changes that may warrant utility verification. "
    "It does not determine legal, permitting, registration, ownership, export, safety, or "
    "interconnection status."
)

result = get_pipeline_result()

tab_data, tab_rules, tab_limits = st.tabs(["Data & Processing", "Rules & Thresholds", "Limitations & Review"])

with tab_data:
    section_title("Input data & observation dates")
    st.markdown(
        f"""
PV Watch compares two manually annotated rooftop PV polygon inventories:

- **Baseline:** {config.app.observation_year_baseline} (nominal observation date used when a source file has no
  per-feature date: `{config.app.observation_date_baseline}`)
- **Latest:** {config.app.observation_year_latest} (nominal observation date: `{config.app.observation_date_latest}`)

Because the only two observation points are {config.app.observation_year_baseline} and
{config.app.observation_year_latest}, PV Watch never claims an installation was *built* in
{config.app.observation_year_latest}. A newly observed installation is instead described as: *"First observed in the
{config.app.observation_year_latest} imagery, with a possible installation window between the
{config.app.observation_year_baseline} and {config.app.observation_year_latest} observation dates."* Likewise, new systems
are described as needing registration/interconnection **verification** — never as "illegal" or definitively
"unregistered."
"""
    )

    section_title("KMZ processing workflow")
    st.markdown(
        """
1. Safely extract the KMZ (zip) archive and locate its KML document (warns if multiple KML files are present; uses
   the first / `doc.kml`).
2. Parse `<Placemark>` geometries directly from KML XML (Polygon / MultiGeometry-of-polygons only); unsupported
   geometry types (points, lines) are skipped with a recorded warning rather than crashing the app.
3. Preserve any `ExtendedData`/`SimpleData` attributes found (e.g. a parcel or building ID), when present.
4. Assign a source year and a nominal observation date.
5. Validate geometries; repair invalid ones (`shapely.make_valid` / zero-width buffer) where possible; drop empty,
   unsupported, or unrepairable geometries and duplicate geometries, all with recorded warnings.
6. Compute polygon area in square meters using a projected CRS — **never** directly in EPSG:4326.
7. Assemble the normalized observation schema (`observation_id`, `source_year`, `observation_date`, `geometry`,
   `area_m2`, `imagery_source`, `annotation_confidence`, `qa_status`, plus `parcel_id`/`raw_name` when available).
"""
    )

    section_title("CRS handling")
    st.markdown(
        f"""
KML/KMZ geometry is always WGS84 (EPSG:4326) per the KML specification. For any area or distance calculation, PV
Watch reprojects to a projected (meters) CRS — auto-selecting the UTM zone containing the dataset's centroid via
GeoPandas' `estimate_utm_crs()`, or using a user-supplied override. Fallback CRS if auto-selection fails:
`{config.crs.fallback_projected_crs}`.
"""
    )
    if result is not None:
        st.info(f"For the currently loaded dataset, PV Watch selected **{result.projected_crs_used}** for area/distance calculations.")

    section_title("Data provenance")
    st.markdown(
        """
Demo mode uses procedurally generated synthetic geometry placed near a real Philippine municipality for visual
realism only — it does not represent actual PV installations, actual parcels, or actual utility infrastructure.
Uploaded KMZ files are processed entirely in-session and are not sent to any third party by this application.
"""
    )

with tab_rules:
    section_title("Installation grouping (heuristic)")
    st.markdown(
        f"""
Individual digitized array polygons are grouped into installations using: proximity (polygons within
**{config.installation_grouping.grouping_distance_m:.0f} m** of one another are merged, computed via buffered
spatial-index intersection — a union-find over pairwise proximity), and a shared parcel/building ID when available
(takes priority over pure distance). **This is a heuristic, not ground truth.** Without authoritative parcel/building
footprints, grouping can over-merge nearby-but-distinct rooftops or under-merge one rooftop's separated arrays.
Always validate grouped installations before operational use.
"""
    )

    section_title("Change-matching rules & classification thresholds")
    cd = config.change_detection
    st.markdown(
        f"""
For every {config.app.observation_year_latest} installation, PV Watch searches for candidate
{config.app.observation_year_baseline} installations within a buffer of the maximum centroid distance, then computes:
intersection-over-union (IoU), the percentage of the {config.app.observation_year_baseline} polygon covered by the
{config.app.observation_year_latest} polygon (and vice versa), centroid displacement, and area change. Exact polygon
equality is never required.

**Current thresholds (initial demonstration assumptions — not scientifically validated):**
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

- **Existing** — a credible match (IoU or overlap above threshold) with area change within the stable-area threshold.
- **Expanded** — a credible match whose area grew beyond the expansion threshold.
- **Newly observed** — no credible match found in the baseline inventory.
- **Potentially removed** — a baseline installation with no credible match in the latest inventory.
- **Uncertain** — ambiguous multi-candidate matches, near-threshold match scores, or area changes that are neither
  clearly stable nor clearly expansion. Always flagged for human review.

Every change record stores a human-readable `classification_reason` explaining exactly why it was classified the
way it was (visible in the PV Change Explorer and Dark Solar Alerts).
"""
    )

    section_title("Capacity estimation assumptions")
    ce = config.capacity_estimation
    st.markdown(
        f"""
`estimated_capacity_kw = pv_area_m2 × {ce.kw_per_m2} kW/m²` — a **demo default factor only**. Actual capacity depends
on module efficiency, panel dimensions, roof layout, tilt, spacing, obstructions, and PV technology type, none of
which are observable from polygon area alone. Installations at or above **{ce.large_system_capacity_kw:.0f} kW**
(area ≥ **{config.alert_engine.large_installation_area_m2:.0f} m²**) are flagged as "large" for alerting purposes.
All capacity figures in this app are estimates, never utility-confirmed nameplate capacity.
"""
    )

    section_title("Registry-matching logic (synthetic demo registry)")
    rm = config.registry_matching
    st.markdown(
        f"""
The registry is entirely **synthetic** — fictional customer references, no real names or account numbers. Matching
is purely spatial-proximity based (not dependent on any generator-internal ID) so the same logic would apply to a
real registry with real customer coordinates: a registry point within **{rm.spatial_match_distance_m:.0f} m** of an
installation (and reciprocally nearest to it) is a confident match, refined into exact / pending / off-grid /
capacity-discrepancy using the registry record's own fields; within **{rm.probable_match_distance_m:.0f} m** is a
probable match; two similarly-close candidates (within 5 m of each other) is ambiguous; no candidate within range is
"no registry match."
"""
    )

    section_title("Alert-priority logic")
    st.markdown(
        """
Two concepts are kept separate: **detection confidence** (how certain the geospatial observation/match is) and
**operational priority** (how important the case may be to the utility). A weighted score combines change type,
registry-match concerns, capacity discrepancy, large-installation status, transformer clustering, low detection
confidence, and network review status. The total score maps to Priority 1 (Immediate verification) through
Priority 4 (Human review required). Every alert stores a human-readable `priority_reason`.
"""
    )
    st.json({"weights": config.alert_engine.weights, "priority_1_min_score": config.alert_engine.priority_1_min_score,
             "priority_2_min_score": config.alert_engine.priority_2_min_score, "priority_3_min_score": config.alert_engine.priority_3_min_score})

with tab_limits:
    section_title("Known limitations")
    st.markdown(
        """
- Installation grouping, change classification, and registry/network matching are all heuristic, threshold-based,
  and demonstration-tuned — not scientifically validated or utility-certified.
- The registry, transformers, feeders, and their capacities are entirely synthetic demonstration data.
- Hosting-capacity indicators are simple illustrative ratios, not a distribution-impact study or power-flow analysis.
- Two observation years cannot establish a precise installation date, ownership, permitting, or interconnection
  status — only a plausible window and a case for verification.
- KMZ ingestion assumes Polygon/MultiPolygon rooftop footprints; other KML feature types are skipped.
- This MVP does not include automated satellite-image download, ML-based PV detection, real-time notifications,
  electrical load-flow simulation, customer identity lookup, production authentication, or full work-order
  management — see the project README for the roadmap.
"""
    )

    section_title("Human-review requirements")
    st.markdown(
        "Every newly observed, expanded, uncertain, or potentially-removed case — and every registry or network concern "
        "— is surfaced as an alert requiring human review before any customer outreach, registration action, safety "
        "review, or grid-planning decision is made. PV Watch supports and accelerates that review; it does not replace it."
    )

render_footer(config)
