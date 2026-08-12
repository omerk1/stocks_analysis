import pandas as pd

from src.sr_lines import events as events_mod
from src.sr_lines.candidates import HorizontalCandidate
from src.sr_lines.config import SRConfig
from src.sr_lines.models import Event, EventType, Pivot, PivotKind


def _bars(rows: list[tuple]) -> pd.DataFrame:
    """rows: list of (date_str, open, high, low, close, volume)"""
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.set_index("timestamp").sort_index()


def _atr(bars: pd.DataFrame) -> pd.Series:
    return pd.Series(1.0, index=bars.index)


def _candidate(center: float = 100.0, half_width: float = 1.0, first_touch: str = "2020-01-01") -> HorizontalCandidate:
    pivot = Pivot(kind=PivotKind.LOW, timestamp=first_touch, value=center, confirmed_at=first_touch, threshold_at_pivot=1.0)
    return HorizontalCandidate(center=center, half_width=half_width, pivots=[pivot, pivot])


def test_wick_only_touch_when_body_stays_outside_the_zone():
    # zone = [99, 101]. Establishing bar closes above (side="above"). Planted
    # bar: body (open/close) entirely above zone_hi=101, only the low wick
    # dips inside the zone without breaching the far edge (zone_lo=99).
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    rows = [
        (dates[0], 103.0, 103.5, 102.5, 103.0, 1_000_000),  # establishes "above"
        (dates[1], 103.0, 103.2, 102.8, 103.0, 1_000_000),
        (dates[2], 102.0, 102.3, 100.5, 101.8, 1_000_000),  # planted: wick-only touch
        (dates[3], 102.0, 102.3, 101.5, 102.0, 1_000_000),
        (dates[4], 102.0, 102.3, 101.5, 102.0, 1_000_000),
    ]
    bars = _bars(rows)
    candidate = _candidate(center=100.0, half_width=1.0, first_touch=dates[0].isoformat())
    config = SRConfig()

    evs, original_side = events_mod.classify_events(bars, candidate, _atr(bars), config)

    assert original_side == "above"
    touches = [e for e in evs if e.start == dates[2].isoformat()]
    assert len(touches) == 1
    assert touches[0].type == EventType.TOUCH


def test_body_touch_when_body_enters_the_zone():
    # Same zone, but the planted bar's body (open/close) actually enters
    # [99, 101] -- a deeper, more convincing test than a pure wick brush.
    # Close must stay on the established side (>101) or this would be a
    # BODY_FAKE/BREAK candidate instead, not a touch of any kind.
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    rows = [
        (dates[0], 103.0, 103.5, 102.5, 103.0, 1_000_000),  # establishes "above"
        (dates[1], 103.0, 103.2, 102.8, 103.0, 1_000_000),
        (dates[2], 100.5, 101.6, 100.3, 101.5, 1_000_000),  # planted: body enters the zone, closes above it
        (dates[3], 102.0, 102.3, 101.5, 102.0, 1_000_000),
        (dates[4], 102.0, 102.3, 101.5, 102.0, 1_000_000),
    ]
    bars = _bars(rows)
    candidate = _candidate(center=100.0, half_width=1.0, first_touch=dates[0].isoformat())
    config = SRConfig()

    evs, original_side = events_mod.classify_events(bars, candidate, _atr(bars), config)

    matching = [e for e in evs if e.start == dates[2].isoformat()]
    assert len(matching) == 1
    assert matching[0].type == EventType.BODY_TOUCH


def test_resolved_body_fake_sets_reclaim_fields():
    # Close beyond the zone, then reclaimed one bar later.
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    rows = [
        (dates[0], 103.0, 103.5, 102.5, 103.0, 1_000_000),  # establishes "above"
        (dates[1], 103.0, 103.2, 102.8, 103.0, 1_000_000),
        (dates[2], 99.0, 99.5, 98.0, 98.5, 1_000_000),  # close beyond zone_lo=99 -> pending break
        (dates[3], 99.5, 102.0, 99.0, 101.5, 1_000_000),  # reclaims (closes back above zone_hi)
        (dates[4], 102.0, 102.3, 101.5, 102.0, 1_000_000),
    ]
    bars = _bars(rows)
    candidate = _candidate(center=100.0, half_width=1.0, first_touch=dates[0].isoformat())
    config = SRConfig(fakeout_reclaim_bars=5)

    evs, _ = events_mod.classify_events(bars, candidate, _atr(bars), config)

    body_fakes = [e for e in evs if e.type == EventType.BODY_FAKE]
    assert len(body_fakes) == 1
    bf = body_fakes[0]
    assert bf.pending is False
    assert bf.reclaimed is True
    assert bf.reclaimed_at == dates[3].isoformat()
    assert bf.bars_to_reclaim == 1


def test_pending_body_fake_leaves_reclaim_fields_none():
    # Close beyond the zone with no bars left to resolve within the window.
    dates = pd.date_range("2020-01-01", periods=3, freq="D")
    rows = [
        (dates[0], 103.0, 103.5, 102.5, 103.0, 1_000_000),  # establishes "above"
        (dates[1], 103.0, 103.2, 102.8, 103.0, 1_000_000),
        (dates[2], 99.0, 99.5, 98.0, 98.5, 1_000_000),  # close beyond zone -> unresolved at end of data
    ]
    bars = _bars(rows)
    candidate = _candidate(center=100.0, half_width=1.0, first_touch=dates[0].isoformat())
    config = SRConfig(fakeout_reclaim_bars=5)

    evs, _ = events_mod.classify_events(bars, candidate, _atr(bars), config)

    body_fakes = [e for e in evs if e.type == EventType.BODY_FAKE]
    assert len(body_fakes) == 1
    bf = body_fakes[0]
    assert bf.pending is True
    assert bf.reclaimed is None
    assert bf.reclaimed_at is None
    assert bf.bars_to_reclaim is None


def test_break_leaves_reclaim_fields_none_at_classification_time():
    # A break not reclaimed within fakeout_reclaim_bars -- events.py never
    # fills in reclaim/reclaimed_at/bars_to_reclaim for BREAK itself; that's
    # flip_status.pair_break_reclaims' job (a later, separate pass), since a
    # break's eventual reclaim (if any) is a real market event that can
    # happen long after this single forward walk finishes.
    dates = pd.date_range("2020-01-01", periods=6, freq="D")
    rows = [
        (dates[0], 103.0, 103.5, 102.5, 103.0, 1_000_000),
        (dates[1], 103.0, 103.2, 102.8, 103.0, 1_000_000),
        (dates[2], 99.0, 99.5, 98.0, 98.5, 1_000_000),  # close beyond zone
        (dates[3], 98.0, 98.5, 97.0, 97.5, 1_000_000),  # stays beyond
        (dates[4], 97.0, 97.5, 96.0, 96.5, 1_000_000),
        (dates[5], 96.0, 96.5, 95.0, 95.5, 1_000_000),  # window (2 bars) elapsed, unreclaimed
    ]
    bars = _bars(rows)
    candidate = _candidate(center=100.0, half_width=1.0, first_touch=dates[0].isoformat())
    config = SRConfig(fakeout_reclaim_bars=2)

    evs, _ = events_mod.classify_events(bars, candidate, _atr(bars), config)

    breaks = [e for e in evs if e.type == EventType.BREAK]
    assert len(breaks) == 1
    assert breaks[0].reclaimed is None
    assert breaks[0].reclaimed_at is None
    assert breaks[0].bars_to_reclaim is None


def test_merge_adjacent_carries_forward_the_later_events_reclaim_fields():
    # Two separate BODY_FAKE incidents close enough in time to merge --
    # the merged event's reclaim fields must reflect where the merged group
    # ended up (the later incident), same convention `pending` already uses.
    idx = pd.bdate_range("2020-01-01", periods=10)
    first = Event(
        type=EventType.BODY_FAKE, start=idx[0].isoformat(), end=idx[1].isoformat(),
        penetration_atr=0.3, reaction_atr=0.0,
        reclaimed=True, reclaimed_at=idx[1].isoformat(), bars_to_reclaim=1,
    )
    second = Event(
        type=EventType.BODY_FAKE, start=idx[3].isoformat(), end=idx[4].isoformat(),
        penetration_atr=0.5, reaction_atr=0.0,
        reclaimed=True, reclaimed_at=idx[4].isoformat(), bars_to_reclaim=1,
    )

    merged = events_mod._merge_adjacent([first, second], idx)

    assert len(merged) == 1
    assert merged[0].reclaimed_at == second.reclaimed_at
    assert merged[0].bars_to_reclaim == second.bars_to_reclaim
