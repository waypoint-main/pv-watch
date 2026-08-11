"""CSV / GeoJSON export helpers, with embedded provenance metadata.

Every export carries a metadata block describing the source observation
years, when the export was generated, which threshold configuration was in
effect, whether the underlying data are synthetic, and the application
version — so a downloaded file remains self-describing outside the app.
"""

from __future__ import annotations

import json
from datetime import date

import geopandas as gpd
import pandas as pd

from src.config import AppConfig
from src.models import ExportMetadata


def build_export_metadata(config: AppConfig, is_synthetic: bool) -> ExportMetadata:
    threshold_summary = {
        "change_detection": vars(config.change_detection),
        "capacity_estimation": vars(config.capacity_estimation),
        "installation_grouping": vars(config.installation_grouping),
        "alert_engine": {"weights": config.alert_engine.weights},
    }
    return ExportMetadata(
        source_year_baseline=config.app.observation_year_baseline,
        source_year_latest=config.app.observation_year_latest,
        processing_date=date.today(),
        is_synthetic=is_synthetic,
        application_version=config.app.version,
        threshold_config_summary=threshold_summary,
    )


def dataframe_to_csv_bytes(df: pd.DataFrame, metadata: ExportMetadata | None = None) -> bytes:
    """Serialize a DataFrame to CSV bytes with a metadata header block."""
    lines = []
    if metadata is not None:
        lines.append("# PV Watch export metadata")
        for k, v in metadata.to_dict().items():
            if k == "threshold_config":
                lines.append(f"# threshold_config: {json.dumps(v)}")
            else:
                lines.append(f"# {k}: {v}")
        lines.append("#")
    header = "\n".join(lines) + ("\n" if lines else "")
    csv_body = df.to_csv(index=False)
    return (header + csv_body).encode("utf-8")


def geodataframe_to_geojson_bytes(
    gdf: gpd.GeoDataFrame, metadata: ExportMetadata | None = None, geographic_crs: str = "EPSG:4326"
) -> bytes:
    """Serialize a GeoDataFrame to GeoJSON bytes (EPSG:4326) with a metadata block."""
    if gdf.crs is not None and str(gdf.crs).upper() != geographic_crs.upper():
        gdf = gdf.to_crs(geographic_crs)
    elif gdf.crs is None:
        gdf = gdf.set_crs(geographic_crs)

    # Drop any leftover internal/helper columns before export.
    drop_cols = [c for c in gdf.columns if c.startswith("_")]
    export_gdf = gdf.drop(columns=drop_cols) if drop_cols else gdf

    geojson = json.loads(export_gdf.to_json())
    if metadata is not None:
        geojson["pv_watch_metadata"] = metadata.to_dict()
    return json.dumps(geojson, default=str).encode("utf-8")
