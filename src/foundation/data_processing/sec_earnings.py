"""Earnings announcement dates from SEC EDGAR's bulk "submissions" file.

`submissions.zip` (sec.gov, EDGAR bulk data) holds one JSON file per filer
(`CIK##########.json`) with its filing index -- form, items, filing date and
the exact acceptance time -- plus overflow files (`...-submissions-001.json`)
for filers with more than ~1,000 filings. Downloaded by hand, read straight
from the ZIP; no network access here.

A results announcement is an 8-K with item 2.02 ("Results of Operations and
Financial Condition", in use since 2004-08-23). Not every item 2.02 8-K is one:
banks and insurers also file them for mid-quarter conference presentations
and outlook updates (PNC: 8-16 a year). So announcements are anchored on the
quarterly report instead: for each 10-Q/10-K, the announcement is the first
item 2.02 8-K accepted after the period ended and no later than the day the
report was filed. With no such 8-K, the report itself is the announcement
(`source` = its form), which can be days or weeks later than the actual
release -- consumers that need the exact day should drop those rows.

The first 8-K in the window is the first public word on the period's results,
but not always the main release: ~7% of periods (2010-2021, 300-company
sample) have more than one, and in ~5% the first comes 7+ days before the
last -- a preliminary announcement, or a presentation after the release. Which
one it is can't be told from the index; `extra_filings` flags these periods.

Timing comes from the acceptance time (UTC in the file, converted to New York
time): before 09:30 on a session day, during the session, after 16:00, or on a
non-session day. `reaction_date` is the first session whose bar can reflect
the news -- the same day for before-open and during-session filings, the next
session otherwise. Half-day sessions (13:00 close) aren't known here, so a
filing between 13:00 and 16:00 on one is read as during the session.

The 8-K can trail the press release (a release at 07:00, the 8-K at 10:00),
which moves the timing but rarely the reaction date; the ingest's gap check
measures how often the reaction date is off.
"""

from __future__ import annotations

import json
import zipfile

import pandas as pd

EARNINGS_ITEM = "2.02"
PERIODIC_FORMS = ("10-Q", "10-K")
# Item 2.02 took effect 2004-08-23; earlier periods would all fall back to the report date.
FIRST_PERIOD_END = pd.Timestamp("2004-09-30")
MARKET_TZ = "America/New_York"
SESSION_OPEN = pd.Timedelta(hours=9, minutes=30)
SESSION_CLOSE = pd.Timedelta(hours=16)

# Checked by hand (2026-10-14, names in submissions.zip): a company whose
# history is filed under an earlier CIK than the one SEC's ticker file gives
# today -- a holding-company reorganisation or redomicile moves future filings
# to a new CIK. Newest first. Some keep filing as subsidiaries (Apache, Xerox
# Corp), so each one is cut off: for earnings dates it only fills periods
# before the earliest period already found; for fundamentals it counts only
# for filings before the newer CIK's first 10-Q/10-K
# (`bulk_sec_fundamentals_ingest.ticker_rows`) -- so a new entry's successor
# must not have filed periodic reports before the reorganisation (all of
# these first did at it). Not here on purpose: tickers whose earlier history is another company
# (FOXA/21st Century Fox, DOW/Dow Chemical, SNDK, CEG, IR/Ingersoll-Rand plc).
PREDECESSOR_CIKS: dict[int, tuple[int, ...]] = {
    2115436: (34088,),  # Exxon Mobil: new holding company, 8-K12B 2026-07-01
    1652044: (1288776,),  # Alphabet <- Google Inc. (2015)
    1744489: (1001039,),  # Walt Disney <- TWDC Enterprises 18 (old Disney, 2019)
    1739940: (701221,),  # Cigna <- Cigna Holding Co (old Cigna, 2018)
    2012383: (1364742,),  # BlackRock <- BlackRock Finance (old BlackRock, 2024)
    1841666: (6769,),  # APA <- Apache Corp (2021)
    1613103: (64670,),  # Medtronic plc <- Medtronic Inc (2015)
    1571949: (1174746,),  # Intercontinental Exchange <- its old holding company (2013)
    1551182: (31277,),  # Eaton plc <- Eaton Corp (2012)
    1730168: (1649338, 1441634),  # Broadcom Inc <- Broadcom Pte (2016-18) <- Avago Technologies
    1770450: (108772,),  # Xerox Holdings <- Xerox Corp (2019)
    1835632: (1058057,),  # Marvell Technology Inc <- Marvell Technology Group (2021)
    1618921: (104207,),  # Walgreens Boots Alliance <- Walgreen Co (2014)
}

_COLUMNS = ["accessionNumber", "form", "items", "filingDate", "acceptanceDateTime", "reportDate"]


def company_filings(zf: zipfile.ZipFile, available: set[str], cik: int) -> pd.DataFrame:
    """Every filing of `cik` (main file plus overflow files): accession, form,
    items, filing_date, accepted_at (UTC), report_date. Empty if the CIK isn't
    in the ZIP."""
    member = f"CIK{cik:010d}.json"
    filings = json.loads(zf.read(member)).get("filings", {}) if member in available else {}
    parts = [filings.get("recent", {})]
    parts += [json.loads(zf.read(f["name"])) for f in filings.get("files", []) if f.get("name") in available]
    frame = pd.concat([pd.DataFrame({c: p.get(c, []) for c in _COLUMNS}) for p in parts], ignore_index=True)
    return pd.DataFrame({
        "accession": frame["accessionNumber"],
        "form": frame["form"],
        "items": frame["items"].fillna("").astype(str),
        "filing_date": pd.to_datetime(frame["filingDate"], errors="coerce"),
        "accepted_at": pd.to_datetime(frame["acceptanceDateTime"], errors="coerce", utc=True),
        "report_date": pd.to_datetime(frame["reportDate"].replace("", None), errors="coerce"),
    }).drop_duplicates("accession")


def has_earnings_item(items: pd.Series) -> pd.Series:
    return items.str.split(",").apply(lambda xs: EARNINGS_ITEM in [x.strip() for x in xs])


def announcements(filings: pd.DataFrame) -> pd.DataFrame:
    """One row per reporting period (10-Q/10-K period end from FIRST_PERIOD_END on):
    period_end, report_form, report_filed, accession, source ('8-K' or the
    report's form), accepted_at, extra_filings (further item 2.02 8-Ks in the
    same window)."""
    reports = filings[filings["form"].isin(PERIODIC_FORMS) & filings["report_date"].notna()]
    reports = (reports[reports["report_date"] >= FIRST_PERIOD_END]
               .sort_values("accepted_at").drop_duplicates("report_date"))  # the original, not a re-filing
    eightks = filings[(filings["form"] == "8-K") & has_earnings_item(filings["items"])]
    eightks = eightks.dropna(subset=["accepted_at"]).sort_values("accepted_at")
    accepted_day = eightks["accepted_at"].dt.tz_convert(MARKET_TZ).dt.tz_localize(None).dt.normalize()

    rows = []
    for r in reports.sort_values("report_date").itertuples(index=False):
        window = eightks[(accepted_day > r.report_date) & (accepted_day <= r.filing_date)]
        first = window.iloc[0] if len(window) else r._asdict()
        rows.append({
            "period_end": r.report_date, "report_form": r.form, "report_filed": r.filing_date,
            "accession": first["accession"], "source": "8-K" if len(window) else r.form,
            "accepted_at": first["accepted_at"], "extra_filings": max(len(window) - 1, 0),
        })
    out = pd.DataFrame(rows, columns=["period_end", "report_form", "report_filed", "accession", "source",
                                      "accepted_at", "extra_filings"])
    out["accepted_at"] = pd.to_datetime(out["accepted_at"], utc=True)
    return out


def classify_timing(accepted_at: pd.Series, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """timing (before_open / during_session / after_close / non_session_day)
    and reaction_date (NaT past the end of `sessions`) for UTC acceptance times."""
    sessions = pd.DatetimeIndex(sessions).normalize().unique().sort_values()
    local = pd.DatetimeIndex(accepted_at).tz_convert(MARKET_TZ).tz_localize(None)
    day = local.normalize()
    clock = local - day
    is_session = day.isin(sessions)
    timing = pd.Series("after_close", index=accepted_at.index, dtype=object)
    timing[(clock < SESSION_CLOSE)] = "during_session"
    timing[(clock < SESSION_OPEN)] = "before_open"
    timing[~is_session] = "non_session_day"
    same_day = timing.isin(["before_open", "during_session"]).to_numpy()
    # first session on/after the day (same-day reactions) or strictly after it
    pos = sessions.searchsorted(day, side="left")
    pos = pos + (~same_day & (pos < len(sessions)) & (sessions[pos.clip(max=len(sessions) - 1)] == day))
    reaction = pd.Series(pd.NaT, index=accepted_at.index, dtype="datetime64[ns]")
    inside = pos < len(sessions)
    reaction[inside] = sessions[pos[inside]]
    return pd.DataFrame({"timing": timing, "reaction_date": reaction})
