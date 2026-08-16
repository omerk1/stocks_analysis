from unittest.mock import MagicMock, patch

import pytest

from src.data_processing.fred_client import FredClient


def _make_response(observations):
    response = MagicMock()
    response.json.return_value = {"observations": observations}
    response.raise_for_status.return_value = None
    return response


def _make_error_response(error_message):
    response = MagicMock()
    response.json.return_value = {"error_code": 400, "error_message": error_message}
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


@patch("src.data_processing.fred_client.requests.get")
def test_get_series_first_release_shapes_dataframe(mock_get):
    mock_get.return_value = _make_response(
        [
            {"date": "2020-01-01", "value": "22768.866", "realtime_start": "2020-04-25", "realtime_end": "2020-05-29"},
            {"date": "2020-04-01", "value": "22918.739", "realtime_start": "2020-07-25", "realtime_end": "2020-08-28"},
        ]
    )

    client = FredClient(api_key="fake-key")
    df = client.get_series_first_release("GDPC1")

    assert list(df.columns) == ["published_at", "first_published_value"]
    assert list(df["published_at"]) == ["2020-04-25", "2020-07-25"]
    assert list(df["first_published_value"]) == [22768.866, 22918.739]


@patch("src.data_processing.fred_client.requests.get")
def test_get_series_first_release_drops_missing_value_sentinel(mock_get):
    mock_get.return_value = _make_response(
        [
            {"date": "2020-01-01", "value": ".", "realtime_start": "2020-04-25", "realtime_end": "2020-05-29"},
            {"date": "2020-04-01", "value": "22918.739", "realtime_start": "2020-07-25", "realtime_end": "2020-08-28"},
        ]
    )

    client = FredClient(api_key="fake-key")
    df = client.get_series_first_release("GDPC1")

    assert len(df) == 1
    assert df["first_published_value"].iloc[0] == 22918.739


@patch("src.data_processing.fred_client.requests.get")
def test_get_series_first_release_returns_empty_frame_on_fred_error(mock_get):
    # e.g. the real vintage-date-cap-exceeded error DFF/DGS10/etc. hit --
    # an expected outcome for some series, not a raised exception.
    mock_get.return_value = _make_error_response(
        "Bad Request.  There are 5087 vintage dates in the specified real-time period."
    )

    client = FredClient(api_key="fake-key")
    df = client.get_series_first_release("DGS10")

    assert df.empty
    assert list(df.columns) == ["published_at", "first_published_value"]


@patch("src.data_processing.fred_client.requests.get")
def test_get_series_first_release_passes_output_type_and_wide_realtime_range(mock_get):
    mock_get.return_value = _make_response([])

    client = FredClient(api_key="fake-key")
    client.get_series_first_release("GDPC1", start="2020-01-01", end="2020-12-31")

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["output_type"] == 4
    assert kwargs["params"]["realtime_start"] == "1776-07-04"
    assert kwargs["params"]["realtime_end"] == "9999-12-31"
    assert kwargs["params"]["observation_start"] == "2020-01-01"
    assert kwargs["params"]["observation_end"] == "2020-12-31"
