"""Daily point-in-time record of the SPY fund's published holdings.

The S&P 500 membership source (`index_membership.py`) stopped at 2026-08-18, so the
paper-traded universe for new dates is SPY's daily holdings file
(`docs/modeling/PREREGISTRATION.md` HT1, "Universe for new dates: SPY"). State Street
publishes one file, overwritten each day, holding the previous trading day's
positions; nothing older can be downloaded later, so a day not recorded is lost.

Each run downloads the file, reads its own "As of" date, and keeps:
- the raw file, `<out>/<as_of>.xlsx`, exactly as served;
- its members, `<out>/<as_of>.csv`: the equity lines (cash and lines without a
  ticker symbol, like a contingent value right, dropped);
- a row in `<out>/fetch_log.csv` (when it was fetched, the as-of date, the file's
  hash, the member count, and what happened), so the record shows what was known
  when. A failed download or a refused file gets a row too.

The first file recorded for a date is the record. A later download with the same
bytes as one already kept for its date is skipped; one with different bytes is kept
beside it as `<as_of>.<hash>.xlsx` and logged, never written over the first. A file
that can't be read is kept anyway, under `<out>/refused/`, so a change in State
Street's layout costs a parser fix, not the day. Files only: nothing is written to
the database.
"""

import argparse
import datetime
import hashlib
import io
import os
import re
from pathlib import Path

import pandas as pd
import requests

from src.foundation.data_processing.retry import attempt_with_limited_retries
from src.foundation.utils.config_loader import load_config

SPY = "SPY"
_URLS = {
    SPY: "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx",
}
_REPO_ROOT = Path(__file__).resolve().parents[3]
_HEADER_ROWS = 4  # fund name, ticker, "As of", blank; the column names are on row 5
_COLUMNS = ["Name", "Ticker", "Identifier", "SEDOL", "Weight", "Sector", "Shares Held", "Local Currency"]
# A listed share symbol, with an optional class suffix as the file and our membership
# table write it (BRK.B, BF.B). Cash ("-") and CVR lines ("2602335D") don't match.
_SYMBOL = re.compile(r"[A-Z]{1,5}(\.[A-Z])?")
# The S&P 500 has ~503 lines (two share classes for a few names); a count far off
# means the file's layout changed or it's the wrong fund.
MIN_MEMBERS, MAX_MEMBERS = 480, 520
LOG_COLUMNS = ["fetched_at", "fund", "as_of", "sha256", "n_members", "status"]


class HoldingsFileError(ValueError):
    """The downloaded file isn't the holdings file we expect."""


def fetch(fund: str = SPY, timeout: float = 60, attempts: int = 3, backoff_seconds: float = 30) -> bytes:
    def get():
        response = requests.get(_URLS[fund], timeout=timeout)
        response.raise_for_status()
        return response

    ok, response, error = attempt_with_limited_retries(get, attempts, backoff_seconds)
    if not ok:
        raise requests.RequestException(f"{fund}: download failed after {attempts} attempts ({error})")
    if not response.content.startswith(b"PK"):  # an .xlsx is a zip archive
        raise HoldingsFileError(f"{fund}: the download isn't a spreadsheet "
                                f"({response.headers.get('content-type')})")
    return response.content


def parse(content: bytes, fund: str = SPY) -> tuple[datetime.date, pd.DataFrame]:
    """The file's as-of date and every holding line, as served (cash included)."""
    raw = pd.read_excel(io.BytesIO(content), header=None, dtype=str)
    if raw.shape[0] <= _HEADER_ROWS or raw.shape[1] < len(_COLUMNS):
        raise HoldingsFileError(f"too small for a holdings file: {raw.shape[0]} rows, {raw.shape[1]} columns")
    labels = raw.iloc[:_HEADER_ROWS, 0].fillna("").str.strip().tolist()
    values = raw.iloc[:_HEADER_ROWS, 1].fillna("").str.strip().tolist()
    if labels[1] != "Ticker Symbol:" or values[1] != fund:
        raise HoldingsFileError(f"not the {fund} holdings file (ticker row: {labels[1]!r} {values[1]!r})")
    match = re.fullmatch(r"As of (\d{1,2}-[A-Za-z]{3}-\d{4})", values[2])
    if labels[2] != "Holdings:" or not match:
        raise HoldingsFileError(f"no as-of date in the header (row 3: {labels[2]!r} {values[2]!r})")
    as_of = datetime.datetime.strptime(match.group(1), "%d-%b-%Y").date()
    header = raw.iloc[_HEADER_ROWS].fillna("").str.strip().tolist()
    if header[: len(_COLUMNS)] != _COLUMNS:
        raise HoldingsFileError(f"unexpected columns: {header}")
    body = raw.iloc[_HEADER_ROWS + 1:, : len(_COLUMNS)]
    body.columns = _COLUMNS
    # The holdings end at the first row with neither a name nor a ticker; disclaimers
    # follow. A line with a name and no ticker is kept here and dropped by `members`.
    blank = body["Ticker"].isna() & body["Name"].isna()
    end = int(blank.to_numpy().argmax()) if blank.any() else len(body)
    holdings = body.iloc[:end].copy()
    holdings["Ticker"] = holdings["Ticker"].fillna("").str.strip()
    holdings["Weight"] = pd.to_numeric(holdings["Weight"], errors="coerce")
    holdings["Shares Held"] = pd.to_numeric(holdings["Shares Held"], errors="coerce")
    return as_of, holdings.reset_index(drop=True)


def members(holdings: pd.DataFrame) -> pd.DataFrame:
    """The equity lines: a ticker symbol and shares held. Both share classes are kept
    where the fund holds both (GOOGL and GOOG)."""
    symbol = holdings["Ticker"].str.fullmatch(_SYMBOL)
    unreadable = symbol & (holdings["Weight"].isna() | holdings["Shares Held"].isna())
    if unreadable.any():
        raise HoldingsFileError(f"a weight or share count isn't a number: {sorted(holdings.loc[unreadable, 'Ticker'])}")
    keep = symbol & (holdings["Shares Held"] > 0)
    out = holdings.loc[keep, ["Ticker", "Name", "Identifier", "Weight", "Shares Held"]]
    out.columns = ["ticker", "name", "identifier", "weight", "shares_held"]
    if out["ticker"].duplicated().any():
        raise HoldingsFileError(f"a ticker appears twice: {sorted(out.loc[out['ticker'].duplicated(), 'ticker'])}")
    return out.reset_index(drop=True)


def _write_atomic(path: Path, data: bytes) -> None:
    """Written whole or not at all: a killed run leaves no half-written file."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _log(out_dir: Path, now: datetime.datetime, fund: str, as_of: str, digest: str, n_members, status: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "fetch_log.csv"
    row = pd.DataFrame([[now.isoformat(timespec="seconds"), fund, as_of, digest, n_members, status]],
                       columns=LOG_COLUMNS)
    row.to_csv(log, mode="a", header=not log.exists(), index=False)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record(content: bytes, out_dir: Path, fund: str = SPY,
           now: datetime.datetime | None = None) -> tuple[str, Path]:
    """Keep one downloaded file under `out_dir`; returns (status, path of the raw file
    kept or matched). Status: "new", "same" (already kept for its date, skipped) or
    "changed" (same as-of date, different bytes, kept beside the first). A file that
    can't be read is kept under `refused/`, logged, and its error raised."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    digest = _sha256(content)
    try:
        as_of, holdings = parse(content, fund)
        picked = members(holdings)
        if not MIN_MEMBERS <= len(picked) <= MAX_MEMBERS:
            raise HoldingsFileError(f"{len(picked)} members on {as_of}, expected {MIN_MEMBERS}-{MAX_MEMBERS}")
    except Exception as e:
        refused = out_dir / "refused"
        refused.mkdir(parents=True, exist_ok=True)
        _write_atomic(refused / f"{now:%Y%m%dT%H%M%S}.{digest[:12]}.xlsx", content)
        _log(out_dir, now, fund, "", digest, "", f"refused: {type(e).__name__}: {e}")
        raise
    out_dir.mkdir(parents=True, exist_ok=True)
    first = out_dir / f"{as_of}.xlsx"
    kept = [first, *sorted(out_dir.glob(f"{as_of}.*.xlsx"))]
    same = next((p for p in kept if p.exists() and _sha256(p.read_bytes()) == digest), None)
    if same is not None:
        status, path = "same", same
    else:
        status, path = ("new", first) if not first.exists() else ("changed", out_dir / f"{as_of}.{digest[:12]}.xlsx")
        # Members first: the raw file is what marks the date recorded, so a run killed
        # between the two writes is redone in full by the next one.
        _write_atomic(path.with_suffix(".csv"), picked.to_csv(index=False).encode())
        _write_atomic(path, content)
    _log(out_dir, now, fund, as_of.isoformat(), digest, len(picked), status)
    return status, path


def default_out_dir(fund: str = SPY) -> Path:
    """Under the repo's raw data folder, wherever the run starts from."""
    raw = Path(load_config().data_paths.raw)
    return (raw if raw.is_absolute() else _REPO_ROOT / raw) / "etf_holdings" / fund.lower()


def main():
    parser = argparse.ArgumentParser(description="Record the SPY fund's published holdings for today's file")
    parser.add_argument("--out", type=Path, default=None, help="default: data/raw/etf_holdings/spy in this checkout")
    args = parser.parse_args()
    out_dir = args.out or default_out_dir(SPY)
    try:
        content = fetch(SPY)
    except Exception as e:
        _log(out_dir, datetime.datetime.now(datetime.timezone.utc), SPY, "", "", "",
             f"fetch failed: {type(e).__name__}: {e}")
        raise
    status, path = record(content, out_dir, SPY)
    print(f"{SPY}: {status} -> {path}")


if __name__ == "__main__":
    main()
