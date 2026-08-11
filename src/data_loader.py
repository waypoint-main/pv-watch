"""KMZ/KML ingestion and normalization into the PV Watch observation schema.

KMZ files are just zip archives containing a KML document (plus optional
images/overlays). We parse the KML directly with ``lxml`` rather than
relying on GDAL's KML driver, because KML driver availability varies across
Fiona/GDAL builds — a direct parse is more portable for an MVP that needs to
"just work" after ``pip install``.

Only Polygon / MultiPolygon / MultiGeometry-of-polygons placemarks are
treated as PV array observations. Points, LineStrings, and other KML
elements (e.g. ``<ScreenOverlay>``, folders-only) are skipped with a
recorded warning rather than crashing the app.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
from lxml import etree
from shapely.geometry import MultiPolygon, Polygon

from src.config import AppConfig
from src.geometry_utils import GeometryQualityReport, compute_area_m2, normalize_geometries
from src.models import OBSERVATION_SCHEMA_FIELDS, QaStatus

logger = logging.getLogger("pv_watch.data_loader")

KML_NAMESPACES = {"kml": "http://www.opengis.net/kml/2.2"}


class KmzLoadError(Exception):
    """Raised for unrecoverable KMZ/KML problems (empty file, no KML, etc.)."""


@dataclass
class LoadResult:
    """Everything the UI needs to report on a KMZ load, success or partial."""

    gdf: gpd.GeoDataFrame
    projected_crs_used: str
    quality: GeometryQualityReport
    layer_count: int = 1
    source_filename: str = ""


def _parse_coordinates(text: str) -> list[tuple[float, float]]:
    """Parse a KML <coordinates> text blob into a list of (lon, lat) tuples.

    KML coordinates are "lon,lat[,alt]" tuples separated by whitespace. We
    intentionally drop altitude — PV Watch works in 2D plan-view geometry.
    """
    coords = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        coords.append((lon, lat))
    return coords


def _polygon_from_kml_polygon(poly_el, ns) -> Optional[Polygon]:
    outer_coords_el = poly_el.find(".//kml:outerBoundaryIs//kml:coordinates", ns)
    if outer_coords_el is None or not outer_coords_el.text:
        return None
    exterior = _parse_coordinates(outer_coords_el.text)
    if len(exterior) < 3:
        return None

    interiors = []
    for inner_el in poly_el.findall(".//kml:innerBoundaryIs//kml:coordinates", ns):
        if inner_el.text:
            ring = _parse_coordinates(inner_el.text)
            if len(ring) >= 3:
                interiors.append(ring)

    try:
        return Polygon(exterior, interiors if interiors else None)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Failed constructing polygon: %s", exc)
        return None


def _extract_extended_data(placemark_el, ns) -> dict:
    data = {}
    for data_el in placemark_el.findall(".//kml:ExtendedData/kml:Data", ns):
        name = data_el.get("name")
        value_el = data_el.find("kml:value", ns)
        if name and value_el is not None:
            data[name] = value_el.text
    for sd_el in placemark_el.findall(".//kml:ExtendedData/kml:SimpleData", ns):
        name = sd_el.get("name")
        if name:
            data[name] = sd_el.text
    return data


def _find_parcel_id(extended: dict, name_hints: tuple[str, ...] = ("parcel_id", "parcelid", "building_id", "parcel")) -> Optional[str]:
    lower_map = {k.lower(): v for k, v in extended.items()}
    for hint in name_hints:
        if hint in lower_map and lower_map[hint]:
            return str(lower_map[hint])
    return None


def parse_kml_placemarks(kml_bytes: bytes) -> tuple[list[dict], list[str], int]:
    """Parse all Polygon-bearing placemarks out of a KML document.

    Returns (records, warnings, document_count) where ``document_count`` is
    the number of top-level ``<Document>``/``<Folder>`` layers encountered
    (used to warn about multi-layer KML files).
    """
    warnings: list[str] = []
    try:
        root = etree.fromstring(kml_bytes)
    except etree.XMLSyntaxError as exc:
        raise KmzLoadError(f"The KML content could not be parsed as XML: {exc}") from exc

    ns = KML_NAMESPACES
    if root.nsmap.get(None):
        ns = {"kml": root.nsmap[None]}

    documents = root.findall(".//kml:Document", ns)
    folders = root.findall(".//kml:Folder", ns)
    layer_count = max(len(documents), 1) + max(len(folders) - 1, 0) if folders else max(len(documents), 1)

    placemarks = root.findall(".//kml:Placemark", ns)
    if not placemarks:
        warnings.append("No <Placemark> elements were found in the KML document.")

    records = []
    for pm in placemarks:
        name_el = pm.find("kml:name", ns)
        name = name_el.text.strip() if name_el is not None and name_el.text else "Unnamed placemark"
        extended = _extract_extended_data(pm, ns)
        parcel_id = _find_parcel_id(extended)

        polygons: list[Polygon] = []
        direct_polys = pm.findall(".//kml:Polygon", ns)
        for poly_el in direct_polys:
            poly = _polygon_from_kml_polygon(poly_el, ns)
            if poly is not None:
                polygons.append(poly)

        if not polygons:
            other_geoms = []
            for tag in ("Point", "LineString", "LinearRing"):
                if pm.findall(f".//kml:{tag}", ns):
                    other_geoms.append(tag)
            if other_geoms:
                warnings.append(
                    f"Placemark '{name}' has unsupported geometry type(s) {other_geoms} and was skipped "
                    f"(PV Watch only ingests Polygon/MultiPolygon features)."
                )
            continue

        geometry = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
        records.append({"raw_name": name, "parcel_id": parcel_id, "geometry": geometry, "extended_data": extended})

    return records, warnings, layer_count


def extract_kml_from_kmz(file_bytes: bytes) -> tuple[bytes, list[str]]:
    """Safely extract the primary KML document from a KMZ zip archive."""
    warnings: list[str] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise KmzLoadError(
            "The uploaded file is not a valid KMZ (zip) archive. Please check the file and try again."
        ) from exc

    kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
    if not kml_names:
        raise KmzLoadError("No .kml file was found inside the uploaded KMZ archive.")

    primary_name = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
    if len(kml_names) > 1:
        warnings.append(
            f"The KMZ archive contains {len(kml_names)} KML files ({', '.join(kml_names)}); "
            f"using '{primary_name}' and ignoring the others."
        )

    try:
        kml_bytes = zf.read(primary_name)
    except KeyError as exc:  # pragma: no cover - defensive
        raise KmzLoadError(f"Could not read '{primary_name}' from the KMZ archive.") from exc

    if not kml_bytes.strip():
        raise KmzLoadError("The KML file inside the KMZ archive is empty.")

    return kml_bytes, warnings


MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB — generous for hand-annotated polygon KMZ


def finalize_raw_observations(
    gdf: gpd.GeoDataFrame,
    source_year: int,
    observation_date: str,
    imagery_source: str,
    projected_crs_override: Optional[str] = None,
    quality: Optional[GeometryQualityReport] = None,
) -> tuple[gpd.GeoDataFrame, str, GeometryQualityReport]:
    """Shared normalization tail used by both KMZ uploads and the synthetic
    demo generator: validate/repair geometry, compute projected-CRS area, and
    assemble the normalized observation schema.
    """
    quality = quality or GeometryQualityReport()
    gdf, quality = normalize_geometries(gdf, quality)
    if gdf.empty:
        return gdf, projected_crs_override or "EPSG:32651", quality

    gdf, projected_crs_used = compute_area_m2(gdf, projected_crs_override)

    n = len(gdf)
    gdf = gdf.reset_index(drop=True)
    gdf["observation_id"] = [f"OBS-{source_year}-{i:05d}" for i in range(n)]
    gdf["source_year"] = source_year
    gdf["observation_date"] = observation_date
    gdf["imagery_source"] = imagery_source
    if "annotation_confidence" not in gdf.columns:
        gdf["annotation_confidence"] = "Not recorded"
    gdf["annotation_confidence"] = gdf["annotation_confidence"].fillna("Not recorded")
    gdf["qa_status"] = QaStatus.OK.value
    if "parcel_id" not in gdf.columns:
        gdf["parcel_id"] = None
    if "raw_name" not in gdf.columns:
        gdf["raw_name"] = None
    gdf = gdf.drop(columns=[c for c in ["extended_data"] if c in gdf.columns])

    ordered_cols = [c for c in OBSERVATION_SCHEMA_FIELDS if c in gdf.columns]
    remaining = [c for c in gdf.columns if c not in ordered_cols]
    gdf = gdf[ordered_cols + remaining]
    return gdf, projected_crs_used, quality


def load_kmz_observations(
    file_bytes: bytes,
    source_year: int,
    observation_date: str,
    imagery_source: str,
    config: AppConfig,
    source_filename: str = "",
    projected_crs_override: Optional[str] = None,
) -> LoadResult:
    """Full KMZ -> normalized observation GeoDataFrame pipeline.

    Steps: safe archive extraction -> KML parse -> geometry validation/repair
    -> CRS assignment (KML is always WGS84 lon/lat) -> projected-CRS area
    calculation -> normalized schema assembly.
    """
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise KmzLoadError(
            f"The uploaded file is {len(file_bytes) / 1e6:.1f} MB, which exceeds the "
            f"{MAX_UPLOAD_BYTES / 1e6:.0f} MB limit for this demo. Please split the KMZ into smaller areas."
        )
    if not file_bytes:
        raise KmzLoadError("The uploaded file is empty.")

    kml_bytes, extract_warnings = extract_kml_from_kmz(file_bytes)
    records, parse_warnings, layer_count = parse_kml_placemarks(kml_bytes)

    quality = GeometryQualityReport()
    for w in extract_warnings + parse_warnings:
        quality.add_warning(w)

    if not records:
        raise KmzLoadError(
            "No usable Polygon/MultiPolygon placemarks were found in this KMZ. "
            "PV Watch expects rooftop PV footprints digitized as polygons."
        )

    df = pd.DataFrame(records)
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")

    gdf, projected_crs_used, quality = finalize_raw_observations(
        gdf, source_year, observation_date, imagery_source, projected_crs_override, quality
    )
    if gdf.empty:
        raise KmzLoadError(
            "All placemarks in this KMZ were invalid, empty, or unsupported after validation. "
            "Nothing could be loaded — see the warnings above."
        )

    if layer_count > 1:
        quality.add_warning(f"This KMZ contains {layer_count} folder/document layers; all were merged into one inventory.")

    logger.info(
        "Loaded %d PV array observation(s) for year %s from '%s' (CRS used for area: %s)",
        len(gdf),
        source_year,
        source_filename or "<unnamed>",
        projected_crs_used,
    )

    return LoadResult(
        gdf=gdf,
        projected_crs_used=projected_crs_used,
        quality=quality,
        layer_count=layer_count,
        source_filename=source_filename,
    )


_BARANGAY_FILENAME_PATTERN = re.compile(r"^\d{4}_Brgy_(.+)$", re.IGNORECASE)


def barangay_name_from_filename(filename: str) -> str:
    """Derive a human-readable barangay name from a per-barangay KMZ filename.

    E.g. ``2020_Brgy_Pulong_Santa_Cruz.kmz`` -> ``Pulong Santa Cruz``. Falls
    back to the bare filename (no extension) if the expected pattern isn't
    found, so unexpected filenames still load rather than error out.
    """
    stem = Path(filename).stem
    match = _BARANGAY_FILENAME_PATTERN.match(stem)
    raw = match.group(1) if match else stem
    return raw.replace("_", " ").strip()


def load_kmz_folder_observations(
    folder_path: Path,
    source_year: int,
    observation_date: str,
    imagery_source: str,
    default_municipality: str,
    projected_crs_override: Optional[str] = None,
) -> LoadResult:
    """Load and merge every ``.kmz`` file in a local folder into one inventory.

    Used for the "local output-kmz folder" data source: instead of requiring
    a single upload, PV Watch scans ``folder_path`` for per-barangay KMZ
    files (e.g. ``2020_Brgy_Sinalhan.kmz``), parses each one, tags every
    array polygon with the barangay name derived from its filename (more
    accurate than a synthetic spatial-zone join), and concatenates them into
    one normalized observation GeoDataFrame — reusing the exact same
    validation/repair/area-calculation path as a single uploaded KMZ.
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        raise KmzLoadError(f"Local KMZ folder not found: '{folder}'.")

    kmz_files = sorted(folder.glob("*.kmz"))
    if not kmz_files:
        raise KmzLoadError(f"No .kmz files were found in '{folder}'.")

    all_records: list[dict] = []
    quality = GeometryQualityReport()
    files_with_errors: list[str] = []

    for kmz_path in kmz_files:
        barangay = barangay_name_from_filename(kmz_path.name)
        try:
            file_bytes = kmz_path.read_bytes()
            if len(file_bytes) > MAX_UPLOAD_BYTES:
                quality.add_warning(f"'{kmz_path.name}' exceeds the {MAX_UPLOAD_BYTES / 1e6:.0f} MB limit and was skipped.")
                files_with_errors.append(kmz_path.name)
                continue
            kml_bytes, extract_warnings = extract_kml_from_kmz(file_bytes)
            records, parse_warnings, layer_count = parse_kml_placemarks(kml_bytes)
        except KmzLoadError as exc:
            quality.add_warning(f"'{kmz_path.name}' could not be read and was skipped: {exc}")
            files_with_errors.append(kmz_path.name)
            continue

        for w in extract_warnings + parse_warnings:
            quality.add_warning(f"[{kmz_path.name}] {w}")
        if layer_count > 1:
            quality.add_warning(f"[{kmz_path.name}] contains {layer_count} folder/document layers; all were merged.")

        for r in records:
            r["source_barangay"] = barangay
            r["source_file"] = kmz_path.name
        all_records.extend(records)

    if not all_records:
        raise KmzLoadError(
            f"No usable Polygon/MultiPolygon placemarks were found across {len(kmz_files)} KMZ file(s) in '{folder}'."
        )

    df = pd.DataFrame(all_records)
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")

    gdf, projected_crs_used, quality = finalize_raw_observations(
        gdf, source_year, observation_date, imagery_source, projected_crs_override, quality
    )
    if gdf.empty:
        raise KmzLoadError(
            f"All placemarks across {len(kmz_files)} KMZ file(s) in '{folder}' were invalid, empty, or unsupported."
        )

    if "municipality" not in gdf.columns:
        gdf["municipality"] = default_municipality
    gdf = gdf.rename(columns={"source_barangay": "barangay"})

    logger.info(
        "Loaded %d PV array observation(s) for year %s from %d file(s) in '%s' (CRS used for area: %s)",
        len(gdf),
        source_year,
        len(kmz_files),
        folder,
        projected_crs_used,
    )

    return LoadResult(
        gdf=gdf,
        projected_crs_used=projected_crs_used,
        quality=quality,
        layer_count=len(kmz_files),
        source_filename=str(folder),
    )
