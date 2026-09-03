"""Shared least-squares line fit -- the one piece of trendline math genuinely
common between sr_lines' diagonal (RANSAC-style) candidate search and the
patterns module's local triangle/wedge fitting. Everything *around* this call
(candidate seeding/search, log-price normalization, inlier selection, dedup,
scoring) differs by design between the two callers and is deliberately not
shared -- see docs/features/chart_pattern_detection_design_notes.md.

Callers own their own x/y units (bar_index vs. price, or bar_index vs.
log-price) and any origin-shifting of the returned intercept -- this function
is intentionally just `np.polyfit(xs, ys, 1)` behind a typed signature.
"""

from __future__ import annotations

import numpy as np


def fit_line(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float]:
    """Least-squares fit of `ys = slope * xs + intercept`. Returns
    (slope, intercept), intercept at x=0 in whatever units `xs`/`ys` are
    given in -- callers needing an intercept relative to some other origin
    (e.g. sr_lines' `origin_index`) shift it themselves."""
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope), float(intercept)
