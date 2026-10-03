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

from enum import Enum

from src.foundation.data_processing import db


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
}


def source_for(basis: PriceBasis | str) -> str:
    """The `bars_1d.source` value holding bars on `basis`."""
    return SOURCE_BY_BASIS[PriceBasis(basis)]


def basis_for_source(source: str) -> PriceBasis:
    for basis, src in SOURCE_BY_BASIS.items():
        if src == source:
            return basis
    raise ValueError(f"bars_1d source {source!r} is not a price basis")
