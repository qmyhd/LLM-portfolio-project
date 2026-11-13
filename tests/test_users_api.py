"""Tests for the owner-only Users API. SQL is mocked: no database is touched."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth import require_api_key
from app.identity import PENDING_VIEWER, Viewer, resolve_viewer

CALLER = str(uuid.uuid4())
OTHER = str(uuid.uuid4())
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
GOOD_PW = "a-long-enough-password"  # 22 chars


def make_row(uid=OTHER, provider="password", role="guest", username="sam", **extra):
    data = {
        "id": uuid.UUID(uid),
        "provider": provider,
        "provider_user_id": username if provider == "password" else "google-subject-123",
        "email": f"{username}@local" if provider == "password" else "g@example.com",
        "full_name": username,
        "avatar_url": None,
        "role": role,
        "created_at": T0,
        "last_seen_at": T1,
    }
    data.update(extra)
    return SimpleNamespace(_mapping=data)


@pytest.fixture
def app_obj():
    from app.main import app

    return app


@pytest.fixture
def sql(monkeypatch):
    mock = MagicMock(return_value=[])
    monkeypatch.setattr("app.routes.users.execute_sql", mock)
    return mock


@pytest.fixture
def invalidated(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("app.routes.users.invalidate_viewer", mock)
    return mock


@pytest.fixture
def client_as(app_obj):
    saved = dict(app_obj.dependency_overrides)

    def make(role="owner", user_id=CALLER) -> TestClient:
        viewer = PENDING_VIEWER if role == "pending" else Viewer(user_id, role)
        app_obj.dependency_overrides[resolve_viewer] = lambda: viewer
        app_obj.dependency_overrides[require_api_key] = lambda: None
        return TestClient(app_obj, raise_server_exceptions=False)

    yield make
    app_obj.dependency_overrides.clear()
    app_obj.dependency_overrides.update(saved)


@pytest.fixture
def owner(client_as):
    return client_as("owner")


def sql_texts(mock):
    return [c.args[0] if c.args else c.kwargs["query"] for c in mock.call_args_list]


def sql_params(mock):
    return [c.kwargs.get("params") for c in mock.call_args_list]


# --- GET /users ----------------------------------------------------------


def test_list_shape_ordering_and_pending_count(owner, sql):
    sql.return_value = [
        make_row(OTHER, role="pending", username="p1"),
        make_row(CALLER, provider="google", role="owner", username="me"),
        make_row(str(uuid.uuid4()), role="pending", username="p2"),
    ]
    r = owner.get("/users")
    assert r.status_code == 200
    body = r.json()
    assert body["pendingCount"] == 2
    assert [u["role"] for u in body["users"]] == ["pending", "owner", "pending"]
    # Ordering is done in SQL: pending first, then last_seen_at descending.
    text = sql_texts(sql)[0]
    assert "ORDER BY (role = 'pending') DESC, last_seen_at DESC" in text


def test_list_row_fields_are_exact(owner, sql):
    sql.return_value = [
        make_row(OTHER, username="sam"),
        make_row(CALLER, provider="google", role="owner", username="me"),
    ]
    users = owner.get("/users").json()["users"]
    pw, goog = users
    expected = {
        "id", "provider", "username", "email", "fullName", "avatarUrl",
        "role", "createdAt", "lastSeenAt", "isSelf",
    }
    assert set(pw) == expected == set(goog)
    assert pw["username"] == "sam" and pw["provider"] == "password"
    assert pw["isSelf"] is False
    assert pw["createdAt"] == T0.isoformat() and pw["lastSeenAt"] == T1.isoformat()
    assert goog["username"] is None  # the Google account id is not exposed
    assert goog["isSelf"] is True
    assert "google-subject-123" not in str(users)


def test_list_never_selects_or_returns_secrets(owner, sql):
    sql.return_value = [make_row(password_hash="$argon2id$secret", failed_login_count=3)]
    r = owner.get("/users")
    for forbidden in ("password_hash", "failed_login_count", "locked_until", "argon2"):
        assert forbidden not in r.text
        assert forbidden not in sql_texts(sql)[0]


def test_list_without_viewer_id_marks_nobody_self(client_as, sql):
    sql.return_value = [make_row()]
    c = client_as("owner", user_id=None)
    assert c.get("/users").json()["users"][0]["isSelf"] is False


# --- access policy -------------------------------------------------------


@pytest.mark.parametrize("role", ["guest", "family"])
@pytest.mark.parametrize(
    "method,url",
    [
        ("GET", "/users"),
        ("POST", "/users"),
        ("PATCH", f"/users/{OTHER}"),
        ("DELETE", f"/users/{OTHER}"),
        ("POST", f"/users/{OTHER}/password"),
    ],
)
def test_non_owner_gets_403_and_no_sql(client_as, sql, role, method, url):
    r = client_as(role).request(method, url, json={})
    assert r.status_code == 403
    assert r.json()["detail"] == "This action needs the owner"
    sql.assert_not_called()


def test_pending_gets_403(client_as, sql):
    r = client_as("pending").get("/users")
    assert r.status_code == 403
    sql.assert_not_called()


# --- PATCH /users/{id} ---------------------------------------------------


def test_patch_changes_role_and_invalidates(owner, sql, invalidated):
    sql.side_effect = [
        [make_row(OTHER, role="guest")],  # fetch current
        [make_row(OTHER, role="family")],  # guarded update
    ]
    r = owner.patch(f"/users/{OTHER}", json={"role": "family"})
    assert r.status_code == 200
    assert r.json()["role"] == "family"
    assert r.json()["id"] == OTHER
    invalidated.assert_called_once_with(OTHER)
    update_sql = sql_texts(sql)[1]
    assert "CAST(:id AS uuid)" in update_sql
    assert sql_params(sql)[1] == {"id": OTHER, "role": "family"}


def test_patch_demotion_guard_is_in_the_same_statement(owner, sql):
    sql.side_effect = [[make_row(OTHER, role="owner")], [make_row(OTHER, role="guest")]]
    owner.patch(f"/users/{OTHER}", json={"role": "guest"})
    text = " ".join(sql_texts(sql)[1].split())
    assert "FOR UPDATE" in text  # owner rows are locked, so racing requests queue up
    assert "SELECT count(*) FROM owners WHERE id <> CAST(:id AS uuid)) >= 1" in text
    assert text.count("UPDATE app_users") == 1


def test_patch_last_owner_demotion_is_refused(owner, sql, invalidated):
    sql.side_effect = [
        [make_row(OTHER, role="owner")],  # fetch current
        [],  # guarded update changed nothing
        [make_row(OTHER, role="owner")],  # re-fetch: still there
    ]
    r = owner.patch(f"/users/{OTHER}", json={"role": "guest"})
    assert (r.status_code, r.json()["detail"]) == (400, "At least one owner must remain")
    invalidated.assert_not_called()


def test_patch_user_deleted_mid_request_is_404(owner, sql):
    sql.side_effect = [[make_row(OTHER, role="owner")], [], []]
    r = owner.patch(f"/users/{OTHER}", json={"role": "guest"})
    assert (r.status_code, r.json()["detail"]) == (404, "User not found")


def test_patch_owner_on_google_row_is_refused(owner, sql, invalidated):
    sql.side_effect = [[make_row(OTHER, provider="google", role="guest")]]
    r = owner.patch(f"/users/{OTHER}", json={"role": "owner"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Owner access for Google accounts comes from OWNER_EMAILS"
    assert sql.call_count == 1  # nothing was written
    invalidated.assert_not_called()


def test_patch_cannot_promote_password_account_to_owner(owner, sql, invalidated):
    sql.side_effect = [[make_row(OTHER, role="family")]]
    r = owner.patch(f"/users/{OTHER}", json={"role": "owner"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Create a new password account with the Owner role instead"
    assert sql.call_count == 1  # nothing was written
    invalidated.assert_not_called()


def test_patch_update_sql_can_never_set_owner(owner, sql):
    sql.side_effect = [[make_row(OTHER, role="guest")], [make_row(OTHER, role="family")]]
    owner.patch(f"/users/{OTHER}", json={"role": "family"})
    assert ":role <> 'owner'" in " ".join(sql_texts(sql)[1].split())


def test_patch_response_has_no_secrets(owner, sql):
    sql.side_effect = [
        [make_row(OTHER, role="guest", password_hash="$argon2id$x")],
        [make_row(OTHER, role="family", password_hash="$argon2id$x")],
    ]
    r = owner.patch(f"/users/{OTHER}", json={"role": "family"})
    assert "password_hash" not in r.text and "argon2" not in r.text


def test_patch_google_user_can_be_set_to_pending(owner, sql):
    sql.side_effect = [
        [make_row(OTHER, provider="google", role="guest")],
        [make_row(OTHER, provider="google", role="pending")],
    ]
    r = owner.patch(f"/users/{OTHER}", json={"role": "pending"})
    assert r.status_code == 200 and r.json()["role"] == "pending"


def test_patch_own_row_is_refused(owner, sql, invalidated):
    r = owner.patch(f"/users/{CALLER}", json={"role": "guest"})
    assert (r.status_code, r.json()["detail"]) == (400, "You can't change your own access")
    sql.assert_not_called()
    invalidated.assert_not_called()


def test_patch_own_row_rule_is_case_insensitive_on_uuid(owner, sql):
    r = owner.patch(f"/users/{CALLER.upper()}", json={"role": "guest"})
    assert r.status_code == 400
    sql.assert_not_called()


def test_patch_same_role_is_a_noop_200(owner, sql, invalidated):
    sql.side_effect = [[make_row(OTHER, role="family")]]
    r = owner.patch(f"/users/{OTHER}", json={"role": "family"})
    assert r.status_code == 200 and r.json()["role"] == "family"
    assert sql.call_count == 1
    invalidated.assert_not_called()


def test_patch_unknown_user_is_404(owner, sql):
    sql.return_value = []
    r = owner.patch(f"/users/{OTHER}", json={"role": "guest"})
    assert (r.status_code, r.json()["detail"]) == (404, "User not found")


def test_patch_non_uuid_is_404_without_querying(owner, sql):
    r = owner.patch("/users/not-a-uuid", json={"role": "guest"})
    assert (r.status_code, r.json()["detail"]) == (404, "User not found")
    sql.assert_not_called()


def test_patch_rejects_unknown_role(owner, sql):
    r = owner.patch(f"/users/{OTHER}", json={"role": "editor"})
    assert r.status_code == 422
    sql.assert_not_called()


def test_patch_without_viewer_id_still_applies_last_owner_rule(client_as, sql):
    sql.side_effect = [[make_row(OTHER, role="owner")], [], [make_row(OTHER, role="owner")]]
    r = client_as("owner", user_id=None).patch(f"/users/{OTHER}", json={"role": "guest"})
    assert (r.status_code, r.json()["detail"]) == (400, "At least one owner must remain")


# --- DELETE /users/{id} --------------------------------------------------


def test_delete_removes_only_the_user_row(owner, sql, invalidated):
    sql.side_effect = [
        [make_row(OTHER)],
        [SimpleNamespace(_mapping={"id": uuid.UUID(OTHER)})],
    ]
    r = owner.delete(f"/users/{OTHER}")
    assert r.status_code == 204 and r.content == b""
    invalidated.assert_called_once_with(OTHER)
    assert sql.call_count == 2
    text = " ".join(sql_texts(sql)[1].split())
    assert "DELETE FROM app_users" in text
    assert "FOR UPDATE" in text
    assert "SELECT count(*) FROM owners WHERE id <> CAST(:id AS uuid)) >= 1" in text
    assert sql_params(sql)[1] == {"id": OTHER}


def test_delete_last_owner_is_refused(owner, sql, invalidated):
    sql.side_effect = [[make_row(OTHER, role="owner")], [], [make_row(OTHER, role="owner")]]
    r = owner.delete(f"/users/{OTHER}")
    assert (r.status_code, r.json()["detail"]) == (400, "At least one owner must remain")
    invalidated.assert_not_called()


def test_delete_own_row_is_refused(owner, sql):
    r = owner.delete(f"/users/{CALLER}")
    assert (r.status_code, r.json()["detail"]) == (400, "You can't change your own access")
    sql.assert_not_called()


def test_delete_unknown_user_is_404(owner, sql):
    sql.side_effect = [[]]
    r = owner.delete(f"/users/{OTHER}")
    assert (r.status_code, r.json()["detail"]) == (404, "User not found")


def test_delete_non_uuid_is_404_without_querying(owner, sql):
    r = owner.delete("/users/123")
    assert r.status_code == 404
    sql.assert_not_called()


# --- POST /users ---------------------------------------------------------


def create(owner, **over):
    body = {"username": "Sam.Doe", "password": GOOD_PW, "role": "guest"}
    body.update(over)
    return owner.post("/users", json=body)


def test_create_stores_hash_never_the_password(owner, sql, invalidated):
    new_id = str(uuid.uuid4())
    sql.return_value = [make_row(new_id, role="guest", username="sam.doe")]
    r = create(owner)
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "sam.doe" and body["role"] == "guest"
    assert body["isSelf"] is False
    params = sql_params(sql)[0]
    assert params["username"] == "sam.doe"  # normalised
    assert params["email"] == "sam.doe@local"
    assert params["full_name"] == "sam.doe"
    assert params["role"] == "guest"
    assert params["hash"].startswith("$argon2")
    assert GOOD_PW not in params.values()
    assert GOOD_PW not in r.text and "argon2" not in r.text
    text = " ".join(sql_texts(sql)[0].split())
    assert "'password'" in text and "ON CONFLICT DO NOTHING" in text and "RETURNING" in text
    invalidated.assert_called_once_with(new_id)


def test_create_does_not_alter_the_password(owner, sql):
    from app.passwords import verify_password

    sql.return_value = [make_row(role="guest")]
    padded = "  spaced password  "
    create(owner, password=padded)
    assert verify_password(padded, sql_params(sql)[0]["hash"])
    assert not verify_password(padded.strip(), sql_params(sql)[0]["hash"])


def test_create_duplicate_username_is_409(owner, sql, invalidated):
    sql.return_value = []  # ON CONFLICT DO NOTHING returned no row
    r = create(owner)
    assert (r.status_code, r.json()["detail"]) == (409, "That username is taken")
    invalidated.assert_not_called()


def test_create_pending_is_refused(owner, sql):
    r = create(owner, role="pending")
    assert (r.status_code, r.json()["detail"]) == (400, "Pick guest, family or owner")
    sql.assert_not_called()


def test_create_bad_username_returns_the_rule_message(owner, sql):
    from app.passwords import normalize_username

    with pytest.raises(ValueError) as exc:
        normalize_username("a")
    r = create(owner, username="a")
    assert (r.status_code, r.json()["detail"]) == (400, str(exc.value))
    sql.assert_not_called()


def test_create_short_password_returns_the_rule_message(owner, sql):
    r = create(owner, password="short")
    assert (r.status_code, r.json()["detail"]) == (400, "Password must be at least 10 characters")
    sql.assert_not_called()


def test_create_owner_needs_14_characters(owner, sql):
    r = create(owner, role="owner", password="a" * 13)
    assert (r.status_code, r.json()["detail"]) == (400, "Password must be at least 14 characters")
    sql.assert_not_called()
    sql.return_value = [make_row(role="owner")]
    assert create(owner, role="owner", password="a" * 14).status_code == 201


def test_create_too_long_password_is_refused(owner, sql):
    r = create(owner, password="a" * 129)
    assert r.status_code == 400
    sql.assert_not_called()


# --- POST /users/{id}/password -------------------------------------------


def test_reset_sets_hash_and_clears_lockout(owner, sql, invalidated):
    sql.side_effect = [
        [make_row(OTHER, role="guest")],
        [SimpleNamespace(_mapping={"id": uuid.UUID(OTHER)})],
    ]
    r = owner.post(f"/users/{OTHER}/password", json={"password": GOOD_PW})
    assert r.status_code == 204 and r.content == b""
    text = " ".join(sql_texts(sql)[1].split())
    assert "failed_login_count = 0" in text
    assert "locked_until = NULL" in text
    assert "provider = 'password'" in text
    params = sql_params(sql)[1]
    assert params["hash"].startswith("$argon2") and GOOD_PW not in params.values()
    invalidated.assert_called_once_with(OTHER)


def test_reset_on_google_row_is_refused(owner, sql, invalidated):
    sql.side_effect = [[make_row(OTHER, provider="google")]]
    r = owner.post(f"/users/{OTHER}/password", json={"password": GOOD_PW})
    assert (r.status_code, r.json()["detail"]) == (400, "Google accounts sign in with Google")
    assert sql.call_count == 1
    invalidated.assert_not_called()


def test_reset_validates_with_the_rows_current_role(owner, sql):
    sql.side_effect = [[make_row(OTHER, role="owner")]]
    r = owner.post(f"/users/{OTHER}/password", json={"password": "a" * 12})
    assert (r.status_code, r.json()["detail"]) == (400, "Password must be at least 14 characters")
    assert sql.call_count == 1


def test_reset_unknown_and_non_uuid_are_404(owner, sql):
    sql.return_value = []
    r = owner.post(f"/users/{OTHER}/password", json={"password": GOOD_PW})
    assert (r.status_code, r.json()["detail"]) == (404, "User not found")
    sql.reset_mock()
    r = owner.post("/users/nope/password", json={"password": GOOD_PW})
    assert r.status_code == 404
    sql.assert_not_called()


# --- no secrets in logs --------------------------------------------------


def test_logs_carry_ids_and_action_only(owner, sql, caplog):
    sql.side_effect = [[make_row(OTHER, role="guest", username="sam")], [make_row(OTHER, role="family")]]
    with caplog.at_level("INFO", logger="app.routes.users"):
        owner.patch(f"/users/{OTHER}", json={"role": "family"})
    lines = [r.getMessage() for r in caplog.records if r.name == "app.routes.users"]
    assert len(lines) == 1
    assert CALLER in lines[0] and OTHER in lines[0] and "role guest -> family" in lines[0]
    assert "sam" not in lines[0] and "@" not in lines[0]


# --- OWNER_EMAILS accounts -----------------------------------------------

OWNER_EMAIL_MSG = "This account is an owner through OWNER_EMAILS. Remove the email there first"


@pytest.fixture
def owner_email(monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "other@example.com, G@Example.com")


def test_patch_google_owner_email_is_refused(owner, sql, invalidated, owner_email):
    sql.side_effect = [[make_row(OTHER, provider="google", role="owner")]]  # g@example.com
    r = owner.patch(f"/users/{OTHER}", json={"role": "guest"})
    assert (r.status_code, r.json()["detail"]) == (400, OWNER_EMAIL_MSG)
    assert sql.call_count == 1
    invalidated.assert_not_called()


def test_delete_google_owner_email_is_refused(owner, sql, invalidated, owner_email):
    sql.side_effect = [[make_row(OTHER, provider="google", role="owner")]]
    r = owner.delete(f"/users/{OTHER}")
    assert (r.status_code, r.json()["detail"]) == (400, OWNER_EMAIL_MSG)
    assert sql.call_count == 1
    invalidated.assert_not_called()


def test_owner_email_rule_ignores_other_emails(owner, sql, monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "someone-else@example.com")
    sql.side_effect = [
        [make_row(OTHER, provider="google", role="family")],
        [make_row(OTHER, provider="google", role="guest")],
    ]
    assert owner.patch(f"/users/{OTHER}", json={"role": "guest"}).status_code == 200


# --- reset: owner length re-checked in SQL, response, deleted mid-request --


def test_reset_sql_rechecks_owner_length(owner, sql):
    sql.side_effect = [[make_row(OTHER, role="guest")], [SimpleNamespace(_mapping={"id": 1})]]
    owner.post(f"/users/{OTHER}/password", json={"password": "a" * 12})
    assert "AND (role <> 'owner' OR :owner_ok)" in " ".join(sql_texts(sql)[1].split())
    assert sql_params(sql)[1]["owner_ok"] is False
    sql.side_effect = [[make_row(OTHER, role="guest")], [SimpleNamespace(_mapping={"id": 1})]]
    owner.post(f"/users/{OTHER}/password", json={"password": "a" * 14})
    assert sql_params(sql)[3]["owner_ok"] is True


def test_reset_stale_role_promoted_to_owner_is_refused(owner, sql, invalidated):
    # Read as guest, but the row became an owner before the UPDATE ran.
    sql.side_effect = [
        [make_row(OTHER, role="guest")],
        [],
        [make_row(OTHER, role="owner")],
    ]
    r = owner.post(f"/users/{OTHER}/password", json={"password": "a" * 12})
    assert (r.status_code, r.json()["detail"]) == (400, "Password must be at least 14 characters")
    invalidated.assert_not_called()


def test_reset_row_deleted_mid_request_is_404(owner, sql, invalidated):
    sql.side_effect = [[make_row(OTHER, role="guest")], [], []]
    r = owner.post(f"/users/{OTHER}/password", json={"password": GOOD_PW})
    assert (r.status_code, r.json()["detail"]) == (404, "User not found")
    invalidated.assert_not_called()


def test_reset_response_has_no_secrets(owner, sql):
    sql.side_effect = [[make_row(OTHER, role="guest")], [SimpleNamespace(_mapping={"id": 1})]]
    r = owner.post(f"/users/{OTHER}/password", json={"password": GOOD_PW})
    assert "password_hash" not in r.text and "argon2" not in r.text


def test_create_and_reset_handlers_run_in_the_threadpool():
    import inspect

    from app.routes import users

    assert not inspect.iscoroutinefunction(users.create_user)
    assert not inspect.iscoroutinefunction(users.reset_password)
