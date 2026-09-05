import pytest

from src.foundation.market_common.stats import DEFAULT_PERCENTILES, distribution_stats


def test_empty_input_reports_none_not_zero():
    stats = distribution_stats([])

    assert stats.n == 0
    assert stats.mean is None
    assert stats.median is None
    assert stats.winsorized_mean is None
    assert stats.std is None
    assert stats.risk_adjusted_return is None
    assert stats.percentiles == {p: None for p in DEFAULT_PERCENTILES}


def test_single_value_has_no_std_or_risk_adjusted_return():
    stats = distribution_stats([0.05])

    assert stats.n == 1
    assert stats.mean == pytest.approx(0.05)
    assert stats.median == pytest.approx(0.05)
    assert stats.std is None
    assert stats.risk_adjusted_return is None


def test_winsorized_mean_reins_in_a_single_outlier():
    values = [-0.02] * 99 + [30.0]
    stats = distribution_stats(values)

    assert stats.mean > 0
    assert stats.median == pytest.approx(-0.02)
    assert stats.winsorized_mean < 0


def test_winsorized_mean_equals_plain_mean_without_outliers():
    values = [0.01, 0.02, 0.03, 0.04, 0.05]
    stats = distribution_stats(values)

    assert stats.winsorized_mean == pytest.approx(stats.mean, abs=1e-9)


def test_risk_adjusted_return_is_mean_over_std():
    values = [0.01, 0.02, 0.03, 0.04, 0.05]
    stats = distribution_stats(values)

    assert stats.risk_adjusted_return == pytest.approx(stats.mean / stats.std)


def test_risk_adjusted_return_none_when_std_is_zero():
    stats = distribution_stats([0.02, 0.02, 0.02])

    assert stats.std == 0
    assert stats.risk_adjusted_return is None


def test_percentiles_cover_requested_quantiles():
    values = list(range(1, 101))  # 1..100
    stats = distribution_stats([float(v) for v in values], percentiles=(0.10, 0.90))

    assert stats.percentiles[0.10] == pytest.approx(10.9)
    assert stats.percentiles[0.90] == pytest.approx(90.1)
