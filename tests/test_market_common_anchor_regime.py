import pandas as pd

from src.foundation.market_common.anchors import AnchorConfig, AnchorType, discover_anchors
from src.foundation.market_common.models import Timeframe

# Cycle pivots off, tiny 52w window: only the major high/low roles matter here.
BASE = dict(min_bars=1, warmup_bars=0, cycle_scale_mult=1.0e9, trailing_window_bars={"daily": 5, "weekly": 52})


def _bars(closes, start="2015-01-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    c = pd.Series(closes, index=idx, dtype="float64")
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1000.0})


def _roles(bars, **cfg):
    anchors = discover_anchors(bars, Timeframe.DAILY, AnchorConfig(**{**BASE, **cfg}))
    return {r: pd.Timestamp(a.anchor_date) for a in anchors for r in a.anchor_types}


def test_an_old_all_time_high_price_is_still_near_stays_the_ath():
    # ATH of 100 about 3.5 years back, a long consolidation, now 15% below.
    closes = [60.0] * 50 + [100.0] + [80.0] * 850 + [85.0]
    bars = _bars(closes)
    roles = _roles(bars)
    assert roles[AnchorType.ATH] == bars.index[50]
    assert AnchorType.REGIME_HIGH not in roles


def test_an_all_time_low_far_below_today_is_replaced_by_the_regime_low():
    # From 1 up to 300: the 1 is 300x below today; price was last under
    # 150 (half of today) at the 120 stretch, so the regime starts after it.
    closes = [1.0] + [5.0] * 100 + [120.0] * 100 + [200.0] * 50 + [180.0] + [300.0] * 50
    bars = _bars(closes)
    roles = _roles(bars)
    assert AnchorType.ATL not in roles
    assert roles[AnchorType.REGIME_LOW] == bars.index[251]  # the 180 dip, the regime's low


def test_a_collapse_replaces_the_far_all_time_high_with_the_regime_high():
    closes = [500.0] * 100 + [20.0] * 100 + [30.0] + [18.0] * 50 + [20.0]
    bars = _bars(closes)
    roles = _roles(bars)
    assert AnchorType.ATH not in roles
    assert roles[AnchorType.REGIME_HIGH] == bars.index[200]  # 30, within 2x of today's 20


def test_reach_factor_none_keeps_true_all_time_extremes():
    closes = [1.0] + [5.0] * 100 + [300.0] * 50
    bars = _bars(closes)
    roles = _roles(bars, regime_reach_factor=None)
    assert roles[AnchorType.ATL] == bars.index[0]
    assert roles[AnchorType.ATH] == bars.index[101]


def test_regime_is_judged_from_the_as_of_date():
    # As of the middle of the series, the early low is still in reach.
    closes = [10.0] + [12.0] * 100 + [400.0] * 100
    bars = _bars(closes)
    assert _roles(bars.iloc[:101])[AnchorType.ATL] == bars.index[0]
    assert AnchorType.ATL not in _roles(bars)


def test_wider_reach_admits_farther_extremes():
    closes = [100.0] * 50 + [40.0] * 50 + [45.0]   # ATH is 2.2x above today
    bars = _bars(closes)
    assert AnchorType.ATH not in _roles(bars, regime_reach_factor=2.0)
    assert _roles(bars, regime_reach_factor=3.0)[AnchorType.ATH] == bars.index[0]


def test_cycle_swings_out_of_reach_are_dropped():
    # A big early swing (up to 500 and back) far above today's 20.
    closes = [100.0] * 30 + [500.0] * 5 + [100.0] * 30 + [20.0] * 40 + [26.0] * 5 + [20.0] * 40
    bars = _bars(closes)
    cfg = dict(cycle_scale_mult=3.0)
    # ATR of flat stretches is ~0, so give pivots a floor through a noisy copy
    noisy = bars.copy()
    noisy["high"] = noisy["close"] * 1.02
    noisy["low"] = noisy["close"] * 0.98
    keep = discover_anchors(noisy, Timeframe.DAILY, AnchorConfig(**{**BASE, **cfg}))
    allk = discover_anchors(noisy, Timeframe.DAILY, AnchorConfig(**{**BASE, **cfg, "regime_reach_factor": None}))
    cyc = lambda xs: {pd.Timestamp(a.anchor_date) for a in xs if a.anchor_types & {AnchorType.CYCLE_HIGH, AnchorType.CYCLE_LOW}}
    assert any(noisy.loc[d, "close"] >= 400 for d in cyc(allk))
    assert not any(noisy.loc[d, "close"] >= 400 for d in cyc(keep))
