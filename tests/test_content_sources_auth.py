from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Each test starts with a clean auth rate-limit window."""
    import app.auth as auth_module

    auth_module._rate_buckets.clear()
    yield
    auth_module._rate_buckets.clear()


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as c:
            yield c


@pytest.fixture
def secured_client():
    """Client with API-key auth enabled (DISABLE_AUTH off, key set)."""
    with patch.dict(
        "os.environ",
        {"DISABLE_AUTH": "", "API_SECRET_KEY": "test-secret-key"},
    ):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as c:
            yield c


def _row(d):
    r = MagicMock()
    r._mapping = d
    return r


def _idea_row(**overrides):
    base = {
        "id": str(uuid4()),
        "symbol": "AAPL",
        "symbols": ["AAPL"],
        "content": "AAPL thesis from group chat",
        "source": "imessage",
        "status": "draft",
        "tags": ["thesis"],
        "origin_message_id": None,
        "title": None,
        "source_url": None,
        "source_created_at": "2026-06-01T14:30:00+00:00",
        "author": "Qais",
        "author_id": "imsg:qais",
        "platform_message_id": "imsg-1",
        "thread_key": "friends-market-chat",
        "source_metadata": {"chat": "friends"},
        "review_status": "unreviewed",
        "review_notes": None,
        "attributed_person_id": None,
        "attribution_kind": "self",
        "filing_type": None,
        "filing_period": None,
        "institution_name": None,
        "content_hash": "hash",
        "created_at": "2026-06-01T14:31:00+00:00",
        "updated_at": "2026-06-01T14:31:00+00:00",
    }
    base.update(overrides)
    return base


@patch("src.db.execute_sql")
def test_google_auth_tracks_user(mock_sql, client):
    mock_sql.return_value = [
        _row(
            {
                "id": str(uuid4()),
                "provider": "google",
                "provider_user_id": "google-123",
                "email": "qais@example.com",
                "full_name": "Qais",
                "avatar_url": "https://example.com/avatar.png",
                "role": "viewer",
                "created_at": "2026-06-01T00:00:00+00:00",
                "updated_at": "2026-06-01T00:00:00+00:00",
                "last_seen_at": "2026-06-01T00:00:00+00:00",
            }
        )
    ]

    resp = client.post(
        "/auth/google",
        json={
            "providerUserId": "google-123",
            "email": "QAIS@example.com",
            "fullName": "Qais",
            "avatarUrl": "https://example.com/avatar.png",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["providerUserId"] == "google-123"
    assert mock_sql.call_args.kwargs["params"]["email"] == "QAIS@example.com"


def _app_user_row(**overrides):
    base = {
        "id": str(uuid4()),
        "provider": "google",
        "provider_user_id": "google-123",
        "email": "qais@example.com",
        "full_name": "Qais",
        "avatar_url": None,
        "role": "viewer",
        "created_at": "2026-06-01T00:00:00+00:00",
        "updated_at": "2026-06-01T00:00:00+00:00",
        "last_seen_at": "2026-06-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


@patch("src.db.execute_sql")
def test_google_auth_promotes_owner_email(mock_sql, client):
    mock_sql.return_value = [_row(_app_user_row(role="owner"))]

    with patch.dict("os.environ", {"OWNER_EMAILS": "QAIS@example.com, other@x.com"}):
        resp = client.post(
            "/auth/google",
            json={"providerUserId": "google-123", "email": "qais@example.com"},
        )

    assert resp.status_code == 200
    assert resp.json()["role"] == "owner"
    assert mock_sql.call_args.kwargs["params"]["role_override"] == "owner"


@patch("src.db.execute_sql")
def test_google_auth_non_owner_gets_no_role_override(mock_sql, client):
    mock_sql.return_value = [_row(_app_user_row())]

    with patch.dict("os.environ", {"OWNER_EMAILS": "someoneelse@example.com"}):
        resp = client.post(
            "/auth/google",
            json={"providerUserId": "google-123", "email": "qais@example.com"},
        )

    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"
    assert mock_sql.call_args.kwargs["params"]["role_override"] is None


@patch("src.db.execute_sql")
@patch("app.auth._verify_google_id_token")
def test_google_auth_id_token_path_uses_verified_claims(mock_verify, mock_sql, client):
    mock_verify.return_value = {
        "sub": "google-456",
        "email": "verified@example.com",
        "name": "Verified User",
        "picture": "https://example.com/p.png",
    }
    mock_sql.return_value = [
        _row(
            _app_user_row(
                provider_user_id="google-456",
                email="verified@example.com",
                full_name="Verified User",
            )
        )
    ]

    resp = client.post(
        "/auth/google",
        json={
            "idToken": "fake-token",
            # Claims in the body must be ignored in favor of the verified token
            "providerUserId": "spoofed",
            "email": "spoofed@example.com",
        },
    )

    assert resp.status_code == 200
    mock_verify.assert_called_once_with("fake-token")
    params = mock_sql.call_args.kwargs["params"]
    assert params["provider_user_id"] == "google-456"
    assert params["email"] == "verified@example.com"


def test_google_auth_requires_api_key_when_auth_enabled(secured_client):
    resp = secured_client.post(
        "/auth/google",
        json={"providerUserId": "google-123", "email": "qais@example.com"},
    )
    assert resp.status_code == 401


def test_google_auth_rejects_profile_fields_when_auth_enabled(secured_client):
    """With auth enabled, a valid API key still can't skip token verification."""
    resp = secured_client.post(
        "/auth/google",
        json={"providerUserId": "google-123", "email": "qais@example.com"},
        headers={"Authorization": "Bearer test-secret-key"},
    )
    assert resp.status_code == 400
    assert "idToken" in resp.json()["detail"]


@patch("src.db.execute_sql")
def test_auth_config_status_reports_without_secrets(mock_sql, client):
    mock_sql.return_value = [(3,)]
    with patch.dict(
        "os.environ",
        {"GOOGLE_CLIENT_ID": "abc.apps.googleusercontent.com", "OWNER_EMAILS": "a@x.com,b@y.com"},
    ):
        resp = client.get("/auth/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["googleClientIdConfigured"] is True
    assert body["ownerEmailsCount"] == 2
    assert body["appUsersCount"] == 3
    # Never leaks the actual client id
    assert "abc.apps" not in resp.text


@patch("src.db.execute_sql")
def test_google_auth_rate_limited(mock_sql, client, monkeypatch):
    import app.auth as auth_module

    monkeypatch.setattr(auth_module, "AUTH_RATE_LIMIT", 3)
    mock_sql.return_value = [_row(_app_user_row())]

    payload = {"providerUserId": "google-123", "email": "qais@example.com"}
    for _ in range(3):
        assert client.post("/auth/google", json=payload).status_code == 200

    resp = client.post("/auth/google", json=payload)
    assert resp.status_code == 429


@patch("app.routes.ideas.compute_content_hash", return_value="hash")
@patch("app.routes.ideas.execute_sql")
def test_import_messages_creates_imessage_ideas(mock_sql, _mock_hash, client):
    mock_sql.return_value = [_row(_idea_row())]

    resp = client.post(
        "/ideas/import/messages",
        json={
            "source": "imessage",
            "threadKey": "friends-market-chat",
            "defaultAuthor": "Qais",
            "messages": [
                {
                    "content": "AAPL thesis from group chat",
                    "sentAt": "2026-06-01T14:30:00+00:00",
                    "messageId": "imsg-1",
                    "symbols": ["AAPL"],
                    "tags": ["thesis"],
                    "metadata": {"chat": "friends"},
                }
            ],
        },
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["imported"] == 1
    assert body["ideas"][0]["source"] == "imessage"
    assert body["ideas"][0]["threadKey"] == "friends-market-chat"
    params = mock_sql.call_args.kwargs["params"]
    assert params["platform_message_id"] == "imsg-1"
    assert params["thread_key"] == "friends-market-chat"


@patch("app.routes.ideas.execute_sql")
def test_timeline_orders_by_source_created_at(mock_sql, client):
    mock_sql.return_value = [_row(_idea_row())]

    resp = client.get("/ideas/timeline?source=imessage&thread_key=friends-market-chat")

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    query = mock_sql.call_args.args[0]
    assert "COALESCE(source_created_at, created_at) ASC" in query
    assert mock_sql.call_args.kwargs["params"]["thread_key"] == "friends-market-chat"


@patch("app.routes.ideas.execute_sql")
def test_curate_discord_parsed_idea_sets_13f_bucket(mock_sql, client):
    pid = str(uuid4())
    mock_sql.return_value = [
        _row(
            {
                "id": pid,
                "review_status": "reviewed",
                "labels": ["INSTITUTIONAL_FLOW"],
                "primary_symbol": None,
                "symbols": ["AAPL", "MSFT"],
                "attribution_kind": "institution",
                "attributed_person_id": None,
                "thesis_bucket": "berkshire-2026-q1-13f",
            }
        )
    ]

    resp = client.put(
        f"/ideas/discord-parsed/{pid}/curation",
        json={
            "labels": ["INSTITUTIONAL_FLOW"],
            "symbols": ["AAPL", "MSFT"],
            "attributionKind": "institution",
            "thesisBucket": "berkshire-2026-q1-13f",
            "filingType": "13F",
            "institutionName": "Berkshire Hathaway",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["thesisBucket"] == "berkshire-2026-q1-13f"
    query = mock_sql.call_args.args[0]
    assert "UPDATE discord_parsed_ideas" in query
    assert "filing_type = :filing_type" in query
