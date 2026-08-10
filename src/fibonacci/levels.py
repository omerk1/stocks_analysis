"""Retracement/extension price computation and set-weighting.

Retracement and extension are both just points along the origin-end line
(or its log-price equivalent), parameterized by ratio `r`:
  - retracement(r) interpolates from the swing's END back toward its
    ORIGIN (0 < r < 1 lands strictly between them).
  - extension(r) interpolates from the ORIGIN through the END and beyond
    (r > 1 lands past the END, away from the ORIGIN).

This is direction-agnostic by construction: working the algebra out
separately for up-swings (origin=low, end=high) and down-swings
(origin=high, end=low) -- as the spec's prose does -- produces the exact
same two interpolation formulas both times, just with which price is `a`
and which is `b` swapped consistently. So there is deliberately no
if/else on `swing.direction` anywhere below; `origin_price`/`end_price`
already encode the direction, and interpolation doesn't care which one is
numerically larger.
"""

from __future__ import annotations

import math
import uuid

from src.fibonacci.config import FibConfig
from src.fibonacci.models import FibLevel, FibLevelKind, FibSwing


def _interp_linear(a: float, b: float, r: float) -> float:
    return a + r * (b - a)


def _interp_log(a: float, b: float, r: float) -> float:
    return math.exp(math.log(a) + r * (math.log(b) - math.log(a)))


def compute_levels(swing: FibSwing, config: FibConfig) -> list[FibLevel]:
    interp = _interp_log if config.price_scale == "log" else _interp_linear
    origin, end = swing.origin_price, swing.end_price

    levels = [
        FibLevel(id=str(uuid.uuid4()), ratio=r, kind=FibLevelKind.RETRACEMENT, price=interp(end, origin, r))
        for r in config.retracement_ratios
    ]
    levels += [
        FibLevel(id=str(uuid.uuid4()), ratio=r, kind=FibLevelKind.EXTENSION, price=interp(origin, end, r))
        for r in config.extension_ratios
    ]
    return levels


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_weight(swing: FibSwing, bars_since_end: int, config: FibConfig) -> float:
    """Sum of three [0, 1]-clipped components, weighted by
    `config.weight_components`. `recency` is bounded by construction
    (bars_since_end >= 0) so it's deliberately not re-clipped on top of
    that -- see FibConfig.weight_components' docstring in the spec for why
    that's intentional, not an oversight.
    """
    magnitude = _clip(swing.magnitude_atr / 40, 0.0, 1.0)
    duration = _clip(swing.duration_bars / 250, 0.0, 1.0)
    recency = 0.5 ** (bars_since_end / config.recency_half_life_bars)

    w = config.weight_components
    return w["magnitude"] * magnitude + w["duration"] * duration + w["recency"] * recency
