"""Quadratic (parabola) curve fitting -- design doc §4.4 point 3 / §6.1.
Its own small module, not `trendlines.py`: a cup's roundedness isn't a
trendline (linear boundary/level), it's a curve fit over the whole price
path between two rim pivots. Isolated and independently tested before
wiring into Phase 4's cup & handle detector, per the module's own
progress-tracker note.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["fit_roundedness", "QuadraticFit", "fit_quadratic", "max_single_bar_move_frac"]


@dataclass(frozen=True)
class QuadraticFit:
    """A quadratic fit's R² plus the two shape facts a bare R² throws away.

    R² alone is a poor "rounded vs. V-shaped" discriminator, which is the
    whole reason this exists: a monotone price path fits a parabola *arm*
    almost perfectly and scores a high R², so R² rewards exactly the shape
    §4.4 point 3 is trying to exclude. Measured on hand-audited instances,
    the one genuine cup scored the lowest R² of its group. `curvature` and
    `apex_position` are what actually separate them.
    """

    r2: float
    # The `a` in a*x^2+b*x+c. Sign says which way the parabola opens: > 0
    # for a cup / rounding bottom (U), < 0 for their inverses (∩).
    # This fit is deliberately direction-agnostic, so callers have to check
    # this themselves against the shape they expect.
    curvature: float
    # Vertex x, normalised to the window: 0.0 = first bar, 1.0 = last bar.
    # Falls outside [0, 1] when the fit is really a monotone arm rather than
    # a bowl -- exactly the case R² fails to punish. NaN for a degenerate
    # (curvature == 0) fit.
    apex_position: float


def _polyfit2(prices: np.ndarray) -> tuple[float, float, float, np.ndarray]:
    x = np.arange(len(prices), dtype=float)
    a, b, c = np.polyfit(x, prices, 2)
    return float(a), float(b), float(c), x


def fit_quadratic(prices: np.ndarray) -> QuadraticFit:
    """Fit `y = a*x^2 + b*x + c` to `prices` (x = 0..len-1, evenly spaced by
    bar position) and return its R² alongside the curvature sign and apex
    position from that same fit -- §4.4's own "rounded, not V-shaped"
    operationalization (a high R² means the price path genuinely tracks a
    parabola), plus the two facts a bare R² throws away. One `np.polyfit`
    call for all three."""
    a, b, c, x = _polyfit2(prices)
    predicted = a * x**2 + b * x + c
    ss_res = float(np.sum((prices - predicted) ** 2))
    ss_tot = float(np.sum((prices - np.mean(prices)) ** 2))
    r2 = 1.0 if ss_tot == 0 else 1 - ss_res / ss_tot
    span = len(prices) - 1
    apex = float("nan") if a == 0 or span <= 0 else (-b / (2 * a)) / span
    return QuadraticFit(r2=r2, curvature=a, apex_position=apex)


def max_single_bar_move_frac(prices: np.ndarray) -> float:
    """Largest single-bar move as a fraction of the path's full range --
    §4.4 point 3's own "simpler heuristic" that no single-bar move should
    account for a large fraction of the total cup depth. Catches a one-day
    gap (earnings cliff, halt reopen) masquerading as a cup wall, which the
    parabola fit happily accommodates. 0.0 for a flat path."""
    if len(prices) < 2:
        return 0.0
    price_range = float(np.max(prices) - np.min(prices))
    if price_range <= 0:
        return 0.0
    return float(np.max(np.abs(np.diff(prices)))) / price_range


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
