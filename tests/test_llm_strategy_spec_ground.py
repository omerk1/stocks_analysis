"""The grounding session (step 4): sampling, the blind accept/reject loop, the reveal,
holdout refusal, and the chart truncation. Everything runs on the synthetic panel from
the finder tests — no API, no network, no cached data."""

import json
import random

import pandas as pd
import pytest

from src.llm.strategy_spec import charts
from src.llm.strategy_spec.finders import Candidate, GroundingError
from src.llm.strategy_spec.ground import ground, load_spec, pick_finder, sample
from src.models.dataset import HoldoutError
from tests.test_llm_strategy_spec_finders import MATCH, TOUCH_RING, panel, signal_date, spec


# --- loading and dispatch ----------------------------------------------------------


def test_load_spec_reads_bare_specs_and_elicitation_transcripts(tmp_path):
    bare = tmp_path / "spec.json"
    bare.write_text(spec().model_dump_json(exclude_none=True))
    assert load_spec(bare).uses == ["detector:ma.first_touch"]
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps(
        {"idea": "first touch", "turns": [], "spec": json.loads(spec().model_dump_json(exclude_none=True))}))
    assert load_spec(transcript).uses == ["detector:ma.first_touch"]


def test_pick_finder_refuses_clearly():
    assert pick_finder(spec()) == "detector:ma.first_touch"
    with pytest.raises(GroundingError, match="built so far"):
        pick_finder(spec(uses=["detector:pattern.vcp"]))
    with pytest.raises(GroundingError, match="no finder for"):
        pick_finder(spec(), override="detector:pattern.vcp")


# --- sampling ----------------------------------------------------------------------


def candidates(*specs: tuple[str, str]) -> tuple[Candidate, ...]:
    return tuple(Candidate(ticker, pd.Timestamp(date)) for ticker, date in specs)


def test_sample_spreads_across_years_on_distinct_dates():
    pool = candidates(
        ("A", "2015-03-02"), ("B", "2015-03-02"), ("C", "2015-06-01"),  # a loud year
        ("D", "2018-02-01"), ("E", "2020-09-01"))
    picked = sample(pool, 3, random.Random(0))
    assert {c.date.year for c in picked} == {2015, 2018, 2020}  # round-robin, not 2015-heavy
    assert len({c.date for c in picked}) == 3


def test_sample_prefers_unseen_tickers_and_respects_taken_dates():
    pool = candidates(("A", "2016-03-02"), ("A", "2016-04-01"), ("B", "2016-05-02"))
    picked = sample(pool, 2, random.Random(1))
    assert {c.ticker for c in picked} == {"A", "B"}  # not two dates of the same ticker
    taken = {pd.Timestamp("2016-03-02")}
    assert all(c.date not in taken for c in sample(pool, 3, random.Random(1), taken_dates=taken))


def test_sample_is_deterministic_under_a_seed_and_caps_at_the_population():
    pool = candidates(("A", "2015-03-02"), ("B", "2016-03-02"), ("C", "2017-03-02"))
    assert sample(pool, 2, random.Random(7)) == sample(pool, 2, random.Random(7))
    assert len(sample(pool, 10, random.Random(7))) == 3


# --- the session -------------------------------------------------------------------


def session_inputs():
    """Two matches in different years plus one near-miss, so a 2+1 round is exact."""
    frame = pd.concat([
        panel({"MAA": MATCH}, start="2015-01-02"),
        panel({"MBB": MATCH}, start="2016-01-04"),
        panel({"TCC": TOUCH_RING}, start="2017-01-03"),
    ], ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    return spec(), frame


def run(tmp_path, answer, **kwargs):
    test_spec, frame = session_inputs()
    prompts = []

    def ask(text):
        prompts.append(text)
        return answer(text)

    said = []
    result = ground(test_spec, frame, ask=ask, say=said.append, out_dir=tmp_path,
                    seed=42, matches_shown=2, near_misses_shown=1, **kwargs)
    return result, prompts, said, json.loads((tmp_path / "session.json").read_text())


def test_a_full_round_records_verdicts_examples_and_the_rubric(tmp_path):
    result, prompts, said, session = run(tmp_path, lambda text: "y")
    assert len(session["shown"]) == 3
    assert sorted(s["kind"] for s in session["shown"]) == ["match", "match", "near_miss"]
    assert all(s["verdict"] is True for s in session["shown"])
    assert session["population"]["matches"] == 2 and session["population"]["distinct_dates"] == 2
    assert [s["source"] for s in session["rubric"]].count("spec") >= 1  # away distance
    assert len(result.examples) == 3 and all(e.matches for e in result.examples)
    assert (tmp_path / "spec.json").exists()
    for shown in session["shown"]:
        assert (tmp_path / shown["chart"]).exists()
    # Accepting the near-miss is a disagreement: the reveal names the failed constraint.
    reveal = "\n".join(said)
    assert "near-miss you accepted" in reveal and "touch tolerance" in reveal
    assert session["clean_round"] is False


def test_a_clean_round_is_recognised(tmp_path):
    # The trader (who can't see kinds) happens to judge exactly as the definition does.
    answer = lambda text: "y" if "] M" in text else "n, never really touched"
    result, prompts, said, session = run(tmp_path, answer)
    assert session["clean_round"] is True
    assert "Clean round" in "\n".join(said)
    near = next(s for s in session["shown"] if s["kind"] == "near_miss")
    assert near["verdict"] is False and near["comment"] == "never really touched"
    assert [e.matches for e in result.examples].count(False) == 1


def test_the_loop_is_blind_until_the_reveal(tmp_path):
    # The on-disk session file sits next to the charts: while verdicts are being
    # collected it must not carry each instance's truth, or one glance tells the
    # trader which instances to reject.
    def peeking_answer(text):
        on_disk = json.loads((tmp_path / "session.json").read_text())
        # The population's near-miss *count* is fine (the 6+3 design is no secret);
        # per-instance truth is not.
        assert all("kind" not in row and "fails" not in row for row in on_disk["shown"])
        assert "clean_round" not in on_disk
        return "y"

    result, prompts, said, session = run(tmp_path, peeking_answer)
    final = json.loads((tmp_path / "session.json").read_text())
    assert [row["kind"] for row in final["shown"]]  # unblinded once the loop is over
    for prompt, shown in zip(prompts, session["shown"]):
        assert "near" not in prompt.lower() and "fails" not in prompt.lower()
        assert "near" not in shown["chart"].lower()
        html = (tmp_path / shown["chart"]).read_text()
        assert "near_miss" not in html and "fails" not in html
    # Reproducible presentation order under the same seed.
    order = [s["ticker"] for s in session["shown"]]
    _, _, _, again = run(tmp_path, lambda text: "y")
    assert [s["ticker"] for s in again["shown"]] == order


def test_stopping_early_keeps_what_was_answered(tmp_path):
    answers = iter(["y"])
    result, prompts, said, session = run(tmp_path, lambda text: next(answers, None))
    verdicts = [s["verdict"] for s in session["shown"]]
    assert verdicts.count(True) == 1 and verdicts.count(None) == 2
    assert len(result.examples) == 1
    assert session["clean_round"] is False  # an unfinished round is never clean
    # The unanswered instances' truth stays off disk even in the final save — the same
    # sample may be judged blind in a later round.
    for row in session["shown"]:
        assert ("kind" in row and "fails" in row) is (row["verdict"] is not None)


def test_unparseable_answers_stop_the_session(tmp_path):
    result, prompts, said, session = run(tmp_path, lambda text: "maybe")
    assert all(s["verdict"] is None for s in session["shown"])
    assert sum("Answer y or n" in line for line in said) == 2
    assert result.examples == []


def test_a_panel_reaching_past_the_holdout_is_refused(tmp_path):
    test_spec, _ = session_inputs()
    late = panel({"MAA": MATCH}, start="2022-01-03")
    with pytest.raises(HoldoutError):
        ground(test_spec, late, ask=lambda text: "y", say=lambda line: None, out_dir=tmp_path)


# --- charts ------------------------------------------------------------------------


def test_chart_window_truncates_right_after_the_trigger():
    bars = panel({"AAA": MATCH})
    trigger = signal_date(MATCH, 0.1)
    window = charts.chart_window(bars, trigger)
    position = bars.index[bars["date"] == trigger][0]
    assert window["date"].iloc[-1] == bars["date"].iloc[position + charts.FORWARD_BARS]
    assert len(window) <= charts.LOOKBACK_BARS + charts.FORWARD_BARS + 1
    with pytest.raises(ValueError, match="appears 0 times"):
        charts.chart_window(bars, pd.Timestamp("1999-01-04"))


def test_instance_chart_draws_candles_overlay_and_trigger():
    bars = panel({"AAA": MATCH}).assign(ma_display=100.0)
    trigger = signal_date(MATCH, 0.1)
    figure = charts.instance_chart(charts.chart_window(bars, trigger),
                                   "ma_display", "SMA 200", trigger, "AAA")
    kinds = [trace.__class__.__name__ for trace in figure.data]
    assert kinds == ["Candlestick", "Scatter", "Scatter"]
    assert figure.data[-1].x[0] == trigger
