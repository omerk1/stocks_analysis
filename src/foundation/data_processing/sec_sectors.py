"""python -m src.foundation.data_processing.sec_sectors [--dry-run]

Sectors for delisted index members Yahoo has no page for (the Tiingo-only
tickers, `bulk_tiingo_ingest.py`), so the modeling features don't leave their
`sector` blank. Stored in `ticker_sector` with `source = db.SEC_SIC`; a row
from yfinance is never overwritten.

The sector comes from the company's SEC industry code (SIC, in
`submissions.zip`), translated into Yahoo's sector names by learning the
translation from active companies that have both: each SIC code maps to the
Yahoo sector most companies with that code carry (`learn_mapping`), falling
back to the 3- then 2-digit SIC group when fewer than `MIN_COMPANIES` share
the code. Leave-one-out on 5,111 active companies (2026-10-05): 83% of
sectors recovered overall, 87% where the majority holds >= `MIN_SHARE`.

Accepted automatically only when both hold:
1. the CIK is the right company -- the SEC's current or former name for it
   matches the membership-era or Tiingo name (`ticker_renames.names_match`).
   Polygon's CIK is wrong for some old symbols: it gave Yahoo a petroleum
   company's, Chesapeake Energy a paper company's;
2. the SIC code is decisive: its majority sector has share >= MIN_SHARE.
Everything else is in `REVIEWED_SECTORS` (checked by hand) or printed as
`needs_review` and left blank.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import db
from src.foundation.data_processing import sec_companyfacts as sec
from src.foundation.data_processing import ticker_renames as tr
from src.foundation.utils.config_loader import load_config

MIN_COMPANIES = 3
MIN_SHARE = 0.6

# Checked by hand (2026-10-05), in Yahoo's sector names: a wrong CIK, no SIC
# code, an indecisive SIC code, or a SIC code Yahoo's convention overrides.
REVIEWED_SECTORS = {
    # wrong CIK from Polygon, or a name the check doesn't recognise
    "AET": "Healthcare",  # Aetna; health insurers are Healthcare on Yahoo (UNH, CVS)
    "ALXN": "Healthcare",  # Alexion Pharmaceuticals (CIK points at Vanda)
    "CHK": "Energy",  # Chesapeake Energy (CIK points at Chesapeake Corp, paper)
    "LVLT": "Communication Services",  # Level 3 Communications (CIK points at Expeditors)
    "MWV": "Consumer Cyclical",  # MeadWestvaco, packaging (SEC name is the former Westvaco)
    "MWW": "Communication Services",  # Monster Worldwide, online recruiting (CIK points at Morgan Stanley)
    "PETM": "Consumer Cyclical",  # PetSmart, specialty retail (CIK points at Federated Hermes)
    "RRD": "Industrials",  # R.R. Donnelley, commercial printing (CIK points at GameStop)
    "SNI": "Communication Services",  # Scripps Networks (CIK points at Energy Focus)
    "YHOO": "Communication Services",  # Yahoo, internet content (CIK points at FieldPoint Petroleum)
    "SHPG": "Healthcare",  # Shire, pharmaceuticals
    # no SIC code in submissions.zip
    "ACAS": "Financial Services",  # American Capital, business development company
    "BCR": "Healthcare",  # C.R. Bard, medical devices
    "DISCK": "Communication Services",  # Discovery, Series C
    # SIC code doesn't decide the sector
    "BIDU": "Communication Services",  # Baidu, internet search
    "BMS": "Consumer Cyclical",  # Bemis, packaging
    "GAS": "Utilities",  # AGL Resources, gas utility
    "JOY": "Industrials",  # Joy Global, mining machinery
    "NLSN": "Industrials",  # Nielsen, consulting/measurement services
    "PDCO": "Healthcare",  # Patterson, dental/medical distribution
    "RHT": "Technology",  # Red Hat, software
    "TIE": "Basic Materials",  # Titanium Metals
    "TWTR": "Communication Services",  # Twitter
    "PDD": "Consumer Cyclical",  # PDD Holdings, internet retail
    "TCOM": "Consumer Cyclical",  # Trip.com, travel services
    # decisive SIC code, but Yahoo classifies the business elsewhere
    "CTRX": "Healthcare",  # Catamaran, pharmacy benefit manager (SIC: insurance agents)
    "SEE": "Consumer Cyclical",  # Sealed Air, packaging (Yahoo: Packaging & Containers)
}


def sic_info(zf: zipfile.ZipFile, available: set[str], cik: int) -> dict:
    """{sic, description, names} for a CIK from `submissions.zip`; names are
    the current plus former ones. Empty dict if the CIK isn't there."""
    member = f"CIK{cik:010d}.json"
    if member not in available:
        return {}
    data = json.loads(zf.read(member))
    names = [data.get("name")] + [f.get("name") for f in data.get("formerNames") or []]
    return {"sic": data.get("sic") or None, "description": data.get("sicDescription"), "names": [n for n in names if n]}


def training_set(conn: sqlite3.Connection, cik_map: dict[str, int], zf: zipfile.ZipFile) -> pd.DataFrame:
    """One row per company (CIK) with a yfinance sector and a 4-digit SIC
    code: columns cik, sic, sector."""
    sectors = pd.read_sql_query(
        "SELECT ticker, sector FROM ticker_sector WHERE sector IS NOT NULL AND sector != '' "
        "AND (source IS NULL OR source = ?)", conn, params=[db.YFINANCE],
    )
    sectors["cik"] = sectors["ticker"].map(lambda t: cik_map.get(t.replace(".", "-")))
    sectors = sectors.dropna(subset=["cik"]).drop_duplicates("cik")  # one vote per company
    available = set(zf.namelist())
    sectors["sic"] = pd.Series([sic_info(zf, available, int(c)).get("sic") for c in sectors["cik"]],
                               index=sectors.index, dtype=object)
    sectors = sectors[sectors["sic"].astype(str).str.fullmatch(r"\d{4}")]
    return sectors[["cik", "sic", "sector"]].reset_index(drop=True)


def learn_mapping(train: pd.DataFrame) -> dict[str, pd.Series]:
    """SIC prefix (4, 3 or 2 digits) -> sector counts among training companies."""
    mapping = {}
    for digits in (4, 3, 2):
        for prefix, group in train.groupby(train["sic"].str[:digits]):
            mapping[prefix] = group["sector"].value_counts()
    return mapping


def predict(mapping: dict[str, pd.Series], sic: str | None) -> tuple[str | None, float | None]:
    """(majority sector, its share) from the most specific SIC prefix that at
    least MIN_COMPANIES training companies share; (None, None) otherwise."""
    if not sic:
        return None, None
    for digits in (4, 3, 2):
        counts = mapping.get(str(sic)[:digits])
        if counts is not None and counts.sum() >= MIN_COMPANIES:
            return counts.idxmax(), round(float(counts.max() / counts.sum()), 3)
    return None, None


def targets(conn: sqlite3.Connection) -> pd.DataFrame:
    """Tiingo-stored members with no sector, or one this module wrote."""
    return pd.read_sql_query(
        """
        SELECT l.ticker, r.cik, r.old_name, l.tiingo_name
        FROM tiingo_listings l JOIN ticker_renames r ON r.old_ticker = l.ticker
        LEFT JOIN ticker_sector s ON s.ticker = l.ticker
        WHERE l.status = 'stored'
          AND (s.ticker IS NULL OR s.sector IS NULL OR s.sector = '' OR s.source = ?)
        ORDER BY l.ticker
        """, conn, params=[db.SEC_SIC],
    )


def decide(row, info: dict, mapping: dict[str, pd.Series]) -> dict:
    """The sector for one target and why (`status`)."""
    out = {"ticker": row.ticker, "sic": info.get("sic"), "description": info.get("description")}
    if row.ticker in REVIEWED_SECTORS:
        return {**out, "sector": REVIEWED_SECTORS[row.ticker], "status": "reviewed"}
    names = info.get("names", [])
    if not (tr.names_match(row.old_name, names) or tr.names_match(row.tiingo_name, names)):
        return {**out, "status": "needs_review", "detail": "CIK name mismatch: " + "; ".join(names[:2])}
    sector, share = predict(mapping, info.get("sic"))
    if sector is None or share < MIN_SHARE:
        return {**out, "status": "needs_review", "detail": f"indecisive SIC ({sector}, {share})"}
    return {**out, "sector": sector, "share": share, "status": "derived"}


def run(conn: sqlite3.Connection, cik_map: dict[str, int], submissions_zip: str | Path,
        dry_run: bool = False) -> pd.DataFrame:
    with zipfile.ZipFile(submissions_zip) as zf:
        mapping = learn_mapping(training_set(conn, cik_map, zf))
        available = set(zf.namelist())
        rows = [decide(r, sic_info(zf, available, int(r.cik)) if pd.notna(r.cik) else {}, mapping)
                for r in targets(conn).itertuples(index=False)]
    result = pd.DataFrame(rows, columns=["ticker", "sector", "status", "sic", "description", "share", "detail"])
    accepted = result[result["status"].isin(["derived", "reviewed"])]
    if not dry_run:
        # A reviewed row's SIC description may belong to a wrong CIK, so it isn't kept.
        industry = [f"SEC SIC: {d}" if status == "derived" else "reviewed by hand"
                    for status, d in zip(accepted["status"], accepted["description"])]
        db.upsert_ticker_sector(conn, accepted.assign(industry=industry)[["ticker", "sector", "industry"]],
                                source=db.SEC_SIC)
    return result


def main():
    parser = argparse.ArgumentParser(description="Sectors for Tiingo-only index members from SEC industry codes")
    parser.add_argument("--dry-run", action="store_true", help="Print the decisions without writing them")
    args = parser.parse_args()

    config = load_config()
    conn = db.get_connection(db.default_db_path(config.data_paths.raw))
    db.create_tables(conn)
    sec_dir = Path(config.data_paths.raw) / "sec"
    result = run(conn, sec.load_cik_map(sec_dir / "company_tickers.json"), sec_dir / "submissions.zip",
                 dry_run=args.dry_run)
    pd.set_option("display.width", 200)
    print(result.to_string(index=False))
    print(result["status"].value_counts().to_string())
    conn.close()


if __name__ == "__main__":
    main()
