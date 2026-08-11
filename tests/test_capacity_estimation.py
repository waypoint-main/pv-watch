"""Unit tests for the (clearly-labeled, demo-only) capacity estimation logic."""

from __future__ import annotations

import pandas as pd

from src.capacity_estimation import add_estimated_capacity, estimate_capacity_kw, is_large_installation
from src.config import CapacityEstimationConfig


def test_capacity_estimation_uses_configured_factor():
    config = CapacityEstimationConfig(kw_per_m2=0.2, large_system_capacity_kw=15.0)
    assert estimate_capacity_kw(100.0, config) == 20.0

    config2 = CapacityEstimationConfig(kw_per_m2=0.1, large_system_capacity_kw=15.0)
    assert estimate_capacity_kw(100.0, config2) == 10.0


def test_capacity_estimation_handles_zero_and_none_area():
    config = CapacityEstimationConfig(kw_per_m2=0.17)
    assert estimate_capacity_kw(0, config) == 0.0
    assert estimate_capacity_kw(None, config) == 0.0


def test_add_estimated_capacity_is_vectorized_and_uses_config():
    config = CapacityEstimationConfig(kw_per_m2=0.15)
    df = pd.DataFrame({"area_m2": [10.0, 20.0, None]})
    result = add_estimated_capacity(df, "area_m2", config)

    assert list(result["estimated_capacity_kw"]) == [1.5, 3.0, 0.0]


def test_is_large_installation_threshold():
    config = CapacityEstimationConfig()
    assert is_large_installation(100.0, config, large_area_m2=90.0) is True
    assert is_large_installation(50.0, config, large_area_m2=90.0) is False
