from unittest.mock import MagicMock, patch

import pytest

from src.data_processing.fred_client import FredClient


def _make_response(observations):
    response = MagicMock()
    response.json.return_value = {"observations": observations}
    response.raise_for_status.return_value = None
    return response


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(ValueError):
        FredClient(api_key=None)


@patch("src.data_processing.fred_client.requests.get")
def test_get_series_shapes_series(mock_get):
    mock_get.return_value = _make_response(
        [
            {"date": "2024-01-01", "value": "20800.5"},
            {"date": "2024-02-01", "value": "20900.1"},
        ]
    )

    client = FredClient(api_key="fake-key")
    series = client.get_series("M2SL")

    assert len(series) == 2
    assert series.iloc[0] == 20800.5
    assert series.iloc[1] == 20900.1
    assert series.name == "M2SL"


@patch("src.data_processing.fred_client.requests.get")
def test_get_series_drops_missing_value_sentinel(mock_get):
    mock_get.return_value = _make_response(
        [
            {"date": "2024-01-01", "value": "100.0"},
            {"date": "2024-01-02", "value": "."},
            {"date": "2024-01-03", "value": "102.0"},
        ]
    )

    client = FredClient(api_key="fake-key")
    series = client.get_series("SP500")

    assert len(series) == 2
    assert list(series.values) == [100.0, 102.0]


@patch("src.data_processing.fred_client.requests.get")
def test_get_series_passes_date_range_params(mock_get):
    mock_get.return_value = _make_response([])

    client = FredClient(api_key="fake-key")
    client.get_series("DGS10", start="2020-01-01", end="2020-12-31")

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["observation_start"] == "2020-01-01"
    assert kwargs["params"]["observation_end"] == "2020-12-31"
