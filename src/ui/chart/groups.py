"""The groups page: sectors ranked by relative strength, and the members of a
sector (`docs/features/chart_ui_design.md`, "Groups and rankings"). Stored
numbers and the price data only; nothing is written.

Everything on the page is on one date, the page date: the latest date in the
7 days before the last rated date, both ends included, on which the most
sectors have a stored rating (`rs.rank_date`, the rule the RS strip's sector
rank uses too; "not rated that day" uses the same window). Membership, member ratings and the
price columns are all as of that date, so the page is behind the bars when the
relative-strength module hasn't been rerun since they were ingested.

- Ratings are `rs_rating` (1-99) from the relative-strength module's stored runs:
  a sector's ETF against the market, a member against the market. A member's
  rating is ranked within one index's members (the S&P 500 run or the
  Nasdaq-100 run, whichever wrote the row last), shown as "rated in". A
  member whose last rating is older than the page date keeps it, with its
  status saying from when.
- A sector with members but no rating on the page date (its run ended early, or
  a `ticker_sector` name with no sector ETF) is listed after the ranked ones,
  unranked, so its members don't drop off the page.
- Membership is point-in-time (`db.read_index_membership`, the RS module's
  indices together); sectors are `ticker_sector`'s. A ticker that left all of
  them in the `left_window_days` before the page date stays listed, after the
  members, with its last values: "delisted" only when `tickers` marks it
  inactive (today's flag) and it has no bar on the page date, else "left the index", saying when its bars end or that it has
  none. It isn't counted in the sector's members or breadth.
- Price columns are on the chart's basis (traded, split-adjusted only), read in
  bulk (Tiingo for tickers yfinance has no bars for, as `load_prices` says) and
  not validated bar by bar like the chart's own bars. A moving
  average or 52-week high without its full window of bars is missing, never a
  comparison against a shorter one. A sector's breadth counts the members with
  a bar on the page date and the full window.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.market_common import price_basis
from src.foundation.market_common.price_basis import source_for
from src.signals.relative_strength.config import SECTOR_ETF_MAP
from src.ui.chart import rs
from src.ui.chart.bars import CHART_BASIS
from src.ui.chart.config import GroupsConfig

INDEX_NAMES = {"sp500": "S&P 500", "nasdaq100": "Nasdaq-100"}


@dataclass(frozen=True)
class SectorRow:
    sector: str
    etf: str | None
    rating: float | None  # None: not rated on the page date (listed after the ranked ones)
    rank: int | None
    rank_changes: tuple[int | None, ...]  # per `rank_change_days`: places climbed (+) or lost (-)
    pct_above: tuple[float | None, ...]  # per `ma_periods`: share of members above, 0-1
    n_counted: tuple[int, ...]  # members counted in each share
    members: int  # point-in-time members on the page date


@dataclass(frozen=True)
class MemberRow:
    ticker: str
    member: bool  # False: left the indices in the window before the page date
    rating: float | None
    change: float | None
    rated_in: str | None  # the index the rating is ranked within
    pct_from_high: float | None  # last close vs the 52-week high, <= 0
    vs_ma: tuple[float | None, ...]  # per `ma_periods`: last close / MA - 1
    last_bar: str | None
    status: str  # "" for a member with a bar on the page date; else what's off and when


@dataclass(frozen=True)
class GroupsPage:
    as_of: str
    sectors: tuple[SectorRow, ...]  # best first, then the unrated ones with members
    members: dict[str, tuple[MemberRow, ...]]  # sector -> members by rating, gone ones last
    not_rated: tuple[str, ...]  # sectors rated in the week before but not on the page date
    no_sector: tuple[str, ...]  # members without a `ticker_sector` row
    bars_end: str | None  # SPY's last bar, to show how far behind the page date is


def _day(ts: pd.Timestamp | str, days: int = 0) -> str:
    return (pd.Timestamp(ts) + pd.Timedelta(days=days)).strftime("%Y-%m-%d")


def sector_ratings(derived: sqlite3.Connection, date: str) -> pd.Series:
    """{sector: rating} on `date`, best first."""
    rows = pd.read_sql_query(
        "SELECT sector, rs_rating FROM sector_relative_strength "
        "WHERE substr(date, 1, 10) = ? AND rs_rating IS NOT NULL", derived, params=(date,))
    return rows.set_index("sector")["rs_rating"].sort_values(ascending=False, kind="stable")


def ranks(ratings: pd.Series) -> pd.Series:
    """1 = best; ties share the better rank (as in the strip)."""
    return ratings.rank(ascending=False, method="min").astype(int)


def rank_changes(derived: sqlite3.Connection, as_of: str, now: pd.Series, days: int) -> pd.Series:
    """Places each sector climbed (+) or lost (-) since its rank `days` earlier,
    on that earlier date's own rank date; NaN for a sector not ranked then."""
    then_date = rs.rank_date(derived, _day(as_of, -days))
    then = ranks(sector_ratings(derived, then_date)) if then_date else pd.Series(dtype=float)
    return (then.reindex(now.index) - now).astype(float)


def membership(raw: sqlite3.Connection, indices: tuple[str, ...], as_of: str, left_days: int) -> pd.DataFrame:
    """ticker, member, left: the members of any of `indices` on `as_of`, then the
    tickers that left all of them in the `left_days` before (left = the last end date)."""
    frames = [db.read_index_membership(raw, name) for name in indices]
    rows = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if rows.empty:
        return pd.DataFrame({"ticker": [], "member": [], "left": []})
    start = rows["start_date"].astype(str).str[:10]
    end = rows["end_date"].where(rows["end_date"].notna()).astype(str).str[:10]
    still = rows["end_date"].isna()
    current = (start <= as_of) & (still | (end >= as_of))
    members = sorted(set(rows.loc[current, "ticker"]))
    gone = ~still & (end < as_of) & (end >= _day(as_of, -left_days)) & ~rows["ticker"].isin(members)
    left = end[gone].groupby(rows.loc[gone, "ticker"]).max()
    return pd.concat([pd.DataFrame({"ticker": members, "member": True, "left": None}),
                      pd.DataFrame({"ticker": left.index, "member": False, "left": left.to_numpy()})],
                     ignore_index=True)


def load_prices(raw: sqlite3.Connection, tickers: list[str], start: str, as_of: str) -> pd.DataFrame:
    """ticker, date, high, close on the chart's basis, `start` through `as_of`, one
    query per source. Each ticker is read from one source: the primary one, or the
    fallback (Tiingo) for a ticker with no primary bars, e.g. a delisted member
    (`price_basis.resolve_sources`)."""
    empty = pd.DataFrame({"ticker": [], "date": [], "high": [], "close": []})
    sources = price_basis.resolve_sources(raw, tickers, CHART_BASIS, fallback=True)
    frames = []
    for source in dict.fromkeys(sources.values()):
        chosen = [t for t, s in sources.items() if s == source]
        placeholders = ",".join("?" for _ in chosen)
        frames.append(pd.read_sql_query(
            f"SELECT ticker, substr(timestamp, 1, 10) AS date, high, close FROM bars_1d "
            f"WHERE source = ? AND ticker IN ({placeholders}) AND timestamp >= ? AND timestamp < ? "
            f"ORDER BY ticker, timestamp",
            raw, params=[source, *chosen, start, _day(as_of, 1)]))
    return pd.concat(frames, ignore_index=True) if frames else empty


def price_stats(prices: pd.DataFrame, ma_periods: tuple[int, ...], high_bars: int) -> pd.DataFrame:
    """Per ticker, on its own last bar: last_bar, pct_from_high, vs_ma_<n>.
    NaN where the ticker has fewer bars than the window."""
    columns = ["last_bar", "pct_from_high", *(f"vs_ma_{n}" for n in ma_periods)]
    bars = prices.dropna(subset=["close"]).sort_values(["ticker", "date"])
    if bars.empty:
        return pd.DataFrame(columns=columns)
    by_ticker = bars.groupby("ticker")
    last = by_ticker["close"].last()
    count = by_ticker.size()
    out = pd.DataFrame({"last_bar": by_ticker["date"].last()})
    # the max over a window skips missing highs, as a close-only bar has none
    high = by_ticker.tail(high_bars).groupby("ticker")["high"].max()
    out["pct_from_high"] = (last / high - 1).where(count >= high_bars)
    for n in ma_periods:
        ma = by_ticker.tail(n).groupby("ticker")["close"].mean()
        out[f"vs_ma_{n}"] = (last / ma - 1).where(count >= n)
    return out[columns]


def member_ratings(derived: sqlite3.Connection, tickers: list[str], start: str, as_of: str,
                   change_days: int) -> dict[str, tuple[rs.Rating, str | None]]:
    """ticker -> (its last vs-market rating from `start` through `as_of`, the index
    it's ranked within: the run that wrote it; None without a `runs` table)."""
    if not tickers:
        return {}
    placeholders = ",".join("?" for _ in tickers)
    with_runs = "runs" in rs.table_names(derived)
    run_index = "runs.ticker" if with_runs else "NULL"
    join = "LEFT JOIN runs ON runs.run_id = r.run_id " if with_runs else ""
    rows = pd.read_sql_query(
        f"SELECT r.ticker, substr(r.date, 1, 10) AS date, r.rs_rating, r.benchmark, {run_index} AS run_index "
        f"FROM relative_strength r {join}"
        f"WHERE r.comparison = ? AND r.ticker IN ({placeholders}) "
        # plain comparisons on `date` (the store writes YYYY-MM-DD) so the primary key's
        # (ticker, date) range is used: substr() here read every date of every ticker (~10 s)
        f"AND r.date >= ? AND r.date <= ? ORDER BY r.ticker, r.date",
        derived, params=[rs.VS_MARKET, *tickers, start, as_of])
    out = {}
    for ticker, group in rows.groupby("ticker"):
        rating = rs.latest_rating(group, change_days)
        if rating is not None:
            index = group.dropna(subset=["rs_rating"])["run_index"].iloc[-1]
            out[ticker] = (rating, INDEX_NAMES.get(index, index) if isinstance(index, str) else None)
    return out


def _none_if_nan(v) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def _status(member: bool, left: str | None, last_bar: str | None, active: bool | None,
            rating: rs.Rating | None, as_of: str) -> str:
    if member:
        notes = [] if last_bar == as_of else [f"no bar on {as_of}" + (f", last {last_bar}" if last_bar else "")]
        if rating is not None and rating.as_of != as_of:
            notes.append(f"rating from {rating.as_of}")
        return ", ".join(notes)
    # `active` is today's flag, not point-in-time: a ticker still trading on the page
    # date isn't called delisted even if it's inactive now (e.g. renamed since)
    if active is False and (last_bar is None or last_bar < as_of):
        return f"delisted, left the index {left}" + (f", last bar {last_bar}" if last_bar else "")
    if last_bar is None:
        return f"left the index {left}, no bars"
    if last_bar < as_of:
        return f"left the index {left}, bars end {last_bar}"
    return f"left the index {left}"


def member_row(ticker: str, member: bool, left: str | None, stats: pd.Series | None,
               rated: tuple[rs.Rating, str | None] | None, as_of: str, ma_periods: tuple[int, ...],
               active: bool | None = None) -> MemberRow:
    """`active`: the `tickers` table's flag (None: not known); only an inactive
    ticker that left is called delisted."""
    stats = stats if stats is not None else pd.Series(dtype=object)
    last_bar = stats.get("last_bar")
    last_bar = last_bar if isinstance(last_bar, str) else None
    rating, rated_in = rated if rated else (None, None)
    status = _status(member, left, last_bar, active, rating, as_of)
    return MemberRow(ticker, member, rating.value if rating else None, rating.change if rating else None, rated_in,
                     _none_if_nan(stats.get("pct_from_high")),
                     tuple(_none_if_nan(stats.get(f"vs_ma_{n}")) for n in ma_periods), last_bar, status)


def _sort_key(m: MemberRow):
    return (not m.member, m.rating is None, -(m.rating or 0.0), m.ticker)


def sector_row(sector: str, rating: float | None, rank: int | None, changes: tuple[int | None, ...],
               members: tuple[MemberRow, ...], as_of: str, ma_periods: tuple[int, ...]) -> SectorRow:
    current = [m for m in members if m.member]
    shares, counted = [], []
    for i, _ in enumerate(ma_periods):
        values = [m.vs_ma[i] for m in current if m.last_bar == as_of and m.vs_ma[i] is not None]
        counted.append(len(values))
        shares.append(sum(v > 0 for v in values) / len(values) if values else None)
    return SectorRow(sector, SECTOR_ETF_MAP.get(sector), rating, rank, changes, tuple(shares), tuple(counted),
                     len(current))


def build_page(raw: sqlite3.Connection, derived: sqlite3.Connection, config: GroupsConfig) -> GroupsPage | str:
    """The page, or a short message saying why there isn't one."""
    derived_tables, raw_tables = rs.table_names(derived), rs.table_names(raw)
    if "sector_relative_strength" not in derived_tables:
        return "Groups: no sector RS run in the derived database."
    latest = derived.execute("SELECT MAX(substr(date, 1, 10)) FROM sector_relative_strength "
                             "WHERE rs_rating IS NOT NULL").fetchone()[0]
    as_of = rs.rank_date(derived, latest) if latest else None
    if as_of is None:
        return "Groups: no sector RS ratings stored."
    ratings = sector_ratings(derived, as_of)
    now = ranks(ratings)
    changes = [rank_changes(derived, as_of, now, d) for d in config.rank_change_days]
    not_rated = tuple(sorted(rs.window_sectors(derived, as_of) - set(ratings.index)))

    members = (membership(raw, config.indices, as_of, config.left_window_days)
               if "index_membership" in raw_tables else pd.DataFrame({"ticker": [], "member": [], "left": []}))
    sectors = (db.read_ticker_sector(raw)[["ticker", "sector"]] if "ticker_sector" in raw_tables
               else pd.DataFrame({"ticker": [], "sector": []}))
    members = members.merge(sectors, on="ticker", how="left")
    no_sector = tuple(sorted(members.loc[members["member"].astype(bool) & members["sector"].isna(), "ticker"]))
    members = members.dropna(subset=["sector"])

    tickers = sorted(set(members["ticker"]))
    # enough calendar days for the longest window on a ticker that left `left_window_days` ago
    bars = max(config.high_bars, *config.ma_periods)
    start = _day(as_of, -(int(bars * 1.5) + 14 + config.left_window_days))
    stats = (price_stats(load_prices(raw, tickers, start, as_of), config.ma_periods, config.high_bars)
             if "bars_1d" in raw_tables else pd.DataFrame())
    rated = (member_ratings(derived, tickers, _day(as_of, -(config.left_window_days + config.member_change_days + 14)),
                            as_of, config.member_change_days)
             if "relative_strength" in derived_tables else {})
    bars_end = (raw.execute("SELECT MAX(substr(timestamp, 1, 10)) FROM bars_1d WHERE ticker = ? AND source = ?",
                            ("SPY", source_for(CHART_BASIS))).fetchone()[0] if "bars_1d" in raw_tables else None)

    gone = sorted(set(members.loc[~members["member"].astype(bool), "ticker"]))
    active = _active_flags(raw, gone) if "tickers" in raw_tables else {}

    by_sector: dict[str, tuple[MemberRow, ...]] = {}
    for sector, group in members.groupby("sector"):
        rows = [member_row(r.ticker, bool(r.member), r.left, stats.loc[r.ticker] if r.ticker in stats.index else None,
                           rated.get(r.ticker), as_of, config.ma_periods, active.get(r.ticker))
                for r in group.itertuples()]
        by_sector[sector] = tuple(sorted(rows, key=_sort_key))

    ranked = [
        sector_row(sector, float(rating), int(now[sector]),
                   tuple(None if pd.isna(c[sector]) else int(c[sector]) for c in changes),
                   by_sector.get(sector, ()), as_of, config.ma_periods)
        for sector, rating in ratings.items()]
    # sectors with members but no rating that day: unranked, after the ranked ones
    unrated = [sector_row(sector, None, None, (None,) * len(changes), by_sector[sector], as_of, config.ma_periods)
               for sector in sorted(set(by_sector) - set(ratings.index))]
    return GroupsPage(as_of, tuple(ranked + unrated), by_sector, not_rated, no_sector, bars_end)


def _active_flags(raw: sqlite3.Connection, tickers: list[str]) -> dict[str, bool]:
    """ticker -> the `tickers` table's active flag, for those it lists."""
    if not tickers:
        return {}
    placeholders = ",".join("?" for _ in tickers)
    rows = raw.execute(f"SELECT ticker, active FROM tickers WHERE ticker IN ({placeholders})", tickers).fetchall()
    return {t: bool(a) for t, a in rows if a is not None}
