import numpy as np
import pandas as pd
import pytest

from src.foundation.market_common.models import Timeframe
from src.ui.chart import app as app_mod
from src.ui.chart import earnings
from src.ui.chart.config import ChartConfig, ChartType
from src.ui.chart.figure import build_figure, earnings_annotations, earnings_bar


@pytest.fixture
def daily():
    idx = pd.bdate_range("2024-01-01", periods=400)  # to mid-2025
    close = 100 + np.arange(400, dtype=float)
    return pd.DataFrame({"open": close - 0.5, "high": close + 1, "low": close - 1, "close": close,
                         "volume": 1.0}, index=idx)


def _announcements(rows):
    """rows: (period_end, report_form, reaction_date)."""
    return pd.DataFrame([{"ticker": "ABC", "period_end": p, "report_form": form, "accepted_at": "2024-05-01T20:30:00+00:00",
                          "timing": "after_close", "reaction_date": r} for p, form, r in rows])


def _fundamentals(rows):
    """rows: (concept, period_end, value, tag, filed)."""
    return pd.DataFrame([{"concept": c, "period_type": "quarter", "period_end": p, "value": v, "tag": t, "filed": f}
                         for c, p, v, t, f in rows])


NO_SPLITS = pd.DataFrame(columns=["execution_date", "ratio"])


def test_fiscal_labels_from_the_10k_quarters():
    ann = _announcements([("2025-01-26", "10-K", None), ("2025-04-27", "10-Q", None), ("2025-07-27", "10-Q", None),
                          ("2025-10-26", "10-Q", None), ("2026-01-25", "10-K", None), ("2026-04-26", "10-Q", None)])
    labels = earnings.fiscal_labels(ann)
    assert labels[pd.Timestamp("2025-01-26")] == "Q4 FY2025"
    assert labels[pd.Timestamp("2025-07-27")] == "Q2 FY2026"  # named by the year the fiscal year ends in
    assert labels[pd.Timestamp("2026-04-26")] == "Q1 FY2027"  # past the last 10-K
    assert earnings.fiscal_labels(_announcements([("2025-04-27", "10-Q", None)])) == {}


def test_reaction_gap_and_day_move_in_percent_and_atr(daily):
    atr = pd.Series(2.0, index=daily.index)
    day = daily.index[100]
    bar_date, gap_pct, gap_atr, move_pct, move_atr = earnings.reaction(daily, atr, day)
    prev_close = daily["close"].iloc[99]
    assert bar_date == day
    assert gap_pct == pytest.approx((daily["open"].iloc[100] / prev_close - 1) * 100)
    assert gap_atr == pytest.approx(0.25)  # open is +0.5 over the previous close, ATR 2
    assert move_pct == pytest.approx(1 / prev_close * 100) and move_atr == pytest.approx(0.5)
    # a weekend reaction date lands on the next session; nothing before the first bar or after the last
    saturday = pd.Timestamp("2024-05-04")
    assert earnings.reaction(daily, atr, saturday)[0] == pd.Timestamp("2024-05-06")
    assert earnings.reaction(daily, atr, daily.index[0]) is None
    assert earnings.reaction(daily, atr, daily.index[-1] + pd.Timedelta(days=1)) is None
    assert earnings.reaction(daily, atr.where(atr.index > day), day)[2] is None  # no ATR yet: no ATR figure


def test_cards_compare_with_the_same_quarter_a_year_earlier(daily):
    ann = _announcements([("2024-03-31", "10-Q", "2024-05-02"), ("2024-12-31", "10-K", "2025-02-04"),
                          ("2025-03-31", "10-Q", "2025-05-01")])
    fund = _fundamentals([
        ("revenue", "2024-03-31", 100.0, "Revenues", "2024-05-01"),
        ("revenue", "2025-03-31", 120.0, "RevenueFromContractWithCustomerExcludingAssessedTax", "2025-04-30"),
        ("eps_diluted", "2024-03-31", 10.0, "EarningsPerShareDiluted", "2024-05-01"),
        ("eps_diluted", "2025-03-31", 1.5, "EarningsPerShareDiluted", "2025-04-30"),
        ("revenue", "2024-12-31", 90.0, "Revenues", "2025-02-03"),
    ])
    splits = pd.DataFrame({"execution_date": [pd.Timestamp("2024-06-10")], "ratio": [10.0]})
    cards = earnings.build_cards(ann, fund, splits, daily)
    assert [c.reaction_date for c in cards] == [pd.Timestamp("2024-05-02"), pd.Timestamp("2025-02-04"),
                                                pd.Timestamp("2025-05-01")]
    latest = cards[-1]
    assert latest.revenue == 120.0 and latest.revenue_year_ago == 100.0  # both total revenue: comparable
    assert latest.eps_year_ago == pytest.approx(1.0)  # filed before the 10:1 split: put on today's basis
    assert "+20.0% vs year-ago" in earnings.card_text(latest)
    assert "1.50, +50.0% vs year-ago" in earnings.card_text(latest)
    assert "guidance: not yet extracted" in earnings.card_text(latest)
    q4 = cards[1]
    assert q4.label == "Q4 FY2024" and q4.eps is None
    assert "the 10-K reports the year only" in earnings.card_text(q4)
    assert cards[0].revenue_year_ago is None and "no year-ago quarter" in earnings.card_text(cards[0])


def test_revenue_measured_differently_a_year_earlier_is_not_compared(daily):
    ann = _announcements([("2025-03-31", "10-Q", "2025-05-01")])
    fund = _fundamentals([("revenue", "2024-03-31", 100.0, "SalesOfGoods", "2024-05-01"),
                          ("revenue", "2025-03-31", 120.0, "Revenues", "2025-04-30")])
    (card,) = earnings.build_cards(ann, fund, NO_SPLITS, daily)
    assert card.revenue == 120.0 and card.revenue_year_ago is None


def test_change_text():
    assert earnings.change_text(None, 1.0, str) == "n/a"
    assert earnings.change_text(-0.5, -1.0, lambda v: f"{v:.2f}") == "-0.50, vs -1.00 year-ago"  # no % off a loss
    assert earnings.money(96_221_000_000) == "96.2B" and earnings.money(512_000) == "512.0K"


def _card(reaction_date, move_pct=1.0, key="2024-03-31"):
    return earnings.EarningsCard(
        period_end=pd.Timestamp(key), label="Q1 FY2024", report_form="10-Q",
        accepted_at="2024-05-01T20:30:00+00:00", timing="after_close", reaction_date=pd.Timestamp(reaction_date),
        revenue=None, revenue_year_ago=None, eps=None, eps_year_ago=None,
        gap_pct=0.5, gap_atr=0.2, move_pct=move_pct, move_atr=0.4)


def test_marker_lands_on_the_reaction_bar(daily):
    card = _card(daily.index[100])
    assert earnings_bar(daily, card) == daily.index[100]
    weekly = daily[daily.index.dayofweek == 0]  # labelled by Monday, like the chart's weekly bars
    wednesday = pd.Timestamp("2024-05-08")
    assert earnings_bar(weekly, _card(wednesday)) == pd.Timestamp("2024-05-06")
    # in the week still in progress (not on the weekly chart): no marker
    assert earnings_bar(weekly.iloc[:-1], _card(weekly.index[-1] + pd.Timedelta(days=2))) is None


def test_flags_and_cards_point_at_the_high_or_the_low(daily):
    up, down = _card(daily.index[50], 2.0, "2024-01-31"), _card(daily.index[120], -2.0, "2024-04-30")
    flag_up, card_down = earnings_annotations(daily, [up, down], expanded={"2024-04-30"})
    assert flag_up["text"] == "E" and flag_up["y"] == daily["high"].iloc[50] and flag_up["ay"] < 0
    assert card_down["y"] == daily["low"].iloc[120] and card_down["ay"] > 0
    assert card_down["text"].startswith("<b>Q1 FY2024</b>") and card_down["name"] == "2024-04-30"
    assert flag_up["captureevents"] and "after the close" in flag_up["hovertext"]
    fig = build_figure(daily, "ABC", Timeframe.DAILY, ChartType.CANDLES, {}, (), earnings=(up, down))
    assert [a.text for a in fig.layout.annotations] == ["E", "E"]


def test_latest_card_open_by_default_and_clicks_toggle():
    cards = (_card("2024-05-02", key="2024-03-31"), _card("2024-08-01", key="2024-06-30"))
    assert app_mod.open_cards(cards, "ABC", None) == {"2024-06-30"}
    assert app_mod.open_cards(cards, "ABC", None, expand_all=True) == {"2024-03-31", "2024-06-30"}
    assert app_mod.open_cards((), "ABC", None) == frozenset()
    opened = app_mod.toggle_card(cards, "ABC", None, "2024-03-31")
    assert opened == {"ticker": "ABC", "open": ["2024-03-31", "2024-06-30"]}
    opened = app_mod.toggle_card(cards, "ABC", opened, "2024-06-30")  # clicking an open card closes it
    assert app_mod.open_cards(cards, "ABC", opened) == {"2024-03-31"}
    assert app_mod.open_cards(cards, "XYZ", opened) == {"2024-06-30"}  # another ticker's clicks don't carry over
    assert app_mod.clicked_card({"index": 0, "annotation": {"name": "2024-03-31"}}) == "2024-03-31"
    assert app_mod.clicked_card(None) is None and app_mod.clicked_card({"annotation": {}}) is None


class _Data(app_mod.ChartData):
    def __init__(self, frame, cards, note=None):
        super().__init__(None, None)
        self._frame, self._cards, self._note = frame, cards, note

    def _bars(self, ticker, timeframe):
        return self._frame if ticker in ("ABC", "SPY") else self._frame.iloc[0:0]

    def _earnings(self, ticker):
        return self._cards, self._note


def test_render_draws_earnings_only_when_shown(daily):
    cards = (_card(daily.index[-30], key="2024-09-30"),)
    data = _Data(daily, cards)
    args = (data, ChartConfig(), "ABC", Timeframe.DAILY, ChartType.CANDLES, [], True, None, ())
    shown, _ = app_mod.render(*args, ["show"], None)
    assert [a.name for a in shown.layout.annotations] == ["2024-09-30"]
    assert shown.layout.annotations[0].text.startswith("<b>")  # the only card is the latest: open
    hidden, _ = app_mod.render(*args, [], None)
    assert not hidden.layout.annotations
    _, message = app_mod.render(_Data(daily, (), "earnings failed: ValueError: x"), *args[1:], ["show"], None)
    assert message.endswith("earnings failed: ValueError: x")
