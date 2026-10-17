import json
from datetime import datetime, timedelta, timezone

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
                       "requested": "Earnings surprise", "reason": "unsupported_data",
                       "fields": ["supporting_signals"], "details": {"supporting_signals": ["no earnings data"]}}
    assert rows[2]["idea"] is None and rows[2]["details"] == {}


def test_one_request_under_two_fields_is_one_line_with_both(tmp_path):
    path = tmp_path / "log.jsonl"
    again = {**INTRADAY, "requested": "15-Minute  bars", "field": "trigger", "detail": "intraday entry"}
    bars = {**INTRADAY, "detail": "every bar"}
    assert unsupported.log_unsupported(_spec(INTRADAY, again, EARNINGS, bars), path=path) == 2
    first = json.loads(path.read_text().splitlines()[0])
    assert first["requested"] == "15-minute bars"
    assert first["fields"] == ["timeframe", "trigger"]
    # Each detail stays with the field it was given for.
    assert first["details"] == {"timeframe": ["every bar"], "trigger": ["intraday entry"]}


def test_a_same_field_repeat_keeps_its_detail(tmp_path):
    path = tmp_path / "log.jsonl"
    unsupported.log_unsupported(_spec(INTRADAY, {**INTRADAY, "detail": "intraday entry"}), path=path)
    row = json.loads(path.read_text())
    assert row["fields"] == ["timeframe"] and row["details"] == {"timeframe": ["intraday entry"]}


def test_time_is_stored_in_utc_and_naive_time_is_refused(tmp_path):
    path = tmp_path / "log.jsonl"
    unsupported.log_unsupported(_spec(INTRADAY), path=path,
                                now=datetime(2026, 10, 13, 1, tzinfo=timezone(timedelta(hours=3))))
    assert json.loads(path.read_text())["time"] == "2026-10-12T22:00:00+00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        unsupported.log_unsupported(_spec(INTRADAY), path=path, now=datetime(2026, 10, 13))


def test_a_spec_without_unsupported_requests_writes_nothing(tmp_path):
    path = tmp_path / "log.jsonl"
    assert unsupported.log_unsupported(StrategySpec(), path=path) == 0
    assert not path.exists()


def test_damaged_line_is_skipped_with_a_warning(tmp_path):
    path = tmp_path / "log.jsonl"
    unsupported.log_unsupported(_spec(INTRADAY), path=path)
    with path.open("a") as f:
        f.write('{"time": "2026-10-1\n[1, 2]\n')
        f.write('{"time": "2026-10-13T00:00:00", "requested": "x", "reason": "other", "fields": ["trigger"]}\n')
        f.write('{"time": "2026-10-13T00:00:00+00:00", "requested": "x", "reason": "other", "fields": []}\n')
        f.write('{"time": "2026-10-13T00:00:00+00:00", "requested": "x", "reason": "other", "fields": [null]}\n')
        ok = '{"time": "2026-10-13T00:00:00+00:00", "requested": "x", "reason": "other", "fields": ["trigger"]'
        f.write(ok + "}\n")  # no details: still counted, the summary doesn't need them
        for bad in ('["a flat list"]', '{"trigger": "a string"}', '{"trigger": [null]}', '{"trigger": []}',
                    '{"timeframe": ["not one of its fields"]}'):
            f.write(f'{ok}, "details": {bad}}}\n')
        f.write(ok + ', "details": null}\n')  # one shape for details: a dict, or no key
        good = json.loads(ok + "}")
        for bad in ({"reason": 5}, {"reason": " "}, {"requested": ""}, {"fields": [""]},
                    {"details": {"trigger": ["  "]}}):
            f.write(json.dumps({**good, **bad}) + "\n")
        # Shape only: a reason or field today's schema doesn't have still counts.
        f.write(ok.replace('"other"', '"since_renamed"') + "}\n")
        f.write(ok.replace('"trigger"', '"old_field"') + "}\n")
    unsupported.log_unsupported(_spec(EARNINGS), path=path)
    with pytest.warns(UserWarning, match="unreadable line") as caught:
        rows = unsupported.read_log(path)
    assert sum("unreadable line" in str(w.message) for w in caught) == 16
    assert [r["requested"] for r in rows] == ["15-minute bars", "x", "x", "x", "Earnings surprise"]
    assert all(isinstance(r["time"], str) for r in rows)  # rows as stored


def _row(time, requested, fields, reason="unsupported_data"):
    return {"time": time, "requested": requested, "fields": fields, "reason": reason}


def test_summary_groups_by_wording_and_reason_most_requested_first():
    rows = [
        _row("2026-10-12T23:00:00+00:00", "Earnings surprise", ["supporting_signals"]),
        _row("2026-10-13T01:00:00+03:00", "earnings  SURPRISE", ["trigger"]),  # 22:00 UTC, earlier
        _row("2026-10-02T00:00:00+00:00", "15-minute bars", ["timeframe"], "unsupported_timeframe"),
    ]
    lines = unsupported.summarise(rows)
    assert len(lines) == 2
    # Shown as the user first put it, not the folded grouping key.
    assert lines[0].split() == ["2", "unsupported_data", "supporting_signals,trigger", "last", "2026-10-12",
                                "Earnings", "surprise"]
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
