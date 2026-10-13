"""Tests for scripts/list_trial_ids.py (prints one experiment's trial IDs from TRIALS.csv)."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "list_trial_ids.py"

spec = importlib.util.spec_from_file_location("list_trial_ids", SCRIPT)
list_trial_ids = importlib.util.module_from_spec(spec)
spec.loader.exec_module(list_trial_ids)


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """Run main() against a temp TRIALS.csv; returns (exit code, stdout, stderr)."""

    def _run(experiment_id, rows="S1,t1\nS1b,t2\nS1,t3\nS2,t4\n"):
        csv_path = tmp_path / "TRIALS.csv"
        csv_path.write_text("experiment_id,trial_id\n" + rows)
        monkeypatch.setattr(list_trial_ids, "TRIALS_CSV", csv_path)
        monkeypatch.setattr(sys, "argv", ["list_trial_ids.py", experiment_id])
        code = list_trial_ids.main()
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


def test_prints_matching_ids_space_separated_in_file_order(run):
    code, out, _ = run("S1")
    assert code == 0
    assert out == "t1 t3\n"


def test_match_is_exact_not_prefix(run):
    code, out, _ = run("S1b")
    assert code == 0
    assert out == "t2\n"


def test_unknown_experiment_returns_1_with_message_on_stderr(run):
    code, out, err = run("S9")
    assert code == 1
    assert out == ""
    assert "no trials for experiment_id 'S9'" in err


def test_real_trials_csv_has_expected_columns():
    # Guards the script's assumed schema against the real file.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "no-such-experiment"], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "KeyError" not in result.stderr
    assert "no trials for experiment_id" in result.stderr
