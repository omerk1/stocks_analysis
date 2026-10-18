import itertools

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from src.llm.guidance import prompt, sample
from src.llm.guidance.schema import GuidanceItem, ReleaseLabel

SECTORS = [f"S{k:02d}" for k in range(11)]
YEARS = range(sample.FIRST_YEAR, sample.LAST_YEAR + 1)


def frame(per_cell: int = 3, drop=lambda year, sector, size: False) -> pd.DataFrame:
    rows, n = [], 0
    for year, sector, size in itertools.product(YEARS, SECTORS, sample.SIZES):
        if drop(year, sector, size):
            continue
        for _ in range(per_cell):
            rows.append({"ticker": f"T{n}", "cik": n, "year": year, "sector": sector, "size": size,
                         "market_cap": 5e9})
            n += 1
    return pd.DataFrame(rows)


def test_size_buckets():
    assert sample.size_bucket(12e9) == "large"
    assert sample.size_bucket(10e9) == "large"
    assert sample.size_bucket(3e9) == "mid"
    assert sample.size_bucket(1.9e9) is None
    assert sample.size_bucket(np.nan) is None


def test_cap_is_the_last_close_and_unknown_when_stale():
    days = pd.bdate_range("2015-01-01", "2015-12-31")
    cap = pd.Series(np.arange(len(days), dtype=float), index=days)
    cap = cap[cap.index <= "2015-06-30"]  # prices stop mid-year
    shares = pd.DatetimeIndex(["2014-12-31"])
    ends = pd.DatetimeIndex(["2014-12-31", "2015-03-31", "2015-03-29", "2015-07-03", "2015-09-30"])
    got = sample.cap_at(cap, shares, ends)
    assert np.isnan(got[0])  # before the first close
    assert got[1] == cap["2015-03-31"]
    assert got[2] == cap["2015-03-27"]  # a Sunday end takes Friday's close
    assert got[3] == cap["2015-06-30"]  # 3 days stale: fine
    assert np.isnan(got[4])  # 3 months stale: unknown
    old_shares = pd.DatetimeIndex(["2013-06-30"])
    assert np.isnan(sample.cap_at(cap, old_shares, pd.DatetimeIndex(["2015-03-31"]))[0])
    late_shares = pd.DatetimeIndex(["2015-05-01"])
    assert np.isnan(sample.cap_at(cap, late_shares, pd.DatetimeIndex(["2015-03-31"]))[0])


def test_draw_is_balanced_distinct_and_repeatable():
    s, notes = sample.draw(frame())
    assert len(s) == sample.N_RELEASES and not notes
    assert s["ticker"].is_unique
    assert s.groupby(["year", "sector", "size"]).ngroups == len(s)  # one release per cell
    assert set(s["year"].value_counts()) <= {4, 5}
    assert set(s["sector"].value_counts()) <= {4, 5}
    assert abs((s["size"] == "large").sum() - (s["size"] == "mid").sum()) <= 2
    assert (s.groupby("year")["size"].apply(lambda x: (x == "large").sum() - (x == "mid").sum()).abs() <= 1).all()
    again, _ = sample.draw(frame())
    pd.testing.assert_frame_equal(s, again)
    other, _ = sample.draw(frame(), seed=sample.SEED + 1)
    assert set(other["ticker"]) != set(s["ticker"])


def test_draw_never_repeats_a_company_across_cells():
    f = frame()
    f["cik"] = f.index % 7  # only 7 companies in all, each under many tickers (share classes)
    s, notes = sample.draw(f)
    assert s["cik"].is_unique and len(s) == 7
    assert sum("skipped" in n for n in notes) == sample.N_RELEASES - 7


def test_empty_size_falls_back_to_the_other_size():
    s, notes = sample.draw(frame(drop=lambda year, sector, size: size == "mid"))
    assert len(s) == sample.N_RELEASES and (s["size"] == "large").all()
    assert len(notes) == (s["target_size"] == "mid").sum() > 0


def test_index_url():
    assert sample.index_url(320193, "0001193125-12-435506") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000119312512435506/0001193125-12-435506-index.htm")


def item(**kw) -> dict:
    base = dict(metric="eps", metric_text="adjusted EPS", period="year", period_text="fiscal 2015",
                shape="range", low=2.1, high=2.2, unit="USD per share", basis="adjusted",
                revision="raised", evidence="...")
    return {**base, **kw}


@pytest.mark.parametrize("kw", [
    dict(shape="range", low=2.2, high=2.1),
    dict(shape="point", low=2.1, high=2.2),
    dict(shape="floor", low=2.1, high=2.2),
    dict(shape="ceiling", low=2.1, high=None),
    dict(shape="qualitative", low=2.1, high=None),
    dict(revision="up"),
    dict(confidence=0.9),
    dict(revision="withdrawn"),  # withdrawn is always one qualitative item
])
def test_item_rejects_inconsistent_fields(kw):
    with pytest.raises(ValidationError):
        GuidanceItem(**item(**kw))


@pytest.mark.parametrize("kw", [
    dict(), dict(shape="point", low=2.1, high=2.1), dict(shape="floor", low=5, high=None),
    dict(shape="ceiling", low=None, high=5), dict(shape="qualitative", low=None, high=None, revision="withdrawn"),
])
def test_item_accepts_consistent_fields(kw):
    GuidanceItem(**item(**kw))


def test_presence_matches_items():
    ReleaseLabel(guidance_present=False, items=[])
    ReleaseLabel(guidance_present=True, items=[item()])
    with pytest.raises(ValidationError):
        ReleaseLabel(guidance_present=True, items=[])
    with pytest.raises(ValidationError):
        ReleaseLabel(guidance_present=False, items=[item()])


def test_prompt_v1_is_frozen():
    # v1 is never edited; a changed prompt is a new version (prompt.py docstring).
    assert prompt.PROMPT_VERSION == "v1"
    assert prompt.fingerprint() == "731b0d85cce55504f181de62ca370a9d2de7966744834270d4faee1eb6042a8b"
