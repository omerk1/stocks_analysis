"""Market-wide and sector-relative model features (`VALIDATION_HARNESS.md` §9
step 6, step 2b), computed from every ticker's bars at once rather than one
ticker at a time (`registry.PanelSource`). Row t = close of t. Priors null
(`IDEAS.md` §2: M13 found no regime interaction; sector-relative untested).

- Index trend and volatility, from the benchmark's (SPY's) own bars: the same
  value for every ticker on a date.
- Breadth over the point-in-time index members (`PanelContext.membership`),
  delisted members included -- their bars come from the Tiingo fallback.
  `signals/breadth` isn't reused: it reads one vendor without that fallback,
  so most delisted members would drop out and breadth would lean towards
  survivors. A member counts on a date only if it has a bar that day and the
  value is defined (an SMA still warming up is neither above nor below:
  CLAUDE.md invariant #9).
- Sector-relative 63-day momentum: the stock against the median of that day's
  members in its sector, and its percentile rank among them. `sector` is
  current-state (the baseline's documented leak, `registry.py`), so these
  inherit it. Sector ETFs aren't used: XLRE starts 2015 and XLC 2018.

A market-wide column can't change which names a day's top k are on its own
(it is the same for all of them); it only acts through interactions.

Comparisons of a close with an SMA or the previous close use `TIE_TOLERANCE`
(`ma_family.adx` explains why).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.models.features.indicators import PCTILE_DECIMALS, up_down
from src.models.features.ma_family import TIE_TOLERANCE
from src.signals.moving_averages.features.distance import dist_pct
from src.signals.moving_averages.features.slope import slope_log_k

BENCHMARK = "SPY"
BREADTH_LOOKBACKS = (50, 200)
ADV_DEC_WINDOW = 10
INDEX_RVOL_WINDOW = 21
SECTOR_MOM_WINDOW = 63

INDEX_COLUMNS = ("spy_dist_sma_200", "spy_slope_log_63", "spy_rvol_21")
BREADTH_COLUMNS = ("breadth_above_sma50", "breadth_above_sma200", "adv_dec_10")
SECTOR_COLUMNS = ("sector_rel_mom_63", "sector_rank_mom_63")


@dataclass(frozen=True)
class PanelContext:
    """What a panel source needs besides the bars.

    membership: (ticker, date) rows of point-in-time index members; None = every
        bar row except the benchmark's (synthetic data, a hand-picked ticker set).
    sectors: ticker -> sector; None or a missing ticker = unknown (its sector
        columns are NaN).
    fundamentals, earnings: rows of the `fundamentals` and
        `earnings_announcements` tables (`fundamentals.load_tables`) for the
        company-financials columns; None = those columns are NaN.
    """
    membership: pd.DataFrame | None = None
    sectors: pd.Series | None = None
    benchmark: str = BENCHMARK
    fundamentals: pd.DataFrame | None = None
    earnings: pd.DataFrame | None = None


def members_from_intervals(intervals: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """(ticker, date) member rows: each bar row of `bars` that falls inside one
    of its ticker's (start_date, end_date) intervals (end NULL = still a member)."""
    j = bars[["ticker", "date"]].merge(intervals[["ticker", "start_date", "end_date"]], on="ticker")
    start = pd.to_datetime(j["start_date"])
    end = pd.to_datetime(j["end_date"]).fillna(pd.Timestamp.max)
    return j.loc[(j["date"] >= start) & (j["date"] <= end), ["ticker", "date"]].drop_duplicates(ignore_index=True)


def _is_member(stocks: pd.DataFrame, ctx: PanelContext) -> pd.Series:
    if ctx.membership is None:
        return pd.Series(True, index=stocks.index)
    m = ctx.membership[["ticker", "date"]].drop_duplicates()
    flag = stocks[["ticker", "date"]].merge(m, on=["ticker", "date"], how="left", indicator=True)["_merge"]
    return pd.Series((flag == "both").to_numpy(), index=stocks.index)


def _by_ticker(stocks: pd.DataFrame, fn) -> pd.Series:
    """`fn` applied to each ticker's close series (rows sorted by ticker, date)."""
    return stocks.groupby("ticker", sort=False)["close"].transform(fn)


def index_features(bench_close: pd.Series) -> pd.DataFrame:
    """The benchmark's trend and volatility, by date."""
    sma_50 = bench_close.rolling(50, min_periods=50).mean()
    sma_200 = bench_close.rolling(200, min_periods=200).mean()
    return pd.DataFrame({
        "spy_dist_sma_200": dist_pct(bench_close, sma_200),
        "spy_slope_log_63": slope_log_k(sma_50, 63),
        "spy_rvol_21": bench_close.pct_change().rolling(INDEX_RVOL_WINDOW, min_periods=INDEX_RVOL_WINDOW).std(),
    })


def breadth_features(stocks: pd.DataFrame, member: pd.Series) -> pd.DataFrame:
    """Share of members above their SMA50 / SMA200, and the 10-day mean of the
    daily net advance share ((advancers - decliners) / members with a prior
    bar), by date."""
    close = stocks["close"]
    eps = TIE_TOLERANCE * close.abs()
    out = {}
    for k in BREADTH_LOOKBACKS:
        sma = _by_ticker(stocks, lambda s: s.rolling(k, min_periods=k).mean())
        above = (close - sma > eps).astype(float).where(sma.notna())
        out[f"breadth_above_sma{k}"] = above[member].groupby(stocks.loc[member, "date"]).mean()
    sign = _by_ticker(stocks, up_down)
    daily = sign[member].groupby(stocks.loc[member, "date"]).mean().sort_index()
    out["adv_dec_10"] = daily.rolling(ADV_DEC_WINDOW, min_periods=ADV_DEC_WINDOW).mean()
    return pd.DataFrame(out)


def sector_features(stocks: pd.DataFrame, member: pd.Series, sectors: pd.Series | None) -> pd.DataFrame:
    """63-day return minus the median of that date's same-sector members, and
    its percentile rank among them; both NaN on rows that aren't members."""
    # Rounded: two members' returns can tie exactly on cent prices, and float
    # noise from a later split or dividend would otherwise break the tie in the rank.
    mom = _by_ticker(stocks, lambda s: s / s.shift(SECTOR_MOM_WINDOW) - 1).round(PCTILE_DECIMALS)
    sector = (stocks["ticker"].map(sectors) if sectors is not None
              else pd.Series(np.nan, index=stocks.index, dtype=object))
    sector = sector.replace("", np.nan)
    peer = member & mom.notna() & sector.notna()
    keys = [stocks["date"], sector]
    median = mom[peer].groupby([k[peer] for k in keys]).median()
    idx = pd.MultiIndex.from_arrays([stocks["date"], sector])
    rel = (mom - median.reindex(idx).to_numpy()).where(member)
    rank = pd.Series(np.nan, index=stocks.index)
    rank[peer] = mom[peer].groupby([k[peer] for k in keys]).rank(pct=True)
    return pd.DataFrame({"sector_rel_mom_63": rel, "sector_rank_mom_63": rank}, index=stocks.index)


def panel_features(bars: pd.DataFrame, ctx: PanelContext) -> pd.DataFrame:
    """Every market-wide and sector-relative column for every (ticker, date)
    row of `bars` (one basis, long; the benchmark's rows included, if present)."""
    bars = bars.sort_values(["ticker", "date"], ignore_index=True)
    stocks = bars[bars["ticker"] != ctx.benchmark].reset_index(drop=True)
    member = _is_member(stocks, ctx)

    bench = bars.loc[bars["ticker"] == ctx.benchmark].set_index("date")["close"]
    by_date = index_features(bench).join(breadth_features(stocks, member), how="outer")
    by_date.index.name = "date"

    out = bars[["ticker", "date"]].merge(by_date.reset_index(), on="date", how="left")
    sector = sector_features(stocks, member, ctx.sectors).assign(ticker=stocks["ticker"], date=stocks["date"])
    out = out.merge(sector, on=["ticker", "date"], how="left")
    cols = [*INDEX_COLUMNS, *BREADTH_COLUMNS, *SECTOR_COLUMNS]
    out[cols] = out[cols].astype("float32")
    return out[["ticker", "date", *cols]]
