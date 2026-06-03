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


# --------------------------------------------------------------------------- #
# E2 — identities + unmatched review queue
# --------------------------------------------------------------------------- #


@patch("app.routes.people.transaction")
def test_link_inserts_confirmed_identity(mock_tx, client):
    conn = MagicMock()
    # SELECT existing -> none; INSERT -> returns row
    select_result = MagicMock()
    select_result.fetchone.return_value = None
    insert_result = MagicMock()
    insert_result.fetchone.return_value = (10,)
    conn.execute.side_effect = [MagicMock(), select_result, insert_result]
    mock_tx.return_value.__enter__.return_value = conn

    r = client.post(
        "/people/1/identities",
        json={"platform": "twitter", "platformUserId": "999", "handle": "@jane"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 10
    assert body["personId"] == 1
    assert body["matchStatus"] == "confirmed"
    sql_texts = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any("INSERT INTO source_identities" in s for s in sql_texts)


@patch("app.routes.people.transaction")
def test_link_conflict_returns_409_and_marks_conflict(mock_tx, client):
    conn = MagicMock()
    select_result = MagicMock()
    # existing row already linked to person 2
    select_result.fetchone.return_value = (5, 2, "confirmed")
    conn.execute.side_effect = [MagicMock(), select_result, MagicMock()]
    mock_tx.return_value.__enter__.return_value = conn

    r = client.post(
        "/people/1/identities",
        json={"platform": "twitter", "platformUserId": "999"},
    )
    assert r.status_code == 409
    sql_texts = [str(call.args[0]) for call in conn.execute.call_args_list]
    # an UPDATE marking conflict must have run
    assert any("conflict" in s.lower() and "update" in s.lower() for s in sql_texts)


@patch("app.routes.people.transaction")
def test_link_when_existing_person_id_null(mock_tx, client):
    conn = MagicMock()
    select_result = MagicMock()
    select_result.fetchone.return_value = (5, None, "suggested")
    update_result = MagicMock()
    update_result.fetchone.return_value = (5,)
    conn.execute.side_effect = [MagicMock(), select_result, update_result]
    mock_tx.return_value.__enter__.return_value = conn

    r = client.post(
        "/people/1/identities",
        json={"platform": "twitter", "platformUserId": "999", "handle": "@jane"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 5
    assert body["personId"] == 1
    assert body["matchStatus"] == "confirmed"
    sql_texts = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any("UPDATE source_identities" in s for s in sql_texts)


@patch("app.routes.people.execute_sql")
def test_delete_identity_unlinks_scoped(mock_sql, client):
    mock_sql.return_value = []
    r = client.delete("/people/1/identities/5")
    assert r.status_code == 200
    assert r.json() == {"status": "unlinked", "id": 5}
    sql_text = str(mock_sql.call_args.args[0])
    assert "DELETE FROM source_identities" in sql_text
    params = mock_sql.call_args.kwargs["params"]
    assert params["sid"] == 5
    assert params["id"] == 1


@patch("app.routes.people.execute_sql")
def test_unmatched_merges_flagged_and_discord(mock_sql, client):
    def _side_effect(query, *args, **kwargs):
        if "discord_parsed_ideas" in query:
            return [_row({"platform_user_id": "777", "handle": "discorduser"})]
        return [_row({"id": 5, "person_id": None, "platform": "twitter",
                      "platform_user_id": "999", "handle": "@jane",
                      "match_status": "suggested"})]

    mock_sql.side_effect = _side_effect
    r = client.get("/identities/unmatched")
    assert r.status_code == 200
    items = r.json()["unmatched"]
    kinds = {it["kind"] for it in items}
    assert "flagged" in kinds
    assert "discord_unattributed" in kinds
    flagged = next(it for it in items if it["kind"] == "flagged")
    assert flagged["id"] == 5
    assert flagged["matchStatus"] == "suggested"
    discord = next(it for it in items if it["kind"] == "discord_unattributed")
    assert discord["id"] is None
    assert discord["platform"] == "discord"
    assert discord["platformUserId"] == "777"
    assert discord["matchStatus"] is None
