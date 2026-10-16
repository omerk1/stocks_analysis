"""The exploratory look (step 5): event-row lag alignment, planted-effect recovery
against the matched controls, refusals, the rubric's unapplied-field disclosures, the
three-way verdict, and the session artifacts.

The synthetic panel follows `test_llm_strategy_spec_finders.py`'s construction (distance
sequences lagged one bar, exactly as the cached feature panel is), extended with closes
that plant a known forward return on event rows only, and with the C2 context columns
(constant per ticker, so per-date terciles are deterministic).
"""

import json

import pandas as pd
import pytest

from src.llm.strategy_spec.finders import GroundingError, find_first_touch
from src.llm.strategy_spec.look import event_mask, look, verdict
from src.llm.strategy_spec.schema import Control, Example, Rule, Size, StrategySpec
from src.models.dataset import HoldoutError

QUIET = [0.5] * 10
BURST = [2.0] * 5 + [0.1]      # an away run, then a clean touch on the 0.1 bar
N_SIGNALS = 30
HORIZON = 5


def seq_and_signals(n_signals: int) -> tuple[list[float], list[int]]:
    seq = QUIET + (BURST + QUIET) * n_signals     # one signal per block
    idx = [len(QUIET) + i * (len(BURST) + len(QUIET)) + 5 for i in range(n_signals)]
    return seq, idx


EVENT_SEQ, SIGNAL_IDX = seq_and_signals(N_SIGNALS)

# Context values constant per ticker: per-date terciles are then the same every day, and
# the event ticker shares its stratum with the two controls holding the same values.
CONTEXT = {"EVT": (1.0, 1.0), "C1": (1.0, 1.0), "C2": (1.0, 1.0), "C3": (2.0, 2.0),
           "C4": (2.0, 2.0), "C5": (3.0, 3.0), "C6": (3.0, 3.0), "C7": (4.0, 4.0),
           "C8": (4.0, 4.0), "SHT": (4.0, 4.0)}


def planted_close(seq_len: int, signal_idx: list[int], step: float) -> list[float]:
    """Flat at 100, stepping ×(1+step) three bars after each signal — inside every event
    row's 5-bar forward window (event row = signal+1, window to signal+6), so each event
    row's fwd_ret_5 is exactly `step` while every control row's is 0."""
    close, level = [], 100.0
    steps_at = {p + 4 for p in signal_idx}
    for i in range(seq_len):
        if i in steps_at:
            level *= 1.0 + step
        close.append(level)
    return close


def panel(tickers: dict[str, tuple[list[float], list[float] | None]],
          start: str = "2015-01-02") -> pd.DataFrame:
    """tickers: name -> (signal-bar distance sequence, closes or None for flat 100)."""
    frames = []
    for ticker, (dist, close) in tickers.items():
        dist = pd.Series(dist, dtype="float64")
        mom, vol = CONTEXT[ticker]
        frames.append(pd.DataFrame({
            "ticker": ticker, "date": pd.bdate_range(start, periods=len(dist)),
            "close": close if close is not None else 100.0,
            "sma_200": pd.Series(100.0, index=dist.index).shift(1),
            "dist_atr_sma_200": dist.shift(1),       # cache convention: one-bar-lagged
            "mom_12_1": mom, "realized_vol_63": vol, "sector": "TECH",
        }))
    return (pd.concat(frames, ignore_index=True)
            .sort_values(["ticker", "date"]).reset_index(drop=True))


def effect_panel(step: float = 0.02, n_signals: int = N_SIGNALS) -> pd.DataFrame:
    seq, idx = seq_and_signals(n_signals)
    quiet = [0.5] * len(seq)
    return panel({
        "EVT": (seq, planted_close(len(seq), idx, step)),
        **{name: (quiet, None) for name in CONTEXT if name not in ("EVT", "SHT")},
    })


def spec(**overrides) -> StrategySpec:
    fields = dict(name="first touch", direction="long", timeframe="daily",
                  size=Size(normalisation="atr", min=1.0),
                  uses=["detector:ma.first_touch"], horizons_bars=[HORIZON])
    return StrategySpec(**{**fields, **overrides})


def run_look(spec_, panel_, tmp_path, **kwargs):
    said = []
    result = look(spec_, panel_, say=said.append, out_dir=tmp_path / "session", **kwargs)
    return result, said


def test_event_rows_are_one_bar_after_the_signal():
    frame = effect_panel()
    matches = find_first_touch(spec(), frame).matches
    event, dropped = event_mask(frame, matches)
    assert dropped == 0  # this finder's search window already excludes each last bar
    event_rows = frame[event]
    assert len(event_rows) == len(matches) == N_SIGNALS
    by_date = frame[frame["ticker"] == "EVT"].reset_index(drop=True)
    signal_positions = [by_date.index[by_date["date"] == m.date][0] for m in matches]
    event_positions = [p for p, flag in
                       enumerate(event[frame["ticker"] == "EVT"].to_numpy()) if flag]
    # The exact inverse of the finder's display un-lag: condition one row later.
    assert event_positions == [p + 1 for p in signal_positions]


def test_planted_effect_is_recovered_against_the_matched_control(tmp_path):
    result, said = run_look(spec(), effect_panel(step=0.02), tmp_path)
    (cell,) = result["cells"]
    assert cell["side"] == "long" and cell["horizon"] == HORIZON
    assert cell["n_events"] == N_SIGNALS and cell["n_dates"] == N_SIGNALS
    # Every event row's forward return is exactly the planted step; every same-stratum
    # control row's is 0 — the C2 delta must recover the step, and its CI exclude zero.
    assert cell["delta_c2"] == pytest.approx(0.02, abs=1e-9)
    assert cell["ci_low"] > 0
    assert cell["effective_n_dates"] == N_SIGNALS
    assert cell["hit_rate"] == pytest.approx(1.0)
    # Annualized vs the 10 bps hurdle at ~1.7 signals/ticker-year: alive, and said so
    # in Track A words.
    assert cell["verdict"].startswith("looks alive")
    assert any("TRACK A" in line for line in said)
    # Artifacts: result.json round-trips, report.md carries what was said, the alive
    # cell earned a pre-registration draft with the kill-criterion skeleton.
    session = tmp_path / "session"
    assert json.loads((session / "result.json").read_text())["cells"][0]["verdict"] == cell["verdict"]
    report = (session / "report.md").read_text()
    assert "TRACK A" in report and "Search rubric" in report
    assert "hit rate 100% (" in report  # a rate, not a signed excess
    draft = (session / "prereg_draft.md").read_text()
    assert "Kill criterion" in draft and "TODO" in draft and "never dead" in draft
    assert result["prereg_draft"] == "prereg_draft.md"
    assert any("EXPLORATION_LOG" in line for line in said)


def test_no_effect_looks_dead_and_earns_no_draft(tmp_path):
    result, _ = run_look(spec(), effect_panel(step=0.0), tmp_path)
    (cell,) = result["cells"]
    assert cell["delta_c2"] == pytest.approx(0.0, abs=1e-12)
    assert cell["verdict"].startswith("looks dead")
    assert result["prereg_draft"] is None
    assert not (tmp_path / "session" / "prereg_draft.md").exists()


def test_direction_both_is_tested_per_side_with_uncontaminated_controls(tmp_path):
    # SHT fires from below one bar AFTER each of EVT's long signals, with a planted -2%
    # forward move: SHT's signal-bar rows then land exactly on the long side's event
    # dates, each carrying most of the short move in its own forward window. Everything
    # of SHT's within a horizon of its events must leave the long side's control pool —
    # excluding only the event rows (the first fix) still let these signal bars drag the
    # date-matched control mean down and inflate the long delta: the pooled-cancellation
    # confound re-imported through the control side of the split.
    sht_seq = [-0.5] + [-x for x in EVENT_SEQ[:-1]]
    sht_idx = [p + 1 for p in SIGNAL_IDX]
    frame = panel({
        "EVT": (EVENT_SEQ, planted_close(len(EVENT_SEQ), SIGNAL_IDX, 0.02)),
        "SHT": (sht_seq, planted_close(len(sht_seq), sht_idx, -0.02)),
        **{name: ([0.5] * len(EVENT_SEQ), None) for name in CONTEXT
           if name not in ("EVT", "SHT")},
    })
    result, _ = run_look(spec(direction="both"), frame, tmp_path)
    by_side = {c["side"]: c for c in result["cells"]}
    assert set(by_side) == {"long", "short"}
    assert by_side["long"]["n_events"] == N_SIGNALS   # EVT fires from above only
    assert by_side["short"]["n_events"] == N_SIGNALS  # SHT from below only
    assert result["population"]["long"]["matches"] == N_SIGNALS
    assert by_side["long"]["delta_c1"] == pytest.approx(0.02, abs=1e-9)
    assert by_side["long"]["delta_c2"] == pytest.approx(0.02, abs=1e-9)
    assert by_side["short"]["delta_c1"] == pytest.approx(-0.02, abs=1e-9)
    with pytest.raises(GroundingError, match="direction"):
        look(spec(direction=None), frame, say=lambda _: None)


def test_refusals_name_the_problem(tmp_path):
    frame = effect_panel()
    with pytest.raises(GroundingError, match="horizons_bars"):
        look(spec(horizons_bars=[]), frame, say=lambda _: None)
    # A horizon below 1 bar would report a PAST return as the forward outcome (the
    # shift's sign flips); a duplicate double-counts its cell. Both refused.
    with pytest.raises(GroundingError, match="at least 1 bar"):
        look(spec(horizons_bars=[-5]), frame, say=lambda _: None)
    with pytest.raises(GroundingError, match="listed once"):
        look(spec(horizons_bars=[5, 5]), frame, say=lambda _: None)
    with pytest.raises(GroundingError, match="not a feature panel"):
        look(spec(), frame.drop(columns=["mom_12_1"]), say=lambda _: None)
    with pytest.raises(GroundingError, match="empty"):
        look(spec(), frame.iloc[0:0], say=lambda _: None)
    beyond = frame.copy()
    beyond["date"] = beyond["date"] + pd.DateOffset(years=10)
    with pytest.raises(HoldoutError):
        look(spec(), beyond, say=lambda _: None)


def test_rubric_discloses_every_unapplied_field_and_the_cost_source(tmp_path):
    constrained = spec(
        direction="both",
        control=Control(description="placebo MA lookbacks around the 200-day"),
        invalidation=[Rule(description="exit on a close back through the MA", phase="after_entry"),
                      Rule(description="skip if earnings within 5 days", phase="before_entry")],
        secondary_metrics=["max drawdown"])
    frame = panel({
        "EVT": (EVENT_SEQ, planted_close(len(EVENT_SEQ), SIGNAL_IDX, 0.02)),
        **{name: ([0.5] * len(EVENT_SEQ), None) for name in CONTEXT
           if name not in ("EVT", "SHT")},
    })
    result, _ = run_look(constrained, frame, tmp_path)
    rubric = {r["parameter"]: r for r in result["rubric"]}
    # A spec with no judged examples was never grounded — the look says so rather than
    # silently testing a definition no one confirmed on charts.
    assert rubric["grounding"]["value"] == "NOT CONFIRMED"
    grounded, _ = run_look(
        constrained.model_copy(update={"examples": [Example(ticker="EVT", date="2015-01-20",
                                                            matches=True)]}),
        frame, tmp_path / "grounded")
    assert {r["parameter"]: r for r in grounded["rubric"]}["grounding"]["source"] == "spec"
    assert rubric["entry timing"]["source"] == "default"       # the one-bar lag, stated
    assert rubric["outcome"]["source"] == "spec"               # horizons are the trader's
    assert rubric["your stated control"]["value"] == "NOT APPLIED"
    assert "platform tiers" in rubric["your stated control"]["detail"]
    after = rubric["invalidation (after entry): exit on a close back through the MA"]
    assert after["value"] == "NOT APPLIED" and "exits" in after["detail"]
    # The before-entry rule stays the finder's disclosure (NOT READ), carried through.
    assert rubric["invalidation (before entry): skip if earnings within 5 days"]["value"] == "NOT READ"
    assert rubric["secondary metric: max drawdown"]["value"] == "NOT COMPUTED"
    # A split look drops the finder's one-sided direction line: "direction split" owns it.
    assert "direction" not in rubric and rubric["direction split"]["source"] == "default"
    assert rubric["cost"]["source"] == "default"
    override, _ = run_look(constrained, frame, tmp_path / "b", cost_bps=25.0)
    cost = {r["parameter"]: r for r in override["rubric"]}["cost"]
    assert cost["source"] == "run option" and "25" in cost["value"]
    assert override["cost_round_trip_bps"] == 25.0


def test_verdict_is_three_way_and_never_calls_underpowered_dead():
    assert verdict(0.05, 0.10, hurdle=0.02, sign=1).startswith("looks alive")
    assert verdict(-0.10, -0.05, hurdle=0.02, sign=1).startswith("looks inverted")
    assert verdict(-0.01, 0.01, hurdle=0.02, sign=1).startswith("looks dead")
    # Spans zero but reaches past the band: underpowered, never dead (three-verdict rule).
    assert verdict(-0.01, 0.10, hurdle=0.02, sign=1).startswith("inconclusive")
    # Excludes zero but can't clear the hurdle, and doesn't fit inside the band either.
    assert verdict(0.01, 0.10, hurdle=0.05, sign=1).startswith("inconclusive")
    assert verdict(float("nan"), float("nan"), hurdle=0.02, sign=1).startswith("inconclusive")


def test_cost_hurdle_counts_fired_events_not_only_c2_scorable_ones(tmp_path):
    # Blank one event's momentum: it can't be C2-scored, but it fired and the trader
    # pays for it — the hurdle must not shrink because the control bookkeeping did.
    frame = effect_panel(step=0.02)
    matches = find_first_touch(spec(), frame).matches
    evt = frame[frame["ticker"] == "EVT"].reset_index(drop=True)
    signal_pos = evt.index[evt["date"] == matches[1].date][0]
    event_date = evt.loc[signal_pos + 1, "date"]
    frame.loc[(frame["ticker"] == "EVT") & (frame["date"] == event_date), "mom_12_1"] = float("nan")
    result, _ = run_look(spec(), frame, tmp_path)
    (cell_,) = result["cells"]
    assert cell_["n_events"] == N_SIGNALS - 1 and cell_["n_events_fired"] == N_SIGNALS
    years = (frame["date"].max() - frame["date"].min()).days / 365.25
    assert cell_["signals_per_ticker_year"] == pytest.approx(N_SIGNALS / (years * 9))


def test_too_few_dates_still_reports_real_effective_n_and_valid_json(tmp_path):
    # 4 event dates < the 10-row block floor: no CI, but the C2 point and the real
    # distinct-date count are still reported (invariant #6 — 0 would be indistinguishable
    # from no observations), the verdict is inconclusive, and result.json stays strict
    # JSON (NaN must land as null, or nothing outside Python parses the artifact).
    result, _ = run_look(spec(), effect_panel(step=0.02, n_signals=4), tmp_path)
    (cell_,) = result["cells"]
    assert cell_["delta_c2"] == pytest.approx(0.02, abs=1e-9)
    assert pd.isna(cell_["ci_low"]) and cell_["effective_n_dates"] == 4
    assert cell_["verdict"].startswith("inconclusive")
    text = (tmp_path / "session" / "result.json").read_text()
    parsed = json.loads(text, parse_constant=lambda c: pytest.fail(f"non-JSON constant {c}"))
    assert parsed["cells"][0]["ci_low"] is None


def test_finder_skips_the_near_miss_rings_when_asked():
    # The look only consumes matches; near_misses=False must change nothing about them
    # (or the refusals — the degeneracy guard runs either way), only skip the ring cost.
    frame = effect_panel()
    full = find_first_touch(spec(), frame)
    lean = find_first_touch(spec(), frame, near_misses=False)
    assert lean.matches == full.matches and lean.rubric == full.rubric
    assert lean.near_misses == ()
    with pytest.raises(GroundingError, match="degenerates"):
        find_first_touch(spec(size=Size(normalisation="atr", min=0.3)), frame, near_misses=False)


def test_waterfall_runs_on_one_common_row_set(tmp_path):
    # With controls flat at 0 and the event stratum containing exactly the event ticker
    # plus its two same-bucket controls, C1 and C2 agree exactly; C0's baseline includes
    # the event rows themselves, so it is diluted below them — the documented
    # c0 = (1 - p) * pooled relationship, evidence all three ran on the same rows.
    result, _ = run_look(spec(), effect_panel(step=0.02), tmp_path)
    (cell,) = result["cells"]
    assert cell["delta_c1"] == pytest.approx(cell["delta_c2"], abs=1e-12)
    assert 0 < cell["delta_c0"] < cell["delta_c2"]
