import pytest

from src.market_common.models import Direction, Pivot, PivotKind, Timeframe


def test_pivot_price_and_atr_at_pivot_are_read_only_aliases():
    # sr_lines predates this shared module and reads .price/.atr_at_pivot
    # throughout -- these aliases are what let it keep working unchanged.
    pivot = Pivot(
        kind=PivotKind.HIGH, timestamp="2020-01-01", value=123.5,
        confirmed_at="2020-01-05", threshold_at_pivot=4.5, bar_index=7,
    )

    assert pivot.price == 123.5
    assert pivot.atr_at_pivot == 4.5


def test_pivot_constructor_uses_the_new_field_names_not_the_aliases():
    # A `@property` is not a constructor kwarg -- confirms the dataclass
    # only accepts the real field names, so any code trying to construct
    # with the old price=/atr_at_pivot= kwargs fails loudly, not silently.
    with pytest.raises(TypeError):
        Pivot(kind=PivotKind.HIGH, timestamp="2020-01-01", price=100.0, confirmed_at="2020-01-01", atr_at_pivot=1.0)


def test_pivot_bar_index_defaults_to_zero():
    pivot = Pivot(kind=PivotKind.LOW, timestamp="2020-01-01", value=1.0, confirmed_at="2020-01-01", threshold_at_pivot=0.1)
    assert pivot.bar_index == 0


def test_pivot_to_dict_excludes_the_alias_properties():
    pivot = Pivot(
        kind=PivotKind.LOW, timestamp="2020-01-01", value=1.0,
        confirmed_at="2020-01-01", threshold_at_pivot=0.1,
    )
    d = pivot.to_dict()
    assert "value" in d and "threshold_at_pivot" in d
    assert "price" not in d and "atr_at_pivot" not in d


def test_timeframe_serializes_lowercase():
    assert Timeframe.DAILY.value == "daily"
    assert Timeframe.WEEKLY.value == "weekly"


def test_direction_serializes_lowercase():
    assert Direction.BULLISH.value == "bullish"
    assert Direction.BEARISH.value == "bearish"
