import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.models.features import valuation as V
from src.models.features.market import PanelContext

DAYS = pd.bdate_range("2020-01-01", "2021-06-30")
QUARTER_ENDS = pd.date_range("2019-03-31", "2021-03-31", freq="QE")
AVAILABLE = [e + pd.Timedelta(days=40) for e in QUARTER_ENDS]


def _bars(close=10.0, days=DAYS):
    return pd.DataFrame({"ticker": "AAA", "date": days, "close": close})


def _filings(concept, values, period_type="quarter", ends=QUARTER_ENDS, available=AVAILABLE):
    return pd.DataFrame({"ticker": "AAA", "concept": concept, "period_type": period_type,
                         "period_end": ends[:len(values)], "value": values, "tag": "Revenues",
                         "available_date": pd.to_datetime(list(available)[:len(values)])})


def _shares(dates, counts):
    return pd.DataFrame({"ticker": "AAA", "date": pd.to_datetime(dates), "shares_outstanding": counts})


def _at(out, day, col):
    """The value on the first bar on or after `day`."""
    return out.loc[out["date"] >= pd.Timestamp(day), col].iloc[0]


def _features(bars, fundamentals, shares, splits=None):
    return V.panel_features(bars, PanelContext(fundamentals=fundamentals, shares=shares, splits=splits or {}))


INCOME = _filings("net_income", [1, 2, 3, 4, 5, 6, 7, 8, -40])
REVENUE = _filings("revenue", [10] * 9)


def test_yields_divide_trailing_four_quarters_by_the_market_cap():
    equity = _filings("equity", [500, 500, 500, 500, 500, -1], period_type="instant")
    shares = _shares(["2019-11-15", "2020-11-16"], [100.0, 100.0])  # cap: 10 x 100 = 1,000
    out = _features(_bars(), pd.concat([INCOME, REVENUE, equity], ignore_index=True), shares)

    assert _at(out, AVAILABLE[4], "earnings_yield") == pytest.approx((2 + 3 + 4 + 5) / 1000)
    assert _at(out, AVAILABLE[4], "sales_yield") == pytest.approx(40 / 1000)
    assert _at(out, AVAILABLE[4], "book_to_market") == pytest.approx(0.5)
    assert np.isnan(_at(out, AVAILABLE[5], "book_to_market"))  # negative equity
    # a loss year: a negative yield, not a dropped row
    assert _at(out, AVAILABLE[8], "earnings_yield") == pytest.approx((6 + 7 + 8 - 40) / 1000)


def test_a_share_count_counts_from_the_next_session_and_goes_stale():
    shares = _shares(["2020-03-02", "2020-06-01"], [100.0, 200.0])
    out = _features(_bars(), pd.concat([INCOME, REVENUE], ignore_index=True), shares).set_index("date")
    ey = out["earnings_yield"]
    assert np.isnan(ey.loc["2020-03-02"])  # filed that day, perhaps after the close
    assert ey.loc["2020-03-03"] == pytest.approx(10 / 1000)  # TTM of Q1-Q4 2019 = 1 + 2 + 3 + 4
    assert ey.loc["2020-06-01"] == pytest.approx(14 / 1000)  # the old count still; Q1 2020 is in the TTM
    assert ey.loc["2020-06-02"] == pytest.approx(14 / 2000)
    # 200 days after 2020-06-01 is 2020-12-18
    assert ey.loc["2020-12-18"] == ey.loc["2020-12-18"] and np.isnan(ey.loc["2020-12-21"])


def test_the_cap_is_the_traded_price_across_a_split_and_its_filing_lag():
    # a 2-for-1 on 2020-06-01: traded 20 before and 10 after, so the
    # split-adjusted close is 10 throughout; 100 shares become 200, but the
    # first filing after the split still reports 100
    shares = _shares(["2020-01-02", "2020-06-15", "2020-09-01"], [100.0, 100.0, 202.0])
    splits = {"AAA": pd.DataFrame({"execution_date": [pd.Timestamp("2020-06-01")], "ratio": [2.0]})}
    out = _features(_bars(), pd.concat([INCOME, REVENUE], ignore_index=True), shares, splits).set_index("date")
    sy = out["sales_yield"]
    assert sy.loc["2020-05-29"] == pytest.approx(40 / 2000)  # 20 x 100
    assert sy.loc["2020-06-01"] == pytest.approx(40 / 2000)  # 10 x 100, the pre-split count x 2
    assert sy.loc["2020-06-16"] == pytest.approx(40 / 2000)  # the stale filing, bridged
    assert sy.loc["2020-09-02"] == pytest.approx(40 / 2020)


def test_no_shares_or_filings_gives_nan_columns():
    out = _features(_bars(), INCOME, None)
    assert list(out.columns) == ["ticker", "date", *V.COLUMNS]
    assert out[list(V.COLUMNS)].isna().all().all()


def test_the_gate_catches_an_adjusted_price_level(monkeypatch):
    from src.models import gates

    bars, splits, cut, context = gates.synthetic_leakage_inputs()
    real = V._shares_known  # the count left as filed: the cap is the adjusted close x it
    monkeypatch.setattr(V, "_shares_known", lambda s, sp: real(s, sp).assign(basis=1.0))
    result = gates.leakage_gate(bars, splits, cut, context=context)
    assert "earnings_yield" in result["leaks"]["future_split"]


def test_the_gate_catches_a_share_count_used_on_its_filing_day(monkeypatch):
    from src.models import gates

    bars, splits, cut, context = gates.synthetic_leakage_inputs()
    shares = context.shares.copy()
    shares.loc[shares.index[0], "date"] = cut  # one filing on the cut day itself
    real = V._shares_known
    monkeypatch.setattr(V, "_shares_known", lambda s, sp: real(s, sp).assign(known_at=lambda f: f["dated"]))
    from dataclasses import replace
    result = gates.leakage_gate(bars, splits, cut, context=replace(context, shares=shares))
    assert result["leaks"]["future_filings"]


def test_load_shares_reads_nothing_after_end():
    conn = db.get_connection(":memory:")
    db.create_tables(conn)
    for day, n in (("2021-12-30", 1e6), ("2022-01-03", 2e6)):
        conn.execute("INSERT INTO shares_outstanding VALUES ('AAA', ?, ?, ?)", (day, n, db.SEC_EDGAR))
    out = V.load_shares(conn, ["AAA"], "2021-12-31", {})
    assert out["date"].tolist() == [pd.Timestamp("2021-12-30")]


def test_load_shares_uses_yfinance_only_where_sec_is_stale():
    conn = db.get_connection(":memory:")
    db.create_tables(conn)
    rows = [("2010-01-04", db.SEC_EDGAR), ("2010-03-01", db.YFINANCE),  # SEC fresh: not used
            ("2011-01-03", db.YFINANCE),  # 364 days after SEC's last: used
            ("2011-02-01", db.SEC_EDGAR), ("2011-05-02", db.YFINANCE)]  # SEC again: not used
    for day, source in rows:
        conn.execute("INSERT INTO shares_outstanding VALUES ('AAA', ?, 1e6, ?)", (day, source))
    out = V.load_shares(conn, ["AAA"], "2021-12-31", {})
    assert out["date"].dt.strftime("%Y-%m-%d").tolist() == ["2010-01-04", "2011-01-03", "2011-02-01"]
