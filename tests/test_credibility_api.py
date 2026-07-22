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


# --------------------------------------------------------------------------- #
# E3 — credibility config: categories, tier multipliers, stock topic tags
# --------------------------------------------------------------------------- #


@patch("app.routes.credibility.execute_sql")
def test_get_categories_returns_list(mock_sql, client):
    mock_sql.return_value = [
        _row({"slug": "macro", "label": "Macro", "description": "Big picture",
              "sort_order": 0}),
        _row({"slug": "equities", "label": "Equities", "description": None,
              "sort_order": 1}),
    ]
    r = client.get("/credibility/categories")
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert len(cats) == 2
    assert cats[0]["slug"] == "macro"
    assert cats[0]["sortOrder"] == 0
    assert cats[1]["description"] is None


@patch("app.routes.credibility.transaction")
def test_put_categories_upserts_and_returns(mock_tx, client):
    conn = MagicMock()
    mock_tx.return_value.__enter__.return_value = conn

    r = client.put(
        "/credibility/categories",
        json={"categories": [
            {"slug": "macro", "label": "Macro", "description": "Big picture",
             "sortOrder": 0},
        ]},
    )
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert cats[0]["slug"] == "macro"
    assert cats[0]["label"] == "Macro"
    # transaction must have been used, with an upsert INSERT
    assert mock_tx.called
    sql_texts = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any("INSERT INTO credibility_categories" in s for s in sql_texts)
    assert any("ON CONFLICT (slug)" in s for s in sql_texts)


@patch("app.routes.credibility.execute_sql")
def test_get_tier_multipliers_returns_dict(mock_sql, client):
    mock_sql.return_value = [
        _row({"tier": "S", "multiplier": 1.5}),
        _row({"tier": "C", "multiplier": 0.8}),
    ]
    r = client.get("/credibility/tier-multipliers")
    assert r.status_code == 200
    mults = r.json()["multipliers"]
    assert mults["S"] == 1.5
    assert mults["C"] == 0.8


@patch("app.routes.credibility.transaction")
def test_put_tier_multipliers_400_on_invalid_tier(mock_tx, client):
    r = client.put(
        "/credibility/tier-multipliers",
        json={"multipliers": {"X": 1.2}},
    )
    assert r.status_code == 400
    assert "invalid tier" in r.json()["detail"]


@patch("app.routes.credibility.transaction")
def test_put_tier_multipliers_valid_returns(mock_tx, client):
    conn = MagicMock()
    mock_tx.return_value.__enter__.return_value = conn

    r = client.put(
        "/credibility/tier-multipliers",
        json={"multipliers": {"S": 1.5, "A": 1.2}},
    )
    assert r.status_code == 200
    assert r.json()["multipliers"] == {"S": 1.5, "A": 1.2}
    sql_texts = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any("INSERT INTO tier_multipliers" in s for s in sql_texts)


# (topic-tags route tests removed — the stock_topic_tags feature was cut.)
