"""GapConfig -- every tunable knob for gap/FVG detection and lifecycle, kept
in one place so the CLI and plotting can drive it without touching detection
code (same reasoning as sr_lines.config.SRConfig).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GapConfig:
    # Zones smaller than this x ATR (at the creation bar) are discarded --
    # keeps genuinely tradeable imbalances distinct from the routine
    # sub-noise-band gaps every series produces at every bar-to-bar step.
    min_gap_atr: float = 0.3
    atr_period: int = 14

    # Fill-percentage threshold for SOFT_CLOSED (see lifecycle.py) -- a gap
    # that's been mostly, but not completely, retraced reads differently to
    # a trader than one barely touched or one fully closed.
    soft_close_pct: float = 80.0

    # "wick" or "body_close" -- what counts toward fill. Wick is the
    # permissive default (any intraday touch counts); body_close is the
    # stricter reading some gap-trading approaches use ("the market has to
    # actually accept price inside the zone, not just wick through it").
    fill_by: str = "wick"

    # Below this many rows (after filtering to the running as_of), skip the
    # (ticker, timeframe) series entirely rather than run detection on too
    # short a history to have a meaningful, fully-warmed-up ATR.
    min_bars: int = 150

    # Skip this many leading bars of each series for detection purposes --
    # guarantees ATR(atr_period) is fully formed (no NaN warmup tail) before
    # any gap is ever sized against it. Gaps created inside the warmup
    # window are simply never recorded, not recorded-then-discarded.
    warmup_bars: int = 50
