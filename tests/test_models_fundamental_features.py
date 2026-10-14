import numpy as np
import pandas as pd
import pytest

from src.foundation.data_processing import db
from src.models.features import fundamentals as F
from src.models.features.market import PanelContext

DAYS = pd.bdate_range("2019-01-01", "2021-06-30")
BARS = pd.DataFrame({"ticker": "AAA", "date": DAYS})
QUARTER_ENDS = pd.date_range("2019-03-31", "2021-03-31", freq="QE")


def _rows(concept, values, available, period_type="quarter", tag="Revenues", ends=QUARTER_ENDS):
    return pd.DataFrame({"ticker": "AAA", "concept": concept, "period_type": period_type,
                         "period_end": ends[:len(values)], "value": values, "tag": tag,
                         "available_date": pd.to_datetime(list(available)[:len(values)])})


def _at(out, day, col):
    """The value on the first bar on or after `day`."""
    return out.loc[out["date"] >= pd.Timestamp(day), col].iloc[0]


def _features(fundamentals=None, earnings=None):
    return F.panel_features(BARS, PanelContext(fundamentals=fundamentals, earnings=earnings))


AVAILABLE = [e + pd.Timedelta(days=40) for e in QUARTER_ENDS]


def test_revenue_growth_appears_on_its_filing_day_needs_the_same_tag_and_goes_stale():
    revenue = [100, 110, 120, 130, 120, 132, 150, 130, 999]
    rows = _rows("revenue", revenue, AVAILABLE)
    rows.loc[7, "tag"] = "SalesRevenueGoodsNet"  # Q4 2020 under a narrower tag: not comparable
    rows.loc[6, "tag"] = "SalesRevenueNet"  # another total-revenue tag: still comparable
    out = _features(rows)
    q1_2020_known = AVAILABLE[4]

    assert np.isnan(_at(out, q1_2020_known - pd.offsets.BDay(1), "rev_growth_yoy"))  # no year-ago before
    assert _at(out, q1_2020_known, "rev_growth_yoy") == pytest.approx(0.2)  # 120 / 100 - 1
    assert _at(out, AVAILABLE[6], "rev_growth_yoy") == pytest.approx(150 / 120 - 1)
    assert np.isnan(_at(out, AVAILABLE[7], "rev_growth_yoy"))  # the tag switch: newest quarter undefined
    # Q1 2021 is known from 2021-05-10 and goes stale MAX_AGE_DAYS (200) after 2021-03-31: 2021-10-17
    assert _at(out, "2021-06-30", "rev_growth_yoy") == pytest.approx(999 / 120 - 1)
    late = F.panel_features(pd.DataFrame({"ticker": "AAA", "date": pd.bdate_range("2021-10-11", "2021-10-29")}),
                            PanelContext(fundamentals=rows)).set_index("date")["rev_growth_yoy"]
    assert late.loc[:"2021-10-15"].notna().all() and late.loc["2021-10-18":].isna().all()


def test_a_late_report_of_an_old_quarter_changes_nothing():
    rows = _rows("revenue", [100, 110, 120, 130, 120, 132], AVAILABLE)
    late = _rows("revenue", [5], ["2020-09-01"], ends=pd.DatetimeIndex(["2018-12-31"]))
    before, after = _features(rows), _features(pd.concat([rows, late], ignore_index=True))
    pd.testing.assert_frame_equal(before, after)


def test_sue_scales_the_year_over_year_change_by_the_spread_of_earlier_changes():
    ends = pd.date_range("2017-03-31", "2020-12-31", freq="QE")
    income = [10, 11, 12, 13, 11, 13, 12, 16, 13, 12, 15, 15, 14, 20, 14, 30]
    available = [e + pd.Timedelta(days=35) for e in ends]
    out = _features(_rows("net_income", income, available, tag="NetIncomeLoss", ends=ends))
    changes = pd.Series(income).diff(4)
    expected = changes.iloc[15] / changes.iloc[7:15].std()  # the previous 8 changes
    assert _at(out, available[15], "sue_net_income") == pytest.approx(expected, rel=1e-5)
    # three earlier changes only (fewer than SUE_MIN = 4): undefined
    assert np.isnan(_at(out, available[6] + pd.offsets.BDay(1), "sue_net_income"))


def test_eps_surprise_sees_through_a_split_and_drops_scale_errors():
    ends = pd.date_range("2017-03-31", "2020-12-31", freq="QE")
    eps = np.array([1.0, 1.1, 1.2, 1.3, 1.1, 1.3, 1.2, 1.6, 1.3, 1.2, 1.5, 1.5, 1.4, 2.0, 1.4, 3.0])
    available = pd.DatetimeIndex([e + pd.Timedelta(days=35) for e in ends])
    split = pd.Timestamp("2019-08-15")  # a 4-for-1 split: filings after it report a quarter of the EPS
    as_filed = np.where(available > split, eps / 4, eps)
    rows = _rows("eps_diluted", as_filed, available, tag="EarningsPerShareDiluted", ends=ends)
    splits = {"AAA": pd.DataFrame({"execution_date": [split], "ratio": [4.0]})}
    out = F.panel_features(BARS, PanelContext(fundamentals=rows, splits=splits))
    plain = _features(_rows("eps_diluted", eps, available, tag="EarningsPerShareDiluted", ends=ends))
    pd.testing.assert_series_equal(out["sue_eps"], plain["sue_eps"], rtol=1e-5)
    assert out["sue_eps"].notna().any()

    income = _rows("net_income", eps * 10, available, tag="NetIncomeLoss", ends=ends)
    for bad in (3.0e-9, as_filed[15] / 1000):  # out of range, and a /1000 slip inside it
        broken = rows.copy()
        broken.loc[15, "value"] = bad
        out = F.panel_features(BARS, PanelContext(fundamentals=pd.concat([broken, income]), splits=splits))
        # dropped, not a huge surprise: the previous quarter's value stays
        assert _at(out, available[15], "sue_eps") == _at(out, available[14], "sue_eps")

    # through the registry: the splits it's given reach the panel source
    from src.models.features import baseline, registry
    specs = tuple(registry.model_specs(group="fundamentals"))
    via = registry.compute_registered({baseline.FEATURE_BASIS: BARS}, splits, specs, rank=False,
                                      context=PanelContext(fundamentals=rows))
    np.testing.assert_allclose(via["sue_eps"], plain["sue_eps"], rtol=1e-5)


def test_fourth_quarter_eps_is_derived_from_the_year_and_spin_offs_are_not_splits():
    ends = pd.date_range("2019-03-31", "2020-12-31", freq="QE")
    available = pd.DatetimeIndex([e + pd.Timedelta(days=35) for e in ends])
    quarters = _rows("eps_diluted", [1, 1, 1, 1, 2, 2, 2], available, tag="EarningsPerShareDiluted", ends=ends)
    quarters = quarters.drop(index=3)  # Q4 2019 not tagged
    year = _rows("eps_diluted", [4.5], [available[3]], period_type="year", tag="EarningsPerShareDiluted",
                 ends=ends[3:4])
    eps = F.eps_quarters(pd.concat([quarters, year], ignore_index=True), None,
                         pd.DataFrame(columns=["ticker", "period_end", "ni", "ni_at"]))
    q4 = eps[eps["period_end"] == ends[3]]
    assert q4[["eps", "eps_at"]].values.tolist() == [[1.5, available[3]]]  # 4.5 - 3 x 1
    # a quarter filed after the year (here a late Q4 report) doesn't undo the derived one
    late = _rows("eps_diluted", [9.0], [available[6]], tag="EarningsPerShareDiluted", ends=ends[3:4])
    again = F.eps_quarters(pd.concat([quarters, year, late], ignore_index=True), None,
                           pd.DataFrame(columns=["ticker", "period_end", "ni", "ni_at"]))
    pd.testing.assert_frame_equal(again, eps)

    assert all(map(F.is_share_split, (2.0, 4.0, 0.25, 1.5, 7.0, 1 / 3)))
    assert not any(map(F.is_share_split, (1.324, 0.0, -2.0)))


def test_revenue_acceleration_needs_consecutive_quarters():
    rows = _rows("revenue", [100, 100, 100, 100, 110, 120, 125, 125], AVAILABLE).drop(index=6)
    out = _features(rows)
    assert np.isnan(_at(out, AVAILABLE[7], "rev_growth_accel"))  # Q3 2020 missing: no previous quarter


def test_revenue_acceleration_is_the_change_in_year_over_year_growth():
    rows = _rows("revenue", [100, 100, 100, 100, 110, 120, 125, 125], AVAILABLE)
    out = _features(rows)
    assert np.isnan(_at(out, AVAILABLE[4], "rev_growth_accel"))  # no growth for the quarter before
    assert _at(out, AVAILABLE[5], "rev_growth_accel") == pytest.approx(0.2 - 0.1)
    assert _at(out, AVAILABLE[7], "rev_growth_accel") == pytest.approx(0.0)


def test_net_margin_needs_four_quarters_and_debt_to_equity_needs_positive_equity():
    revenue = _rows("revenue", [100, 100, 100, 100, 100], AVAILABLE)
    income = _rows("net_income", [10, 20, 30, 40, 50], AVAILABLE, tag="NetIncomeLoss")
    ends = QUARTER_ENDS[:3]
    equity = _rows("equity", [200, -5, 400], AVAILABLE[:3], period_type="instant", ends=ends)
    debt_nc = _rows("long_term_debt_noncurrent", [100, 100, 100], AVAILABLE[:3], period_type="instant", ends=ends)
    debt = _rows("long_term_debt", [300], AVAILABLE[2:3], period_type="instant", ends=ends[2:3])
    out = _features(pd.concat([revenue, income, equity, debt_nc, debt], ignore_index=True))

    assert np.isnan(_at(out, AVAILABLE[2], "net_margin_ttm"))
    assert _at(out, AVAILABLE[3], "net_margin_ttm") == pytest.approx(0.25)  # 100 / 400
    assert _at(out, AVAILABLE[4], "net_margin_ttm") == pytest.approx(0.35)  # 140 / 400
    assert _at(out, AVAILABLE[0], "debt_to_equity") == pytest.approx(0.5)  # noncurrent, no total tagged
    assert np.isnan(_at(out, AVAILABLE[1], "debt_to_equity"))  # negative equity
    assert _at(out, AVAILABLE[2], "debt_to_equity") == pytest.approx(0.75)  # the total wins over noncurrent


def test_earnings_timing_uses_past_reactions_only():
    reactions = pd.to_datetime(["2019-04-25", "2019-07-25", "2019-10-24", "2020-01-30", "2020-04-30"])
    earnings = pd.DataFrame({"ticker": "AAA", "period_end": QUARTER_ENDS[:5], "reaction_date": reactions})
    out = _features(earnings=earnings)

    assert np.isnan(_at(out, "2019-04-24", "days_since_earnings"))
    assert _at(out, "2019-04-25", "days_since_earnings") == 0
    assert _at(out, "2019-05-02", "days_since_earnings") == 5
    # the 4th announcement (2020-01-30) expects the next a year after the 1st: 2019-04-25 + 52 weeks
    expected = pd.Timestamp("2019-04-25") + pd.Timedelta(weeks=52)
    assert np.isnan(_at(out, "2020-01-29", "days_to_earnings_expected"))  # only three known before
    assert _at(out, "2020-01-30", "days_to_earnings_expected") == np.busday_count("2020-01-30", expected.date())
    assert _at(out, "2020-04-29", "days_to_earnings_expected") == 0  # overdue: the realized date isn't used
    assert out["days_to_earnings_expected"].min() >= 0


def test_earnings_ignore_a_late_announcement_and_count_from_before_the_first_bar():
    reactions = pd.to_datetime(["2018-10-25", "2019-01-30", "2019-04-25", "2019-07-25", "2019-10-24"])
    ends = pd.date_range("2018-09-30", "2019-09-30", freq="QE")
    earnings = pd.DataFrame({"ticker": "AAA", "period_end": ends, "reaction_date": reactions})
    late = pd.DataFrame({"ticker": ["AAA"], "period_end": [pd.Timestamp("2018-06-30")],
                         "reaction_date": [pd.Timestamp("2019-08-01")]})
    bars = pd.DataFrame({"ticker": "AAA", "date": pd.bdate_range("2018-11-01", "2019-12-31")})
    before = F.panel_features(bars, PanelContext(earnings=earnings))
    after = F.panel_features(bars, PanelContext(earnings=pd.concat([earnings, late], ignore_index=True)))

    pd.testing.assert_frame_equal(before, after)
    assert _at(before, "2018-11-01", "days_since_earnings") == 5  # the reaction predates the first bar


def test_the_gate_catches_a_value_used_from_its_quarter_end(monkeypatch):
    from src.models import gates

    bars, splits, cut, context = gates.synthetic_leakage_inputs()
    f = context.fundamentals
    assert ((f["period_end"] <= cut) & (f["available_date"] > cut)).any()  # filings straddle the cut
    real = F.quarter_features
    monkeypatch.setattr(F, "quarter_features",
                        lambda fundamentals, splits=None: {k: v.assign(known_at=v["period_end"])
                                                           for k, v in real(fundamentals, splits).items()})
    result = gates.leakage_gate(bars, splits, cut, context=context)
    assert result["leaks"]["future_filings"]


def test_no_tables_gives_nan_columns():
    out = _features()
    assert list(out.columns) == ["ticker", "date", *F.COLUMNS]
    assert out[list(F.COLUMNS)].isna().all().all()


def test_load_tables_reads_nothing_known_after_end():
    conn = db.get_connection(":memory:")
    db.create_tables(conn)
    for day in ("2021-12-30", "2022-01-03"):
        conn.execute("INSERT INTO fundamentals VALUES ('AAA', 'revenue', 'quarter', '2021-09-30', NULL, 1.0, 'Revenues', "
                     "0, 'a', '10-Q', ?, '2021-12-30T21:00:00+00:00', ?, 1, 'sec_ticker_file', 1)", (day, day))
        conn.execute("INSERT INTO earnings_announcements VALUES ('AAA', ?, 1, 'sec_ticker_file', 1, '10-Q', "
                     "'2021-11-01', 'a', '8-K', '2021-10-28T20:00:00+00:00', 'after_close', ?, 0)",
                     ("2021-09-30" if day < "2022" else "2021-12-31", day))
        conn.execute("UPDATE fundamentals SET period_end = '2021-06-30' WHERE available_date = '2021-12-30'")
    fundamentals, earnings = F.load_tables(conn, ["AAA"], "2021-12-31")
    assert fundamentals["available_date"].tolist() == [pd.Timestamp("2021-12-30")]
    assert earnings["reaction_date"].tolist() == [pd.Timestamp("2021-12-30")]
