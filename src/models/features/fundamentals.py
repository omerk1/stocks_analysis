"""Company-financials model features (`docs/fundamentals/plan.md`, step 3), from
the `fundamentals` and `earnings_announcements` tables rather than from bars.
Row t = close of t. A value counts on t only from its `available_date` (the
first session whose close may use it; for earnings, the `reaction_date`), so
the leakage gate's `future_filings` perturbation must not move anything
dated before a filing.

- `days_since_earnings`: sessions since the last earnings reaction date.
- `days_to_earnings_expected`: business days to the *expected* next one --
  the same quarter's reaction date a year earlier + 52 weeks. Never the
  realized next date, which is future information on every day before it.
  0 when overdue.
- `sue_net_income`: standardized unexpected earnings against the company's
  own history (no analyst consensus): net income minus the same quarter a
  year earlier, over the standard deviation of that change across the
  previous 8 quarters (at least 4). Net income, not EPS: the stored EPS is as
  filed, so it jumps at splits and carries scale errors.
- `rev_growth_yoy`: revenue over the same quarter a year earlier, minus 1;
  only when both measure the same thing (the same XBRL tag, or two of the
  total-revenue tags in `REVENUE_FAMILY`) and are positive.
- `net_margin_ttm`: trailing four quarters' net income over their revenue.
- `debt_to_equity`: long-term debt (current maturities included, else the
  noncurrent part) over equity, at the latest balance-sheet date; NaN when
  equity isn't positive or no debt is tagged (absent isn't zero).

A quarter-based value goes stale: NaN once its quarter ended more than
`MAX_AGE_DAYS` before t, so a company that stopped filing doesn't carry its
last numbers forever. Out-of-order filings (an old quarter first reported
late) never replace a newer quarter's value.

Valuation (P/E, P/S) needs a point-in-time market cap and is left out here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COLUMNS = ("days_since_earnings", "days_to_earnings_expected", "sue_net_income", "rev_growth_yoy",
           "net_margin_ttm", "debt_to_equity")
YEAR_AGO_DAYS, YEAR_AGO_TOLERANCE = 365, 15
SUE_WINDOW, SUE_MIN = 8, 4
MAX_AGE_DAYS = 200
FOUR_QUARTERS_SPAN = (250, 300)  # days from the first quarter's end to the fourth's
EXPECTED_GAP = pd.Timedelta(weeks=52)
MAX_DAYS_SINCE = 200  # sessions; longer means the earnings history has a hole
# Revenue tags that all mean total revenue: a switch among them (ASC 606 moved
# nearly every filer from `SalesRevenueNet` to `RevenueFromContractWith...` in
# 2018) keeps growth comparable. Any other switch (goods only, net of
# interest) doesn't.
REVENUE_FAMILY = {tag: "total" for tag in (
    "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax")}


def _ns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return frame.assign(**{c: pd.to_datetime(frame[c]).astype("datetime64[ns]") for c in columns})


def _year_ago(q: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """`cols` of each row's quarter one year earlier (by period end, within
    YEAR_AGO_TOLERANCE days), aligned to `q`'s rows; NaN where none."""
    left = q[["ticker", "period_end"]].assign(target=q["period_end"] - pd.Timedelta(days=YEAR_AGO_DAYS),
                                              row=np.arange(len(q)))
    right = q[["ticker", "period_end", *cols]].rename(columns={"period_end": "target"})
    m = pd.merge_asof(left.sort_values("target"), right.sort_values("target"), on="target", by="ticker",
                      direction="nearest", tolerance=pd.Timedelta(days=YEAR_AGO_TOLERANCE))
    return m.sort_values("row")[cols].reset_index(drop=True)


def _in_order(rows: pd.DataFrame) -> pd.DataFrame:
    """One concept's rows without the late reports of old periods: a period
    ending before one already known when it arrives is dropped. What's left
    arrives in period order, so a quarter's feature reads only quarters known
    before it -- a late report can't change, after the fact, which quarter
    counted as "a year earlier" or which ones filled a window."""
    rows = rows.sort_values(["ticker", "available_date", "period_end"])
    newest = rows.groupby("ticker")["period_end"].cummax().groupby(rows["ticker"]).shift(1)
    return rows[newest.isna() | (rows["period_end"] > newest)]


def _quarters(fundamentals: pd.DataFrame) -> pd.DataFrame:
    """One row per (ticker, quarter end) with net income and revenue, their
    availability and revenue's tag; sorted by ticker, period_end."""
    q = fundamentals[fundamentals["period_type"] == "quarter"]
    parts = []
    for concept, short in (("net_income", "ni"), ("revenue", "rev")):
        c = _in_order(q.loc[q["concept"] == concept, ["ticker", "period_end", "value", "available_date", "tag"]])
        parts.append(c.rename(columns={"value": short, "available_date": f"{short}_at", "tag": f"{short}_tag"}))
    out = parts[0].merge(parts[1], on=["ticker", "period_end"], how="outer")
    return out.sort_values(["ticker", "period_end"], ignore_index=True)


def _rolling_max_dates(s: pd.Series, by: pd.Series, window: int) -> pd.Series:
    as_int = s.astype("int64").where(s.notna())
    out = as_int.groupby(by).transform(lambda x: x.rolling(window, min_periods=1).max())
    return pd.to_datetime(out)


def quarter_features(fundamentals: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per feature, its events: (ticker, period_end, known_at, value), one per
    quarter or balance-sheet date. `known_at` is the latest availability of
    every value the feature read."""
    q = _quarters(fundamentals)
    events = {}
    if len(q):
        prev = _year_ago(q, ["ni", "ni_at", "rev", "rev_at", "rev_tag"])
        # SUE: the change vs a year earlier, scaled by the spread of the previous changes
        change = q["ni"] - prev["ni"]
        spread = change.groupby(q["ticker"]).transform(
            lambda x: x.shift(1).rolling(SUE_WINDOW, min_periods=SUE_MIN).std())
        sue = (change / spread.where(spread > 0))
        # everything read: this quarter, its year-ago, and the window's quarters and year-agos
        read_at = pd.concat([q["ni_at"], prev["ni_at"]], axis=1).max(axis=1)
        # an event exists only once the quarter's own value is known (a quarter with
        # revenue but no net income yet mustn't count as known from its inputs' dates)
        sue_at = _rolling_max_dates(read_at, q["ticker"], SUE_WINDOW + 1).where(q["ni_at"].notna())
        events["sue_net_income"] = pd.DataFrame({"ticker": q["ticker"], "period_end": q["period_end"],
                                                 "known_at": sue_at, "value": sue})

        family = lambda tags: tags.map(lambda t: REVENUE_FAMILY.get(t, t), na_action="ignore")
        same_tag = q["rev_tag"].notna() & (family(q["rev_tag"]) == family(prev["rev_tag"]))
        growth = (q["rev"] / prev["rev"] - 1).where(same_tag & (q["rev"] > 0) & (prev["rev"] > 0))
        events["rev_growth_yoy"] = pd.DataFrame({
            "ticker": q["ticker"], "period_end": q["period_end"],
            "known_at": pd.concat([q["rev_at"], prev["rev_at"]], axis=1).max(axis=1).where(q["rev_at"].notna()),
            "value": growth})

        by = q["ticker"]
        both = q["ni"].notna() & q["rev"].notna()
        ni4 = q["ni"].where(both).groupby(by).transform(lambda x: x.rolling(4, min_periods=4).sum())
        rev4 = q["rev"].where(both).groupby(by).transform(lambda x: x.rolling(4, min_periods=4).sum())
        span = (q["period_end"] - q.groupby("ticker")["period_end"].shift(3)).dt.days
        margin = (ni4 / rev4).where(span.between(*FOUR_QUARTERS_SPAN) & (rev4 > 0))
        margin_at = _rolling_max_dates(pd.concat([q["ni_at"], q["rev_at"]], axis=1).max(axis=1), by, 4).where(both)
        events["net_margin_ttm"] = pd.DataFrame({"ticker": q["ticker"], "period_end": q["period_end"],
                                                 "known_at": margin_at, "value": margin})

    inst = fundamentals[fundamentals["period_type"] == "instant"]
    keys = ["ticker", "period_end"]
    pick = lambda c: _in_order(inst.loc[inst["concept"] == c, [*keys, "value", "available_date"]]).set_index(keys)
    equity, debt, debt_nc = pick("equity"), pick("long_term_debt"), pick("long_term_debt_noncurrent")
    debt = debt.combine_first(debt_nc)  # with current maturities when tagged, else the noncurrent part
    bs = equity.join(debt, how="inner", lsuffix="_eq", rsuffix="_debt").reset_index()
    events["debt_to_equity"] = pd.DataFrame({
        "ticker": bs["ticker"], "period_end": bs["period_end"],
        "known_at": bs[["available_date_eq", "available_date_debt"]].max(axis=1),
        "value": (bs["value_debt"] / bs["value_eq"]).where(bs["value_eq"] > 0)})
    return events


def _as_of(rows: pd.DataFrame, events: pd.DataFrame) -> pd.Series:
    """For each (ticker, date) row: the value of the newest quarter known by
    that date, NaN if none or if that quarter ended over MAX_AGE_DAYS ago."""
    ev = _ns(events.dropna(subset=["known_at"]), ["known_at", "period_end"])
    ev = ev.sort_values(["ticker", "known_at", "period_end"])
    # an old quarter first known late must not displace a newer one
    newest = ev.groupby("ticker")["period_end"].cummax()
    ev = ev[ev["period_end"] >= newest].sort_values("known_at")
    left = rows[["ticker", "date"]].assign(row=np.arange(len(rows))).sort_values("date")
    m = pd.merge_asof(left, ev[["ticker", "known_at", "period_end", "value"]], left_on="date",
                      right_on="known_at", by="ticker", direction="backward").sort_values("row")
    fresh = (m["date"] - m["period_end"]).dt.days <= MAX_AGE_DAYS
    return pd.Series(m["value"].where(fresh).to_numpy(), index=rows.index)


def earnings_features(rows: pd.DataFrame, earnings: pd.DataFrame) -> pd.DataFrame:
    """`days_since_earnings` and `days_to_earnings_expected` for each (ticker,
    date) row (`rows` sorted by ticker, date: one ticker's bars in order)."""
    out = pd.DataFrame(np.nan, index=rows.index, columns=["days_since_earnings", "days_to_earnings_expected"])
    ann = earnings.dropna(subset=["reaction_date"]).sort_values(["ticker", "period_end"], ignore_index=True)
    if ann.empty:
        return out
    # the expected next reaction, known once this one has happened: the reaction
    # three announcements back (the next one's year-ago quarter) + 52 weeks
    back = ann.groupby("ticker")[["period_end", "reaction_date"]].shift(3)
    span = (ann["period_end"] - back["period_end"]).dt.days
    ann["expected_next"] = (back["reaction_date"] + EXPECTED_GAP).where(span.between(*FOUR_QUARTERS_SPAN))

    pos = rows.groupby("ticker").cumcount()
    bars = rows[["ticker", "date"]].assign(pos=pos.to_numpy())
    # the session position of each reaction (first bar on or after it)
    reaction_pos = pd.merge_asof(ann[["ticker", "reaction_date"]].assign(i=np.arange(len(ann)))
                                 .sort_values("reaction_date"), bars.sort_values("date"), left_on="reaction_date",
                                 right_on="date", by="ticker", direction="forward").sort_values("i")
    ann["reaction_pos"] = reaction_pos["pos"].to_numpy()
    ev = ann.sort_values("reaction_date")
    left = bars.assign(row=np.arange(len(bars))).sort_values("date")
    m = pd.merge_asof(left, ev[["ticker", "reaction_date", "reaction_pos", "expected_next"]], left_on="date",
                      right_on="reaction_date", by="ticker", direction="backward").sort_values("row")
    since = (m["pos"] - m["reaction_pos"]).where(lambda s: s <= MAX_DAYS_SINCE)
    ok = m["expected_next"].notna() & since.notna()
    to = np.full(len(m), np.nan)
    to[ok.to_numpy()] = np.busday_count(m.loc[ok, "date"].to_numpy().astype("datetime64[D]"),
                                        m.loc[ok, "expected_next"].to_numpy().astype("datetime64[D]"))
    out["days_since_earnings"] = since.to_numpy()
    out["days_to_earnings_expected"] = np.clip(to, 0, None)
    return out


CONCEPTS_READ = ("net_income", "revenue", "equity", "long_term_debt", "long_term_debt_noncurrent")


def load_tables(conn, tickers: list[str], end) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(fundamentals, earnings) rows for `tickers` that were known by `end`
    (`available_date` / `reaction_date` <= end): nothing past the holdout
    boundary is read. Dates parsed."""
    end = str(pd.Timestamp(end).date())
    marks = ", ".join("?" * len(tickers))
    concepts = ", ".join("?" * len(CONCEPTS_READ))
    fundamentals = pd.read_sql_query(
        f"SELECT ticker, concept, period_type, period_end, value, tag, available_date FROM fundamentals "
        f"WHERE ticker IN ({marks}) AND concept IN ({concepts}) AND available_date <= ?",
        conn, params=[*tickers, *CONCEPTS_READ, end], parse_dates=["period_end", "available_date"])
    earnings = pd.read_sql_query(
        f"SELECT ticker, period_end, reaction_date FROM earnings_announcements "
        f"WHERE ticker IN ({marks}) AND reaction_date <= ?",
        conn, params=[*tickers, end], parse_dates=["period_end", "reaction_date"])
    return fundamentals, earnings


def panel_features(bars: pd.DataFrame, ctx) -> pd.DataFrame:
    """Every column for every (ticker, date) row of `bars` (long, one basis):
    a `registry.PanelSource`. Reads `ctx.fundamentals` and `ctx.earnings`; NaN
    where a ticker has none."""
    out = bars[["ticker", "date"]].sort_values(["ticker", "date"], ignore_index=True)
    rows = _ns(out, ["date"])  # one datetime resolution for every merge (inputs can come in us or ns)
    for col in COLUMNS:
        out[col] = np.nan
    if ctx.earnings is not None and len(ctx.earnings):
        out[["days_since_earnings", "days_to_earnings_expected"]] = earnings_features(
            rows, _ns(ctx.earnings, ["period_end", "reaction_date"]))
    if ctx.fundamentals is not None and len(ctx.fundamentals):
        for col, events in quarter_features(_ns(ctx.fundamentals, ["period_end", "available_date"])).items():
            out[col] = _as_of(rows, events)
    out[list(COLUMNS)] = out[list(COLUMNS)].astype("float32")
    return out
