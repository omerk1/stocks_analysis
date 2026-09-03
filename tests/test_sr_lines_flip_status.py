import pandas as pd

from src.signals.sr_lines.flip_status import pair_break_reclaims
from src.signals.sr_lines.models import Event, EventType


def _bars(n_days: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01", periods=n_days, freq="D")
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1_000_000}, index=idx,
    )


def _touch(date: str) -> Event:
    return Event(type=EventType.TOUCH, start=date, end=date, penetration_atr=0.1, reaction_atr=1.0)


def _break(start: str, end: str | None = None) -> Event:
    end = end or start
    return Event(type=EventType.BREAK, start=start, end=end, penetration_atr=1.0, reaction_atr=0.0)


def test_single_break_reclaimed_by_a_later_touch():
    idx = pd.date_range("2020-01-01", periods=30, freq="D")
    bars = _bars()
    events = [_break(idx[5].isoformat()), _touch(idx[8].isoformat())]

    results = pair_break_reclaims(events, bars)

    assert len(results) == 1
    assert results[0].reclaimed is True
    assert results[0].reclaimed_at == idx[8].isoformat()
    assert results[0].bars_to_reclaim == 3


def test_single_break_never_reclaimed():
    idx = pd.date_range("2020-01-01", periods=30, freq="D")
    bars = _bars()
    events = [_break(idx[5].isoformat())]

    results = pair_break_reclaims(events, bars)

    assert len(results) == 1
    assert results[0].reclaimed is False
    assert results[0].reclaimed_at is None
    assert results[0].bars_to_reclaim is None


def test_two_independent_breaks_each_reclaimed_separately():
    idx = pd.date_range("2020-01-01", periods=30, freq="D")
    bars = _bars()
    events = [
        _break(idx[2].isoformat()), _touch(idx[3].isoformat()),   # reclaimed in 1 bar
        _break(idx[10].isoformat()), _touch(idx[15].isoformat()),  # reclaimed in 5 bars
    ]

    results = pair_break_reclaims(events, bars)

    assert len(results) == 2
    first, second = results
    assert first.reclaimed is True and first.bars_to_reclaim == 1
    assert second.reclaimed is True and second.bars_to_reclaim == 5


def test_a_break_superseded_by_a_second_break_before_any_confirmation_reports_unreclaimed():
    # Conservative choice, documented in pair_break_reclaims: a later BREAK
    # is never itself treated as a reclaim of an earlier one. With no
    # confirming event between them, the first break is reported unreclaimed
    # even though a second break eventually follows it.
    idx = pd.date_range("2020-01-01", periods=30, freq="D")
    bars = _bars()
    events = [_break(idx[2].isoformat()), _break(idx[6].isoformat())]

    results = pair_break_reclaims(events, bars)

    assert len(results) == 2
    first, second = results
    assert first.reclaimed is False
    assert first.bars_to_reclaim is None
    assert second.reclaimed is False
    assert second.bars_to_reclaim is None


def test_a_pending_body_fake_does_not_reclaim_a_break():
    # A pending (unresolved) BODY_FAKE isn't confirmation evidence yet --
    # is_confirmation_event excludes it -- so it must not reclaim a break.
    idx = pd.date_range("2020-01-01", periods=30, freq="D")
    bars = _bars()
    events = [
        _break(idx[2].isoformat()),
        Event(type=EventType.BODY_FAKE, start=idx[4].isoformat(), end=idx[5].isoformat(),
              penetration_atr=0.4, reaction_atr=0.0, pending=True),
    ]

    results = pair_break_reclaims(events, bars)

    assert len(results) == 1
    assert results[0].reclaimed is False


def test_empty_events_returns_empty_list():
    bars = _bars()
    assert pair_break_reclaims([], bars) == []


def test_no_breaks_returns_empty_list():
    idx = pd.date_range("2020-01-01", periods=30, freq="D")
    bars = _bars()
    events = [_touch(idx[3].isoformat()), _touch(idx[5].isoformat())]

    assert pair_break_reclaims(events, bars) == []
