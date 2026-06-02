from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient

        from app.main import app
        with TestClient(app) as c:
            yield c


def _row(d):
    r = MagicMock()
    r._mapping = d
    return r


@patch("app.routes.profiles.execute_sql")
def test_queue_orders_no_profile_first(mock_sql, client):
    mock_sql.return_value = [
        _row({"symbol": "AAPL", "bucket": "long_term", "has_profile": True,
              "reviewed_at": "2020-01-01T00:00:00+00:00", "stale": True, "changed": False}),
        _row({"symbol": "NVDA", "bucket": "long_term", "has_profile": False,
              "reviewed_at": None, "stale": False, "changed": False}),
    ]
    r = client.get("/profiles?queue=1&bucket=long_term")
    assert r.status_code == 200
    items = r.json()["queue"]
    assert items[0]["symbol"] == "NVDA"        # no-profile first
    assert items[0]["reason"] == "no_profile"
    assert items[1]["reason"] == "stale"
