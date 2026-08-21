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

from src.market_common.models import Direction
from src.patterns.config import PatternConfig


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def price_symmetry(a: float, b: float) -> float:
    """1 - |a-b|/avg(a,b), clipped to [0,1] -- e.g. two peaks'/shoulders'
    price symmetry (§6.1)."""
    avg = (a + b) / 2
    if avg <= 0:
        return 0.0
    return _clip01(1 - abs(a - b) / avg)


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
