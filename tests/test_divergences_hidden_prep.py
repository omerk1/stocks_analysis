"""Unit tests for the hidden-forms prep looks' derivations
(src/analysis/divergence_hidden_prep.py): the pivot-to-pivot retrace
fraction, the hidden/regular co-occurrence interval matching, and the
NA discipline of the shape classifier."""

import numpy as np
import pandas as pd
import pytest

from src.analysis.divergence_hidden_prep import (
    attach_cooccurrence,
    classify_hidden_shape,
    hidden_fit_retrace_frac,
)


def _scalar_frame(direction, retrace_pct, leg2_gain_pct):
    return pd.DataFrame(
        {
            "direction": [direction],
            "interpeak_retrace_pct": [retrace_pct],
            "leg2_gain_pct": [leg2_gain_pct],
        }
    )


class TestHiddenFitRetraceFrac:
    def test_bullish_low_pair_matches_hand_computation(self):
        # L1=100, interpeak high H=120, L2=110: retrace_pct=(120-100)/100=0.2,
        # leg2_gain=(120-110)/120=1/12; counter-move 10 / trend-leg 20 = 0.5.
        frac = hidden_fit_retrace_frac(_scalar_frame("bullish", 0.2, 1 / 12))
        assert frac.iloc[0] == pytest.approx(0.5)

    def test_bearish_high_pair_matches_hand_computation(self):
        # H1=100, interpeak low L=80, H2=90: retrace_pct=0.2,
        # leg2_gain=(90-80)/80=0.125; counter-move 10 / trend-leg 20 = 0.5.
        frac = hidden_fit_retrace_frac(_scalar_frame("bearish", 0.2, 0.125))
        assert frac.iloc[0] == pytest.approx(0.5)

    def test_nan_inputs_stay_nan(self):
        for retrace, leg2 in ((np.nan, 0.1), (0.2, np.nan)):
            frac = hidden_fit_retrace_frac(_scalar_frame("bullish", retrace, leg2))
            assert frac.isna().all()

    def test_zero_trend_leg_is_nan_not_inf(self):
        frac = hidden_fit_retrace_frac(_scalar_frame("bearish", 0.0, 0.1))
        assert frac.isna().all()


class TestClassifyHiddenShape:
    def test_buckets(self):
        shape = classify_hidden_shape(
            pd.Series([0.1, 0.5, 0.5]), pd.Series([10.0, 10.0, 2.0])
        )
        assert shape.tolist() == [
            "shallow (extension-analogue)",
            "deep+slow (pullback-analogue)",
            "deep-fast",
        ]

    def test_na_leg2_bars_is_na_not_deep_fast(self):
        # Invariant #9: a NaN leg2_bars with a defined fraction must come
        # out NA, never "fast" (the comparison alone would read NaN as
        # False and misbucket the row into deep-fast).
        shape = classify_hidden_shape(pd.Series([0.5, 0.5]), pd.Series([np.nan, 2.0]))
        assert shape.isna().tolist() == [True, False]

    def test_na_frac_is_na(self):
        shape = classify_hidden_shape(pd.Series([np.nan]), pd.Series([10.0]))
        assert shape.isna().all()


def _event(ticker, form, direction, indicator, p1, p2, confirmed_at=None):
    return {
        "ticker": ticker,
        "form": form,
        "direction": direction,
        "indicator": indicator,
        "p1_ts": pd.Timestamp(p1),
        "p2_ts": pd.Timestamp(p2),
        "confirmed_at": confirmed_at or (pd.Timestamp(p2) + pd.Timedelta(days=3)).isoformat(),
    }


class TestAttachCooccurrence:
    def test_regular_p2_inside_hidden_window_sets_both_sides(self):
        events = attach_cooccurrence(
            pd.DataFrame(
                [
                    _event("A", "hidden", "bullish", "rsi", "2020-01-01", "2020-02-01"),
                    _event("A", "regular", "bearish", "rsi", "2019-12-01", "2020-01-15"),
                ]
            )
        )
        hidden, regular = events.iloc[0], events.iloc[1]
        assert hidden["counterpart_any"] and hidden["counterpart_same_ind"]
        assert regular["inside_hidden_any"] and regular["inside_hidden_same_ind"]

    def test_boundary_dates_are_exclusive(self):
        # Regular p2 exactly on the hidden pair's own pivot dates is not
        # "between the pivots".
        for reg_p2 in ("2020-01-01", "2020-02-01"):
            events = attach_cooccurrence(
                pd.DataFrame(
                    [
                        _event("A", "hidden", "bullish", "rsi", "2020-01-01", "2020-02-01"),
                        _event("A", "regular", "bearish", "rsi", "2019-12-01", reg_p2),
                    ]
                )
            )
            assert not events.iloc[0]["counterpart_any"]
            assert not events.iloc[1]["inside_hidden_any"]

    def test_same_direction_regular_does_not_match(self):
        # hidden/bullish mirrors regular/BEARISH only.
        events = attach_cooccurrence(
            pd.DataFrame(
                [
                    _event("A", "hidden", "bullish", "rsi", "2020-01-01", "2020-02-01"),
                    _event("A", "regular", "bullish", "rsi", "2019-12-01", "2020-01-15"),
                ]
            )
        )
        assert not events.iloc[0]["counterpart_any"]
        assert not events.iloc[1]["inside_hidden_any"]

    def test_other_indicator_counts_for_any_but_not_same(self):
        events = attach_cooccurrence(
            pd.DataFrame(
                [
                    _event("A", "hidden", "bullish", "rsi", "2020-01-01", "2020-02-01"),
                    _event("A", "regular", "bearish", "macd_hist", "2019-12-01", "2020-01-15"),
                ]
            )
        )
        hidden = events.iloc[0]
        assert hidden["counterpart_any"]
        assert not hidden["counterpart_same_ind"]

    def test_no_cross_ticker_leakage(self):
        events = attach_cooccurrence(
            pd.DataFrame(
                [
                    _event("A", "hidden", "bullish", "rsi", "2020-01-01", "2020-02-01"),
                    _event("B", "regular", "bearish", "rsi", "2019-12-01", "2020-01-15"),
                ]
            )
        )
        assert not events.iloc[0]["counterpart_any"]
        assert not events.iloc[1]["inside_hidden_any"]

    def test_bearish_mirror(self):
        events = attach_cooccurrence(
            pd.DataFrame(
                [
                    _event("A", "hidden", "bearish", "obv", "2020-03-01", "2020-04-01"),
                    _event("A", "regular", "bullish", "obv", "2020-02-15", "2020-03-20"),
                ]
            )
        )
        assert events.iloc[0]["counterpart_any"]
        assert events.iloc[1]["inside_hidden_any"]

    def test_pit_flag_requires_counterpart_confirmed_first(self):
        # Counterpart confirms AFTER the hidden event's own confirmed_at:
        # structure-level flag True, PIT flag False.
        events = attach_cooccurrence(
            pd.DataFrame(
                [
                    _event("A", "hidden", "bullish", "rsi", "2020-01-01", "2020-02-01",
                           confirmed_at="2020-02-04T00:00:00"),
                    _event("A", "regular", "bearish", "rsi", "2019-12-01", "2020-01-30",
                           confirmed_at="2020-02-10T00:00:00"),
                ]
            )
        )
        hidden = events.iloc[0]
        assert hidden["counterpart_any"]
        assert not hidden["counterpart_pit"]

    def test_pit_flag_set_when_counterpart_already_confirmed(self):
        events = attach_cooccurrence(
            pd.DataFrame(
                [
                    _event("A", "hidden", "bullish", "rsi", "2020-01-01", "2020-02-01",
                           confirmed_at="2020-02-04T00:00:00"),
                    _event("A", "regular", "bearish", "rsi", "2019-12-01", "2020-01-15",
                           confirmed_at="2020-01-20T00:00:00"),
                ]
            )
        )
        assert events.iloc[0]["counterpart_pit"]

    def test_hidden_only_frame_gets_all_false_flags(self):
        events = attach_cooccurrence(
            pd.DataFrame(
                [_event("A", "hidden", "bullish", "rsi", "2020-01-01", "2020-02-01")]
            )
        )
        assert not events.iloc[0]["counterpart_any"]
        assert not events.iloc[0]["counterpart_pit"]
