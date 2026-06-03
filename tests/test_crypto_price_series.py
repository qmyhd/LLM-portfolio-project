from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd


def test_get_crypto_price_series_maps_symbol_and_returns_closes():
    idx = pd.to_datetime(["2026-05-01", "2026-05-02"])
    hist = pd.DataFrame({"Close": [100.0, 110.0]}, index=idx)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        import importlib

        import src.market_data_service as mds
        importlib.reload(mds)  # ensure a clean cache for the assertion
        series = mds.get_crypto_price_series("BTC", date(2026, 5, 1), date(2026, 5, 2))

    assert series == {"2026-05-01": 100.0, "2026-05-02": 110.0}
    # _yf_symbol maps BTC -> BTC-USD
    mock_yf.Ticker.assert_called_once_with("BTC-USD")


def test_get_crypto_price_series_empty_on_failure():
    mock_yf = MagicMock()
    mock_yf.Ticker.side_effect = RuntimeError("network down")
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        import importlib

        import src.market_data_service as mds
        importlib.reload(mds)
        series = mds.get_crypto_price_series("ETH", date(2026, 5, 1), date(2026, 5, 2))
    assert series == {}


def test_get_crypto_price_series_drops_nan_closes():
    import math

    # yfinance routinely returns a NaN close for an incomplete/sparse day.
    idx = pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"])
    hist = pd.DataFrame({"Close": [100.0, float("nan"), 110.0]}, index=idx)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        import importlib

        import src.market_data_service as mds
        importlib.reload(mds)
        series = mds.get_crypto_price_series("BTC", date(2026, 5, 1), date(2026, 5, 3))

    # The NaN day is dropped (matching the equity path's dropna), so it never
    # corrupts the return-series index / produces invalid JSON.
    assert series == {"2026-05-01": 100.0, "2026-05-03": 110.0}
    assert all(not math.isnan(v) for v in series.values())
