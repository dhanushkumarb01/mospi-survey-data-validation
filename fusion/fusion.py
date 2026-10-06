"""Pure risk-combination helpers for the V1 fusion layer."""

from __future__ import annotations

from typing import Mapping


def combine_risk(ranks: Mapping[str, float | None], weights: Mapping[str, float], override_threshold: float) -> tuple[float | None, bool]:
    """Weighted available-evidence mean with a transparent extreme-rank floor."""
    available = {name: value for name, value in ranks.items() if value is not None}
    denominator = sum(weights[name] for name in available)
    if not available or denominator <= 0:
        return None, False
    weighted = sum(weights[name] * value for name, value in available.items()) / denominator
    maximum = max(available.values())
    overridden = maximum >= override_threshold
    return (max(weighted, maximum) if overridden else weighted), overridden
