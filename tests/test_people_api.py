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
# E1 — core CRUD + tiers + revisions
# --------------------------------------------------------------------------- #


@patch("app.routes.people.transaction")
def test_create_appends_revision(mock_tx, client):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (1,)
    mock_tx.return_value.__enter__.return_value = conn

    r = client.post(
        "/people",
        json={
            "fullName": "Jane Analyst",
            "displayName": "Jane",
            "role": "trader",
            "tiers": [{"categorySlug": "macro", "tier": "A", "muted": False}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert body["fullName"] == "Jane Analyst"
    # a revision INSERT must have run
    sql_texts = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any("person_revisions" in s for s in sql_texts)
    assert any("person_category_tiers" in s for s in sql_texts)


@patch("app.routes.people.execute_sql")
def test_get_detail_returns_tiers_and_identities(mock_sql, client):
    mock_sql.side_effect = [
        [_row({"id": 1, "full_name": "Jane Analyst", "display_name": "Jane",
               "role": "trader", "bio": None, "notes": None, "status": "active",
               "updated_at": "2026-01-01T00:00:00+00:00"})],
        [_row({"category_slug": "macro", "tier": "A", "muted": False, "rationale": None})],
        [_row({"id": 5, "platform": "twitter", "platform_user_id": "999",
               "handle": "@jane", "match_status": "confirmed"})],
    ]
    r = client.get("/people/1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert body["fullName"] == "Jane Analyst"
    assert body["tiers"][0]["categorySlug"] == "macro"
    assert body["identities"][0]["platform"] == "twitter"
    assert body["identities"][0]["matchStatus"] == "confirmed"


@patch("app.routes.people.execute_sql")
def test_get_detail_404_when_missing(mock_sql, client):
    mock_sql.return_value = []
    r = client.get("/people/999")
    assert r.status_code == 404


@patch("app.routes.people.transaction")
def test_put_404_when_missing(mock_tx, client):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    mock_tx.return_value.__enter__.return_value = conn

    r = client.put("/people/999", json={"fullName": "Ghost"})
    assert r.status_code == 404


@patch("app.routes.people.execute_sql")
@patch("app.routes.people.transaction")
def test_put_replaces_tiers_and_appends_revision(mock_tx, mock_sql, client):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (1,)
    mock_tx.return_value.__enter__.return_value = conn
    # detail re-fetch after update
    mock_sql.side_effect = [
        [_row({"id": 1, "full_name": "Jane Analyst", "display_name": "Jane",
               "role": "trader", "bio": None, "notes": None, "status": "active",
               "updated_at": "2026-01-01T00:00:00+00:00"})],
        [_row({"category_slug": "macro", "tier": "B", "muted": False, "rationale": None})],
        [],
    ]
    r = client.put(
        "/people/1",
        json={"fullName": "Jane Analyst",
              "tiers": [{"categorySlug": "macro", "tier": "B"}]},
    )
    assert r.status_code == 200
    sql_texts = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any("DELETE FROM person_category_tiers" in s for s in sql_texts)
    assert any("person_revisions" in s for s in sql_texts)


@patch("app.routes.people.execute_sql")
def test_delete_soft_archives(mock_sql, client):
    mock_sql.return_value = []
    r = client.delete("/people/1")
    assert r.status_code == 200
    assert r.json() == {"status": "archived", "id": 1}
    sql_text = str(mock_sql.call_args.args[0])
    assert "status='archived'" in sql_text or "status = 'archived'" in sql_text


@patch("app.routes.people.execute_sql")
def test_revisions_returns_desc_list(mock_sql, client):
    mock_sql.return_value = [
        _row({"snapshot_json": {"fullName": "Jane v2"},
              "created_at": "2026-02-01T00:00:00+00:00"}),
        _row({"snapshot_json": {"fullName": "Jane v1"},
              "created_at": "2026-01-01T00:00:00+00:00"}),
    ]
    r = client.get("/people/1/revisions")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert len(body["revisions"]) == 2
    assert body["revisions"][0]["snapshot"]["fullName"] == "Jane v2"


@patch("app.routes.people.execute_sql")
def test_list_returns_people_with_needs_attention(mock_sql, client):
    mock_sql.return_value = [
        _row({"id": 1, "full_name": "Jane", "display_name": "Jane", "role": "trader",
              "status": "active", "updated_at": "2026-01-01T00:00:00+00:00",
              "needs_attention": True}),
        _row({"id": 2, "full_name": "Bob", "display_name": None, "role": None,
              "status": "active", "updated_at": "2026-01-02T00:00:00+00:00",
              "needs_attention": False}),
    ]
    r = client.get("/people")
    assert r.status_code == 200
    people = r.json()["people"]
    assert len(people) == 2
    assert "needsAttention" in people[0]
    assert people[0]["needsAttention"] is True
