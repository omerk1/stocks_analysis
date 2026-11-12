"""The cache builders' `--open-holdout` (`cli.py`) and the directory claim that
keeps the two sides of the boundary apart (`dataset.claim_cache_dir`). Nothing
here reads past 2021-12-31: the builders are stubbed or refuse before any
read (conn=None: one that got past its checks would fail on the read)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.models import cli, dataset
from src.models.dataset import OPEN_MARKER, HoldoutError
from src.models.features import cache, level_cache, level_features

PAST = "2026-11-06"


def _dev_files(directory: Path) -> Path:
    """A dev cache, or one a dev build left before writing its manifest."""
    (directory / "sr_line").mkdir(parents=True)
    (directory / "sr_line" / "AAA.parquet").write_bytes(b"dev")
    return directory


def test_claim_cache_dir(tmp_path):
    held = tmp_path / "held"
    dataset.claim_cache_dir(held, open_holdout=True)        # new: claimed
    assert (held / OPEN_MARKER).exists()
    dataset.claim_cache_dir(held, open_holdout=True)        # resumable: its own
    with pytest.raises(HoldoutError, match="another --out"):
        dataset.claim_cache_dir(held, open_holdout=False)
    dev = _dev_files(tmp_path / "dev")
    dataset.claim_cache_dir(dev, open_holdout=False)
    assert not (dev / OPEN_MARKER).exists()
    with pytest.raises(HoldoutError, match="isn't empty"):
        dataset.claim_cache_dir(dev, open_holdout=True)
    assert (dev / "sr_line" / "AAA.parquet").read_bytes() == b"dev"
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / ".DS_Store").write_bytes(b"")    # what Finder leaves isn't a cache
    dataset.claim_cache_dir(tmp_path / "empty", open_holdout=True)
    with pytest.raises(ValueError, match="nothing to open"):
        dataset.check_open_end("2021-12-31", open_holdout=True)
    dataset.check_open_end("2021-12-31", open_holdout=False)


def _universe(end: str) -> pd.DataFrame:
    return pd.DataFrame({"ticker": ["A"], "date": [pd.Timestamp(end)], "eligible": [True]})


def test_each_builder_claims_its_directory_before_reading(tmp_path):
    with pytest.raises(HoldoutError, match="isn't empty"):
        cache.build_feature_cache(None, _universe(PAST), _dev_files(tmp_path / "f"), open_holdout=True,
                                  specs=cli.scorecard_specs("HT1"))   # no level columns: the claim decides
    with pytest.raises(HoldoutError, match="isn't empty"):
        dataset.build_labels(None, _universe(PAST)[["ticker", "date"]], 21, _dev_files(tmp_path / "l"),
                             open_holdout=True)
    with pytest.raises(HoldoutError, match="isn't empty"):
        level_cache.build_level_cache(None, ["A"], _dev_files(tmp_path / "v"), PAST, open_holdout=True)
    for d in ("f", "l", "v"):
        assert not (tmp_path / d / OPEN_MARKER).exists()


def test_each_builder_refuses_open_over_dev_dates(tmp_path):
    with pytest.raises(ValueError, match="nothing to open"):
        cache.build_feature_cache(None, _universe("2021-06-01"), tmp_path / "f", open_holdout=True)
    with pytest.raises(ValueError, match="nothing to open"):
        dataset.build_labels(None, _universe("2021-06-01")[["ticker", "date"]], 21, tmp_path / "l",
                             open_holdout=True)
    with pytest.raises(ValueError, match="nothing to open"):
        level_cache.build_level_cache(None, ["A"], tmp_path / "v", "2021-12-31", open_holdout=True)


def test_level_columns_read_a_snapshot_cache_from_their_own_side(tmp_path):
    dev_levels = _dev_files(tmp_path / "levels")
    with pytest.raises(HoldoutError, match="build-levels --open-holdout"):
        cache.build_feature_cache(None, _universe(PAST), tmp_path / "f", open_holdout=True, levels_root=dev_levels)
    assert not (tmp_path / "f").exists()                      # refused before the claim: nothing left behind
    held_levels = tmp_path / "held_levels"
    dataset.claim_cache_dir(held_levels, open_holdout=True)
    with pytest.raises(HoldoutError, match="a dev build reads a dev one"):
        cache.build_feature_cache(None, _universe("2021-06-01"), tmp_path / "g", levels_root=held_levels)


def test_levels_out_is_the_snapshot_caches_default():
    assert cli.LEVELS_OUT == level_features.DEFAULT_ROOT


@pytest.fixture
def no_db(monkeypatch):
    monkeypatch.setattr(cli, "_read_only", lambda path: pytest.fail("opened the database"))


@pytest.mark.parametrize("argv", [
    ["build-features", "--db", "x", "--out", "o", "--scorecard", "HT1"], ["build-levels", "--db", "x", "--out", "o"],
    ["build-labels", "--db", "x", "--out", "o"], ["vendor-check", "--db", "x"]])
def test_open_holdout_needs_an_end_past_the_boundary(no_db, argv):
    with pytest.raises(SystemExit, match="nothing to open"):
        cli.main([*argv, "--open-holdout"])
    with pytest.raises(SystemExit, match="nothing to open"):
        cli.main([*argv, "--open-holdout", "--end", "2021-12-31"])


@pytest.mark.parametrize("command", ["build-levels", "build-labels"])
def test_open_holdout_needs_an_explicit_out(no_db, command):
    with pytest.raises(SystemExit, match="explicit --out"):
        cli.main([command, "--db", "x", "--end", PAST, "--open-holdout"])


def test_open_feature_build_with_level_columns_needs_a_claimed_levels(no_db, tmp_path):
    argv = ["build-features", "--db", "x", "--out", str(tmp_path / "o"), "--end", PAST, "--open-holdout"]
    with pytest.raises(SystemExit, match="explicit --levels"):
        cli.main(argv)
    with pytest.raises(SystemExit, match="build-levels --open-holdout"):
        cli.main([*argv, "--levels", str(_dev_files(tmp_path / "levels"))])
    assert not (tmp_path / "o").exists()
    with pytest.raises(SystemExit, match="nothing to open"):   # the end is checked first
        cli.main(["build-features", "--db", "x", "--out", str(tmp_path / "o"), "--open-holdout"])


@pytest.mark.parametrize("command", ["build-features", "build-levels", "build-labels"])
def test_a_refused_directory_is_refused_before_the_database_opens(no_db, tmp_path, command):
    extra = ["--scorecard", "HT1"] if command == "build-features" else []
    with pytest.raises(SystemExit, match="isn't empty"):
        cli.main([command, "--db", "x", "--out", str(_dev_files(tmp_path / "dev")), "--end", PAST,
                  "--open-holdout", *extra])
    held = tmp_path / "held"
    dataset.claim_cache_dir(held, open_holdout=True)
    with pytest.raises(SystemExit, match="another --out"):
        cli.main([command, "--db", "x", "--out", str(held), *extra])


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
    end = ["--end", PAST, "--open-holdout"] if opens else []
    out = lambda name: ["--out", str(tmp_path / name)]
    assert cli.main(["build-features", "--db", "x", *out("f"), "--scorecard", "HT1", *end]) == 0
    assert cli.main(["build-labels", "--db", "x", *out("l"), "--horizons", "21", *end]) == 0
    assert cli.main(["build-levels", "--db", "x", *out("v"), *end]) == 0
    n = len(cli.scorecard_specs("HT1"))
    assert stubs == [("universe", opens), ("build_features", opens, n), ("read_features", opens),
                     ("universe", opens), ("build_labels", opens), ("read_labels", opens),
                     ("universe", opens), ("build_levels", opens)]
    assert all((tmp_path / d / OPEN_MARKER).exists() == opens for d in ("f", "l", "v"))


def test_a_build_that_fails_before_writing_gives_its_claim_back(stubs, monkeypatch, tmp_path):
    def no_trading_day(*a, **k):
        raise ValueError("nothing to open")                   # as an --end of 2022-01-01 would, inside the builder
    monkeypatch.setattr(dataset, "build_labels", no_trading_day)
    with pytest.raises(ValueError):
        cli.main(["build-labels", "--db", "x", "--out", str(tmp_path / "l"), "--end", PAST, "--open-holdout"])
    assert not (tmp_path / "l" / OPEN_MARKER).exists()
    held = tmp_path / "held"
    dataset.claim_cache_dir(held, open_holdout=True)           # a claim from an earlier run is kept
    with pytest.raises(ValueError):
        cli.main(["build-labels", "--db", "x", "--out", str(held), "--end", PAST, "--open-holdout"])
    assert (held / OPEN_MARKER).exists()


def test_build_features_scorecard_specs():
    from src.models import trading
    from src.models.features import registry
    specs = cli.scorecard_specs("HT1")
    sc = trading.PREREGISTERED["HT1"]
    assert {registry.model_input(s) for s in specs} == set(sc.model_columns)   # B4 is inside the 24
    assert not any(registry.is_detector(s) for s in specs)                     # no level snapshots needed
    with pytest.raises(SystemExit, match="no pre-registered scorecard"):
        cli.scorecard_specs("nope")
