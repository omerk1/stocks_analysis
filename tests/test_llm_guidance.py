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
            rows.append({"ticker": f"T{n}", "year": year, "sector": sector, "size": size, "market_cap": 5e9})
            n += 1
    return pd.DataFrame(rows)


def test_size_buckets():
    assert sample.size_bucket(12e9) == "large"
    assert sample.size_bucket(10e9) == "large"
    assert sample.size_bucket(3e9) == "mid"
    assert sample.size_bucket(1.9e9) is None
    assert sample.size_bucket(np.nan) is None


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
    f["ticker"] = "SAME" + (f.index % 7).astype(str)  # only 7 companies in all
    s, notes = sample.draw(f)
    assert s["ticker"].is_unique and len(s) == 7
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
    assert prompt.fingerprint() == "f33ba93b80d8afa4d2c05a3a5179ae4c1a9781d1f8cb15ef7030c226e851cd5c"
