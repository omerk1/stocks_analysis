import json
from datetime import datetime, timezone

import pytest

from src.llm.strategy_spec import unsupported
from src.llm.strategy_spec.schema import StrategySpec, UnsupportedRequest


def _spec(*items):
    return StrategySpec(name="idea", unsupported=[UnsupportedRequest(**i) for i in items])


INTRADAY = dict(requested="15-minute bars", field="timeframe", reason="unsupported_timeframe")
EARNINGS = dict(requested="Earnings surprise", field="supporting_signals", reason="unsupported_data",
                detail="no earnings data")


def test_log_appends_one_line_per_request(tmp_path):
    path = tmp_path / "llm" / "log.jsonl"
    now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    assert unsupported.log_unsupported(_spec(INTRADAY, EARNINGS), idea="buy beats", path=path, now=now) == 2
    assert unsupported.log_unsupported(_spec(INTRADAY), path=path, now=now) == 1
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 3
    assert rows[1] == {"time": "2026-10-13T12:00:00+00:00", "spec_name": "idea", "idea": "buy beats",
                       **EARNINGS}
    assert rows[2]["idea"] is None and rows[2]["detail"] is None


def test_a_request_repeated_within_one_spec_is_logged_once(tmp_path):
    path = tmp_path / "log.jsonl"
    repeat = {**INTRADAY, "requested": "15-Minute  bars", "field": "trigger"}
    assert unsupported.log_unsupported(_spec(INTRADAY, repeat, EARNINGS), path=path) == 2
    assert [json.loads(line)["field"] for line in path.read_text().splitlines()] == ["timeframe",
                                                                                     "supporting_signals"]


def test_naive_time_is_refused(tmp_path):
    with pytest.raises(ValueError, match="timezone-aware"):
        unsupported.log_unsupported(_spec(INTRADAY), path=tmp_path / "log.jsonl", now=datetime(2026, 10, 13))


def test_a_spec_without_unsupported_requests_writes_nothing(tmp_path):
    path = tmp_path / "log.jsonl"
    assert unsupported.log_unsupported(StrategySpec(), path=path) == 0
    assert not path.exists()


def test_damaged_line_is_skipped_with_a_warning(tmp_path):
    path = tmp_path / "log.jsonl"
    unsupported.log_unsupported(_spec(INTRADAY), path=path)
    with path.open("a") as f:
        f.write('{"time": "2026-10-1\n[1, 2]\n')
    unsupported.log_unsupported(_spec(EARNINGS), path=path)
    with pytest.warns(UserWarning, match="unreadable line"):
        rows = unsupported.read_log(path)
    assert [r["requested"] for r in rows] == ["15-minute bars", "Earnings surprise"]


def test_summary_groups_by_wording_and_reason_most_requested_first():
    rows = [
        {"time": "2026-10-01T00:00:00+00:00", "requested": "Earnings surprise", "field": "supporting_signals",
         "reason": "unsupported_data"},
        {"time": "2026-10-03T00:00:00+00:00", "requested": "earnings  SURPRISE", "field": "trigger",
         "reason": "unsupported_data"},
        {"time": "2026-10-02T00:00:00+00:00", "requested": "15-minute bars", "field": "timeframe",
         "reason": "unsupported_timeframe"},
    ]
    lines = unsupported.summarise(rows)
    assert len(lines) == 2
    assert lines[0].split() == ["2", "unsupported_data", "supporting_signals,trigger", "last", "2026-10-03",
                                "earnings", "surprise"]
    assert lines[1].split()[0] == "1" and lines[1].endswith("15-minute bars")
    assert unsupported.summarise(rows, top=1) == lines[:1]


def test_cli_summary_reads_the_default_log(tmp_path, monkeypatch, capsys):
    path = tmp_path / "log.jsonl"
    monkeypatch.setattr(unsupported, "default_log_path", lambda: path)
    unsupported.log_unsupported(_spec(INTRADAY), path=path)
    unsupported.log_unsupported(_spec(INTRADAY), path=path)
    unsupported.main(["summary", "--top", "5"])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"log: {path} (2 requests)"
    assert out[1].split()[:2] == ["2", "unsupported_timeframe"]


def test_default_log_is_in_the_main_checkouts_data_dir():
    path = unsupported.default_log_path()
    assert path.name == "unsupported_requests.jsonl"
    assert path.parent.parts[-2:] == ("data", "llm")
    assert ".claude" not in path.parts  # not inside a worktree
