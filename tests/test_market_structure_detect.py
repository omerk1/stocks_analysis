import pandas as pd
import pytest

from src.foundation.market_common.models import Pivot, PivotKind, Timeframe
from src.signals.market_structure.config import MarketStructureConfig
from src.signals.market_structure.detect import track_market_structure
from src.signals.market_structure.models import Direction, StructureEvent


def _bars(closes: list[float], volumes: list[float] | None = None, start: str = "2020-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=len(closes))
    vols = volumes if volumes is not None else [1000.0] * len(closes)
    closes_s = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame(
        {"open": closes_s, "high": closes_s + 0.3, "low": closes_s - 0.3, "close": closes_s, "volume": vols},
        index=idx,
    )


def _pivot(bar_index: int, price: float, kind: PivotKind, df: pd.DataFrame) -> Pivot:
    ts = df.index[bar_index].isoformat()
    return Pivot(kind=kind, timestamp=ts, value=price, confirmed_at=ts, threshold_at_pivot=1.0, bar_index=bar_index)


def _config(**overrides) -> MarketStructureConfig:
    defaults = dict(volume_sma_period=3, breakout_volume_mult=1.4, min_bars=2)
    defaults.update(overrides)
    return MarketStructureConfig(**defaults)


def test_bootstrap_bos_then_choch_advances_structural_pivot():
    # LOW(2)=95, HIGH(5)=105 bootstraps a BULLISH regime. close[10]=106
    # breaks the HIGH -> BOS (continuation, still bullish). A fresh
    # LOW(11)=99 then HIGH(13)=112 confirm before close[14]=90 breaks the
    # *updated* structural low (99, not the original 95) -> CHOCH, flips
    # bearish. close[15] stays above the new BOS reference (the
    # just-broken 99, now consumed) so nothing fires a third time.
    closes = [100, 98, 95, 97, 100, 105, 101, 100, 102, 100, 106, 104, 103, 108, 90, 89]
    df = _bars(closes)
    pivots = [
        _pivot(2, 95.0, PivotKind.LOW, df),
        _pivot(5, 105.0, PivotKind.HIGH, df),
        _pivot(11, 99.0, PivotKind.LOW, df),
        _pivot(13, 112.0, PivotKind.HIGH, df),
    ]

    events = track_market_structure(df, pivots, _config(), "TST", Timeframe.DAILY)

    assert len(events) == 2
    bos, choch = events
    assert bos.event == StructureEvent.BOS
    assert bos.direction == Direction.BULLISH
    assert bos.broken_pivot.value == 105.0
    assert bos.close == 106.0
    assert bos.broken_at == df.index[10].isoformat()

    assert choch.event == StructureEvent.CHOCH
    assert choch.direction == Direction.BEARISH
    assert choch.broken_pivot.value == 99.0  # the updated structural low, not the original 95
    assert choch.close == 90.0
    assert choch.broken_at == df.index[14].isoformat()


def test_require_volume_surge_blocks_unconfirmed_break():
    closes = [100, 99, 95, 97, 100, 105, 101, 110]
    pivots_at = lambda df: [  # noqa: E731
        _pivot(2, 95.0, PivotKind.LOW, df),
        _pivot(5, 105.0, PivotKind.HIGH, df),
    ]
    config = _config(require_volume_surge=True)

    df_flat = _bars(closes, volumes=[1000.0] * len(closes))
    events_blocked = track_market_structure(df_flat, pivots_at(df_flat), config, "TST", Timeframe.DAILY)
    assert events_blocked == []

    volumes_surge = [1000.0] * 7 + [2000.0]  # 3-bar trailing SMA ratio at bar 7: 2000/((1000+1000+2000)/3)=1.5
    df_surge = _bars(closes, volumes=volumes_surge)
    events_confirmed = track_market_structure(df_surge, pivots_at(df_surge), config, "TST", Timeframe.DAILY)
    assert len(events_confirmed) == 1
    assert events_confirmed[0].event == StructureEvent.BOS
    assert events_confirmed[0].volume_confirmed is True
