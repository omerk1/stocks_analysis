"""Share-count history from SEC EDGAR's bulk XBRL "company facts" file.

`companyfacts.zip` (sec.gov, EDGAR bulk data) holds one JSON file per SEC
filer (`CIK##########.json`) with every non-dimensional XBRL fact it has
reported since structured filings began (~2009 for large filers, ~2011 for
all). It's downloaded by hand in a browser -- no API calls, no network
access from this module -- and read straight from the ZIP.

Two concepts carry a company's share count:

- `dei:EntityCommonStockSharesOutstanding` -- the filing's cover page, "as
  of" a date days before filing. The same point-in-time meaning as
  yfinance's `get_shares_full`, so it's preferred.
- `us-gaap:CommonStockSharesOutstanding` -- the balance sheet, as of the
  period end. Every filing repeats prior periods too, so only the filing's
  own latest period is used. Fallback when a filing has no cover-page count.

One value per filing, stored under the date it was *filed* -- when the
number became public -- so a reader never sees a count before it was
knowable. Stale facts (a period ending more than MAX_REPORT_LAG_DAYS
before the filing, e.g. an amendment restating an old year) are dropped.

Two ways a company's numbers can be wrong for a ticker, both handled by
the caller (`bulk_sec_shares_ingest`) rather than guessed at here:

- Share classes. The bulk file omits dimensional facts, so for a company
  with several classes the non-dimensional count is one class or all of
  them combined -- never reliably the class a ticker trades (BRK's cover
  page count is its ~940K Class A shares, >1,000x off for BRK.B).
- Scale. Some filers tag values "in thousands"/"in millions" without the
  matching decimals, so every value is 1,000x or 1,000,000x off.

Both show up as disagreement with yfinance's count where the two
overlap, which is what `agreement` measures.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

COVER_CONCEPT = ("dei", "EntityCommonStockSharesOutstanding")
BALANCE_SHEET_CONCEPT = ("us-gaap", "CommonStockSharesOutstanding")
MAX_REPORT_LAG_DAYS = 200


def to_sec_ticker(ticker: str) -> str:
    """SEC's ticker file spells share classes with '-' (BRK-B), like Yahoo."""
    return ticker.replace(".", "-").upper()


def load_cik_map(company_tickers_path: str | Path) -> dict[str, int]:
    """SEC-spelled ticker -> CIK. Several tickers can share a CIK (share
    classes, but also preferreds, notes and warrants of one issuer)."""
    raw = json.loads(Path(company_tickers_path).read_text())
    entries = raw.values() if isinstance(raw, dict) else raw
    return {str(e["ticker"]).upper(): int(e["cik_str"]) for e in entries}


def _facts(company: dict, concept: tuple[str, str]) -> pd.DataFrame:
    ns, name = concept
    rows = company.get("facts", {}).get(ns, {}).get(name, {}).get("units", {}).get("shares", [])
    df = pd.DataFrame(rows, columns=["end", "val", "accn", "filed", "form"])
    if df.empty:
        return df
    df["end"] = pd.to_datetime(df["end"], errors="coerce")
    df["filed"] = pd.to_datetime(df["filed"], errors="coerce")
    df["val"] = pd.to_numeric(df["val"], errors="coerce")
    df = df.dropna(subset=["end", "filed", "val"])
    lag = (df["filed"] - df["end"]).dt.days
    return df[(df["val"] > 0) & (lag >= 0) & (lag <= MAX_REPORT_LAG_DAYS)]


def share_counts(company: dict) -> pd.Series:
    """One share count per filing, indexed by filing date (ascending).
    Within a filing, the latest-dated fact of the preferred concept wins;
    when two filings share a date, the later-reported period wins.
    """
    per_filing = []
    for priority, concept in enumerate((COVER_CONCEPT, BALANCE_SHEET_CONCEPT)):
        df = _facts(company, concept)
        if df.empty:
            continue
        latest = df.sort_values("end").groupby("accn", as_index=False).last()
        latest["priority"] = priority
        per_filing.append(latest)
    if not per_filing:
        return pd.Series(dtype="float64", name="shares_outstanding").rename_axis("date")

    both = pd.concat(per_filing)
    chosen = both.sort_values(["accn", "priority"]).groupby("accn", as_index=False).first()
    chosen = chosen.sort_values(["filed", "end"]).groupby("filed", as_index=False).last()
    series = chosen.set_index("filed")["val"].astype("float64")
    series.index.name = "date"
    series.name = "shares_outstanding"
    return series


def drop_isolated_spikes(series: pd.Series, factor: float = 10.0) -> pd.Series:
    """Drop single filings >= `factor` x off from both neighbours while the
    neighbours agree with each other (within 2x) -- a mis-tagged filing,
    not a real change: a genuine reverse split or issuance doesn't revert
    at the next filing."""
    if len(series) < 3:
        return series
    prev, nxt = series.shift(1), series.shift(-1)
    jump = series / prev
    spike = ((jump >= factor) | (jump <= 1 / factor)) & (nxt / prev).between(0.5, 2)
    return series[~spike]


def agreement(sec_series: pd.Series, reference: pd.Series, tolerance_days: int = 10) -> tuple[int, float | None]:
    """(number of SEC points with a `reference` point within
    `tolerance_days`, median SEC/reference ratio over them)."""
    if sec_series.empty or reference.empty:
        return 0, None
    left = pd.DataFrame({"date": pd.to_datetime(sec_series.index), "sec": sec_series.to_numpy()}).sort_values("date")
    right = pd.DataFrame({"date": pd.to_datetime(reference.index), "ref": reference.to_numpy()}).sort_values("date")
    m = pd.merge_asof(left, right, on="date", direction="nearest",
                      tolerance=pd.Timedelta(days=tolerance_days)).dropna()
    m = m[m["ref"] > 0]
    if m.empty:
        return 0, None
    return len(m), float((m["sec"] / m["ref"]).median())


def read_company(zf: zipfile.ZipFile, cik: int) -> dict | None:
    name = f"CIK{cik:010d}.json"
    try:
        return json.loads(zf.read(name))
    except KeyError:
        return None
