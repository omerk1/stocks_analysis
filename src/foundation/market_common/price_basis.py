"""Which price series each module computes on -- one explicit, recorded
choice per module, so no calculation ever mixes the two.

`bars_1d` holds the same yfinance daily bars on two bases:

- `TOTAL_RETURN` (source `yfinance`): adjusted for splits *and*
  dividends. Right for anything that measures returns -- the dividend is
  part of what a holder earned. Every past dividend shifts all earlier
  prices down, and each new one rescales the whole history again.
- `TRADED` (source `yfinance_split_only`): adjusted for splits only --
  the prices that actually traded (on today's share basis), and what
  TradingView charts by default. Right for anything that places a *price
  level* (a gap zone, an AVWAP, an S/R line): levels sit where trades
  happened, and history only changes when the stock splits.

Price-level modules and market caps compute on TRADED; returns and
return-based modules on TOTAL_RETURN (reasoning in the decision record,
`docs/decisions/price-basis.md`).
`MODULE_PRICE_BASIS` below is the single source of truth: each module's
config defaults its `price_basis` from it, the shared loader
(`market_common.data.load_bars`) refuses to load without a basis, and
`tests/test_market_common_price_basis.py` fails if a module's declared
basis drifts from this table. Changing a module's basis means changing it
here, updating the decision record, and rerunning that module's stored
results.
"""

from __future__ import annotations

import sqlite3
from enum import Enum

from src.foundation.data_processing import db
from src.foundation.market_common import price_disputes
from src.foundation.market_common.price_disputes import DisputedDay, vendor_of
from src.foundation.market_common.vendor_overrides import PREFER_TIINGO


class PriceBasis(str, Enum):
    TOTAL_RETURN = "total_return"
    TRADED = "traded"


SOURCE_BY_BASIS: dict[PriceBasis, str] = {
    PriceBasis.TOTAL_RETURN: db.YFINANCE,
    PriceBasis.TRADED: db.YFINANCE_SPLIT_ONLY,
}

# Price-level modules on TRADED (since 2026-10-02), returns on
# TOTAL_RETURN. See docs/decisions/price-basis.md for each row's reason.
MODULE_PRICE_BASIS: dict[str, PriceBasis] = {
    # price levels
    "gaps": PriceBasis.TRADED,
    "avwap": PriceBasis.TRADED,
    "volume_profile": PriceBasis.TRADED,
    "sr_lines": PriceBasis.TRADED,
    "fibonacci": PriceBasis.TRADED,
    "market_structure": PriceBasis.TRADED,
    "patterns": PriceBasis.TRADED,
    "divergences": PriceBasis.TRADED,
    # market cap = the price that traded x shares outstanding
    "market_cap": PriceBasis.TRADED,
    # returns and return-based state
    "moving_averages": PriceBasis.TOTAL_RETURN,
    "relative_strength": PriceBasis.TOTAL_RETURN,
    "breadth": PriceBasis.TOTAL_RETURN,
    # modeling harness (src/models/dataset.py): two bases, never mixed in one
    # calculation -- labels, ATR and the decision close are returns; the
    # liquidity floor and traded-price checks need the prices that traded
    "models_labels": PriceBasis.TOTAL_RETURN,
    "models_universe": PriceBasis.TRADED,
    # the baselines' factor columns (src/models/features/baseline.py): the MA
    # study's definitions, on the study's basis
    "models_features": PriceBasis.TOTAL_RETURN,
}


# Delisted index members yfinance can't serve have Tiingo bars on the same
# two bases (`bulk_tiingo_ingest.py`). A module listed here reads them for
# tickers with no bars on the primary source; every other module reads the
# primary source only (the completed MA study stays reproducible). The
# choice is per ticker, never per date: one ticker's series always comes
# from one vendor.
FALLBACK_SOURCE_BY_BASIS: dict[PriceBasis, str] = {
    PriceBasis.TOTAL_RETURN: db.TIINGO,
    PriceBasis.TRADED: db.TIINGO_SPLIT_ONLY,
}
# Splits matching each bar source (`history_breaks` recovers traded prices
# from them).
SPLITS_SOURCE_BY_BAR_SOURCE: dict[str, str] = {
    db.YFINANCE: db.YFINANCE, db.YFINANCE_SPLIT_ONLY: db.YFINANCE,
    db.TIINGO: db.TIINGO, db.TIINGO_SPLIT_ONLY: db.TIINGO,
}
MODULES_WITH_FALLBACK: frozenset[str] = frozenset({
    "models_labels", "models_universe", "models_features",
    # Divergences opted in 2026-10-08 (backlog: the event base was
    # survivors-only — delisted members' bars exist only on the Tiingo
    # sources). The other signal modules and breadth/RS stay primary-only
    # until each one's stored tables are deliberately rerun.
    "divergences",
})


def source_for(basis: PriceBasis | str) -> str:
    """The `bars_1d.source` value holding bars on `basis`."""
    return SOURCE_BY_BASIS[PriceBasis(basis)]


def sources_for(basis: PriceBasis | str, fallback: bool) -> list[str]:
    """`bars_1d.source` values to read for `basis`, in priority order."""
    basis = PriceBasis(basis)
    return [SOURCE_BY_BASIS[basis], FALLBACK_SOURCE_BY_BASIS[basis]] if fallback else [SOURCE_BY_BASIS[basis]]


def ticker_sources(
    conn: sqlite3.Connection, tickers: list[str], basis: PriceBasis | str, fallback: bool,
    members: dict[str, set[str]] | None = None,
) -> dict[str, str]:
    """ticker -> the one source its `basis` bars are read from: the first of
    `sources_for(basis, fallback)` holding any bar for it (whatever the
    dates, so the choice doesn't depend on the window asked for). Tickers
    with no bars on any of them are left out.

    With `fallback`, a ticker in `vendor_overrides.PREFER_TIINGO` is read
    from the fallback source instead, and must have bars there: a listed
    ticker silently read from yfinance would carry the error it's listed for.

    `members` ({source: its full ticker set}) lets a FULL-UNIVERSE caller
    that already listed each source's tickers (one DISTINCT scan apiece on
    the 4GB file) reuse those sets — without it, membership is a per-ticker
    probe, which is right for the usual few-hundred-ticker list (an early
    LIMIT 1 hit) but takes minutes for thousands of tickers, since bars_1d's
    PK is (ticker, timestamp, source) and a source-absent probe walks every
    bar of the ticker.
    """
    basis = PriceBasis(basis)
    srcs = sources_for(basis, fallback)

    def has_bars(ticker: str, source: str) -> bool:
        if members is not None:
            return ticker in members[source]
        return _has_bars(conn, ticker, source)

    out: dict[str, str] = {}
    if fallback:
        fb_source = FALLBACK_SOURCE_BY_BASIS[basis]
        preferred = [t for t in tickers if t in PREFER_TIINGO]
        missing = [t for t in preferred if not has_bars(t, fb_source)]
        if missing:
            raise ValueError(
                f"{missing} are in vendor_overrides.PREFER_TIINGO but have no {fb_source} "
                "bars; run bulk_tiingo_ingest --store-preferred"
            )
        out.update(dict.fromkeys(preferred, fb_source))
    for source in srcs:
        for ticker in tickers:
            if ticker not in out and has_bars(ticker, source):
                out[ticker] = source
    return out


def resolve_sources(
    conn: sqlite3.Connection, tickers: list[str], basis: PriceBasis | str, fallback: bool,
    members: dict[str, set[str]] | None = None,
    disputes: tuple[DisputedDay, ...] | None = None,
) -> dict[str, str]:
    """ticker -> the `bars_1d.source` its `basis` bars come from. Without
    `fallback`, every ticker maps to the basis's primary source (no lookup).
    With it (the modules in MODULES_WITH_FALLBACK), a ticker whose vendor has
    a whole-history dispute (`price_disputes`, no date: e.g. a reused symbol
    whose bars are another company's) is left out, so it has no bars at
    all -- not in the universe, the ranks, the labels, or a detector's scan.
    `members` as in `ticker_sources` (full-universe callers pass the
    per-source ticker sets they already listed). `disputes` defaults to
    `price_disputes.DISPUTED_DAYS`, read through the module at call time so
    patching that one canonical name reaches this policy; a module with its own binding of that list
    (models.dataset, whose tests patch it) passes it explicitly so exclusion
    and its cache manifest can never read two different lists.
    (Moved here from models.dataset when divergences opted into the
    fallback -- one policy, not two drifting copies.)"""
    if not fallback:
        return dict.fromkeys(tickers, source_for(basis))
    sources = ticker_sources(conn, tickers, basis, fallback=True, members=members)
    excluded = _whole_history_disputes(price_disputes.DISPUTED_DAYS if disputes is None else disputes)
    return {t: s for t, s in sources.items() if (t, vendor_of(s)) not in excluded}


def _whole_history_disputes(disputes: tuple[DisputedDay, ...]) -> set[tuple[str, str]]:
    return {(d.ticker, d.vendor) for d in disputes if d.date is None}


def source_members(
    conn: sqlite3.Connection, basis: PriceBasis | str, fallback: bool,
) -> dict[str, set[str]]:
    """{source: every ticker with any bar on it}, for each source
    `sources_for(basis, fallback)` reads -- the `members` argument of
    `ticker_sources`/`resolve_sources` for FULL-UNIVERSE callers. One
    DISTINCT index scan per source (minutes on the 4GB file, but once),
    instead of a per-ticker probe that walks a source-absent ticker's
    whole bar history (fine for a few hundred tickers, slow for thousands)."""
    return {
        s: {r[0] for r in conn.execute("SELECT DISTINCT ticker FROM bars_1d WHERE source = ?", (s,))}
        for s in sources_for(basis, fallback)
    }


def _has_bars(conn: sqlite3.Connection, ticker: str, source: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM bars_1d WHERE ticker = ? AND source = ? LIMIT 1", (ticker, source)
    ).fetchone() is not None


def basis_for_source(source: str) -> PriceBasis:
    for table in (SOURCE_BY_BASIS, FALLBACK_SOURCE_BY_BASIS):
        for basis, src in table.items():
            if src == source:
                return basis
    raise ValueError(f"bars_1d source {source!r} is not a price basis")
