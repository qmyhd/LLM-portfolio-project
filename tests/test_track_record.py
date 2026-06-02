from datetime import datetime
from unittest.mock import MagicMock, patch


def _row(d):
    r = MagicMock()
    r._mapping = d
    return r


@patch("app.track_record.execute_sql")
def test_track_record_realized_and_winrate(mock_sql):
    # One symbol: BUY 10 @100, SELL 10 @120 (closed, +20%). Then a position row.
    activities = [
        _row({"id": "a1", "symbol": "AAPL", "side": "BUY", "price": 100.0, "units": 10,
              "amount": 1000.0, "fee": 0.0, "executed_at": datetime(2026, 1, 2), "description": None}),
        _row({"id": "a2", "symbol": "AAPL", "side": "SELL", "price": 120.0, "units": 10,
              "amount": 1200.0, "fee": 0.0, "executed_at": datetime(2026, 2, 1), "description": None}),
    ]
    positions = []  # nothing held now
    all_positions = []
    mock_sql.side_effect = [activities, [], positions, all_positions]

    from app.track_record import compute_stock_track_record
    tr = compute_stock_track_record("AAPL", None)

    assert tr["symbol"] == "AAPL"
    assert tr["tradeCount"] == 2
    assert tr["winRate"] == 100.0          # the single closed SELL was profitable
    assert round(tr["realizedPnlPct"], 1) == 20.0
    assert tr["avgHoldDays"] == 30          # Jan 2 -> Feb 1
    assert tr["currentQty"] == 0.0


@patch("app.track_record.execute_sql")
def test_track_record_empty(mock_sql):
    mock_sql.side_effect = [[], [], [], []]
    from app.track_record import compute_stock_track_record
    tr = compute_stock_track_record("ZZZZ", None)
    assert tr["tradeCount"] == 0
    assert tr["realizedPnlPct"] == 0.0
    assert tr["winRate"] == 0.0
