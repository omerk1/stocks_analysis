"""§6 confidence scoring + §6.1 geometric-cleanliness sub-metrics.

Each detector computes its own component scores (a `dict[str, float]`, one
entry per `config.scoring_weights` key) and calls `score_pattern` to combine
them into one confidence in [0, 1] plus a `notes` list -- e.g.
"geometric_cleanliness: 0.91, volume_signature: 0.62" -- so a real value is
visible per component during tuning instead of one opaque number (§6.1's own
stated reasoning for keeping these un-collapsed).

Deliberately thin for now, same as config.py: only the pattern-agnostic
sub-metrics Phase 1 (double top/bottom) needs. Pattern-specific cleanliness
additions (H&S time symmetry, triangle convergence quality, cup roundedness
R², VCP contraction-monotonicity strictness) get added alongside each
detector as later phases land, not built ahead of any pattern that needs
them.
"""

from __future__ import annotations

from src.foundation.market_common.models import Direction
from src.signals.patterns.config import PatternConfig


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def price_symmetry(a: float, b: float) -> float:
    """1 - |a-b|/avg(a,b), clipped to [0,1] -- e.g. two peaks'/shoulders'
    price symmetry (§6.1)."""
    avg = (a + b) / 2
    if avg <= 0:
        return 0.0
    return _clip01(1 - abs(a - b) / avg)


def hs_price_symmetry(left_shoulder: float, right_shoulder: float, head: float) -> float:
    """§6.1 H&S/Inverse-H&S price symmetry: `1 - |LS-RS|/Head`, clipped to
    [0,1] -- the design doc's own explicit H&S formula. Distinct from
    `price_symmetry` (normalized by avg(a,b), what double top/bottom uses):
    here the natural normalizer is head height, since LS/RS are being
    compared to each other in the context of a much taller head."""
    if head <= 0:
        return 0.0
    return _clip01(1 - abs(left_shoulder - right_shoulder) / head)


def hs_time_symmetry(bars_ls_to_head: int, bars_head_to_rs: int, bars_ls_to_rs: int) -> float:
    """§6.1: `1 - |bars(LS->Head) - bars(Head->RS)| / bars(LS->RS)`, clipped
    to [0,1] -- does the pattern take roughly the same number of bars to
    form on each side of the head, independent of price symmetry."""
    if bars_ls_to_rs <= 0:
        return 0.0
    return _clip01(1 - abs(bars_ls_to_head - bars_head_to_rs) / bars_ls_to_rs)


def point_count_score(n_touches: int, min_required: int) -> float:
    """§6.1 "Point count vs. minimum": `min(n_touches/min_required, 1.0)` --
    a boundary with more touches than the bare hard-gate floor scores
    higher, capping once it reaches the floor's own multiple of itself."""
    if min_required <= 0:
        return 0.0
    return _clip01(n_touches / min_required)


def range_monotonicity_score(leg_ranges: list[float]) -> float:
    """§6.1 triangle/wedge addition: fraction of consecutive leg-to-leg
    amplitude pairs that actually shrink (`leg_ranges[k+1] <=
    leg_ranges[k]`), same "successive contraction" idea VCP's own
    monotonicity check (§4.5) will use -- penalizes a triangle whose range
    widens on an intermediate swing before resuming convergence, even
    though the *fitted* boundary lines (linear by construction) always
    converge cleanly once the hard convergence gate has passed. Computed
    from `leg_ranges`, not the fitted lines, for exactly that reason: a
    monotonicity check against the fitted lines' own evaluated values
    would be vacuously 1.0 every time. Vacuously 1.0 itself when fewer
    than 2 legs are given (nothing to compare)."""
    if len(leg_ranges) < 2:
        return 1.0
    pairs = list(zip(leg_ranges, leg_ranges[1:]))
    shrank = sum(1 for a, b in pairs if b <= a)
    return shrank / len(pairs)


def apex_proximity_score(window_start_bar: int, window_end_bar: int, apex_bar: float) -> float:
    """§6.1: how close the pattern's last known pivot sits to its apex,
    as a fraction of the window's own span to the apex -- "too early =
    little conviction yet ... right before the apex = classic
    high-conviction zone." Clipped to [0,1]; callers already hard-gate
    `apex_bar > window_end_bar`, so this is always a fraction short of a
    full "reached the apex" 1.0 in practice, not literally guaranteed to
    hit it."""
    denom = apex_bar - window_start_bar
    if denom <= 0:
        return 0.0
    return _clip01((window_end_bar - window_start_bar) / denom)


def contraction_tightness_score(ratio: float, max_ratio: float) -> float:
    """§4.5 point 7 / §6.1 VCP addition: the ATR(short)/ATR(long)
    contraction ratio, turned into a continuous [0,1] cleanliness score --
    0 at the hard gate's own ceiling (`max_ratio`), 1.0 at a fully
    contracted ratio of 0. Distinct from the hard gate itself (which
    rejects any candidate above `max_ratio` outright); this scores *how*
    tight a passing candidate's final contraction actually is, since two
    candidates can both clear the same gate by very different margins."""
    if max_ratio <= 0:
        return 0.0
    return _clip01(1 - ratio / max_ratio)


def breakout_close_strength(
    breakout_close: float, level_price: float, atr: float | None, direction: Direction, cap_atr: float
) -> float:
    """How far beyond the trigger level the breakout close moved, in ATR,
    clipped to [0, 1] at `cap_atr`+."""
    if atr is None or atr <= 0:
        return 0.0
    move = (
        (level_price - breakout_close) / atr
        if direction == Direction.BEARISH
        else (breakout_close - level_price) / atr
    )
    return _clip01(move / cap_atr) if cap_atr > 0 else 0.0


def duration_fit(formation_bars: int, typical_min_bars: int, typical_max_bars: int) -> float:
    """1.0 within [typical_min_bars, typical_max_bars]; ramps up linearly
    below the minimum (too short to be a real pattern yet); decays above
    the maximum but floors at 0.3 (running long is a real quality concern,
    not grounds for zeroing out an otherwise-valid pattern -- same floor
    reasoning as sr_lines' body-fake decay)."""
    if typical_min_bars <= formation_bars <= typical_max_bars:
        return 1.0
    if formation_bars < typical_min_bars:
        return _clip01(formation_bars / typical_min_bars) if typical_min_bars > 0 else 0.0
    overage = (formation_bars - typical_max_bars) / typical_max_bars if typical_max_bars > 0 else 1.0
    return max(0.3, _clip01(1.0 - overage))


def prior_trend_strength(pct_move: float, cap_pct: float) -> float:
    return _clip01(pct_move / cap_pct) if cap_pct > 0 else 0.0


def volume_signature_score(rel_vol: float | None, cap_mult: float) -> float:
    """rel_vol <= 1.0x (no expansion at all) scores 0; `cap_mult`+ scores
    1.0, linear between."""
    if rel_vol is None or rel_vol <= 1.0 or cap_mult <= 1.0:
        return 0.0
    return _clip01((rel_vol - 1.0) / (cap_mult - 1.0))


def score_pattern(components: dict[str, float], config: PatternConfig) -> tuple[float, list[str]]:
    """Combine per-component [0,1] scores via `config.scoring_weights` into
    one confidence + human-readable notes. Assumes `components` supplies
    exactly the keys `config.scoring_weights` has (weights sum to 1.0 by
    construction, see config._default_scoring_weights) -- a missing key is
    a caller bug, not silently ignored, so this deliberately does not
    fall back to a subset/renormalized sum the way sr_lines' relevance
    gate does (that renormalization exists there because proximity was
    *removed* from the additive terms after the fact; nothing here is in
    that situation)."""
    weights = config.scoring_weights
    total = sum(weights[k] * components[k] for k in weights)
    notes = [f"{k}: {components[k]:.2f}" for k in sorted(components)]
    return _clip01(total), notes
