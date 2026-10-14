"""Reported financials from SEC EDGAR's bulk XBRL "company facts" file.

`companyfacts.zip` holds every non-dimensional XBRL fact a filer has reported
(see `sec_companyfacts`). Each fact is a value for a period -- a span
(start, end) for income and cash-flow items, a single date for balance-sheet
items -- tagged with the filing (accession) that reported it. Every filing
repeats earlier periods as comparatives, so one period appears many times,
sometimes revised.

What's kept, per concept and period:

- **The first-reported value.** The fact from the earliest-accepted filing
  that reported the period, under any of the concept's tags; a later
  restatement is look-ahead and is dropped. Ties within one filing go to the
  tag listed first in CONCEPTS.
- **Its acceptance time**, from the filing index in `submissions.zip`
  (the facts file only has the filing date). Facts whose filing isn't in the
  filer's index are dropped.
- **Quarters, fiscal years and balance-sheet dates only.** Many filers
  report some quarters only year-to-date (cash flow almost always; the fourth
  quarter is usually only in the annual report), so a missing quarter is
  derived as the difference of two cumulative values with the same start and
  tag (Q4 = full year - nine months; Q3 = nine months - six months),
  available once the later of the two was. `derived` flags these. Not done
  for per-share values, which don't add up across quarters.

Only 10-Q/10-K filings (and their amendments and transition reports) count,
and only USD values: a foreign filer reporting in another currency has no
rows. The values are as filed, the scale included -- no sanity checks here.
"""

from __future__ import annotations

import pandas as pd

# concept -> (instant?, unit, additive?, tags in order of preference). All us-gaap.
CONCEPTS: dict[str, tuple[bool, str, bool, tuple[str, ...]]] = {
    "revenue": (False, "USD", True, (
        "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense",
        "SalesRevenueGoodsNet", "SalesRevenueServicesNet")),
    "gross_profit": (False, "USD", True, ("GrossProfit",)),
    "operating_income": (False, "USD", True, ("OperatingIncomeLoss",)),
    "net_income": (False, "USD", True, (
        "NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss")),
    "eps_basic": (False, "USD/shares", False, ("EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted")),
    "eps_diluted": (False, "USD/shares", False, ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted")),
    "operating_cash_flow": (False, "USD", True, (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")),
    "cash": (True, "USD", False, (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash")),
    # current maturities included / excluded: not interchangeable, so two concepts
    "long_term_debt": (True, "USD", False, (
        "LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities")),
    "long_term_debt_noncurrent": (True, "USD", False, (
        "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations")),
    "equity": (True, "USD", False, (
        "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")),
}

# Within one filing, the largest of these concepts' values wins over tag order:
# some filers put a partial figure under `Revenues` next to the full one under
# another tag (Conagra FY2014: $2.2B vs $17.7B), and a part is never larger than
# the total.
LARGEST_WINS = ("revenue",)

FORMS = ("10-Q", "10-K", "10-QT", "10-KT", "10-Q/A", "10-K/A", "10-QT/A", "10-KT/A")
QUARTER_DAYS = (80, 100)  # (end - start).days: 13 weeks = 90, 14 weeks = 97
YEAR_DAYS = (350, 380)  # 52/53-week years included

_FACT_COLUMNS = ["concept", "priority", "tag", "start", "end", "value", "accession", "form", "filed"]
OUT_COLUMNS = ["concept", "period_type", "period_start", "period_end", "value", "tag", "derived",
               "accession", "form", "filed", "accepted_at"]


def company_facts(company: dict | None) -> pd.DataFrame:
    """The CONCEPTS facts of one company-facts JSON, one row per fact as filed."""
    gaap = (company or {}).get("facts", {}).get("us-gaap", {})
    rows = []
    for concept, (instant, unit, _, tags) in CONCEPTS.items():
        for priority, tag in enumerate(tags):
            for f in gaap.get(tag, {}).get("units", {}).get(unit, []):
                if f.get("form") in FORMS and ("start" in f) != instant:
                    rows.append((concept, priority, tag, f.get("start"), f["end"], f["val"], f["accn"],
                                 f["form"], f["filed"]))
    facts = pd.DataFrame(rows, columns=_FACT_COLUMNS)
    for column in ("start", "end", "filed"):
        facts[column] = pd.to_datetime(facts[column], errors="coerce")
    facts["value"] = pd.to_numeric(facts["value"], errors="coerce")
    return facts.dropna(subset=["end", "filed", "value"])


def _period_type(days: pd.Series) -> pd.Series:
    out = pd.Series("cumulative", index=days.index, dtype=object)  # half-years, nine months
    out[days.between(*QUARTER_DAYS)] = "quarter"
    out[days.between(*YEAR_DAYS)] = "year"
    return out


def _derived_quarters(durations: pd.DataFrame) -> pd.DataFrame:
    """Quarters as the difference of consecutive cumulative values that share a
    start (the fiscal year's) and a tag, three months apart."""
    cumulative = durations.sort_values(["concept", "tag", "start", "end"]).reset_index(drop=True)
    earlier = cumulative.groupby(["concept", "tag", "start"])[
        ["end", "value", "accession", "form", "filed", "accepted_at"]].shift(1)
    ok = (cumulative["end"] - earlier["end"]).dt.days.between(*QUARTER_DAYS)
    later, earlier = cumulative[ok].reset_index(drop=True), earlier[ok].reset_index(drop=True)
    if later.empty:
        return pd.DataFrame()
    later_known = later["accepted_at"] >= earlier["accepted_at"]
    last = later[earlier.columns].where(later_known, earlier)  # whichever was accepted last carries the date
    return pd.DataFrame({
        "concept": later["concept"], "priority": later["priority"], "tag": later["tag"],
        "start": earlier["end"] + pd.Timedelta(days=1), "end": later["end"],
        "value": later["value"] - earlier["value"], "accession": last["accession"], "form": last["form"],
        "filed": last["filed"], "accepted_at": last["accepted_at"], "period_type": "quarter", "derived": 1})


def fundamentals(facts: pd.DataFrame, accepted: pd.Series) -> pd.DataFrame:
    """First-reported values per (concept, period_type, period_end), OUT_COLUMNS.
    `accepted` maps accession -> acceptance time (UTC)."""
    if facts.empty or accepted.empty:
        return pd.DataFrame(columns=OUT_COLUMNS)
    facts = facts.assign(accepted_at=facts["accession"].map(accepted)).dropna(subset=["accepted_at"])
    # a period can't end after the filing that reports it: a mistyped date (REG's 10-K of 2012-02-29
    # has a quarter ending 2012-03-31)
    facts = facts[facts["end"] < facts["accepted_at"].dt.tz_convert(None).dt.normalize()]
    if facts.empty:
        return pd.DataFrame(columns=OUT_COLUMNS)
    # first report of each period under each tag
    facts = facts.sort_values("accepted_at").drop_duplicates(["concept", "tag", "start", "end"])
    instant = facts["start"].isna()
    durations = facts[~instant].assign(period_type=lambda d: _period_type((d["end"] - d["start"]).dt.days),
                                       derived=0)
    # a "quarter" equal to the same filing's year ending that day is the year under a mistyped
    # start date (Oracle's 10-Ks: full-year revenue tagged as the fourth quarter)
    year_keys = ["concept", "end", "accession", "value"]
    years = durations.loc[durations["period_type"] == "year", year_keys].drop_duplicates()
    as_year = durations[year_keys].merge(years, how="left", indicator=True)["_merge"].eq("both").to_numpy()
    durations = durations[~((durations["period_type"] == "quarter").to_numpy() & as_year
                            & (durations["value"] != 0).to_numpy())]
    additive = durations["concept"].map(lambda c: CONCEPTS[c][2]).astype(bool)
    candidates = pd.concat([
        facts[instant].assign(period_type="instant", derived=0),
        durations[durations["period_type"] != "cumulative"],
        _derived_quarters(durations.loc[additive]),
    ], ignore_index=True)
    if candidates.empty:  # e.g. only half-year per-share values
        return pd.DataFrame(columns=OUT_COLUMNS)
    # earliest filing wins; within a filing a reported value beats a derived one, then tag order --
    # except revenue, where the largest wins (see LARGEST_WINS)
    largest = candidates["concept"].isin(LARGEST_WINS)
    candidates["rank"] = candidates["priority"].astype(float).where(~largest, -candidates["value"])
    best = (candidates.sort_values(["accepted_at", "derived", "rank"])
            .drop_duplicates(["concept", "period_type", "end"]))
    out = best.rename(columns={"start": "period_start", "end": "period_end"})[OUT_COLUMNS]
    return out.sort_values(["concept", "period_type", "period_end"]).reset_index(drop=True)


def accepted_times(filings: pd.DataFrame) -> pd.Series:
    """accession -> accepted_at, from `sec_earnings.company_filings`."""
    return filings.dropna(subset=["accepted_at"]).set_index("accession")["accepted_at"]
