"""Hand-reviewed days where a vendor's daily bars are wrong or unverifiable.

Around corporate actions (spin-offs, special and stock dividends, cash
mergers, share consolidations) yfinance and Tiingo each have their own bugs,
and with two vendors a disagreement can't always be settled: DHR +45% in
yfinance on the Fortive spin-off, RRD +214% in Tiingo on its reverse split
and double spin-off, FHN's stock dividends booked by Tiingo as $1 cash. Found
by comparing the two vendors' daily returns for every S&P 500 / Nasdaq-100
member, 2010-2021, and by checking the Tiingo-only delisted members against
their own split and dividend records (backlog: vendor disagreements).

An entry names the vendor whose bars carry the problem; it only matters for
a ticker read from that vendor (`price_basis.ticker_sources`). When it isn't
known which vendor is wrong, both are listed. `date=None` disputes the whole
history (the two vendors' series are different securities).

Consumers don't guess a fix: `src/models/dataset.build_labels` drops every
label whose window, or the ATR window before it, touches a disputed day.
"""

from __future__ import annotations

from dataclasses import dataclass

YFINANCE = "yfinance"
TIINGO = "tiingo"


@dataclass(frozen=True)
class DisputedDay:
    ticker: str
    date: str | None  # YYYY-MM-DD, or None for the whole history
    vendor: str  # YFINANCE or TIINGO: whose bars are wrong (both bases)
    reason: str


DISPUTED_DAYS: tuple[DisputedDay, ...] = ()


def vendor_of(source: str) -> str:
    """`bars_1d.source` -> the vendor it comes from."""
    return TIINGO if source.startswith(TIINGO) else YFINANCE
