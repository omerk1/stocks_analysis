"""The cache builders' `--open-holdout` (`cli.py`) and the guard that keeps a
build from writing over a cache from the other side of the boundary
(`dataset.check_cache_target`). Nothing here reads past 2021-12-31: the
builders are stubbed, and the guard runs before any read."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.models import cli, dataset
from src.models.dataset import HoldoutError
from src.models.features import cache, level_cache


def _manifest(path: Path, **fields) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields))
    return path


def test_check_cache_target_refuses_the_other_side(tmp_path):
    dataset.check_cache_target(tmp_path / "none.json", open_holdout=True)   # nothing there yet
    dev = _manifest(tmp_path / "dev.json", open_holdout=False)
    held = _manifest(tmp_path / "held.json", open_holdout=True)
    legacy = _manifest(tmp_path / "legacy.json", end="2021-12-31")          # predates the field: dev
    dataset.check_cache_target(dev, open_holdout=False)
    dataset.check_cache_target(held, open_holdout=True)
    for path, opens in ((dev, True), (legacy, True), (held, False)):
        with pytest.raises(HoldoutError, match="another --out"):
            dataset.check_cache_target(path, open_holdout=opens)


def test_each_builder_checks_its_target_before_reading(tmp_path):
    """conn=None: a builder that got past the guard would fail on the read."""
    feats = _manifest(tmp_path / "f" / "model_features.json", open_holdout=False)
    universe = pd.DataFrame({"ticker": ["A"], "date": [pd.Timestamp("2021-06-01")], "eligible": [True]})
    with pytest.raises(HoldoutError, match="another --out"):
        cache.build_feature_cache(None, universe, feats.parent, open_holdout=True)
    labels = _manifest(dataset.label_path(tmp_path / "l", 21).with_suffix(".json"), open_holdout=False)
    with pytest.raises(HoldoutError, match="another --out"):
        dataset.build_labels(None, universe[["ticker", "date"]], 21, tmp_path / "l", open_holdout=True)
    assert labels.exists()
    _manifest(tmp_path / "v" / level_cache.MANIFEST, open_holdout=False)
    with pytest.raises(HoldoutError, match="another --out"):
        level_cache.build_level_cache(None, ["A"], tmp_path / "v", "2026-11-06", open_holdout=True)


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(cli, "_read_only", lambda path: pytest.fail("opened the database"))


@pytest.mark.parametrize("argv", [
    ["build-features", "--db", "x", "--out", "o"], ["build-levels", "--db", "x", "--out", "o"],
    ["build-labels", "--db", "x", "--out", "o"], ["vendor-check", "--db", "x"]])
def test_open_holdout_needs_an_end_past_the_boundary(no_db, argv):
    with pytest.raises(SystemExit, match="nothing to open"):
        cli.main([*argv, "--open-holdout"])
    with pytest.raises(SystemExit, match="nothing to open"):
        cli.main([*argv, "--open-holdout", "--end", "2021-12-31"])


@pytest.mark.parametrize("command", ["build-levels", "build-labels"])
def test_open_holdout_needs_an_explicit_out(no_db, command):
    with pytest.raises(SystemExit, match="explicit --out"):
        cli.main([command, "--db", "x", "--end", "2026-11-06", "--open-holdout"])


class _Conn:
    def close(self):
        pass


@pytest.fixture
def stubs(monkeypatch):
    """Every read and build the commands make, recording `open_holdout`."""
    seen = []

    def universe_mask(conn, start, end, indices=("sp500",), open_holdout=False):
        seen.append(("universe", open_holdout))
        return pd.DataFrame({"ticker": ["A"], "date": [pd.Timestamp(end)], "eligible": [True], "has_bars": [True]})

    def build_feature_cache(conn, universe, out, specs=None, open_holdout=False, **kw):
        seen.append(("build_features", open_holdout, None if specs is None else len(specs)))
        return Path(out) / cache.CACHE_NAME

    def read_feature_cache(out, open_holdout=False):
        seen.append(("read_features", open_holdout))
        f = pd.DataFrame()
        f.attrs["manifest"] = {"n_rows": 1, "n_tickers": 1, "start": "s", "end": "e", "price_sources": {},
                               "missing_share": {}}
        return f

    def build_labels(conn, rows, h, out, open_holdout=False):
        seen.append(("build_labels", open_holdout))
        return dataset.label_path(out, h)

    def read_labels(out, h, open_holdout=False):
        seen.append(("read_labels", open_holdout))
        f = pd.DataFrame()
        f.attrs["manifest"] = {"n_rows": 1, "n_tickers": 1, "n_disputed_dropped": 0, "disputes": "d"}
        return f

    def build_level_cache(conn, tickers, out, end, workers=4, open_holdout=False, progress=print):
        seen.append(("build_levels", open_holdout))
        return {"last_run": {"n_tickers": 1, "cpu_hours": 0.0, "failed": 0}, "n_tickers": 1, "rows": {},
                "price_sources": {}, "no_bars": [], "failed": {}}

    monkeypatch.setattr(cli, "_read_only", lambda path: _Conn())
    monkeypatch.setattr(dataset, "universe_mask", universe_mask)
    monkeypatch.setattr(dataset, "build_labels", build_labels)
    monkeypatch.setattr(dataset, "read_labels", read_labels)
    monkeypatch.setattr(cache, "build_feature_cache", build_feature_cache)
    monkeypatch.setattr(cache, "read_feature_cache", read_feature_cache)
    monkeypatch.setattr(level_cache, "build_level_cache", build_level_cache)
    return seen


@pytest.mark.parametrize("opens", [False, True])
def test_the_flag_reaches_every_read_and_build(stubs, tmp_path, opens):
    end = ["--end", "2026-11-06", "--open-holdout"] if opens else []
    out = ["--out", str(tmp_path)]
    assert cli.main(["build-features", "--db", "x", *out, *end]) == 0
    assert cli.main(["build-labels", "--db", "x", *out, "--horizons", "21", *end]) == 0
    assert cli.main(["build-levels", "--db", "x", *out, *end]) == 0
    assert stubs == [("universe", opens), ("build_features", opens, None), ("read_features", opens),
                     ("universe", opens), ("build_labels", opens), ("read_labels", opens),
                     ("universe", opens), ("build_levels", opens)]


def test_build_features_scorecard_builds_its_columns_only(stubs, tmp_path):
    from src.models import trading
    from src.models.features import registry
    specs = cli.scorecard_specs("HT1")
    sc = trading.PREREGISTERED["HT1"]
    assert {registry.model_input(s) for s in specs} == set(sc.model_columns)   # B4 is inside the 24
    assert not any(registry.is_detector(s) for s in specs)                     # no level snapshots needed
    assert cli.main(["build-features", "--db", "x", "--out", str(tmp_path), "--scorecard", "HT1"]) == 0
    assert ("build_features", False, len(specs)) in stubs
    with pytest.raises(SystemExit, match="no pre-registered scorecard"):
        cli.scorecard_specs("nope")
