"""Quadratic (parabola) curve fitting -- design doc §4.4 point 3 / §6.1.
Its own small module, not `trendlines.py`: a cup's roundedness isn't a
trendline (linear boundary/level), it's a curve fit over the whole price
path between two rim pivots. Isolated and independently tested before
wiring into Phase 4's cup & handle detector, per the module's own
progress-tracker note.
"""

from __future__ import annotations

import numpy as np

__all__ = ["fit_roundedness"]


def fit_roundedness(prices: np.ndarray) -> float:
    """Fit `y = a*x^2 + b*x + c` to `prices` (x = 0..len-1, evenly spaced
    by bar position) and return its R² -- §4.4's own operationalization of
    "rounded, not V-shaped": a high R² means the price path genuinely
    tracks a parabola, a low R² means it's sharp/angular and doesn't.

    Direction-agnostic: a downward-opening parabola (rounding top /
    inverse cup & handle's own bulge) fits exactly as well as an
    upward-opening one (a regular cup) -- which shape is *expected* is a
    question for the caller's own pivot kind, not this function.

    Same `1 - ss_res/ss_tot` R² as `trendlines.r_squared`, computed
    separately rather than shared: one is a 2-coefficient linear fit, this
    is a 3-coefficient quadratic one -- different `np.polyfit` degree,
    different domain (curve roundedness vs. trendline touches), not worth
    forcing through one generic signature for two call sites.
    """
    x = np.arange(len(prices), dtype=float)
    a, b, c = np.polyfit(x, prices, 2)
    predicted = a * x**2 + b * x + c
    ss_res = float(np.sum((prices - predicted) ** 2))
    ss_tot = float(np.sum((prices - np.mean(prices)) ** 2))
    if ss_tot == 0:
        return 1.0
    return 1 - ss_res / ss_tot
