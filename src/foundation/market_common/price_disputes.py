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
known which vendor is wrong, the entry names the vendor the ticker is read
from, so its labels are dropped rather than trusted. `date=None` disputes the whole
history (the two vendors' series are different securities).

The entries live in `price_disputes.csv` (ticker, date, vendor, gap, reason),
one row per disputed day; "unverified" in the reason means only that the two
vendors disagree, not which one is wrong. The comparison covered 355 of the 665
members so far (Tiingo's free tier allows 500 symbols a month); the rest are
added when it resumes.

Because an entry is tied to a vendor, switching a ticker's vendor (adding it to
`vendor_overrides.PREFER_TIINGO`, or Tiingo bars appearing for it) turns its
yfinance entries off. Review the ticker's entries for the new vendor when you
do -- the unverified ones in particular named yfinance only because that's
where the ticker was read from.

Consumers don't guess a fix: `src/models/dataset.build_labels` drops every
label whose window, or the ATR window before it, touches a disputed day.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

YFINANCE = "yfinance"
TIINGO = "tiingo"


@dataclass(frozen=True)
class DisputedDay:
    ticker: str
    date: str | None  # YYYY-MM-DD, or None for the whole history
    vendor: str  # YFINANCE or TIINGO: whose bars are wrong (both bases)
    reason: str


CSV_PATH = Path(__file__).with_name("price_disputes.csv")


def load(path: Path = CSV_PATH) -> tuple[DisputedDay, ...]:
    """The disputes file, validated: a misspelled vendor would otherwise
    never match any ticker and silently dispute nothing."""
    days = []
    with open(path, newline="") as f:
        for line, r in enumerate(csv.DictReader(f), start=2):
            if r["vendor"] not in (YFINANCE, TIINGO):
                raise ValueError(f"{path.name}:{line}: vendor {r['vendor']!r} is not {YFINANCE!r} or {TIINGO!r}")
            if not r["ticker"] or not r["reason"]:
                raise ValueError(f"{path.name}:{line}: ticker and reason are required")
            if r["date"]:
                date.fromisoformat(r["date"])  # raises on a malformed date
            days.append(DisputedDay(r["ticker"], r["date"] or None, r["vendor"], r["reason"]))
    return tuple(days)


DISPUTED_DAYS: tuple[DisputedDay, ...] = load()


def vendor_of(source: str) -> str:
    """`bars_1d.source` -> the vendor it comes from."""
    return TIINGO if source.startswith(TIINGO) else YFINANCE
