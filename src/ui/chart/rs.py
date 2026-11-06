"""The relative-strength strip above the chart: stored numbers only, nothing
computed here beyond a change and a rank.

Ratings are `rs_rating` (1-99 percentile) from the relative-strength module's
stored runs (`src/signals/relative_strength/`): the ticker against the market
(SPY) and against its sector ETF, and the ticker's sector against the market.
The sector's rank is its place among the sectors rated on the same date; sectors
with no rating that day are counted and shown, not mixed in from other dates.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from src.foundation.data_processing import db
from src.signals.relative_strength import store

VS_MARKET = "vs_market"
VS_SECTOR = "vs_sector"


@dataclass(frozen=True)
class Rating:
    value: float
    change: float | None  # vs the last rating on or before `change_days` earlier; None without one
    as_of: str
    benchmark: str | None = None


@dataclass(frozen=True)
class SectorRank:
    rating: Rating
    rank: int
    of: int  # sectors with a rating on the same date
    missing: int = 0  # sectors in the table without a rating that day


@dataclass(frozen=True)
class RSStrip:
    vs_market: Rating | None
    vs_sector: Rating | None
    sector: str | None
    industry: str | None
    sector_rank: SectorRank | None


def _rating(rows: pd.DataFrame, change_days: int) -> Rating | None:
    rows = rows.dropna(subset=["rs_rating"])
    if rows.empty:
        return None
    dates = pd.to_datetime(rows["date"])
    last = rows.iloc[-1]
    earlier = rows[dates <= dates.iloc[-1] - pd.Timedelta(days=change_days)]
    change = float(last["rs_rating"] - earlier.iloc[-1]["rs_rating"]) if not earlier.empty else None
    benchmark = last["benchmark"] if "benchmark" in rows.columns and pd.notna(last["benchmark"]) else None
    return Rating(float(last["rs_rating"]), change, str(last["date"])[:10], benchmark)


def _sector_rank(derived: sqlite3.Connection, sector: str, change_days: int) -> SectorRank | None:
    rating = _rating(store.read_sector_relative_strength(derived, sector), change_days)
    if rating is None:
        return None
    # Ranked against the ratings on the same date only, so every number compared is
    # from one day. `missing` counts sectors with stored ratings but none that day.
    peers = pd.read_sql_query(
        "SELECT rs_rating FROM sector_relative_strength WHERE date = ? AND rs_rating IS NOT NULL",
        derived, params=(rating.as_of,))["rs_rating"]
    total = derived.execute("SELECT COUNT(DISTINCT sector) FROM sector_relative_strength").fetchone()[0]
    rank = int((peers > rating.value).sum()) + 1
    return SectorRank(rating, rank, len(peers), total - len(peers))


def _has_tables(conn: sqlite3.Connection, *tables: str) -> bool:
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return set(tables) <= names


def rs_strip(raw: sqlite3.Connection, derived: sqlite3.Connection, ticker: str, change_days: int) -> RSStrip:
    """Missing tables (RS never run in this database, no sector data) read as no rows."""
    ticker = ticker.upper()
    vs_market = vs_sector = None
    if _has_tables(derived, "relative_strength"):
        rows = store.read_relative_strength(derived, ticker)
        vs_market = _rating(rows[rows["comparison"] == VS_MARKET], change_days)
        vs_sector = _rating(rows[rows["comparison"] == VS_SECTOR], change_days)
    sector = industry = None
    if _has_tables(raw, "ticker_sector"):
        meta = db.read_ticker_sector(raw, ticker)
        if not meta.empty:
            sector = meta["sector"].iloc[0] if pd.notna(meta["sector"].iloc[0]) else None
            industry = meta["industry"].iloc[0] if pd.notna(meta["industry"].iloc[0]) else None
    sector_rank = None
    if sector and _has_tables(derived, "sector_relative_strength"):
        sector_rank = _sector_rank(derived, sector, change_days)
    return RSStrip(vs_market, vs_sector, sector, industry, sector_rank)


def _fmt(rating: Rating, change_days: int) -> str:
    change = "" if rating.change is None else f" ({rating.change:+.0f} in {change_days}d)"
    return f"{rating.value:.0f}{change}"


def strip_parts(strip: RSStrip, change_days: int) -> list[str]:
    """The strip as short text pieces, in display order."""
    parts = [f"RS vs market: {_fmt(strip.vs_market, change_days)}" if strip.vs_market
             else "RS vs market: no RS run"]
    if strip.vs_sector:
        etf = f" ({strip.vs_sector.benchmark})" if strip.vs_sector.benchmark else ""
        parts.append(f"RS vs sector{etf}: {_fmt(strip.vs_sector, change_days)}")
    else:
        parts.append("RS vs sector: no RS run")
    if strip.sector:
        sector = strip.sector
        if strip.sector_rank:
            r = strip.sector_rank
            sector += f" · RS {r.rating.value:.0f} · {_ordinal(r.rank)} of {r.of}"
            if r.missing:
                sector += f" ({r.missing} not rated that day)"
        parts.append(sector)
    if strip.industry:
        parts.append(strip.industry)
    as_of = (strip.vs_market or strip.vs_sector)
    if as_of:
        parts.append(f"as of {as_of.as_of}")
    return parts


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
