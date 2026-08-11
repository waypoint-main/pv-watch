"""Transparent, rule-based spatial change detection between two PV inventories.

This module never requires exact polygon equality. It compares each 2025
installation against candidate 2020 installations using four independent
signals — intersection-over-union (IoU), the percentage of each polygon
covered by the other, centroid displacement, and area change — and applies
explicit, configurable thresholds (see ``config/settings.yaml``) to assign one
of five change classes. Every classification records a human-readable
``classification_reason`` so a reviewer can see exactly why a case was
labeled the way it was.

These thresholds are INITIAL DEMONSTRATION ASSUMPTIONS, not scientifically
validated values — see ``pages/6_Methodology.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import geopandas as gpd
import pandas as pd

from src.config import ChangeDetectionConfig
from src.geometry_utils import to_projected
from src.models import ChangeType, DetectionConfidence

logger = logging.getLogger("pv_watch.change_detection")


@dataclass
class _Candidate:
    index_2020: int
    installation_id_2020: str
    iou: float
    overlap_ratio_2020: float
    overlap_ratio_2025: float
    centroid_distance_m: float
    match_score: float


def _blended_score(iou: float, overlap_2020: float, overlap_2025: float) -> float:
    """A single ranking score blending the three overlap signals.

    Weighted toward IoU (the most conservative signal) while still letting a
    strongly one-sided overlap (e.g. a small 2025 array fully inside a larger
    2020 footprint) contribute to ranking candidates.
    """
    return 0.5 * iou + 0.3 * overlap_2025 + 0.2 * overlap_2020


def _find_candidates(
    geom_2025,
    idx_2025: int,
    installations_2020_proj: gpd.GeoDataFrame,
    sindex_2020,
    max_centroid_distance: float,
) -> list[_Candidate]:
    search_geom = geom_2025.centroid.buffer(max_centroid_distance).union(geom_2025)
    candidate_positions = list(sindex_2020.query(search_geom, predicate="intersects"))
    candidates = []
    for pos in candidate_positions:
        row_2020 = installations_2020_proj.iloc[pos]
        geom_2020 = row_2020.geometry
        centroid_distance = geom_2025.centroid.distance(geom_2020.centroid)

        intersection_area = geom_2025.intersection(geom_2020).area
        union_area = geom_2025.union(geom_2020).area
        iou = intersection_area / union_area if union_area > 0 else 0.0
        overlap_2020 = intersection_area / geom_2020.area if geom_2020.area > 0 else 0.0
        overlap_2025 = intersection_area / geom_2025.area if geom_2025.area > 0 else 0.0

        if intersection_area <= 0 and centroid_distance > max_centroid_distance:
            continue

        candidates.append(
            _Candidate(
                index_2020=pos,
                installation_id_2020=row_2020["installation_id"],
                iou=iou,
                overlap_ratio_2020=overlap_2020,
                overlap_ratio_2025=overlap_2025,
                centroid_distance_m=centroid_distance,
                match_score=_blended_score(iou, overlap_2020, overlap_2025),
            )
        )
    candidates.sort(key=lambda c: c.match_score, reverse=True)
    return candidates


def _confidence_for(annotation_confidences: list[str]) -> str:
    order = {"Low": 0, "Not recorded": 0, "Medium": 1, "High": 2}
    cleaned = [c if c in order else "Not recorded" for c in annotation_confidences]
    return min(cleaned, key=lambda c: order[c]) if cleaned else "Not recorded"


def classify_changes(
    installations_2020: gpd.GeoDataFrame,
    installations_2025: gpd.GeoDataFrame,
    config: ChangeDetectionConfig,
    projected_crs: Optional[str] = None,
) -> pd.DataFrame:
    """Classify every 2020/2025 installation pair-or-singleton into a change record.

    Returns a plain ``pandas.DataFrame`` (one row per change record) with the
    columns defined in ``models.CHANGE_RECORD_FIELDS``. Geometry is
    intentionally NOT carried on this table; callers join back to
    ``installations_2020`` / ``installations_2025`` by installation ID when a
    geometry is needed (e.g. for map display).
    """
    combined = pd.concat(
        [installations_2020[["geometry"]] if not installations_2020.empty else None,
         installations_2025[["geometry"]] if not installations_2025.empty else None],
        ignore_index=True,
    ) if not (installations_2020.empty and installations_2025.empty) else None

    if projected_crs is None and combined is not None and not combined.empty:
        combined_gdf = gpd.GeoDataFrame(combined, crs="EPSG:4326")
        from src.geometry_utils import estimate_utm_crs

        projected_crs = estimate_utm_crs(combined_gdf)

    installations_2020_proj = (
        to_projected(installations_2020, projected_crs)[0] if not installations_2020.empty else installations_2020
    )
    installations_2025_proj = (
        to_projected(installations_2025, projected_crs)[0] if not installations_2025.empty else installations_2025
    )

    if not installations_2020_proj.empty:
        installations_2020_proj = installations_2020_proj.reset_index(drop=True)
        sindex_2020 = installations_2020_proj.sindex
    else:
        sindex_2020 = None

    records: list[dict] = []
    matched_2020_ids: set[str] = set()
    change_counter = 0

    for _, row_2025 in installations_2025_proj.reset_index(drop=True).iterrows():
        change_counter += 1
        change_id = f"CHG-{change_counter:05d}"
        geom_2025 = row_2025.geometry
        area_2025 = geom_2025.area

        candidates: list[_Candidate] = []
        if sindex_2020 is not None:
            candidates = _find_candidates(
                geom_2025, row_2025.name, installations_2020_proj, sindex_2020, config.maximum_centroid_distance_m
            )

        if not candidates:
            records.append(
                _new_record(
                    change_id,
                    None,
                    row_2025["installation_id"],
                    ChangeType.NEWLY_OBSERVED,
                    match_score=0.0,
                    iou=0.0,
                    overlap_2020=0.0,
                    overlap_2025=0.0,
                    centroid_distance=float("nan"),
                    area_2020=None,
                    area_2025=area_2025,
                    reason=(
                        f"No 2020 installation was found within {config.maximum_centroid_distance_m:.0f} metres "
                        f"and no overlapping 2020 geometry was detected."
                    ),
                    detection_confidence=(
                        DetectionConfidence.LOW.value
                        if row_2025.get("annotation_confidence") == "Low"
                        else DetectionConfidence.HIGH.value
                    ),
                )
            )
            continue

        best = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None

        is_credible = best.iou >= config.minimum_iou_match or best.overlap_ratio_2025 >= config.minimum_overlap_ratio

        if not is_credible:
            has_weak_signal = best.centroid_distance_m <= config.maximum_centroid_distance_m and (
                best.iou > 0 or best.overlap_ratio_2025 > 0
            )
            if has_weak_signal:
                records.append(
                    _new_record(
                        change_id,
                        best.installation_id_2020,
                        row_2025["installation_id"],
                        ChangeType.UNCERTAIN,
                        best.match_score,
                        best.iou,
                        best.overlap_ratio_2020,
                        best.overlap_ratio_2025,
                        best.centroid_distance_m,
                        installations_2020_proj.iloc[best.index_2020].geometry.area,
                        area_2025,
                        reason=(
                            f"A 2020 installation was found within {config.maximum_centroid_distance_m:.0f} metres "
                            f"but the overlap score (IoU={best.iou:.2f}, 2025 overlap={best.overlap_ratio_2025:.2f}) "
                            f"was below the matching threshold (IoU>={config.minimum_iou_match:.2f} or "
                            f"overlap>={config.minimum_overlap_ratio:.2f}). Flagged for human review."
                        ),
                        detection_confidence=DetectionConfidence.LOW.value,
                    )
                )
                matched_2020_ids.add(best.installation_id_2020)
            else:
                records.append(
                    _new_record(
                        change_id,
                        None,
                        row_2025["installation_id"],
                        ChangeType.NEWLY_OBSERVED,
                        best.match_score,
                        best.iou,
                        best.overlap_ratio_2020,
                        best.overlap_ratio_2025,
                        best.centroid_distance_m,
                        None,
                        area_2025,
                        reason=(
                            f"The nearest 2020 installation had an overlap score below the matching threshold "
                            f"and lies farther than {config.maximum_centroid_distance_m:.0f} metres away; "
                            f"treated as newly observed rather than a weak match."
                        ),
                        detection_confidence=DetectionConfidence.HIGH.value,
                    )
                )
            continue

        ambiguous = (
            second is not None
            and second.match_score >= best.match_score - config.ambiguous_secondary_match_margin
            and (second.iou > 0 or second.overlap_ratio_2025 > 0)
        )
        near_threshold_margin = max(
            best.iou - config.minimum_iou_match, best.overlap_ratio_2025 - config.minimum_overlap_ratio
        )
        near_threshold = 0 <= near_threshold_margin < config.uncertainty_margin

        area_2020 = installations_2020_proj.iloc[best.index_2020].geometry.area
        area_change_ratio = (area_2025 - area_2020) / area_2020 if area_2020 > 0 else float("inf")

        if ambiguous:
            records.append(
                _new_record(
                    change_id,
                    best.installation_id_2020,
                    row_2025["installation_id"],
                    ChangeType.UNCERTAIN,
                    best.match_score,
                    best.iou,
                    best.overlap_ratio_2020,
                    best.overlap_ratio_2025,
                    best.centroid_distance_m,
                    area_2020,
                    area_2025,
                    reason=(
                        f"Multiple 2020 installations matched this 2025 installation with similar scores "
                        f"(best={best.match_score:.2f}, next={second.match_score:.2f}), so the match is ambiguous "
                        f"and requires human review."
                    ),
                    detection_confidence=DetectionConfidence.LOW.value,
                )
            )
            matched_2020_ids.add(best.installation_id_2020)
            continue

        if near_threshold:
            records.append(
                _new_record(
                    change_id,
                    best.installation_id_2020,
                    row_2025["installation_id"],
                    ChangeType.UNCERTAIN,
                    best.match_score,
                    best.iou,
                    best.overlap_ratio_2020,
                    best.overlap_ratio_2025,
                    best.centroid_distance_m,
                    area_2020,
                    area_2025,
                    reason=(
                        f"The match score (IoU={best.iou:.2f}, 2025 overlap={best.overlap_ratio_2025:.2f}) is only "
                        f"marginally above the matching threshold, so the match confidence is too low to classify "
                        f"automatically as existing or expanded."
                    ),
                    detection_confidence=DetectionConfidence.MEDIUM.value,
                )
            )
            matched_2020_ids.add(best.installation_id_2020)
            continue

        if area_2025 > area_2020 * (1 + config.expansion_area_change_ratio):
            change_type = ChangeType.EXPANDED
            reason = (
                f"This 2025 installation matches a 2020 installation (IoU={best.iou:.2f}) but its area increased "
                f"by {area_change_ratio * 100:.0f}%, exceeding the configured expansion threshold "
                f"({config.expansion_area_change_ratio * 100:.0f}%)."
            )
        elif abs(area_change_ratio) <= config.stable_area_change_ratio:
            change_type = ChangeType.EXISTING
            reason = (
                f"This 2025 installation credibly matches a 2020 installation (IoU={best.iou:.2f}) and its area "
                f"changed by only {area_change_ratio * 100:.0f}%, within the stable-area threshold "
                f"({config.stable_area_change_ratio * 100:.0f}%)."
            )
        else:
            change_type = ChangeType.UNCERTAIN
            reason = (
                f"This 2025 installation matches a 2020 installation (IoU={best.iou:.2f}) but its area changed by "
                f"{area_change_ratio * 100:.0f}%, which is beyond the stable-area threshold but does not clearly "
                f"indicate expansion. Flagged for human review."
            )

        conf = (
            DetectionConfidence.HIGH.value
            if best.iou >= config.minimum_iou_match + 0.15
            else DetectionConfidence.MEDIUM.value
        )
        if change_type == ChangeType.UNCERTAIN:
            conf = DetectionConfidence.LOW.value

        records.append(
            _new_record(
                change_id,
                best.installation_id_2020,
                row_2025["installation_id"],
                change_type,
                best.match_score,
                best.iou,
                best.overlap_ratio_2020,
                best.overlap_ratio_2025,
                best.centroid_distance_m,
                area_2020,
                area_2025,
                reason=reason,
                detection_confidence=conf,
            )
        )
        matched_2020_ids.add(best.installation_id_2020)

    # --- Potentially removed: 2020 installations never credibly matched ---
    if not installations_2020_proj.empty:
        for _, row_2020 in installations_2020_proj.reset_index(drop=True).iterrows():
            inst_id = row_2020["installation_id"]
            if inst_id in matched_2020_ids:
                continue
            change_counter += 1
            change_id = f"CHG-{change_counter:05d}"
            records.append(
                _new_record(
                    change_id,
                    inst_id,
                    None,
                    ChangeType.POTENTIALLY_REMOVED,
                    match_score=0.0,
                    iou=0.0,
                    overlap_2020=0.0,
                    overlap_2025=0.0,
                    centroid_distance=float("nan"),
                    area_2020=row_2020.geometry.area,
                    area_2025=None,
                    reason=(
                        "No 2025 installation was found near this 2020 installation's location. This may indicate "
                        "the system was removed, decommissioned, obscured in the 2025 imagery, or simply not "
                        "re-annotated — field or record verification is recommended before drawing conclusions."
                    ),
                    detection_confidence=(
                        DetectionConfidence.LOW.value
                        if row_2020.get("annotation_confidence") == "Low"
                        else DetectionConfidence.MEDIUM.value
                    ),
                )
            )

    if not records:
        logger.warning("Change detection produced zero records (both inventories may be empty).")
        return pd.DataFrame(columns=[
            "change_id", "installation_id_2020", "installation_id_2025", "change_type", "match_score", "iou",
            "overlap_ratio_2020", "overlap_ratio_2025", "centroid_distance_m", "area_2020_m2", "area_2025_m2",
            "area_change_m2", "area_change_percent", "classification_reason", "review_required", "detection_confidence",
        ])

    return pd.DataFrame(records)


def _new_record(
    change_id: str,
    installation_id_2020: Optional[str],
    installation_id_2025: Optional[str],
    change_type: ChangeType,
    match_score: float,
    iou: float,
    overlap_2020: float,
    overlap_2025: float,
    centroid_distance: float,
    area_2020: Optional[float],
    area_2025: Optional[float],
    reason: str,
    detection_confidence: str,
) -> dict:
    area_change_m2 = None
    area_change_percent = None
    if area_2020 is not None and area_2025 is not None:
        area_change_m2 = area_2025 - area_2020
        area_change_percent = (area_change_m2 / area_2020 * 100) if area_2020 > 0 else None

    review_required = change_type in {
        ChangeType.NEWLY_OBSERVED,
        ChangeType.EXPANDED,
        ChangeType.UNCERTAIN,
        ChangeType.POTENTIALLY_REMOVED,
    }

    return {
        "change_id": change_id,
        "installation_id_2020": installation_id_2020,
        "installation_id_2025": installation_id_2025,
        "change_type": change_type.value,
        "match_score": round(match_score, 4),
        "iou": round(iou, 4),
        "overlap_ratio_2020": round(overlap_2020, 4),
        "overlap_ratio_2025": round(overlap_2025, 4),
        "centroid_distance_m": round(centroid_distance, 2) if centroid_distance == centroid_distance else None,
        "area_2020_m2": round(area_2020, 2) if area_2020 is not None else None,
        "area_2025_m2": round(area_2025, 2) if area_2025 is not None else None,
        "area_change_m2": round(area_change_m2, 2) if area_change_m2 is not None else None,
        "area_change_percent": round(area_change_percent, 1) if area_change_percent is not None else None,
        "classification_reason": reason,
        "review_required": review_required,
        "detection_confidence": detection_confidence,
    }
