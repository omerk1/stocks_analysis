"""Earnings announcements + reported financials -> earnings cards
(`docs/features/chart_ui_design.md`, "Earnings on the chart", step 3).

One card per row of `earnings_announcements`, on its `reaction_date` (the first
session whose bar can reflect it). It shows:

- the fiscal period ("Q2 FY2027"), read off the announcements themselves: the
  quarters reported in a 10-K end the fiscal years, and a fiscal year is named
  by the calendar year it ends in. Without a 10-K near enough, only the
  quarter's end date.
- revenue and diluted EPS for the quarter from `fundamentals` (first-reported
  values), each against the same quarter a year earlier. There's no analyst
  consensus, so it's "vs year-ago", never a beat or miss. Revenue is compared
  only when both quarters use the same measure (`REVENUE_FAMILY`, as the
  revenue-growth feature). EPS is as filed, so it's put on today's share basis
  (divided by the ratios of the splits executed after its filing) before the
  comparison, like the split-adjusted bars it's drawn on. A fourth quarter has
  no EPS: the 10-K reports the year, and EPS doesn't add up across quarters.
- the reaction on daily bars: the gap at the open and the day's close-to-close
  move vs the previous close, in % and in ATR (the ATR as of the previous bar,
  known before the news).

Guidance isn't extracted yet (`docs/fundamentals/plan.md` step 5); the card says so.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.foundation.data_processing import db, market_cap
from src.foundation.market_common import indicators
from src.models.features.fundamentals import REVENUE_FAMILY, YEAR_AGO_DAYS, YEAR_AGO_TOLERANCE

QUARTER_DAYS = 91.31  # 365.25 / 4
FISCAL_YEAR_MAX_DAYS = 380  # a quarter's fiscal year ends within this many days after it
TIMING_TEXT = {"before_open": "before the open", "after_close": "after the close",
               "during_session": "during the session", "non_session_day": "on a non-trading day"}


@dataclass(frozen=True)
class EarningsCard:
    period_end: pd.Timestamp
    label: str  # "Q2 FY2027", or "quarter ended 2026-07-26"
    report_form: str
    accepted_at: str  # UTC, as stored
    timing: str
    reaction_date: pd.Timestamp  # the daily bar the reaction is measured on
    revenue: float | None
    revenue_year_ago: float | None
    eps: float | None  # diluted, on today's share basis
    eps_year_ago: float | None
    gap_pct: float | None
    gap_atr: float | None
    move_pct: float | None
    move_atr: float | None

    @property
    def key(self) -> str:
        return self.period_end.strftime("%Y-%m-%d")

    @property
    def fell(self) -> bool:
        return self.move_pct is not None and self.move_pct < 0


def fiscal_labels(announcements: pd.DataFrame) -> dict[pd.Timestamp, str]:
    """period_end -> "Q<n> FY<year>". A quarter's fiscal year ends at the next
    quarter reported in a 10-K; past the last 10-K, a year after it."""
    ends = pd.to_datetime(announcements["period_end"])
    year_ends = pd.DatetimeIndex(sorted(ends[announcements["report_form"].str.startswith("10-K")]))
    labels = {}
    for p in ends:
        later = year_ends[(year_ends >= p) & (year_ends <= p + pd.Timedelta(days=FISCAL_YEAR_MAX_DAYS))]
        earlier = year_ends[(year_ends < p) & (year_ends >= p - pd.Timedelta(days=FISCAL_YEAR_MAX_DAYS))]
        if len(later):
            year, quarter = later[0].year, 4 - round((later[0] - p).days / QUARTER_DAYS)
        elif len(earlier):
            year, quarter = earlier[-1].year + 1, round((p - earlier[-1]).days / QUARTER_DAYS)
        else:
            continue
        if 1 <= quarter <= 4:
            labels[p] = f"Q{quarter} FY{year}"
    return labels


def _year_ago(values: pd.DataFrame, period_end: pd.Timestamp) -> pd.Series | None:
    """The row whose quarter ended about a year before `period_end`, or None."""
    target = period_end - pd.Timedelta(days=YEAR_AGO_DAYS)
    near = values[(values["period_end"] - target).abs() <= pd.Timedelta(days=YEAR_AGO_TOLERANCE)]
    if near.empty:
        return None
    return near.loc[(near["period_end"] - target).abs().idxmin()]


def _value(row: pd.Series | None, column: str = "value") -> float | None:
    return None if row is None or pd.isna(row[column]) else float(row[column])


def quarter_values(fundamentals: pd.DataFrame, splits: pd.DataFrame | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(revenue, diluted EPS) quarters: period_end, value, and revenue's measure
    (`family`). EPS is put on today's share basis, by its filing date."""
    q = fundamentals[fundamentals["period_type"] == "quarter"].assign(
        period_end=lambda f: pd.to_datetime(f["period_end"]), filed=lambda f: pd.to_datetime(f["filed"]))
    revenue = q[q["concept"] == "revenue"].assign(family=lambda f: f["tag"].map(lambda t: REVENUE_FAMILY.get(t, t)))
    eps = q[q["concept"] == "eps_diluted"]
    eps = eps.assign(value=eps["value"].to_numpy() / market_cap.split_factor(pd.DatetimeIndex(eps["filed"]),
                                                                             splits).to_numpy())
    return revenue[["period_end", "value", "family"]], eps[["period_end", "value"]]


def reaction(daily: pd.DataFrame, atr: pd.Series, reaction_date: pd.Timestamp):
    """(bar date, gap %, gap ATR, move %, move ATR) on the first daily bar on or
    after `reaction_date`, the ATR (`atr`, aligned to `daily`) taken at the bar
    before; None when there's no such bar or no bar before it."""
    at = daily.index.searchsorted(reaction_date)
    if at >= len(daily) or at == 0:
        return None
    bar, prev_close = daily.iloc[at], float(daily["close"].iloc[at - 1])
    prev_atr = float(atr.iloc[at - 1])
    in_atr = lambda move: move / prev_atr if prev_atr > 0 else None  # NaN > 0 is False
    gap, move = float(bar["open"]) - prev_close, float(bar["close"]) - prev_close
    return (daily.index[at], gap / prev_close * 100, in_atr(gap), move / prev_close * 100, in_atr(move))


def build_cards(announcements: pd.DataFrame, fundamentals: pd.DataFrame, splits: pd.DataFrame | None,
                daily: pd.DataFrame, atr_period: int = 14) -> list[EarningsCard]:
    """One card per announcement with a reaction bar in `daily`, oldest first."""
    if announcements.empty or daily.empty:
        return []
    labels = fiscal_labels(announcements)
    revenue, eps = quarter_values(fundamentals, splits)
    atr = indicators.atr(daily, atr_period)
    cards = []
    for row in announcements.sort_values("period_end").itertuples():
        if not isinstance(row.reaction_date, str):
            continue
        measured = reaction(daily, atr, pd.Timestamp(row.reaction_date))
        if measured is None:
            continue
        p = pd.Timestamp(row.period_end)
        rev_now = revenue[revenue["period_end"] == p]
        rev_now = rev_now.iloc[0] if len(rev_now) else None
        rev_prev = _year_ago(revenue, p) if rev_now is not None else None
        if rev_prev is not None and rev_prev["family"] != rev_now["family"]:
            rev_prev = None  # a different measure a year earlier: not comparable
        eps_now = eps[eps["period_end"] == p]
        eps_now = eps_now.iloc[0] if len(eps_now) else None
        bar_date, gap_pct, gap_atr, move_pct, move_atr = measured
        cards.append(EarningsCard(
            period_end=p, label=labels.get(p, f"quarter ended {p:%Y-%m-%d}"), report_form=row.report_form,
            accepted_at=row.accepted_at, timing=row.timing, reaction_date=bar_date,
            revenue=_value(rev_now), revenue_year_ago=_value(rev_prev),
            eps=_value(eps_now), eps_year_ago=_value(_year_ago(eps, p)) if eps_now is not None else None,
            gap_pct=gap_pct, gap_atr=gap_atr, move_pct=move_pct, move_atr=move_atr))
    return cards


def load_cards(conn: sqlite3.Connection, ticker: str, daily: pd.DataFrame, atr_period: int = 14) -> list[EarningsCard]:
    announcements = db.read_earnings_announcements(conn, ticker)
    if announcements.empty:
        return []
    fundamentals = db.read_fundamentals(conn, ticker)
    fundamentals = fundamentals[fundamentals["concept"].isin(["revenue", "eps_diluted"])]
    splits = market_cap.load_splits(conn, [ticker])
    return build_cards(announcements, fundamentals, splits, daily, atr_period)


# --- text ---------------------------------------------------------------------------

def money(value: float) -> str:
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= size:
            return f"{value / size:.1f}{suffix}"
    return f"{value:.0f}"


def change_text(now: float | None, year_ago: float | None, fmt) -> str:
    """"96.2B, +105.9% vs year-ago" -- the % only against a positive year-ago value."""
    if now is None:
        return "n/a"
    if year_ago is None:
        return f"{fmt(now)}, no year-ago quarter"
    if year_ago > 0:
        return f"{fmt(now)}, {(now / year_ago - 1) * 100:+.1f}% vs year-ago"
    return f"{fmt(now)}, vs {fmt(year_ago)} year-ago"


def _move_text(pct: float | None, atr: float | None) -> str:
    if pct is None:
        return "n/a"
    return f"{pct:+.1f}%" + ("" if atr is None or np.isnan(atr) else f" ({atr:+.1f} ATR)")


def eps_text(card: EarningsCard) -> str:
    if card.eps is None and card.report_form.startswith("10-K"):
        return "n/a (the 10-K reports the year only)"
    return change_text(card.eps, card.eps_year_ago, lambda v: f"{v:.2f}")


def card_text(card: EarningsCard) -> str:
    """The card, as plotly annotation HTML."""
    filed = pd.Timestamp(card.accepted_at).tz_convert("America/New_York")
    return "<br>".join([
        f"<b>{card.label}</b> · quarter ended {card.period_end:%Y-%m-%d}",
        f"announced {filed:%Y-%m-%d} {TIMING_TEXT.get(card.timing, card.timing)} ({card.report_form})",
        f"Revenue: {change_text(card.revenue, card.revenue_year_ago, money)}",
        f"EPS (diluted): {eps_text(card)}",
        f"Reaction: gap {_move_text(card.gap_pct, card.gap_atr)} · day {_move_text(card.move_pct, card.move_atr)}",
        "<i>guidance: not yet extracted</i>",
    ])


def hover_text(card: EarningsCard) -> str:
    filed = pd.Timestamp(card.accepted_at).tz_convert("America/New_York")
    return (f"{card.label}: accepted {filed:%Y-%m-%d %H:%M} ET ({TIMING_TEXT.get(card.timing, card.timing)})"
            f"<br>reaction bar {card.reaction_date:%Y-%m-%d}")
