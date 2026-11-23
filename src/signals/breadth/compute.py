"""Market breadth: % of an index's constituents above key moving averages,
golden-cross breadth, new 52-week highs/lows (market-wide and per sector)
and advance/decline counts -- computed cross-
sectionally (one row per date, aggregated across every index member that
day), unlike sr_lines/gaps/divergences/fibonacci/avwap which each walk one
ticker's bars chronologically.

Point-in-time correct by construction: membership comes from
`data_processing.db.read_index_membership`, which returns dated intervals,
not today's roster -- a ticker that left the index years ago still counts
on the dates it was actually a member, and a ticker that joined late is
excluded before its own start_date. This is the same survivorship-bias
concern `as_of` truncation guards elsewhere in this codebase, just on the
membership axis instead of the price-bar axis.

WEIGHTING: every metric below is really a weighted aggregate over a date's
members -- `config.weighting="equal"` (the original, still-default
behavior) gives every member weight 1.0, so each formula reduces exactly
to a plain count/mean; `weighting="cap"` weights each member by its real
historical market cap that date instead, via `_load_market_caps`
(`data_processing.market_cap.reconcile_market_cap`, split-reconciled,
using the local splits cache so no live Polygon call is made). A member
with no weight available for a date (cap-weighted: no market-cap data yet,
e.g. before its shares_outstanding history starts) is excluded from both
the numerator and denominator that date, same treatment as an unwarmed-up
SMA -- never silently a wrong 0.
"""

from __future__ import annotations

import logging
import sqlite3

import numpy as np
import pandas as pd

from src.signals.breadth.config import WEIGHTING_CHOICES, BreadthConfig
from src.foundation.data_processing import db
from src.foundation.data_processing import market_cap
from src.foundation.data_processing import ticker_renames
from src.foundation.market_common import indicators

logger = logging.getLogger(__name__)

# Flagged dates of one member closer together than this are one episode;
# the days in between are excluded too (see `_drop_cap_outliers`).
_OUTLIER_EPISODE_GAP = pd.Timedelta(days=90)

_GOLDEN_CROSS_FAST = 50
_GOLDEN_CROSS_SLOW = 200


def _load_closes(
    conn: sqlite3.Connection, tickers: list[str], source: str, end: str | None = None
) -> pd.DataFrame:
    """Bulk-load `bars_1d` close prices for every ticker in `tickers` (one
    query, not one per ticker) -- long format: ticker, date, close.
    Deliberately not start-bounded -- a moving average needs real prior
    history to be valid, so the caller filters the *output* window after
    computing indicators over each ticker's full available series (same
    "warm up on the full series, slice after" pattern
    `divergences.detect._indicator_pivots` already uses). Bounded above by
    `end` when given: every indicator here looks backwards only, so bars
    after `end` can't change any value on or before it, and they are never
    read at all (keeps a held-out period genuinely unread).
    """
    if not tickers:
        return pd.DataFrame(columns=["ticker", "date", "close"])
    placeholders = ",".join("?" for _ in tickers)
    query = (
        f"SELECT ticker, timestamp AS date, close FROM bars_1d "
        f"WHERE source = ? AND ticker IN ({placeholders})"
    )
    params: list = [source, *tickers]
    if end is not None:
        # Timestamps are stored as ISO text ("2021-12-31T00:00:00"), so
        # "before the next day" compares correctly as a string.
        query += " AND timestamp < ?"
        params.append((pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
    query += " ORDER BY ticker, timestamp"
    df = pd.read_sql_query(query, conn, params=params, parse_dates=["date"])
    return df


def _load_market_caps(conn: sqlite3.Connection, prices: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Bulk market cap per (ticker, date) for `tickers` -- long format:
    ticker, date, market_cap. `prices` is the caller's `_load_closes`
    result for `market_cap.PRICE_SOURCE` (split-only closes); the signal
    prices are reused when they already come from that source. Two more bulk queries (shares
    outstanding, splits), then `market_cap.reconcile_market_cap` (a pure,
    no-DB-access function) is looped per ticker in Python to do the actual
    split-reconciliation -- not `market_cap.historical_market_cap`, which
    is single-ticker end-to-end (its own `db.read_bars`/
    `db.read_shares_outstanding` calls per invocation) and would reissue
    one query per ticker per table here, exactly the N+1 pattern this
    module's `_load_closes` docstring already rejects.

    A ticker with no shares_outstanding data at all contributes no rows
    (not zero-filled) -- nothing to reconcile against yet.
    """
    if prices.empty:
        return pd.DataFrame(columns=["ticker", "date", "market_cap"])

    shares = market_cap.load_shares_outstanding(conn, tickers)
    if shares.empty:
        return pd.DataFrame(columns=["ticker", "date", "market_cap"])
    splits = market_cap.load_splits(conn, tickers)

    shares_by_ticker = {
        ticker: group.set_index("date")["shares_outstanding"]
        for ticker, group in shares.groupby("ticker")
    }
    splits_by_ticker = dict(tuple(splits.groupby("ticker"))) if not splits.empty else {}

    frames = []
    for ticker, price_group in prices.groupby("ticker"):
        ticker_shares = shares_by_ticker.get(ticker)
        if ticker_shares is None or ticker_shares.empty:
            continue
        price_series = price_group.set_index("date")["close"].sort_index()
        reconciled = market_cap.reconcile_market_cap(
            price_series, ticker_shares, splits_by_ticker.get(ticker)
        )
        if reconciled.empty:
            continue
        frames.append(
            pd.DataFrame(
                {"ticker": ticker, "date": reconciled.index, "market_cap": reconciled["market_cap"].to_numpy()}
            )
        )
    if not frames:
        return pd.DataFrame(columns=["ticker", "date", "market_cap"])
    return pd.concat(frames, ignore_index=True)


def _mask_duplicate_share_classes(members: pd.DataFrame, secondary_to_primary: dict[str, str]) -> pd.Series:
    """`members["market_cap"]` with each configured secondary share class's
    cap set to NaN on every date its primary also has one -- i.e. the
    secondary is excluded from that date's weighted aggregates exactly like
    a member with no cap data (`_weighted_fraction`), because the primary
    already carries the whole company's cap
    (`BreadthConfig.share_class_secondaries`: the share-count source
    reports company-total shares under both class tickers, so keeping both
    double-counts the company). On a date where the primary has no cap --
    not a member, no bar, no share count yet -- the secondary keeps its
    own, so the company never silently drops out. Runs AFTER
    `_drop_cap_outliers`, on the guarded caps: a primary whose cap that
    date is a mis-scaled outlier has already been masked, so the sane
    secondary stands in instead of being masked by a value the guard
    rejected. The cost is that the guard's median sees the company twice --
    a second copy of one genuine cap among hundreds of members, which
    barely moves a median, vs. silently losing the company entirely.
    """
    tangled = set(secondary_to_primary) & set(secondary_to_primary.values())
    if tangled:
        raise ValueError(
            f"share_class_secondaries lists {sorted(tangled)} as both secondary and primary -- "
            "a reciprocal or chained mapping masks against already-masked caps and can drop "
            "the company from cap-weighted breadth entirely; pick one primary per company"
        )
    # One representative class per company per date: the primary where it
    # has a cap, else the first (sorted) secondary that does -- a three-
    # class company with a cap-less primary must not have BOTH secondaries
    # stand in, which would be the very double-count this fixes.
    by_primary: dict[str, list[str]] = {}
    for secondary, primary in sorted(secondary_to_primary.items()):
        by_primary.setdefault(primary, []).append(secondary)
    caps = members["market_cap"]
    for primary, secondaries in by_primary.items():
        covered = set(members.loc[(members["ticker"] == primary) & caps.notna(), "date"])
        for secondary in secondaries:
            has_cap = (members["ticker"] == secondary) & caps.notna()
            duplicate = has_cap & members["date"].isin(covered)
            if duplicate.any():
                # warning, not info: the module CLIs configure no logging,
                # and Python's last-resort handler only shows WARNING+ --
                # same "logged, never silent" treatment as
                # _drop_cap_outliers.
                logger.warning(
                    "cap-weighted breadth: excluded %d %s member-days whose market cap duplicates "
                    "%s's or a sibling class's (one company, company-total share counts per class)",
                    int(duplicate.sum()), secondary, primary,
                )
                caps = caps.mask(duplicate)
            covered |= set(members.loc[has_cap & ~duplicate, "date"])
    return caps


def _drop_cap_outliers(members: pd.DataFrame, ratio: float | None, min_members: int) -> pd.Series:
    """`members["market_cap"]` with any cap above `ratio` x that date's
    median member cap set to NaN -- i.e. that member is excluded from that
    date's weighted aggregates exactly like a member with no cap data yet
    (see `_weighted_fraction`). Guards cap-weighted breadth against a
    single mis-scaled share count swallowing the whole index
    (`BreadthConfig.cap_outlier_ratio`). Logged, never silent.

    Only dates with at least `min_members` covered members are tested (a
    thin date's median is dragged by the outlier itself). A member flagged
    on some dates is excluded across the whole episode -- every date from
    its first flagged day to its last, flagged days less than
    `_OUTLIER_EPISODE_GAP` apart being one episode -- so a cap hovering
    around the threshold doesn't flip in and out of the index day to day.
    """
    caps = members["market_cap"]
    if ratio is None:
        return caps
    by_date = caps.groupby(members["date"])
    outlier = (caps > ratio * by_date.transform("median")) & (by_date.transform("count") >= min_members)
    if not outlier.any():
        return caps
    excluded = outlier.copy()
    for ticker, days in members.loc[outlier, "date"].groupby(members.loc[outlier, "ticker"]):
        days = days.sort_values()
        for _, span in days.groupby((days.diff() > _OUTLIER_EPISODE_GAP).cumsum()):
            excluded |= (members["ticker"] == ticker) & members["date"].between(span.iloc[0], span.iloc[-1])
    excluded &= caps.notna()
    hit = members[excluded]
    logger.warning(
        "cap-weighted breadth: excluded %d member-days whose market cap exceeds %gx the date's median "
        "(%d tickers: %s) -- a mis-scaled share count, not a real weight",
        int(excluded.sum()), ratio, hit["ticker"].nunique(), ", ".join(sorted(hit["ticker"].unique())[:10]),
    )
    return caps.mask(excluded)


def _constituent_counts(membership: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    """Point-in-time member count per date, derived purely from membership
    intervals -- independent of whether a member actually has price data
    that day (see `n_with_data` in `compute_breadth` for that, separate,
    axis). A sweep-line over interval start/end+1 deltas, cumsum'd and
    forward-filled onto the real trading-calendar `dates`.
    """
    if membership.empty or len(dates) == 0:
        return pd.Series(0, index=dates, dtype=int)
    sentinel_end = dates.max() + pd.Timedelta(days=1)
    end_filled = membership["end_date"].fillna(sentinel_end) + pd.Timedelta(days=1)
    starts = membership["start_date"].value_counts()
    ends = end_filled.value_counts()
    delta = starts.sub(ends, fill_value=0).sort_index()
    timeline = delta.cumsum()
    return timeline.reindex(dates, method="ffill").fillna(0).astype(int)


def _weighted_fraction(
    condition: pd.Series, valid: pd.Series, weight: pd.Series, date: pd.Series
) -> pd.Series:
    """Weighted mean of boolean `condition` among rows where `valid` is
    True and `weight` isn't NaN -- weight=1.0 everywhere reduces exactly to
    a plain fraction (today's original equal-weight pct_above_sma/ema/
    golden_cross behavior: count(condition)/count(valid))."""
    valid = valid & weight.notna()
    numerator = (condition.astype(float) * weight).where(valid, 0.0).groupby(date).sum()
    denominator = weight.where(valid, 0.0).groupby(date).sum()
    return numerator / denominator.replace(0, np.nan)


def _weighted_sum(condition: pd.Series, valid: pd.Series, weight: pd.Series, date: pd.Series) -> pd.Series:
    """Weighted sum of boolean `condition` among rows where `valid` is True
    and `weight` isn't NaN -- weight=1.0 everywhere reduces exactly to a
    plain count (today's original equal-weight n_advancing/n_declining)."""
    valid = valid & weight.notna()
    return (condition.astype(float) * weight).where(valid, 0.0).groupby(date).sum()


SECTOR_COLUMNS = ["date", "sector", "n_members", "pct_new_high_52w", "pct_new_low_52w", "net_new_high_52w"]


def _sector_new_highs(members: pd.DataFrame, sector_by_ticker: dict[str, str]) -> pd.DataFrame:
    """Long frame, one row per (date, sector) with at least one member that
    day: the new-52-week-high/low fractions among that sector's members,
    weighted exactly like the market-wide columns. `n_members` is the
    unweighted count of the sector's members with data that day (warm-up
    ones included, so a NaN fraction with n_members > 0 reads as "all still
    in their first year", not "no members"). Members with no sector on file
    are left out of every sector row (they still count market-wide)."""
    sector = members["ticker"].map(sector_by_ticker)
    sector = sector.where(sector.notna(), "").astype(str).str.strip()
    sector = sector.where(sector != "")
    known = sector.notna()
    if not known.any():
        return pd.DataFrame(columns=SECTOR_COLUMNS)
    rows = members[known]
    keys = [rows["date"], sector[known]]
    out = pd.DataFrame({"n_members": rows.groupby(keys).size()})
    valid = rows["new_high_valid"]
    out["pct_new_high_52w"] = _weighted_fraction(rows["new_high"], valid, rows["weight"], keys)
    out["pct_new_low_52w"] = _weighted_fraction(rows["new_low"], valid, rows["weight"], keys)
    out["net_new_high_52w"] = out["pct_new_high_52w"] - out["pct_new_low_52w"]
    out.index.names = ["date", "sector"]
    return out.reset_index()[SECTOR_COLUMNS]


def compute_breadth(
    conn: sqlite3.Connection,
    index_name: str,
    config: BreadthConfig,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """One row per date: % of `index_name`'s point-in-time constituents
    above each configured SMA/EMA, golden-cross breadth (% SMA50 > SMA200),
    new 52-week highs/lows, and advance/decline -- weighted per
    `config.weighting` (see this module's docstring and
    BreadthConfig.weighting). The market-wide half of
    `compute_breadth_with_sectors`; see there for the columns.
    """
    return compute_breadth_with_sectors(conn, index_name, config, start=start, end=end)[0]


def compute_breadth_with_sectors(
    conn: sqlite3.Connection,
    index_name: str,
    config: BreadthConfig,
    start: str | None = None,
    end: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(market, sectors) for `index_name`, both from one price load.

    `market` is indexed by date with columns: n_constituents, n_with_data
    (both always unweighted -- a member-count question is meaningless to
    weight), pct_above_sma{period} (per config.sma_periods),
    pct_above_ema{period} (per config.ema_periods), pct_golden_cross (only
    if 50 and 200 are both in sma_periods), pct_new_high_52w,
    pct_new_low_52w, net_new_high_52w (high minus low), n_advancing,
    n_declining (weighted sums -- literal counts under "equal", summed
    market cap under "cap"), net_advances, ad_ratio.

    `sectors` is long (columns `SECTOR_COLUMNS`): the three new-high/low
    columns per sector per date (`_sector_new_highs`). Sectors come from
    `ticker_sector`, which is a current snapshot, not point-in-time -- a
    company that changed sector is counted under today's one throughout.

    Both empty if the index has no membership rows, or (cap-weighted only)
    no member has any market-cap data yet.
    """
    if config.weighting not in WEIGHTING_CHOICES:
        raise ValueError(f"Unknown weighting {config.weighting!r} -- expected one of {WEIGHTING_CHOICES}")
    empty = (pd.DataFrame(), pd.DataFrame(columns=SECTOR_COLUMNS))

    membership = db.read_index_membership(conn, index_name)
    if membership.empty:
        return empty
    membership = membership.copy()
    # Members whose symbol later changed have their prices under the new one
    # (ABC -> COR); without this they'd look price-less and drop out.
    membership = ticker_renames.apply_renames(conn, membership)
    membership["start_date"] = pd.to_datetime(membership["start_date"])
    membership["end_date"] = pd.to_datetime(membership["end_date"])
    if end is not None:
        # Intervals that only start after `end` can't affect the output.
        membership = membership[membership["start_date"] <= pd.Timestamp(end)]
        if membership.empty:
            return empty

    tickers = sorted(membership["ticker"].unique())
    prices = _load_closes(conn, tickers, config.price_source, end=end)
    if prices.empty:
        return empty
    prices = prices.sort_values(["ticker", "date"])

    for period in config.sma_periods:
        prices[f"sma{period}"] = prices.groupby("ticker")["close"].transform(
            lambda s, p=period: indicators.sma(s, p)
        )
    for period in config.ema_periods:
        prices[f"ema{period}"] = prices.groupby("ticker")["close"].transform(
            lambda s, p=period: indicators.ema(s, p)
        )
    prices["prior_close"] = prices.groupby("ticker")["close"].shift(1)
    # Highest/lowest of the PREVIOUS `window` closes (today excluded), NaN
    # until a full window exists -- computed on each ticker's full series,
    # so a stock joining the index late with a year of prior bars counts
    # from its first member day.
    # Rolled over non-null closes only, so one NULL close can't blank out a
    # ticker for the next `window` bars (its own row stays NaN -> invalid).
    window = config.new_high_window
    closes = prices.loc[prices["close"].notna(), ["ticker", "close"]]
    prior = closes.groupby("ticker")["close"].shift(1)
    rolling = prior.groupby(closes["ticker"]).rolling(window, min_periods=window)
    prices["prior_max"] = rolling.max().reset_index(level=0, drop=True)
    prices["prior_min"] = rolling.min().reset_index(level=0, drop=True)

    # Interval join: expand by ticker (a ticker can have multiple
    # non-overlapping membership intervals if it left and rejoined), then
    # keep only rows where the price date actually falls inside that
    # interval -- this both filters to real members and, since intervals
    # are non-overlapping per ticker, never produces a (ticker, date)
    # duplicate.
    merged = prices.merge(membership[["ticker", "start_date", "end_date"]], on="ticker", how="inner")
    in_interval = (merged["date"] >= merged["start_date"]) & (
        merged["end_date"].isna() | (merged["date"] <= merged["end_date"])
    )
    # A renamed member can have back-to-back intervals under one symbol that
    # touch on the rename day; count it once per date.
    members = merged[in_interval].drop_duplicates(["ticker", "date"]).copy()

    if config.weighting == "cap":
        # Weights come from split-only closes, not `config.price_source`'s
        # (dividend-adjusted) closes -- see `market_cap.PRICE_SOURCE`.
        cap_prices = (
            prices if config.price_source == market_cap.PRICE_SOURCE
            else _load_closes(conn, tickers, market_cap.PRICE_SOURCE, end=end)
        )
        market_caps = _load_market_caps(conn, cap_prices, tickers)
        if market_caps.empty:
            return empty
        members = members.merge(market_caps, on=["ticker", "date"], how="left")
        members["market_cap"] = _drop_cap_outliers(
            members, config.cap_outlier_ratio, config.cap_outlier_min_members
        )
        members["weight"] = _mask_duplicate_share_classes(members, config.share_class_secondaries)
    else:
        members["weight"] = 1.0

    dates = pd.DatetimeIndex(sorted(prices["date"].unique()))
    n_constituents = _constituent_counts(membership, dates)

    grouped = members.groupby("date")
    result = pd.DataFrame(index=dates)
    result["n_constituents"] = n_constituents
    # Members with an actual bars_1d row that day -- distinct from a given
    # metric's own (smaller-or-equal) valid-data count, e.g. a ticker with
    # only 100 days of history counts here even though its SMA(200) is
    # still NaN; each pct_* column below excludes NaN on its own via
    # `.where(...)`, so it's never inflated by an unwarmed-up ticker.
    result["n_with_data"] = grouped.size()
    result["n_with_data"] = result["n_with_data"].fillna(0).astype(int)

    weight, date = members["weight"], members["date"]

    for period in config.sma_periods:
        above = members["close"] > members[f"sma{period}"]
        valid = members[f"sma{period}"].notna()
        result[f"pct_above_sma{period}"] = _weighted_fraction(above, valid, weight, date)
    for period in config.ema_periods:
        above = members["close"] > members[f"ema{period}"]
        valid = members[f"ema{period}"].notna()
        result[f"pct_above_ema{period}"] = _weighted_fraction(above, valid, weight, date)

    if _GOLDEN_CROSS_FAST in config.sma_periods and _GOLDEN_CROSS_SLOW in config.sma_periods:
        fast_col, slow_col = f"sma{_GOLDEN_CROSS_FAST}", f"sma{_GOLDEN_CROSS_SLOW}"
        both_valid = members[fast_col].notna() & members[slow_col].notna()
        golden = members[fast_col] > members[slow_col]
        result["pct_golden_cross"] = _weighted_fraction(golden, both_valid, weight, date)
    else:
        result["pct_golden_cross"] = np.nan

    # A comparison against NaN is False, not NaN, so the warm-up rows must
    # be dropped from the denominator explicitly via `valid` -- otherwise a
    # stock in its first year would count as "not at a new high".
    members["new_high_valid"] = members["prior_max"].notna() & members["prior_min"].notna() & members["close"].notna()
    members["new_high"] = members["close"] > members["prior_max"]
    members["new_low"] = members["close"] < members["prior_min"]
    valid_52w = members["new_high_valid"]
    result["pct_new_high_52w"] = _weighted_fraction(members["new_high"], valid_52w, weight, date)
    result["pct_new_low_52w"] = _weighted_fraction(members["new_low"], valid_52w, weight, date)
    result["net_new_high_52w"] = result["pct_new_high_52w"] - result["pct_new_low_52w"]

    prior_valid = members["prior_close"].notna()
    advancing = members["close"] > members["prior_close"]
    declining = members["close"] < members["prior_close"]
    # Assign first (aligns the groupby result onto result's full date
    # index -- a date with zero rows in `members` at all, not just NaN
    # values, isn't a key in the groupby output and becomes NaN here),
    # *then* fillna -- fillna before this alignment (on the smaller,
    # groupby-only series) wouldn't touch those missing-key dates at all.
    result["n_advancing"] = _weighted_sum(advancing, prior_valid, weight, date)
    result["n_declining"] = _weighted_sum(declining, prior_valid, weight, date)
    result["n_advancing"] = result["n_advancing"].fillna(0)
    result["n_declining"] = result["n_declining"].fillna(0)
    if config.weighting == "equal":
        # Preserve the original equal-weight dtype exactly (plain integer
        # counts) -- cap-weighted sums are real dollar figures, not counts,
        # so they stay float.
        result["n_advancing"] = result["n_advancing"].astype(int)
        result["n_declining"] = result["n_declining"].astype(int)
    result["net_advances"] = result["n_advancing"] - result["n_declining"]
    result["ad_ratio"] = result["n_advancing"] / result["n_declining"].replace(0, np.nan)

    sectors_table = db.read_ticker_sector(conn)
    sector_by_ticker = dict(zip(sectors_table["ticker"], sectors_table["sector"]))
    sectors = _sector_new_highs(members, sector_by_ticker)

    if start is not None:
        result = result[result.index >= pd.Timestamp(start)]
        sectors = sectors[sectors["date"] >= pd.Timestamp(start)]
    if end is not None:
        result = result[result.index <= pd.Timestamp(end)]
        sectors = sectors[sectors["date"] <= pd.Timestamp(end)]

    return result, sectors.reset_index(drop=True)


def advance_decline_line(breadth: pd.DataFrame) -> pd.Series:
    """Cumulative A/D line over `breadth`'s own date range -- NOT persisted
    (see compute_breadth's module docstring / this module's design notes):
    a stored absolute cumulative value would be wrong on any partial/
    windowed re-run, since its correct value depends on summing from the
    true start of history, not from wherever a given run's `start` happens
    to be. Compute it on demand from a caller's own full result set instead.
    """
    return breadth["net_advances"].cumsum()
