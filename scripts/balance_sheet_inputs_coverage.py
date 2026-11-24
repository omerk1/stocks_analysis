"""Read-only data check: how often inventory, receivables and cash are filed
for S&P 500 point-in-time member-quarters, 2010-2021, banks and insurers
excluded by industry.

    venv/bin/python -m scripts.balance_sheet_inputs_coverage   # from the repo root

Reads `market_data.sqlite` (read-only URI) for membership, sectors and the
ticker -> CIK pairs already in `fundamentals`, and `companyfacts.zip` for the
facts. Writes nothing to either. Result: `docs/fundamentals/plan.md`,
"Balance-sheet warning inputs: data check (2026-11-24)".

A member-quarter is (ticker, calendar quarter end) for a ticker in the index
on that day. It counts as covered for a concept when the company (its CIK or a
predecessor's) has a balance-sheet value under one of the concept's tags dated
inside that calendar quarter, from a 10-Q/10-K filed on or before 2021-12-31.
Facts filed later are dropped on read, so calendar 2021 is Q1-Q3 only (most
Q4 2021 balance sheets were filed in 2022). Members with no CIK in
`fundamentals` count as not covered.
"""

from __future__ import annotations

import sqlite3
import zipfile
from collections import Counter
from pathlib import Path

import pandas as pd

from src.foundation.data_processing import sec_companyfacts as sec
from src.foundation.data_processing import sec_earnings as se
from src.foundation.data_processing import sec_fundamentals as sf

RAW = Path("/Users/omerkoren/dev/stocks_analysis/data/raw")
LAST_FILED = pd.Timestamp("2021-12-31")
QUARTERS = pd.date_range("2010-03-31", "2021-09-30", freq="QE")

# concept -> us-gaap instant tags (USD), in order of preference
TAGS = {
    "inventory": ("InventoryNet", "InventoryGross", "InventoryFinishedGoodsNetOfReserves",
                  "RetailRelatedInventoryMerchandise", "InventoryNetOfAllowancesCustomerAdvancesAndProgressBillings"),
    "receivables": ("AccountsReceivableNetCurrent", "ReceivablesNetCurrent",
                    "AccountsNotesAndLoansReceivableNetCurrent", "AccountsAndOtherReceivablesNetCurrent",
                    "AccountsReceivableGrossCurrent", "AccountsReceivableNet"),
    "cash": sf.CONCEPTS["cash"][3],
}
# sensitivity: the inventory list plus the stock tags the gap diagnostic below found in use
# (homebuilders, utilities' materials and supplies, oil majors, retailers' single line)
TAGS["inventory_wide"] = TAGS["inventory"] + (
    "InventoryRealEstate", "InventoryOperativeBuilders", "InventoryHomesUnderConstruction",
    "InventoryRawMaterialsAndSupplies", "InventoryCrudeOilProductsAndMerchandise",
    "InventoryFinishedGoods", "InventoryFinishedGoodsAndWorkInProcess")
MAIN_TAG = {"inventory": "InventoryNet", "receivables": "AccountsReceivableNetCurrent",
            "cash": "CashAndCashEquivalentsAtCarryingValue", "inventory_wide": "InventoryNet"}


def is_bank_or_insurer(industry: str | None) -> bool:
    s = industry.lower() if isinstance(industry, str) else ""
    return s.startswith(("banks", "insurance -")) or any(
        w in s for w in ("commercial banks", "savings institution", "casualty insurance", "life insurance"))


def company_instants(company: dict | None) -> tuple[pd.DataFrame, Counter]:
    """(tag, end) of every instant USD fact under TAGS, plus a count of
    other Inventory*/Receivable* tags (to see what the lists miss)."""
    gaap = (company or {}).get("facts", {}).get("us-gaap", {})
    rows, others = [], Counter()
    wanted: dict[str, list[str]] = {}
    for c, tags in TAGS.items():
        for t in tags:
            wanted.setdefault(t, []).append(c)
    for tag, body in gaap.items():
        facts = [f for f in body.get("units", {}).get("USD", [])
                 if "start" not in f and f.get("form") in sf.FORMS and pd.Timestamp(f["filed"]) <= LAST_FILED]
        if not facts:
            continue
        if tag in wanted:
            rows += [(c, tag, f["end"]) for c in wanted[tag] for f in facts]
        elif "Inventor" in tag or "Receivable" in tag:
            others[tag] += 1
    out = pd.DataFrame(rows, columns=["concept", "tag", "end"]).drop_duplicates()
    out["end"] = pd.to_datetime(out["end"], errors="coerce")
    return out.dropna(), others


def main():
    conn = sqlite3.connect(f"file:{RAW / 'market_data.sqlite'}?mode=ro", uri=True)
    members = pd.read_sql_query(
        "SELECT ticker, start_date, end_date FROM index_membership WHERE index_name = 'sp500'", conn)
    sectors = pd.read_sql_query("SELECT ticker, sector, industry FROM ticker_sector", conn)
    ciks = pd.read_sql_query("SELECT DISTINCT ticker, cik FROM fundamentals", conn)
    conn.close()

    mq = []
    for q in QUARTERS:
        d = q.strftime("%Y-%m-%d")
        on = members[(members["start_date"] <= d) & (members["end_date"].isna() | (members["end_date"] >= d))]
        mq.append(pd.DataFrame({"ticker": on["ticker"].unique(), "quarter": q}))
    mq = pd.concat(mq, ignore_index=True).merge(sectors, on="ticker", how="left")
    mq["excluded"] = mq["industry"].map(is_bank_or_insurer)
    print(f"member-quarters {len(mq)}, banks/insurers {int(mq['excluded'].sum())}, "
          f"no sector row {int(mq['sector'].isna().sum())}")
    mq = mq[~mq["excluded"]].merge(ciks, on="ticker", how="left")
    print(f"kept {len(mq)}, without a CIK in fundamentals {int(mq['cik'].isna().sum())}")

    facts, others, others_by_cik = [], Counter(), {}
    with zipfile.ZipFile(RAW / "sec" / "companyfacts.zip") as zf:
        names = set(zf.namelist())
        for cik in sorted(mq["cik"].dropna().astype(int).unique()):
            for c in (cik, *se.PREDECESSOR_CIKS.get(cik, ())):
                if f"CIK{c:010d}.json" not in names:
                    continue
                f, o = company_instants(sec.read_company(zf, c))
                facts.append(f.assign(cik=cik))
                others.update(o)
                others_by_cik.setdefault(cik, set()).update(o)
    facts = pd.concat(facts, ignore_index=True)
    facts["quarter"] = facts["end"] + pd.offsets.QuarterEnd(0)

    keys = ["cik", "quarter"]
    have = mq[keys + ["ticker", "sector"]].copy()
    for concept in TAGS:
        hit = facts.loc[facts["concept"] == concept, keys].drop_duplicates().assign(**{concept: True})
        have = have.merge(hit, on=keys, how="left")
        main = facts.loc[(facts["concept"] == concept) & (facts["tag"] == MAIN_TAG[concept]), keys]
        have = have.merge(main.drop_duplicates().assign(**{concept + "_main": True}), on=keys, how="left")
    have = have.fillna({c: False for c in have.columns if c in TAGS or c.endswith("_main")})
    have["all_three"] = have["inventory"] & have["receivables"] & have["cash"]
    have["recv_cash"] = have["receivables"] & have["cash"]
    have["any_filed"] = have["cash"] | have["receivables"] | have["inventory"]

    cols = ["inventory", "inventory_wide", "receivables", "cash", "recv_cash", "all_three"]
    year = have["quarter"].dt.year
    table = have.groupby(year)[cols].mean().round(3)
    table.insert(0, "member_quarters", have.groupby(year).size())
    table.loc["all"] = [len(have), *have[cols].mean().round(3)]
    pd.set_option("display.width", 200)
    print("\nShare of member-quarters with a value, by year (2021: Q1-Q3)\n", table.to_string())
    print("\nMain tag alone:", have[[c + "_main" for c in TAGS]].mean().round(3).to_dict())
    print("\nAmong member-quarters with any of the three filed:",
          have.loc[have["any_filed"], cols].mean().round(3).to_dict(), int(have["any_filed"].sum()))
    print("\nBy sector:\n", have.groupby(have["sector"].fillna("(none)"))[cols].mean().round(3)
          .assign(n=have.groupby(have["sector"].fillna("(none)")).size()).to_string())
    print("\nTop other Inventory*/Receivable* instant tags (fact counts):")
    for tag, n in others.most_common(25):
        print(f"  {n:7d} {tag}")

    # cash filed but no inventory: a company with no inventory, or a tag the list misses?
    gap = have[have["cash"] & ~have["inventory"]]
    by_company = gap.groupby("cik").agg(n=("quarter", "size"), ticker=("ticker", "first"), sector=("sector", "first"))
    stock_tag = lambda t: t.startswith("Inventor") and not any(  # noqa: E731
        w in t for w in ("Reserve", "Allowance", "Writedown", "WriteDown", "Policy"))
    by_company["other_inventory_tags"] = by_company.index.map(
        lambda c: ",".join(sorted(t for t in others_by_cik.get(c, ()) if stock_tag(t))))
    some = by_company["other_inventory_tags"] != ""
    print(f"\nCash but no inventory: {len(gap)} member-quarters, {len(by_company)} companies; "
          f"{int(some.sum())} of them file some other Inventory* stock tag "
          f"({int(by_company.loc[some, 'n'].sum())} member-quarters)")
    print(by_company[some].sort_values("n", ascending=False).head(30).to_string())
    print("\nWithout any Inventory* tag, by sector (member-quarters):\n",
          by_company[~some].groupby(by_company["sector"].fillna("(none)"))["n"].sum().to_string())


if __name__ == "__main__":
    main()
