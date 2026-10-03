import pandas as pd

from src.foundation.data_processing import market_cap
from src.foundation.data_processing import share_counts as sc

_Q = pd.to_datetime([f"20{y}-{m:02d}-01" for y in (18, 19, 20, 21) for m in (2, 5, 8, 11)])


def test_reference_picks_the_real_scale_even_when_bad_filings_are_the_majority():
    # Recent spin-off: three shell filings at 100 shares, then two real ones;
    # yfinance covers only the listed period. Count alone would trust the
    # shells and drop the real filings.
    idx = _Q[:5]
    series = pd.Series([100.0, 100.0, 100.0, 1.00e8, 1.01e8], index=idx)
    reference = pd.Series([1.00e8, 1.01e8], index=idx[3:])
    assert sc.drop_scale_runs(series, reference=reference).tolist() == [1.00e8, 1.01e8]
    # Seven filings 1,000x too big against five real ones: same story.
    series = pd.Series([3e11] * 7 + [3e8] * 5, index=_Q[:12])
    reference = pd.Series([3.0e8] * 5, index=_Q[7:12])
    assert sc.drop_scale_runs(series, reference=reference).tolist() == [3e8] * 5


def test_without_a_reference_an_implausibly_small_cluster_is_never_trusted():
    series = pd.Series([100.0, 100.0, 100.0, 1.00e8, 1.01e8], index=_Q[:5])
    assert sc.drop_scale_runs(series).tolist() == [1.00e8, 1.01e8]
    # ...but a bad majority inside the plausible range can't be told apart
    # without a reference: the majority is trusted (documented limit). The
    # ingest always passes the yfinance reference, so this only arises at
    # load time for a ticker that was stored without any overlap to check.
    series = pd.Series([3e11] * 7 + [3e8] * 5, index=_Q[:12])
    assert sc.drop_scale_runs(series).tolist() == [3e11] * 7


def test_clusters_that_overlap_the_reference_but_disagree_leave_the_series_alone():
    series = pd.Series([3e11] * 4 + [3e8] * 4, index=_Q[:8])
    reference = pd.Series([1e8] * 8, index=_Q[:8])  # agrees with neither scale
    assert sc.drop_scale_runs(series, reference=reference).tolist() == series.tolist()


def test_split_adjustment_exposes_a_run_hidden_by_forward_splits():
    # Real as-filed counts 6e8 -> 2.4e9 -> 2.44e10 through 4-for-1 and
    # 10-for-1 splits (40x for real), with two filings 1,000x the pre-split
    # count. As filed, 6.1e11 is only 25x the post-split level -- one
    # cluster, nothing judged. On a common split basis the run is 1,000x.
    idx = _Q[:10]
    v = [6.0e8, 6.0e8, 6.1e11, 6.2e11, 6.0e8, 2.4e9, 2.4e9, 2.44e9, 2.44e10, 2.45e10]
    series = pd.Series(v, index=idx)
    assert sc.drop_scale_runs(series).tolist() == v  # as filed: blind
    splits = pd.DataFrame({"execution_date": pd.to_datetime(["2019-04-01", "2019-12-15"]), "ratio": [4.0, 10.0]})
    kept = sc.drop_scale_runs(series, split_factor=market_cap.split_factor(idx, splits))
    assert kept.tolist() == [6.0e8, 6.0e8, 6.0e8, 2.4e9, 2.4e9, 2.44e9, 2.44e10, 2.45e10]


def test_a_run_straddling_a_split_is_dropped_whole_on_a_common_basis():
    # 1e8 x4, a 2-for-1 split, then two 1,000x filings of the post-split
    # count, then 2e8 x4. As filed the bad filings are 2,000x the earlier
    # neighbour and 1,000x the later one; on a common basis 1,000x both.
    idx = _Q[:10]
    v = [1e8] * 4 + [2.0e11, 2.0e11] + [2e8] * 4
    splits = pd.DataFrame({"execution_date": [pd.Timestamp("2019-01-15")], "ratio": [2.0]})
    kept = sc.drop_scale_runs(pd.Series(v, index=idx), split_factor=market_cap.split_factor(idx, splits))
    assert kept.tolist() == [1e8] * 4 + [2e8] * 4


def test_nearest_trusted_filing_is_by_date_not_by_row_position():
    # Irregular gaps: the bad filing sits 1 day after a trusted 1.0e8 and
    # 300 days before a trusted 2.5e8 (a 2.5x real change in between). By
    # position the two neighbours tie; by date it's the 1.0e8 one, and
    # 1.0e11 against it is a clean 1,000x.
    idx = pd.to_datetime(["2020-01-01", "2020-06-01", "2020-06-02", "2021-03-29", "2021-09-01"])
    series = pd.Series([1.0e8, 1.0e8, 1.0e11, 2.5e8, 2.5e8], index=idx)
    assert sc.drop_scale_runs(series).tolist() == [1.0e8, 1.0e8, 2.5e8, 2.5e8]


def test_non_positive_counts_are_left_alone_and_do_not_break_the_clustering():
    series = pd.Series([0.0, 1.0e8, 1.0e8, 1.0e11, 1.0e8], index=_Q[:5])
    assert sc.drop_scale_runs(series).tolist() == [0.0, 1.0e8, 1.0e8, 1.0e8]


def test_reconcile_market_cap_drops_a_mis_scaled_run_before_using_it():
    # CB 2010: two filings 1e6x too big. Caps must stay continuous.
    prices = pd.Series(10.0, index=pd.bdate_range("2010-01-04", periods=250))
    shares = pd.Series([3.36e8, 3.37e8, 3.38e14, 3.39e14, 3.39e8],
                       index=pd.to_datetime(["2010-02-01", "2010-04-01", "2010-06-01", "2010-08-02", "2010-11-01"]))
    caps = market_cap.reconcile_market_cap(prices, shares)["market_cap"].dropna()
    assert caps.max() < 3.4e9 and caps.min() > 3.3e9
