import math

import numpy as np
import pandas as pd
import pytest

from src.ui.chart import relevance
from src.ui.chart.config import RelevanceConfig
from src.ui.chart.overlays import Overlay

CLOSE, ATR = 100.0, 2.0  # reach 3 ATR = 6 points either side


def ov(item_id, lo, hi=None, family="sr_lines", strength=1.0, alive=True, kind="zone"):
    return Overlay(family=family, item_id=item_id, label=item_id, kind=kind, x0=pd.Timestamp("2024-01-01"),
                   lo=lo, hi=lo if hi is None else hi, strength=strength, alive=alive)


def ids(selection):
    return {i for v in selection.values() for i in v}


def test_distance_is_to_the_nearer_edge_in_atrs():
    assert relevance.distance_atr(99.0, 101.0, CLOSE, ATR) == 0.0  # inside the zone
    assert relevance.distance_atr(94.0, 96.0, CLOSE, ATR) == pytest.approx(2.0)  # top edge is 4 below
    assert relevance.distance_atr(103.0, 110.0, CLOSE, ATR) == pytest.approx(1.5)
    assert relevance.distance_atr(103.0, 103.0, CLOSE, float("nan")) == math.inf
    assert relevance.distance_atr(103.0, 103.0, CLOSE, 0.0) == math.inf


def test_strength_is_a_mid_rank_percentile():
    assert relevance._mid_rank_pct([5.0]) == [0.5]
    assert relevance._mid_rank_pct([1.0, 2.0]) == [0.25, 0.75]
    assert relevance._mid_rank_pct([3.0, 3.0]) == [0.5, 0.5]


def test_dead_items_are_never_picked_even_at_price_and_strongest():
    items = [ov("dead", 99.0, 101.0, strength=99.0, alive=False), ov("alive", 104.0, strength=1.0)]
    ranked = relevance.rank(items, CLOSE, ATR, RelevanceConfig())
    dead = next(r for r in ranked if r.overlay.item_id == "dead")
    assert dead.score is None and dead.strength_pct is None  # nor does it count in the percentile
    assert ids(relevance.default_selection(ranked, RelevanceConfig())) == {"alive"}


def test_items_out_of_reach_are_not_picked():
    items = [ov("near", 105.9), ov("far", 106.1)]
    ranked = relevance.rank(items, CLOSE, ATR, RelevanceConfig())
    assert ids(relevance.default_selection(ranked, RelevanceConfig())) == {"near"}
    assert [r.overlay.item_id for r in ranked] == ["near", "far"]  # far still listed, after the scored


def test_weight_moves_the_order_between_proximity_and_strength():
    items = [ov("close_weak", 100.5, strength=1.0), ov("far_strong", 105.0, strength=10.0)]
    by = lambda w: [r.overlay.item_id for r in relevance.rank(items, CLOSE, ATR, RelevanceConfig(), weight=w)]
    assert by(1.0) == ["close_weak", "far_strong"]
    assert by(0.0) == ["far_strong", "close_weak"]
    # the default 0.7: 0.7*(1-0.25/3)+0.3*0.25 = 0.717 vs 0.7*(1-2.5/3)+0.3*0.75 = 0.342
    assert by(None) == ["close_weak", "far_strong"]


def test_a_family_without_strength_scores_on_proximity_alone():
    r = relevance.rank([ov("avwap", 103.0, family="avwap", strength=None, kind="series")], CLOSE, ATR,
                       RelevanceConfig())[0]
    assert r.strength_pct is None and r.score == pytest.approx(1 - 1.5 / 3)


def test_caps_per_family_and_in_total():
    items = [ov(f"{fam}{i}", 100.0 + 0.5 * i, family=fam, strength=float(i))
             for fam in ("sr_lines", "gaps", "avwap", "fibonacci") for i in range(5)]
    cfg = RelevanceConfig()
    ranked = relevance.rank(items, CLOSE, ATR, cfg)
    per_family = relevance.family_defaults(ranked, cfg)
    assert all(len(v) == 3 for v in per_family.values())
    picked = relevance.default_selection(ranked, cfg)
    assert sum(len(v) for v in picked.values()) == 10
    best = [r for r in ranked if r.overlay.item_id in ids(per_family)][:10]
    assert ids(picked) == {r.overlay.item_id for r in best}


def test_one_level_does_not_take_two_slots():
    items = [ov("fvg", 98.0, 99.0, family="gaps"), ov("classic", 98.0, 99.0, family="gaps"),
             ov("inside", 98.5, 99.5, family="gaps"), ov("other", 102.0, 103.0, family="gaps"),
             ov("near_line", 99.65, family="gaps")]  # 0.15 above "inside"'s top edge
    ranked = relevance.rank(items, CLOSE, ATR, RelevanceConfig(), weight=1.0)
    # nearest first: near_line, inside; fvg and classic overlap inside
    assert relevance.family_defaults(ranked, RelevanceConfig()) == {"gaps": ["near_line", "inside", "other"]}
    # within 0.1 ATR (0.2) of a picked item is the same level once the ATR is known: inside is
    # skipped, so fvg (0.65 from near_line) gets its slot and classic, overlapping fvg, doesn't
    assert relevance.family_defaults(ranked, RelevanceConfig(), ATR) == {"gaps": ["near_line", "fvg", "other"]}
    # a different family at the same price is not a duplicate
    both = items[:1] + [ov("sr", 98.0, 99.0)]
    picked = relevance.default_selection(relevance.rank(both, CLOSE, ATR, RelevanceConfig()), RelevanceConfig())
    assert ids(picked) == {"fvg", "sr"}


def test_last_atr_is_nan_on_too_few_bars():
    idx = pd.bdate_range("2024-01-01", periods=30)
    bars = pd.DataFrame({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0}, index=idx)
    assert relevance.last_atr(bars, 14) == pytest.approx(2.0)
    assert np.isnan(relevance.last_atr(bars.iloc[:14], 14))


def ev(item_id, age, strength=0.5, alive=True, same_key=None, price=500.0):
    """An event far from price (distance never matters for events)."""
    return Overlay(family="divergences", item_id=item_id, label=item_id, kind="segment",
                   x0=pd.Timestamp("2024-01-01"), lo=price, hi=price, strength=strength, alive=alive,
                   age_bars=age, same_key=same_key or item_id)


def test_events_rank_by_recency_not_distance_from_price():
    cfg = RelevanceConfig()
    ranked = relevance.rank([ev("old", 39), ev("new", 2), ev("too old", 41), ev("dead", 0, alive=False)],
                            CLOSE, ATR, cfg, weight=1.0)
    assert [r.overlay.item_id for r in ranked] == ["new", "old", "too old", "dead"]  # unscored: alive first
    assert ranked[0].score == pytest.approx(1 - 2 / cfg.reach_bars)
    assert all(r.score is None for r in ranked[2:])  # confirmed more than reach_bars ago, or dead
    # unscored: alive first, then most recent first
    ranked = relevance.rank([ev("a", 60), ev("b", 45)], CLOSE, ATR, cfg)
    assert [r.overlay.item_id for r in ranked] == ["b", "a"]


def test_events_on_one_pivot_take_one_slot_whatever_their_price():
    cfg = RelevanceConfig()
    items = [ev("rsi", 1, same_key="bull:2024-02-01"), ev("macd", 1, strength=0.4, same_key="bull:2024-02-01"),
             ev("other", 5, same_key="bull:2024-03-01", price=500.01)]
    picks = relevance.family_defaults(relevance.rank(items, CLOSE, ATR, cfg), cfg, ATR)
    assert picks == {"divergences": ["rsi", "other"]}  # same price as "rsi", but another event
