import pandas as pd
import pytest

from src.foundation.data_processing import db as raw_db
from src.foundation.market_common import history_breaks as hb
from src.foundation.market_common.anchors import AnchorConfig, AnchorType, discover_anchors
from src.foundation.market_common.models import Timeframe
from src.signals.avwap.anchors import detect as avwap_detect
from src.signals.avwap.config import AvwapConfig
from src.signals.volume_profile.config import VolumeProfileConfig
from src.signals.volume_profile.detect import detect as vp_detect

CFG = hb.HistoryBreakConfig()


def _bars(closes, volumes=None, start="2015-01-01"):
    idx = pd.bdate_range(start, periods=len(closes))
    closes = pd.Series(closes, index=idx, dtype="float64")
    vol = pd.Series(1000.0 if volumes is None else volumes, index=idx, dtype="float64")
    return pd.DataFrame({"open": closes, "high": closes * 1.01, "low": closes * 0.99, "close": closes, "volume": vol})


def _splits(*rows):
    """rows: (date, ratio) -- ratio < 1 is a reverse split (0.05 = 1-for-20)."""
    return pd.DataFrame({"execution_date": pd.to_datetime([r[0] for r in rows]), "ratio": [r[1] for r in rows]})


# ------------------------------------------------------------ unadjusted close

def test_unadjusted_close_multiplies_back_later_splits_only():
    bars = _bars([10.0] * 6, start="2020-01-01")  # 2020-01-01 .. 2020-01-08
    split_day = bars.index[3]
    raw = hb.unadjusted_close(bars, _splits((split_day, 0.05)))
    assert raw.iloc[:3].tolist() == [0.5, 0.5, 0.5]    # before a 1-for-20: traded at 1/20th
    assert raw.iloc[3:].tolist() == [10.0, 10.0, 10.0]  # from the split on: as stored


# ----------------------------------------------------------- anchor start date

def _penny_then_reverse_split(split_ratio=0.05, pre_adjusted=10.0, n_after=300):
    """Adjusted closes flat at `pre_adjusted` before the split; with a
    1-for-20 that means the stock actually traded at pre_adjusted * 0.05."""
    n_before = 300
    bars = _bars([pre_adjusted] * (n_before + n_after))
    return bars, bars.index[n_before]


def test_reverse_split_done_as_a_penny_stock_resets_anchors():
    bars, split_day = _penny_then_reverse_split()  # traded at $0.50 before the 1-for-20
    assert hb.anchor_start_date(bars, _splits((split_day, 0.05)), CFG) == split_day


def test_late_reverse_split_of_a_non_penny_stock_does_not_reset():
    bars, split_day = _penny_then_reverse_split(split_ratio=0.1, pre_adjusted=30.0)  # traded at $3
    assert hb.anchor_start_date(bars, _splits((split_day, 0.1)), CFG) is None


def test_forward_splits_never_reset():
    bars, split_day = _penny_then_reverse_split(pre_adjusted=0.2)
    assert hb.anchor_start_date(bars, _splits((split_day, 4.0)), CFG) is None


def test_latest_qualifying_reverse_split_wins():
    bars = _bars([10.0] * 900)
    first, second = bars.index[200], bars.index[500]
    assert hb.anchor_start_date(bars, _splits((first, 0.05), (second, 0.05)), CFG) == second


def test_reset_waits_until_enough_history_follows_it():
    bars, split_day = _penny_then_reverse_split(n_after=60)  # ~3 months after
    assert hb.anchor_start_date(bars, _splits((split_day, 0.05)), CFG) is None


def test_established_company_crisis_does_not_reset():
    # 12 years of normal $40 trading, a crash to $0.40, a penny 1-for-20.
    n_normal, n_crash, n_after = 3000, 150, 300
    closes = [40.0] * n_normal + [8.0] * n_crash + [8.0] * n_after   # adjusted
    bars = _bars(closes, start="2005-01-03")
    split_day = bars.index[n_normal + n_crash]
    sp = _splits((split_day, 0.05))
    assert hb.unadjusted_close(bars, sp).iloc[n_normal] == pytest.approx(0.4)
    assert hb.anchor_start_date(bars, sp, CFG) is None
    # the same crisis with a short history before it still resets
    short = bars.iloc[n_normal - 500:]
    assert hb.anchor_start_date(short, sp, CFG) == split_day


def test_split_after_the_last_bar_is_not_seen():
    bars, split_day = _penny_then_reverse_split()
    truncated = bars[bars.index < split_day]
    assert hb.anchor_start_date(truncated, _splits((split_day, 0.05)), CFG) is None


def test_overrides_never_reset_or_pin_a_date(monkeypatch):
    bars, split_day = _penny_then_reverse_split()
    sp = _splits((split_day, 0.05))
    monkeypatch.setattr(hb, "HISTORY_RESET_OVERRIDES", {"KEEP": None, "PIN": "2015-06-01", "LATER": "2099-01-01"})
    assert hb.anchor_start_date(bars, sp, CFG, ticker="KEEP") is None
    assert hb.anchor_start_date(bars, sp, CFG, ticker="PIN") == pd.Timestamp("2015-06-01")
    assert hb.anchor_start_date(bars, sp, CFG, ticker="LATER") is None  # not reached yet
    assert hb.anchor_start_date(bars, sp, CFG, ticker="OTHER") == split_day


def test_pds_is_overridden_to_keep_its_history():
    assert hb.HISTORY_RESET_OVERRIDES.get("PDS", "missing") is None


# -------------------------------------------------------- training eligibility

def test_eligibility_flags_penny_post_split_and_dormant_dates():
    closes = [0.5] * 100 + [20.0] * 400          # adjusted; no splits -> traded at these prices
    volumes = [1000.0] * 250 + [0.0] * 100 + [1000.0] * 150
    bars = _bars(closes, volumes)
    split_day = bars.index[400]
    e = hb.training_eligibility(bars, _splits((split_day, 0.5)), CFG)

    # before a 1-for-2, the first 100 dates traded at 0.5 * 0.5 = 0.25
    assert e["penny"].iloc[:100].all() and not e["penny"].iloc[100:].any()
    assert e["post_reverse_split"].iloc[400:].all() and not e["post_reverse_split"].iloc[:400].any()
    # dormant once >50% of the trailing 63 bars are zero volume, and not before
    assert not e["dormant"].iloc[:281].any()
    assert e["dormant"].iloc[300:349].all()
    assert (e["eligible"] == ~(e["penny"] | e["post_reverse_split"] | e["dormant"])).all()


def test_eligibility_marks_dates_and_never_drops_any():
    bars = _bars([0.5] * 50)
    e = hb.training_eligibility(bars, None, CFG)
    assert e.index.equals(bars.index)
    assert not e["eligible"].any()


def test_a_dates_flags_never_depend_on_what_happens_after_it():
    # A normal stretch followed by a collapse, a penny reverse split and a
    # dead spell: every date's flags must be the same whether or not the
    # later bars are in the frame.
    closes = [20.0] * 300 + [0.3] * 200 + [6.0] * 200
    volumes = [1000.0] * 550 + [0.0] * 100 + [1000.0] * 50
    bars = _bars(closes, volumes)
    sp = _splits((bars.index[500], 0.05))
    full = hb.training_eligibility(bars, sp, CFG)
    for cut in (299, 450, 520, 600):
        part = hb.training_eligibility(bars.iloc[: cut + 1], sp, CFG)
        pd.testing.assert_frame_equal(part, full.iloc[: cut + 1])
    assert full["eligible"].iloc[:300].all()  # normal years before the collapse stay in


# ------------------------------------------------------------- anchor wiring

def _gevo_like():
    """A huge early high, then a long slide, a penny 1-for-20, and a new era."""
    closes = [1000.0] * 50 + [5000.0] + [1000.0] * 249 + [10.0] * 300 + [8.0] * 300
    bars = _bars(closes)
    return bars, bars.index[600]


def test_discover_anchors_ignores_highs_before_history_start():
    bars, split_day = _gevo_like()
    # true all-time extremes, so the early spike is an ath to be excluded
    config = AnchorConfig(min_bars=1, warmup_bars=0, regime_reach_factor=None)
    full = {a.anchor_date: a.anchor_types for a in discover_anchors(bars, Timeframe.DAILY, config)}
    assert any(AnchorType.ATH in t for d, t in full.items() if pd.Timestamp(d) < split_day)

    reset = discover_anchors(bars, Timeframe.DAILY, config, history_start=split_day)
    assert reset and all(pd.Timestamp(a.anchor_date) >= split_day for a in reset)


@pytest.fixture
def raw_conn():
    c = raw_db.get_connection(":memory:")
    raw_db.create_tables(c)
    yield c
    c.close()


def _seed(raw_conn, ticker, bars, splits):
    rows = bars.assign(is_partial=0)
    raw_db.upsert_bars(raw_conn, "bars_1d", ticker, raw_db.YFINANCE, rows)
    sp = splits.assign(split_from=1.0 / splits["ratio"], split_to=1.0)
    raw_db.upsert_splits(raw_conn, ticker, raw_db.YFINANCE, sp)


@pytest.mark.parametrize("detect, config_cls", [(avwap_detect, AvwapConfig), (vp_detect, VolumeProfileConfig)])
def test_detect_starts_anchors_at_the_reset_and_can_be_switched_off(raw_conn, detect, config_cls):
    bars, split_day = _gevo_like()
    _seed(raw_conn, "ZOMB", bars, _splits((split_day, 0.05)))

    on, _, reason = detect(raw_conn, "ZOMB", Timeframe.DAILY, config_cls(min_bars=1, warmup_bars=0))
    assert reason is None and on
    assert all(pd.Timestamp(a.anchor_date) >= split_day for a in on)

    off_cfg = config_cls(min_bars=1, warmup_bars=0, history_breaks=hb.HistoryBreakConfig(enabled=False))
    off, _, _ = detect(raw_conn, "ZOMB", Timeframe.DAILY, off_cfg)
    assert any(pd.Timestamp(a.anchor_date) < split_day for a in off)
