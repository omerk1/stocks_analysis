"""Indicator and market-regime model features (`features/indicators.py`,
`features/market.py`; combined-model step 2b) and their registry entries.
Leakage for every registered column is the gate's job
(`tests/test_models_gates.py`); these pin the definitions, missingness
(CLAUDE.md invariant #9) and point-in-time membership."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.models.features import indicators, market, registry

DAYS = pd.bdate_range("2017-01-02", "2019-12-31")
STEP_2B_GROUPS = ("volatility", "volume", "oscillator", "market", "relative")


def _bars(seed: int, n: int = len(DAYS), drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    opn = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "open": opn, "high": np.maximum(opn, close) * 1.01, "low": np.minimum(opn, close) * 0.99,
        "close": close, "volume": rng.lognormal(14, 0.3, n),
    }, index=DAYS[:n])


def _long(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.concat([f.rename_axis("date").reset_index().assign(ticker=t) for t, f in frames.items()],
                     ignore_index=True)


# ---------------------------------------------------------------- registry

def test_registered_with_null_priors_and_their_columns():
    specs = [s for s in registry.REGISTRY if s.group in STEP_2B_GROUPS]
    assert {s.name for s in specs} == set(indicators.INDICATOR_COLUMNS) | set(market.INDEX_COLUMNS) | set(
        market.BREADTH_COLUMNS) | set(market.SECTOR_COLUMNS)
    assert all(s.role == registry.MODEL and s.prior == "null" for s in specs)
    assert {s.name for s in specs if s.shape == "market_wide"} == set(market.INDEX_COLUMNS) | set(
        market.BREADTH_COLUMNS)
    assert [s.name for s in specs if s.ranked] == ["rel_volume_20"]
    registry.check_columns([registry.model_input(s) for s in registry.model_specs()])


# ---------------------------------------------------------------- per ticker

def test_indicator_warmups_are_the_registered_ones():
    f = indicators.ticker_features(_bars(1))
    for spec in registry.REGISTRY:
        if spec.source == "indicators":
            col = f[spec.name]
            assert col.iloc[:spec.warmup_bars - 1].isna().all() and col.iloc[spec.warmup_bars - 1:].notna().all(), \
                spec.name


def test_scale_free():
    """A constant rescaling of the whole history (a later split or dividend)
    leaves every column unchanged; so does scaling volume."""
    bars = _bars(2)
    scaled = bars.assign(**{c: bars[c] * 0.37 for c in ("open", "high", "low", "close")}, volume=bars["volume"] * 3)
    pd.testing.assert_frame_equal(indicators.ticker_features(bars), indicators.ticker_features(scaled), rtol=1e-5)


def test_ties_on_quoted_prices_survive_a_rescaling():
    """Cent-rounded closes repeat: flat days (neither up nor down) and windows
    holding the same values (equal widths, so rank ties). A later rescaling
    must not decide them."""
    bars = (_bars(3) * 100).round() / 100
    bars.iloc[100:130, bars.columns.get_loc("close")] = bars["close"].iloc[99]  # a flat stretch
    c = bars.columns.get_loc("close")
    for i in range(320, 500):  # a 20-day cycle: every window holds the same closes, so equal widths
        bars.iloc[i, c] = bars.iloc[i - 20, c]
    scaled = bars.assign(**{c: bars[c] / 3 for c in ("open", "high", "low", "close")})
    a, b = indicators.ticker_features(bars), indicators.ticker_features(scaled)
    np.testing.assert_allclose(a.to_numpy(), b.to_numpy(), rtol=1e-6, equal_nan=True)
    assert (indicators.up_down(bars["close"]).iloc[101:130] == 0).all()
    assert (a["updown_volume_20"].iloc[129] == 0)  # 20 flat days: no signed volume


def test_up_down_is_undefined_on_the_first_bar():
    sign = indicators.up_down(pd.Series([10.0, 10.5, 10.5, 10.0]))
    assert np.isnan(sign.iloc[0]) and sign.iloc[1:].tolist() == [1.0, 0.0, -1.0]


def test_no_volume_is_undefined_not_zero_or_infinite():
    bars = _bars(4)
    bars.iloc[100:130, bars.columns.get_loc("volume")] = 0.0
    f = indicators.ticker_features(bars)
    assert f["rel_volume_20"].iloc[119:130].isna().all() and f["updown_volume_20"].iloc[119:130].isna().all()
    assert np.isfinite(f["rel_volume_20"].dropna()).all()


def test_trailing_pctile_reads_only_the_past():
    x = pd.Series(np.arange(300, dtype=float))
    p = indicators.trailing_pctile(x, 10)
    assert p.iloc[:9].isna().all() and (p.iloc[9:] == 1.0).all()  # a rising series is always at its high
    changed = x.copy()
    changed.iloc[200:] = -1.0
    pd.testing.assert_series_equal(p.iloc[:200], indicators.trailing_pctile(changed, 10).iloc[:200])


# ---------------------------------------------------------------- panel

def _panel():
    """Three stocks and SPY over 300 days. STAY is a member throughout; LATE
    joins on day 250; GONE delists after day 220 (its bars stop)."""
    days = DAYS[:300]
    frames = {
        "STAY": _bars(10, 300, drift=0.003), "LATE": _bars(11, 300, drift=-0.003), "GONE": _bars(12, 221),
        "SPY": _bars(13, 300),
    }
    bars = _long(frames)
    intervals = pd.DataFrame({"ticker": ["STAY", "LATE", "GONE"], "start_date": [days[0], days[250], days[0]],
                              "end_date": [None, None, days[220]]})
    sectors = pd.Series({"STAY": "Energy", "LATE": "Energy", "GONE": "Technology"})
    ctx = market.PanelContext(membership=market.members_from_intervals(intervals, bars), sectors=sectors)
    return bars, ctx, days


def test_members_from_intervals():
    bars, ctx, days = _panel()
    m = ctx.membership
    assert m.loc[m["ticker"] == "LATE", "date"].min() == days[250]
    assert m.loc[m["ticker"] == "GONE", "date"].max() == days[220]
    assert "SPY" not in set(m["ticker"]) and len(m[m["ticker"] == "STAY"]) == 300


def test_breadth_counts_point_in_time_members_only():
    bars, ctx, days = _panel()
    f = market.panel_features(bars, ctx).set_index(["ticker", "date"])
    by_date = f.xs("SPY", level="ticker")
    above = {t: (g.set_index("date")["close"] > g.set_index("date")["close"].rolling(50).mean())
             for t, g in bars.groupby("ticker")}
    # Day 100: STAY and GONE are members, LATE isn't yet.
    d = days[100]
    assert by_date.loc[d, "breadth_above_sma50"] == pytest.approx((float(above["STAY"][d]) + float(above["GONE"][d])) / 2)
    # Day 260: GONE has delisted, LATE has joined.
    d = days[260]
    assert by_date.loc[d, "breadth_above_sma50"] == pytest.approx((float(above["STAY"][d]) + float(above["LATE"][d])) / 2)
    # The same value on every ticker's row that day.
    assert f.xs(d, level="date")["breadth_above_sma50"].nunique() == 1


def test_breadth_is_undefined_while_every_member_warms_up():
    """A member whose SMA isn't defined yet is neither above nor below it (CLAUDE.md
    invariant #9): before any SMA200 exists, breadth is NaN, not 0."""
    bars, ctx, days = _panel()
    by_date = market.panel_features(bars, ctx).query("ticker == 'SPY'").set_index("date")
    assert by_date["breadth_above_sma200"].iloc[:199].isna().all()
    assert by_date["breadth_above_sma200"].iloc[199:].notna().all()
    assert by_date["breadth_above_sma50"].iloc[:49].isna().all() and by_date["breadth_above_sma50"].iloc[49:].notna().all()
    assert by_date["adv_dec_10"].iloc[:10].isna().all() and by_date["adv_dec_10"].iloc[10:].notna().all()


def test_index_columns_come_from_the_benchmark_only():
    bars, ctx, days = _panel()
    f = market.panel_features(bars, ctx)
    spy = bars[bars["ticker"] == "SPY"].set_index("date")["close"]
    expected = spy / spy.rolling(200).mean() - 1
    got = f[f["ticker"] == "STAY"].set_index("date")["spy_dist_sma_200"]
    np.testing.assert_allclose(got.to_numpy(), expected.to_numpy(dtype="float32"), rtol=1e-5, equal_nan=True)
    without = market.panel_features(bars[bars["ticker"] != "SPY"], ctx)
    assert without[list(market.INDEX_COLUMNS)].isna().all().all()
    assert without["breadth_above_sma50"].notna().any()


def test_sector_columns_rank_among_that_days_sector_members():
    bars, ctx, days = _panel()
    f = market.panel_features(bars, ctx).set_index(["ticker", "date"])
    mom = {t: g.set_index("date")["close"].pct_change(63) for t, g in bars.groupby("ticker")}
    # Day 100: STAY is Energy's only member (LATE hasn't joined): its own median, rank 1.
    assert f.loc[("STAY", days[100]), "sector_rel_mom_63"] == pytest.approx(0.0, abs=1e-6)
    assert f.loc[("STAY", days[100]), "sector_rank_mom_63"] == 1.0
    # LATE isn't a member yet: no rank; its relative return is against the members' median.
    assert np.isnan(f.loc[("LATE", days[100]), "sector_rank_mom_63"])
    assert f.loc[("LATE", days[100]), "sector_rel_mom_63"] == pytest.approx(
        mom["LATE"][days[100]] - mom["STAY"][days[100]], rel=1e-4)
    # Day 280: both Energy names are members.
    d = days[280]
    a, b = mom["STAY"][d], mom["LATE"][d]
    assert f.loc[("STAY", d), "sector_rel_mom_63"] == pytest.approx(a - (a + b) / 2, rel=1e-4)
    assert {f.loc[("STAY", d), "sector_rank_mom_63"], f.loc[("LATE", d), "sector_rank_mom_63"]} == {0.5, 1.0}
    # The benchmark has no sector.
    assert f.xs("SPY", level="ticker")[list(market.SECTOR_COLUMNS)].isna().all().all()


def test_unknown_sector_is_undefined():
    bars, ctx, days = _panel()
    ctx = market.PanelContext(membership=ctx.membership, sectors=pd.Series({"STAY": "Energy", "LATE": ""}))
    f = market.panel_features(bars, ctx)
    assert f.loc[f["ticker"].isin(["LATE", "GONE"]), list(market.SECTOR_COLUMNS)].isna().all().all()


def test_tied_sector_returns_stay_tied_after_a_rescaling():
    """Two members' 63-day returns tie exactly on cent prices (18.82/17.11 and
    37.64/34.22). A later dividend rescales one's past prices by 0.97; the
    float ratio then drifts, and the rank must not move."""
    days = DAYS[:80]
    a = pd.Series(17.11, index=days); a.iloc[70:] = 18.82
    b = pd.Series(34.22, index=days); b.iloc[70:] = 37.64
    frames = {t: pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e6}) for t, c in
              {"A": a, "B": b}.items()}
    sectors = pd.Series({"A": "Energy", "B": "Energy"})
    ctx = market.PanelContext(sectors=sectors)
    rank = lambda fr: market.panel_features(_long(fr), ctx).set_index(["ticker", "date"])["sector_rank_mom_63"]
    base = rank(frames)
    for factor in (0.97, 3.0, 0.25):
        rescaled = {"A": frames["A"] * factor, "B": frames["B"]}
        pd.testing.assert_series_equal(base, rank(rescaled))
    assert base.loc[("A", days[75])] == base.loc[("B", days[75])] == 0.75  # a tie: the average rank


def test_gate_warmup_check_flags_a_missing_benchmark():
    from src.models import gates
    values = pd.DataFrame({"ticker": "X", "date": DAYS[:300], "breadth_above_sma50": 0.5})
    spec = registry.BY_NAME["breadth_above_sma50"]
    assert "breadth_above_sma50" in gates._warmup_mismatches(values, (spec,))


def test_vendor_check_refuses_a_cache_without_the_registered_columns():
    from src.models import vendor_check as vc
    old = pd.DataFrame({"ticker": ["A"], "date": [DAYS[0]], "mom_12_1_rank": [0.5]})
    with pytest.raises(ValueError, match="rebuild"):
        vc.run(old, old, {"A": "yfinance"}, DAYS, pd.Series(dtype="datetime64[ns]"))
