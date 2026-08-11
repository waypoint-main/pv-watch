# PV Watch — Distributed Solar Change Intelligence

PV Watch is a demonstration Streamlit application showing how temporal geospatial data (two annotated rooftop-solar inventories, 2020 and 2025) can help electricity distribution utilities identify newly observed rooftop PV installations, reconcile them with utility records, and prioritize cases for verification or grid-planning review.

> **Disclaimer:** This demonstration identifies geospatial changes that may warrant utility verification. It does not determine legal, permitting, registration, ownership, export, safety, or interconnection status. All registry, feeder, and transformer data shown are **synthetic demonstration data** — not real utility records.

## Business problem

Distribution utilities in the Philippines (Meralco, AboitizPower, and others) increasingly need visibility into distributed rooftop solar that may not yet be reflected in their internal registration and net-metering records. PV Watch demonstrates a workflow for maintaining an independent geospatial inventory of rooftop PV, comparing it against utility records, and routing discrepancies to the right team — without ever asserting that an unregistered-looking system is "illegal."

Two observation years only support a *possible installation window*, not a construction date: a newly observed system is described as *"first observed in the 2025 imagery, with a possible installation window between the 2020 and 2025 observation dates,"* and is flagged for registration/interconnection **verification**, never labeled as illegal or definitively unregistered.

## Intended users

- Meralco, AboitizPower, and other Philippine distribution utilities
- Distribution network engineers
- Grid innovation leads
- Distributed-energy-resource (DER) program teams

## What it demonstrates

- **Observe** — maintain an independent geospatial inventory of rooftop solar from annotated KMZ imagery.
- **Verify** — compare observed installations with a (synthetic) utility registry.
- **Integrate** — route results into customer outreach, registration reconciliation, safety review, and grid planning.

## Pages

1. **Executive Overview** — KPIs, the main change-classification map, growth-by-barangay, change-type distribution, alerts by priority/review status, and top PV-growth hotspots. Answers: *where is distributed solar growing beyond what the utility may currently see in its records?*
2. **PV Change Explorer** — a map-first page with six map modes (2020, 2025, newly observed, change classification, registry-match status, alert priority), compact sidebar filters, click-to-inspect popups with full case detail, and a 2020-vs-2025 side-by-side view.
3. **Alert Inbox** — a filterable/sortable alert table plus a per-alert review panel (location map, evidence metrics, registry/network context, classification & priority reasons, and a reviewer-action form). Review decisions persist for the session (and to a local JSON file).
4. **Grid Planning** — aggregates observed/new PV by transformer, feeder, and municipality/barangay, with synthetic hosting-capacity indicators.
5. **Methodology** — full documentation of inputs, processing, thresholds, assumptions, and limitations.

## Installation

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
pip install -r requirements.txt
```

On Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> **Note:** `geopandas`/`fiona`/`pyproj` pull in compiled geospatial libraries (GDAL/PROJ). If you hit a build error on `pip install`, installing via conda/mamba (`conda install -c conda-forge geopandas fiona pyproj`) is usually the smoothest path, especially on Windows.

## Running the app

```bash
streamlit run app.py
```

### Data sources

PV Watch offers three data sources, selectable at the top of the landing page:

1. **Local KMZ folder (real data)** — the default whenever `output-kmz/2020/` and `output-kmz/2025/` (relative to the project root) exist and contain `.kmz` files. PV Watch automatically loads and merges **every** `.kmz` file in each folder into one baseline/latest inventory — no upload step needed. Each array polygon's barangay is taken directly from its filename (e.g. `2020_Brgy_Sinalhan.kmz` → barangay "Sinalhan"), which is more accurate than the synthetic spatial-zone join used for the other two modes. This repository ships with 18 real per-barangay KMZ pairs (Santa Rosa, Laguna) in `output-kmz/`, covering 109 digitized array polygons in 2020 and 1,287 in 2025 — to point PV Watch at a different folder, edit `data_sources` in `config/settings.yaml`.
   - Note: the ~12x increase in digitized array count between 2020 and 2025 in this sample dataset reflects a mix of real rooftop-PV growth **and** a more exhaustive 2025 digitization pass — treat the "newly observed" totals as a starting point for verification, not a precise growth measurement, exactly as the app's disclaimers describe.
2. **Synthetic demo data** — works immediately with no files at all; procedurally generated, fictional geometries (see below).
3. **Upload my own KMZ files** — manually upload a single 2020 KMZ and a single 2025 KMZ.

Two small sample KMZ files (one barangay, real digitized footprints, used here purely to illustrate the expected file format) are also included at `data/raw/pv_2020_sample_malusak.kmz` and `data/raw/pv_2025_sample_malusak.kmz` if you want to try the upload flow.

## Expected KMZ structure

- A KMZ is a zipped KML. PV Watch extracts the first `.kml` it finds (warns if more than one is present).
- Only `Placemark` features with `Polygon` (or `MultiGeometry` of polygons) geometry are treated as PV array footprints; other geometry types (points, lines) are skipped with a warning.
- KML coordinates are assumed WGS84 lon/lat (per the KML spec) — no CRS tag needed in the file.
- Optional `ExtendedData`/`SimpleData` fields such as `parcel_id` / `ParcelID` / `building_id` are picked up automatically and used to strengthen installation grouping.
- Invalid, empty, unsupported, or duplicate geometries are repaired where possible and otherwise skipped with a warning — a single bad record will not crash the app.

## Demo mode

Demo mode procedurally generates a synthetic rooftop-PV scenario (34 baseline / 52 latest installations, with existing, expanded, newly observed, potentially removed, and uncertain cases; 6 transformers across 2 feeders; a synthetic registry with exact/probable/no-match/pending/off-grid/capacity-discrepancy/ambiguous outcomes) placed near a real Philippine municipality for visual realism only. **The synthetic geometries do not represent actual PV installations.**

## Change-detection methodology (summary)

For each 2025 installation, PV Watch searches for candidate 2020 installations within a centroid-distance buffer and computes intersection-over-union (IoU), coverage percentage in each direction, centroid displacement, and area change — never requiring exact polygon equality. Explicit, configurable thresholds (see below) classify each case as **Existing**, **Expanded**, **Newly observed**, **Potentially removed**, or **Uncertain**, each with a human-readable `classification_reason`. Full detail — including installation grouping, capacity estimation, registry matching, and alert-priority scoring — is documented on the in-app **Methodology** page.

## Configuration

All thresholds and assumptions live in `config/settings.yaml` (loaded via `src/config.py`) rather than being hard-coded — nothing analytical is hidden in the code:

- `installation_grouping` — proximity/parcel-ID grouping of array polygons into installations.
- `change_detection` — IoU/overlap/centroid/area-change thresholds.
- `capacity_estimation` — the demo `kw_per_m2` factor and "large system" threshold.
- `alert_engine` — priority scoring weights and priority-tier cut points.
- `registry_matching` — spatial match/probable-match distances.
- `synthetic_demo` — demo dataset size and location.

These are **initial demonstration assumptions, not scientifically validated values** — see the Methodology page for the full rationale.

## Known limitations

- Installation grouping, change classification, and registry/network matching are heuristic and threshold-based, tuned for a clear demo — not scientifically validated or utility-certified.
- The registry, transformers, and feeders are entirely synthetic; hosting-capacity indicators are simple illustrative ratios, not a distribution-impact study or power-flow analysis.
- Two observation years cannot establish an exact installation date, ownership, permitting, or interconnection status — only a plausible window and a case for human verification.
- Review decisions are stored in session state + a local JSON file for this MVP (`data/processed/review_decisions.json`), not a database.
- No automated satellite-image download, ML-based PV detection, real-time notifications, load-flow simulation, customer identity lookup, production authentication, or full work-order management — see **Roadmap** below.

## Testing

```bash
pytest
```

Unit tests cover: exact/near spatial matches classified as existing; major area growth classified as expanded; unmatched 2025/2020 records classified as newly observed / potentially removed; ambiguous multi-candidate matches classified as uncertain; invalid-geometry repair vs. graceful rejection; area computed in a projected CRS; configurable capacity estimation; installation grouping by proximity and by parcel ID; registry exact/probable/no-match outcomes; and alert priority scoring (including that detection confidence and operational priority are independent).

## Data disclaimer

Demo-mode geometries are synthetic and do not represent real PV installations, parcels, or utility infrastructure. The utility registry, transformers, and feeders are entirely fictional (fictional customer references only — no real names, account numbers, or personal data). Uploaded KMZ files are processed only within your local app session and are not sent to any third party by this application.

## Roadmap (beyond this MVP)

- Automated satellite/aerial imagery ingestion and ML-based PV detection.
- Real building/parcel footprints to replace heuristic installation grouping.
- A real utility registry/CRM integration in place of the synthetic registry.
- Database-backed review-decision storage (replacing the session/file store behind `src/review_store.py`).
- Optional grid-cell aggregation (independent of administrative boundaries) on the Grid Planning page.
- Electrical hosting-capacity analysis backed by real load-flow simulation.
- Real-time alerting/notifications and a full work-order management workflow.
- Production authentication and role-based access for utility reviewers.

## Project structure

```text
pv-watch/
├── app.py                     # Entrypoint: st.navigation router + custom sidebar nav (no page content)
├── config/settings.yaml       # All thresholds, weights, and demo assumptions
├── data/
│   ├── raw/                   # Sample KMZ files
│   ├── processed/             # Runtime artifacts (e.g. review_decisions.json)
│   └── synthetic/             # Reserved for exported synthetic reference data
├── pages/                     # One file per page — 0_Home.py (data source selection;
│                               # formerly app.py's own content) plus pages 1-6

├── src/                       # All analytical/data logic, framework-agnostic where possible
│   ├── config.py               # Typed config loader
│   ├── models.py                # Enums & dataclasses (ChangeType, Priority, schemas, ...)
│   ├── data_loader.py            # KMZ/KML extraction & normalization
│   ├── geometry_utils.py         # CRS handling, validation/repair, area calculation
│   ├── installation_grouping.py  # Array-polygon -> installation heuristic grouping
│   ├── change_detection.py       # Rule-based spatial change classification
│   ├── capacity_estimation.py    # Demo capacity estimate (area x kW/m^2)
│   ├── synthetic_data.py         # Demo inventories, registry, transformers, feeders
│   ├── registry_matching.py      # Spatial registry matching logic
│   ├── network_context.py        # Transformer/feeder assignment & summaries
│   ├── alert_engine.py           # Priority scoring & alert generation
│   ├── pipeline.py               # Cached end-to-end orchestration
│   ├── review_store.py           # Session/file-backed review decisions (swappable)
│   ├── export_utils.py           # CSV/GeoJSON export with embedded metadata
│   └── ui_components.py          # Shared header, badges, maps, KPI cards
└── tests/                     # pytest unit tests for the analytical modules
```

## License / attribution

This is a demonstration/MVP application built for Waypoint GeoInt. Sample KMZ files are digitized rooftop footprints used here only to illustrate the expected file format.
