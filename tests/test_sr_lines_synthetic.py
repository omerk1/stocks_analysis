import pandas as pd
import pytest

from src.sr_lines import candidates as candidates_mod
from src.sr_lines import events as events_mod
from src.sr_lines import lifecycle
from src.sr_lines import pivots as pivots_mod
from src.sr_lines import scoring as scoring_mod
from src.sr_lines.config import SRConfig
from src.sr_lines.models import EventType, LineState


def _make_bars(rows: list[tuple]) -> pd.DataFrame:
    """rows: list of (date_str, open, high, low, close, volume)"""
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp").sort_index()


def _oscillating_series(n_cycles: int, leg_bars: int, low: float, high: float, start="2020-01-01") -> pd.DataFrame:
    """Deterministic sawtooth between `low` and `high`, turning exactly at
    each extreme (no noise) -- reversal magnitude (high-low) is large
    relative to the resulting ATR so pivots confirm reliably."""
    rows = []
    dates = pd.bdate_range(start, periods=n_cycles * 2 * leg_bars + 1)
    price = low
    step_up = (high - low) / leg_bars
    d_i = 0
    for _cycle in range(n_cycles):
        for _ in range(leg_bars):
            o = price
            price = min(price + step_up, high)
            c = price
            rows.append((dates[d_i], o, max(o, c) + 0.05, min(o, c) - 0.05, c, 1_000_000))
            d_i += 1
        for _ in range(leg_bars):
            o = price
            price = max(price - step_up, low)
            c = price
            rows.append((dates[d_i], o, max(o, c) + 0.05, min(o, c) - 0.05, c, 1_000_000))
            d_i += 1
    return _make_bars(rows)


def _established_index(bars: pd.DataFrame, candidate) -> int:
    """First bar index in `bars` where events.py's walk for `candidate` has
    already set current_side -- i.e. a safe place to start planting
    synthetic interactions without them being silently excluded (the walk
    only starts at the candidate's earliest pivot timestamp) or landing on
    the ambiguous first "inside the zone" bar."""
    first_pivot_ts = pd.Timestamp(min(p.timestamp for p in candidate.pivots))
    return bars.index.get_loc(first_pivot_ts) + 3


def _run_horizontal_pipeline(bars: pd.DataFrame, config: SRConfig):
    atr = pivots_mod.compute_atr(bars, config)
    pivot_list = pivots_mod.detect_pivots(bars, config, atr=atr)
    cands = candidates_mod.generate_horizontal_candidates(pivot_list, config)
    lines = []
    for i, cand in enumerate(cands):
        evs, original_side = events_mod.classify_events(bars, cand, atr, config)
        scores = scoring_mod.score_line(evs, bars, atr, cand.center, config, diagonal=False)
        lines.append(lifecycle.build_line(f"h{i}", cand, evs, original_side, scores))
    return lines, pivot_list, atr


def test_flat_level_finds_one_line_near_each_extreme():
    bars = _oscillating_series(n_cycles=4, leg_bars=15, low=95.0, high=105.0)
    config = SRConfig(window_years=1.0, pivot_atr_mult=2.0, zone_width_atr=0.4)

    lines, pivot_list, _ = _run_horizontal_pipeline(bars, config)

    assert len(pivot_list) >= 6  # multiple confirmed swing highs/lows across 4 cycles

    centers = sorted(line.center for line in lines)
    assert any(abs(c - 95.0) < 1.0 for c in centers)
    assert any(abs(c - 105.0) < 1.0 for c in centers)

    low_line = min(lines, key=lambda l: l.center)
    assert low_line.n_touches >= 2


def test_planted_wick_fake_is_classified_and_line_survives():
    bars = _oscillating_series(n_cycles=3, leg_bars=15, low=95.0, high=105.0)
    config = SRConfig(window_years=1.0, pivot_atr_mult=2.0, zone_width_atr=0.4)

    atr = pivots_mod.compute_atr(bars, config)
    pivot_list = pivots_mod.detect_pivots(bars, config, atr=atr)
    cands = candidates_mod.generate_horizontal_candidates(pivot_list, config)
    low_cand = min(cands, key=lambda c: c.center)

    # Plant a bar right after an established "support" touch: low pierces
    # well below the zone, but the close snaps back above it.
    zone_lo = low_cand.center - low_cand.half_width
    plant_date = bars.index[_established_index(bars, low_cand)]
    bars.loc[plant_date, ["open", "high", "low", "close"]] = [
        low_cand.center + 0.3, low_cand.center + 0.4, zone_lo - 2.0, low_cand.center + 0.2,
    ]
    bars = bars.sort_index()

    atr = pivots_mod.compute_atr(bars, config)
    evs, original_side = events_mod.classify_events(bars, low_cand, atr, config)

    assert any(e.type == EventType.WICK_FAKE for e in evs)
    scores = scoring_mod.score_line(evs, bars, atr, low_cand.center, config, diagonal=False)
    line = lifecycle.build_line("h0", low_cand, evs, original_side, scores)
    assert line.state == LineState.ACTIVE
    assert scores.resilience > 0


def test_planted_body_fake_reclaims_and_stays_active():
    bars = _oscillating_series(n_cycles=3, leg_bars=15, low=95.0, high=105.0)
    config = SRConfig(window_years=1.0, pivot_atr_mult=2.0, zone_width_atr=0.4, fakeout_reclaim_bars=5)

    atr = pivots_mod.compute_atr(bars, config)
    pivot_list = pivots_mod.detect_pivots(bars, config, atr=atr)
    cands = candidates_mod.generate_horizontal_candidates(pivot_list, config)
    low_cand = min(cands, key=lambda c: c.center)
    zone_lo = low_cand.center - low_cand.half_width

    # Two closes below the zone, then a reclaim within K bars.
    start_i = _established_index(bars, low_cand)
    d0, d1, d2 = bars.index[start_i], bars.index[start_i + 1], bars.index[start_i + 2]
    bars.loc[d0, ["open", "high", "low", "close"]] = [zone_lo - 0.1, zone_lo, zone_lo - 1.5, zone_lo - 1.0]
    bars.loc[d1, ["open", "high", "low", "close"]] = [zone_lo - 1.0, zone_lo - 0.5, zone_lo - 2.0, zone_lo - 1.5]
    bars.loc[d2, ["open", "high", "low", "close"]] = [
        zone_lo - 1.5, low_cand.center + 0.3, zone_lo - 1.5, low_cand.center + 0.2,
    ]
    bars = bars.sort_index()

    atr = pivots_mod.compute_atr(bars, config)
    evs, original_side = events_mod.classify_events(bars, low_cand, atr, config)

    assert any(e.type == EventType.BODY_FAKE and not e.pending for e in evs)
    assert not any(e.type == EventType.BREAK for e in evs)
    scores = scoring_mod.score_line(evs, bars, atr, low_cand.center, config, diagonal=False)
    line = lifecycle.build_line("h0", low_cand, evs, original_side, scores)
    assert line.state == LineState.ACTIVE


def test_real_break_then_retest_flips_role():
    bars = _oscillating_series(n_cycles=3, leg_bars=15, low=95.0, high=105.0)
    config = SRConfig(window_years=1.0, pivot_atr_mult=2.0, zone_width_atr=0.4, fakeout_reclaim_bars=5)

    atr = pivots_mod.compute_atr(bars, config)
    pivot_list = pivots_mod.detect_pivots(bars, config, atr=atr)
    cands = candidates_mod.generate_horizontal_candidates(pivot_list, config)
    low_cand = min(cands, key=lambda c: c.center)
    zone_lo = low_cand.center - low_cand.half_width
    zone_hi = low_cand.center + low_cand.half_width

    # A sustained break below the zone (no reclaim within K bars) ...
    start_i = _established_index(bars, low_cand)
    price = zone_lo - 0.5
    for offset in range(8):
        d = bars.index[start_i + offset]
        price -= 0.3
        bars.loc[d, ["open", "high", "low", "close"]] = [price + 0.3, price + 0.4, price - 0.2, price]
    # ... followed later by a retest from below that respects the level as
    # resistance (touches and bounces back down).
    retest_i = start_i + 20
    d = bars.index[retest_i]
    bars.loc[d, ["open", "high", "low", "close"]] = [
        zone_lo - 0.5, zone_hi + 0.3, zone_lo - 0.6, zone_lo - 0.4,
    ]
    bars = bars.sort_index()

    atr = pivots_mod.compute_atr(bars, config)
    evs, original_side = events_mod.classify_events(bars, low_cand, atr, config)

    assert any(e.type == EventType.BREAK for e in evs)
    scores = scoring_mod.score_line(evs, bars, atr, low_cand.center, config, diagonal=False)
    line = lifecycle.build_line("h0", low_cand, evs, original_side, scores)

    assert line.state == LineState.FLIPPED
    assert scores.role_reversal == 1.0


def test_pivots_alternate_and_confirmed_at_is_after_the_pivot():
    bars = _oscillating_series(n_cycles=3, leg_bars=15, low=95.0, high=105.0)
    config = SRConfig(window_years=1.0, pivot_atr_mult=2.0)

    atr = pivots_mod.compute_atr(bars, config)
    pivot_list = pivots_mod.detect_pivots(bars, config, atr=atr)

    assert len(pivot_list) >= 4
    for a, b in zip(pivot_list, pivot_list[1:]):
        assert a.kind != b.kind  # strictly alternating
    for p in pivot_list:
        assert pd.Timestamp(p.confirmed_at) > pd.Timestamp(p.timestamp)
