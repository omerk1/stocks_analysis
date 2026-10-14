"""Company-financials model features (`docs/fundamentals/plan.md`, step 3), from
the `fundamentals` and `earnings_announcements` tables rather than from bars.
Row t = close of t. A value counts on t only from its `available_date` (the
first session whose close may use it; for earnings, the `reaction_date`), so
the leakage gate's `future_filings` perturbation must not move anything
dated before a filing.

- `days_since_earnings`: business days since the last earnings reaction date.
- `days_to_earnings_expected`: business days to the *expected* next one --
  the same quarter's reaction date a year earlier + 52 weeks. Never the
  realized next date, which is future information on every day before it.
  0 when overdue.
- `sue_net_income`: standardized unexpected earnings against the company's
  own history (no analyst consensus): net income minus the same quarter a
  year earlier, over the standard deviation of that change across the
  previous 8 quarters (at least 4).
- `sue_eps`: the same on diluted EPS, which adds what net income misses --
  buybacks and dilution. Stored EPS is as filed, so it's first put on one
  share basis with the ticker's splits (`PanelContext.splits`): each value
  divided by every share split executed after its filing (spin-offs booked
  as splits ignored, `is_share_split`). That basis uses later splits, but a
  SUE is a ratio and every value in one quarter's window gets the same factor
  from the splits after that quarter's filing, so the result equals a
  computation with only the splits known then. Scale errors dropped and the
  missing fourth quarter derived: `eps_quarters`.
- `rev_growth_yoy`: revenue over the same quarter a year earlier, minus 1;
  only when both measure the same thing (the same XBRL tag, or two of the
  total-revenue tags in `REVENUE_FAMILY`) and are positive.
- `rev_growth_accel`: this quarter's `rev_growth_yoy` minus the previous
  quarter's -- whether growth is speeding up, without the seasonality a plain
  quarter-over-quarter change carries.
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

COLUMNS = ("days_since_earnings", "days_to_earnings_expected", "sue_net_income", "sue_eps", "rev_growth_yoy",
           "rev_growth_accel", "net_margin_ttm", "debt_to_equity")
EPS_PLAUSIBLE = (1e-3, 1e5)  # |EPS| outside this is an XBRL scale error (0 is kept);
                             # 1e5 leaves Berkshire's per-Class-A-share EPS in
SHARES_JUMP = 50  # implied share count this many times off its recent median: a scale error
QUARTER_GAP = (80, 100)  # days between consecutive quarter ends
YEAR_AGO_DAYS, YEAR_AGO_TOLERANCE = 365, 15
SUE_WINDOW, SUE_MIN = 8, 4
MAX_AGE_DAYS = 200
FOUR_QUARTERS_SPAN = (250, 300)  # days from the first quarter's end to the fourth's
EXPECTED_GAP = pd.Timedelta(weeks=52)
MAX_DAYS_SINCE = 200  # business days; longer means the earnings history has a hole
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


def _in_order(rows: pd.DataFrame, known: str = "available_date") -> pd.DataFrame:
    """One concept's rows (or the announcements) without the late reports of
    old periods: a period ending before one already known when it arrives is
    dropped. What's left arrives in period order, so a quarter's feature reads
    only quarters known before it -- a late report can't change, after the
    fact, which quarter counted as "a year earlier" or which ones filled a
    window."""
    rows = rows.sort_values(["ticker", known, "period_end"], kind="stable")
    newest = rows.groupby("ticker")["period_end"].cummax().groupby(rows["ticker"]).shift(1)
    return rows[newest.isna() | (rows["period_end"] > newest)]


def _rolling(s: pd.Series, by: pd.Series, window: int, how: str, min_periods: int) -> pd.Series:
    """`how` over each ticker's trailing `window` rows (rows sorted by ticker)."""
    out = s.groupby(by).rolling(window, min_periods=min_periods).agg(how)
    return out.reset_index(level=0, drop=True).sort_index()


def is_share_split(ratio: float) -> bool:
    """A small-number ratio (2, 3, 3/2, 1/4, 7): a share split. Vendors also
    book spin-offs as "splits" with ratios like 1.324 (T, 2022), which would
    fake an EPS change."""
    if not ratio or not np.isfinite(ratio) or ratio <= 0:
        return False
    return any(abs(x * k - round(x * k)) < 0.005 for x in (ratio, 1 / ratio) for k in range(1, 11))


def split_adjusted(rows: pd.DataFrame, splits: dict[str, pd.DataFrame] | None) -> pd.DataFrame:
    """Per-share `value`s divided by the ratio of every share split of their
    ticker executed after their `available_date` (a filing already reports in
    the share basis of its day): all on the basis after the last split."""
    parts = [s[["execution_date", "ratio"]].assign(ticker=t) for t, s in (splits or {}).items()
             if s is not None and len(s)]
    if not parts or rows.empty:
        return rows
    s = pd.concat(parts, ignore_index=True)
    s = s[s["ratio"].astype(float).map(is_share_split)]
    s = _ns(s, ["execution_date"]).sort_values(["ticker", "execution_date"], ascending=[True, False])
    s["after"] = s.groupby("ticker")["ratio"].cumprod()  # this split and every later one
    left = rows.assign(row=np.arange(len(rows))).sort_values("available_date")
    m = pd.merge_asof(left, s[["ticker", "execution_date", "after"]].sort_values("execution_date"),
                      left_on="available_date", right_on="execution_date", by="ticker", direction="forward",
                      allow_exact_matches=False).sort_values("row")
    return rows.assign(value=rows["value"].to_numpy() / m["after"].fillna(1.0).to_numpy())


def _quarters(fundamentals: pd.DataFrame) -> pd.DataFrame:
    """One row per (ticker, quarter end) with net income and revenue, their
    availability and revenue's tag; sorted by ticker, period_end."""
    q = fundamentals[fundamentals["period_type"] == "quarter"]
    cols = ["ticker", "period_end", "value", "available_date", "tag"]
    out = None
    for short, concept in (("ni", "net_income"), ("rev", "revenue")):
        part = _in_order(q.loc[q["concept"] == concept, cols]).rename(
            columns={"value": short, "available_date": f"{short}_at", "tag": f"{short}_tag"})
        out = part if out is None else out.merge(part, on=["ticker", "period_end"], how="outer")
    return out.sort_values(["ticker", "period_end"], ignore_index=True)


def eps_quarters(fundamentals: pd.DataFrame, splits: dict[str, pd.DataFrame] | None,
                 net_income: pd.DataFrame) -> pd.DataFrame:
    """Diluted EPS per (ticker, quarter end), its own series (eps, eps_at),
    sorted by ticker, period_end:
    - |EPS| outside EPS_PLAUSIBLE dropped (XBRL scale errors), then put on one
      share basis (`split_adjusted`);
    - a missing fourth quarter derived as the fiscal year's EPS minus the
      three quarters before it (10-Ks rarely tag Q4 EPS, and per-share values
      don't subtract exactly -- share counts move -- so it's approximate);
    - an EPS whose implied share count (net income / EPS) is over
      SHARES_JUMP x off the median of the previous quarters' is dropped: a
      scale error inside the plausible range. Checked only when that quarter's
      net income was known by the EPS's own filing.
    `net_income`: `_quarters` output (ni, ni_at)."""
    cols = ["ticker", "period_end", "value", "available_date"]
    rows = fundamentals.loc[fundamentals["concept"] == "eps_diluted", [*cols, "period_type"]]
    size = rows["value"].abs()
    rows = split_adjusted(rows[(size == 0) | size.between(*EPS_PLAUSIBLE)], splits)
    quarters, years = rows[rows["period_type"] == "quarter"][cols], rows[rows["period_type"] == "year"][cols]

    # Q4 = year - the three quarters inside it, where the year has no fourth quarter reported
    # only quarters filed by the year's own filing count, so a later report can't undo a derived Q4
    j = years.merge(quarters, on="ticker", suffixes=("", "_q"))
    j = j[j["available_date_q"] <= j["available_date"]]
    lag = (j["period_end"] - j["period_end_q"]).dt.days
    inside = j[lag.between(20, 350)].groupby(["ticker", "period_end"]).agg(
        n=("value_q", "size"), total=("value_q", "sum"), at=("available_date_q", "max"))
    q4 = years.set_index(["ticker", "period_end"]).join(inside, how="inner").query("n == 3").reset_index()
    has_q4 = j.loc[lag.abs() <= 10, ["ticker", "period_end"]].drop_duplicates().rename(
        columns={"period_end": "period_end_y"})
    q4 = q4.merge(has_q4, left_on=["ticker", "period_end"], right_on=["ticker", "period_end_y"], how="left")
    q4 = q4[q4["period_end_y"].isna()]
    derived = pd.DataFrame({"ticker": q4["ticker"], "period_end": q4["period_end"], "value": q4["value"] - q4["total"],
                            "available_date": q4[["available_date", "at"]].max(axis=1)})

    eps = _in_order(pd.concat([quarters, derived], ignore_index=True)).rename(
        columns={"value": "eps", "available_date": "eps_at"}).sort_values(["ticker", "period_end"], ignore_index=True)
    ni = eps.merge(net_income[["ticker", "period_end", "ni", "ni_at"]], on=["ticker", "period_end"], how="left")
    implied = (ni["ni"] / ni["eps"]).abs().where((ni["eps"] != 0) & (ni["ni_at"] <= ni["eps_at"]))
    ref = _rolling(implied.groupby(ni["ticker"]).shift(1), ni["ticker"], SUE_WINDOW, "median", 1)
    off = (implied / ref).where(ref > 0)
    keep = off.isna() | off.between(1 / SHARES_JUMP, SHARES_JUMP)
    return eps[keep.to_numpy()].reset_index(drop=True)


def _sue(q: pd.DataFrame, prev: pd.DataFrame, value: str) -> pd.DataFrame:
    """Events for the SUE of column `value` (`<value>_at` its availability)."""
    at = f"{value}_at"
    change = q[value] - prev[value]
    spread = _rolling(change.groupby(q["ticker"]).shift(1), q["ticker"], SUE_WINDOW, "std", SUE_MIN)
    # everything read: this quarter, its year-ago, and the window's quarters and year-agos;
    # an event exists only once the quarter's own value is known (a quarter with revenue
    # but no net income yet mustn't count as known from its inputs' dates)
    read_at = pd.concat([q[at], prev[at]], axis=1).max(axis=1)
    known_at = _rolling_max_dates(read_at, q["ticker"], SUE_WINDOW + 1).where(q[at].notna())
    return pd.DataFrame({"ticker": q["ticker"], "period_end": q["period_end"], "known_at": known_at,
                         "value": change / spread.where(spread > 0)})


def _rolling_max_dates(s: pd.Series, by: pd.Series, window: int) -> pd.Series:
    as_int = s.astype("int64").where(s.notna()).astype(float)
    return pd.to_datetime(_rolling(as_int, by, window, "max", 1))


def quarter_features(fundamentals: pd.DataFrame,
                     splits: dict[str, pd.DataFrame] | None = None) -> dict[str, pd.DataFrame]:
    """Per feature, its events: (ticker, period_end, known_at, value), one per
    quarter or balance-sheet date. `known_at` is the latest availability of
    every value the feature read. `splits`: ticker -> (execution_date, ratio),
    for EPS."""
    fundamentals = _ns(fundamentals, ["period_end", "available_date"])  # date arithmetic below assumes ns
    q = _quarters(fundamentals)
    events = {}
    eps = eps_quarters(fundamentals, splits, q)
    if len(eps):
        events["sue_eps"] = _sue(eps, _year_ago(eps, ["eps", "eps_at"]), "eps")
    if len(q):
        prev = _year_ago(q, ["ni", "ni_at", "rev", "rev_at", "rev_tag"])
        # SUE: the change vs a year earlier, scaled by the spread of the previous changes
        events["sue_net_income"] = _sue(q, prev, "ni")

        family = lambda tags: tags.map(lambda t: REVENUE_FAMILY.get(t, t), na_action="ignore")
        same_tag = q["rev_tag"].notna() & (family(q["rev_tag"]) == family(prev["rev_tag"]))
        growth = (q["rev"] / prev["rev"] - 1).where(same_tag & (q["rev"] > 0) & (prev["rev"] > 0))
        growth_at = pd.concat([q["rev_at"], prev["rev_at"]], axis=1).max(axis=1).where(q["rev_at"].notna())
        events["rev_growth_yoy"] = pd.DataFrame({"ticker": q["ticker"], "period_end": q["period_end"],
                                                 "known_at": growth_at, "value": growth})
        # acceleration: vs the previous quarter's growth (rows with revenue, consecutive quarters)
        has_rev = q["rev_at"].notna()
        g = pd.DataFrame({"ticker": q["ticker"], "period_end": q["period_end"], "growth": growth,
                          "at": growth_at})[has_rev]
        before = g.groupby("ticker")[["period_end", "growth", "at"]].shift(1)
        consecutive = (g["period_end"] - before["period_end"]).dt.days.between(*QUARTER_GAP)
        events["rev_growth_accel"] = pd.DataFrame({
            "ticker": g["ticker"], "period_end": g["period_end"],
            "known_at": pd.concat([g["at"], before["at"]], axis=1).max(axis=1),
            "value": (g["growth"] - before["growth"]).where(consecutive)})

        by = q["ticker"]
        both = q["ni"].notna() & q["rev"].notna()
        ni4 = _rolling(q["ni"].where(both), by, 4, "sum", 4)
        rev4 = _rolling(q["rev"].where(both), by, 4, "sum", 4)
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
    # ties on known_at: the newest period last, so the as-of merge takes it
    ev = ev[ev["period_end"] >= newest].sort_values(["known_at", "period_end"], kind="stable")
    left = rows[["ticker", "date"]].assign(row=np.arange(len(rows))).sort_values("date")
    m = pd.merge_asof(left, ev[["ticker", "known_at", "period_end", "value"]], left_on="date",
                      right_on="known_at", by="ticker", direction="backward").sort_values("row")
    fresh = (m["date"] - m["period_end"]).dt.days <= MAX_AGE_DAYS
    return pd.Series(m["value"].where(fresh).to_numpy(), index=rows.index)


def earnings_features(rows: pd.DataFrame, earnings: pd.DataFrame) -> pd.DataFrame:
    """`days_since_earnings` and `days_to_earnings_expected` for each (ticker,
    date) row. Both count business days (weekends out, holidays in), so a gap
    in a ticker's bars or a reaction before its first bar doesn't shift them."""
    out = pd.DataFrame(np.nan, index=rows.index, columns=["days_since_earnings", "days_to_earnings_expected"])
    # announcements in the order they happened; a late one for an old period is dropped
    ann = _in_order(earnings.dropna(subset=["reaction_date"]), known="reaction_date").reset_index(drop=True)
    if ann.empty:
        return out
    # the expected next reaction, known once this one has happened: the reaction
    # three announcements back (the next one's year-ago quarter) + 52 weeks
    back = ann.groupby("ticker")[["period_end", "reaction_date"]].shift(3)
    span = (ann["period_end"] - back["period_end"]).dt.days
    ann["expected_next"] = (back["reaction_date"] + EXPECTED_GAP).where(span.between(*FOUR_QUARTERS_SPAN))

    ev = ann.sort_values(["reaction_date", "period_end"], kind="stable")  # ties: the newest period last
    left = rows[["ticker", "date"]].assign(row=np.arange(len(rows))).sort_values("date", kind="stable")
    m = pd.merge_asof(left, ev[["ticker", "reaction_date", "expected_next"]], left_on="date",
                      right_on="reaction_date", by="ticker", direction="backward").sort_values("row")
    day = lambda s: s.to_numpy().astype("datetime64[D]")
    has = m["reaction_date"].notna().to_numpy()
    since = np.full(len(m), np.nan)
    since[has] = np.busday_count(day(m.loc[has, "reaction_date"]), day(m.loc[has, "date"]))
    since[since > MAX_DAYS_SINCE] = np.nan
    ok = m["expected_next"].notna().to_numpy() & ~np.isnan(since)
    to = np.full(len(m), np.nan)
    to[ok] = np.busday_count(day(m.loc[ok, "date"]), day(m.loc[ok, "expected_next"]))
    out["days_since_earnings"] = since
    out["days_to_earnings_expected"] = np.clip(to, 0, None)
    return out


CONCEPTS_READ = ("net_income", "revenue", "eps_diluted", "equity", "long_term_debt", "long_term_debt_noncurrent")


def load_tables(conn, tickers: list[str], end) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(fundamentals, earnings) rows for `tickers` that were known by `end`
    (`available_date` / `reaction_date` <= end): nothing past the holdout
    boundary is read. Dates parsed."""
    end = str(pd.Timestamp(end).date())
    marks = ", ".join("?" * len(tickers))
    concepts = ", ".join("?" * len(CONCEPTS_READ))
    fundamentals = pd.read_sql_query(
        f"SELECT ticker, concept, period_type, period_end, value, tag, available_date FROM fundamentals "
        f"WHERE ticker IN ({marks}) AND concept IN ({concepts}) "
        f"AND (period_type IN ('quarter', 'instant') OR (period_type = 'year' AND concept = 'eps_diluted')) "
        f"AND available_date <= ?",
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
        for col, events in quarter_features(ctx.fundamentals, ctx.splits).items():
            out[col] = _as_of(rows, events)
    out[list(COLUMNS)] = out[list(COLUMNS)].astype("float32")
    return out
