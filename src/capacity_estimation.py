"""Optional, clearly-labeled estimated PV capacity calculation.

``estimated_capacity_kw = pv_area_m2 * kw_per_m2``

The ``kw_per_m2`` factor is a configurable demo default only (see
``config/settings.yaml: capacity_estimation.kw_per_m2``). Actual capacity
depends on module efficiency, panel dimensions, roof layout, tilt, spacing,
obstructions, and PV technology type — none of which are observable from
polygon area alone. Every value this module produces must be presented to
users as an ESTIMATE, never as utility-confirmed nameplate capacity.
"""

from __future__ import annotations

import pandas as pd

from src.config import CapacityEstimationConfig

ESTIMATE_DISCLAIMER = (
    "Estimated from digitized rooftop area using a simple area-to-capacity factor. "
    "This is NOT a utility-confirmed nameplate capacity. Actual capacity depends on "
    "module efficiency, panel dimensions, roof layout, tilt, spacing, obstructions, "
    "and technology type."
)


def estimate_capacity_kw(area_m2: float, config: CapacityEstimationConfig) -> float:
    """Estimate capacity in kW for a single installation's area in m^2."""
    if area_m2 is None or area_m2 <= 0:
        return 0.0
    return round(area_m2 * config.kw_per_m2, 2)


def add_estimated_capacity(df: pd.DataFrame, area_col: str, config: CapacityEstimationConfig, out_col: str = "estimated_capacity_kw") -> pd.DataFrame:
    """Vectorized capacity estimation for a DataFrame column of areas."""
    result = df.copy()
    result[out_col] = (result[area_col].fillna(0) * config.kw_per_m2).round(2)
    return result


def is_large_installation(area_m2: float, config, large_area_m2: float) -> bool:
    """Flag installations above the configured 'large system' area threshold."""
    return (area_m2 or 0) >= large_area_m2
