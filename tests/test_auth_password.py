"""Password accounts, lockout, Google sign-in as pending, and /auth/me.

SQL is mocked (`app.auth.execute_sql`); no test touches a database. Where a
rule lives in SQL, the tests also assert on the statement text.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth as auth
from app import passwords

UID = str(uuid.uuid4())
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
GOOD = "correct horse battery"
GOOD_HASH = passwords.hash_password(GOOD)


@pytest.fixture(autouse=True)
def _clean_rate_limit():
    auth._rate_buckets.clear()
    yield
    auth._rate_buckets.clear()


@pytest.fixture
def client():
    api = FastAPI()
    api.include_router(auth.router, prefix="/auth")
    return TestClient(api)


def _user_row(role="guest", provider="password", **extra):
    row = {
        "id": UID,
        "provider": provider,
        "provider_user_id": "dev",
        "email": "dev@local",
        "full_name": "dev",
        "avatar_url": None,
        "role": role,
        "created_at": NOW,
        "updated_at": NOW,
        "last_seen_at": NOW,
    }
    row.update(extra)
    return row


def _login_row(password_hash=GOOD_HASH, is_locked=False):
    return {"id": UID, "password_hash": password_hash, "is_locked": is_locked}


def _login(client, username="dev", password=GOOD):
    return client.post("/auth/password", json={"username": username, "password": password})


# ---------------------------------------------------------------- passwords


def test_normalize_username_lowercases_and_trims():
    assert passwords.normalize_username("  Dev.User ") == "dev.user"


@pytest.mark.parametrize("bad", ["a@b.com", "a b", "ab", "", "-abc", "a" * 33])
def test_normalize_username_rejects_email_and_spaces(bad):
    with pytest.raises(ValueError, match="Username must be 3 to 32 characters"):
        passwords.normalize_username(bad)


def test_password_too_long_rejected_before_hashing():
    with patch.object(passwords, "hash_password") as hp:
        with pytest.raises(ValueError, match="128"):
            passwords.check_password_rules("x" * 129, "guest")
    hp.assert_not_called()
    passwords.check_password_rules("x" * 128, "guest")


def test_password_of_spaces_rejected():
    with pytest.raises(ValueError, match="spaces"):
        passwords.check_password_rules(" " * 20, "guest")


def test_password_length_is_checked_as_given_not_trimmed():
    passwords.check_password_rules(" abcdefgh ", "guest")  # 10 chars with edge spaces
    with pytest.raises(ValueError, match="at least 10"):
        passwords.check_password_rules("123456789", "guest")


def test_owner_needs_14_chars():
    with pytest.raises(ValueError, match="at least 14"):
        passwords.check_password_rules("x" * 13, "owner")
    passwords.check_password_rules("x" * 14, "owner")
    passwords.check_password_rules("x" * 10, "family")


def test_hash_then_verify_roundtrip():
    h = passwords.hash_password(" spaced pass ")
    assert h.startswith("$argon2")
    assert passwords.verify_password(" spaced pass ", h) is True
    assert passwords.verify_password("spaced pass", h) is False
    assert passwords.verify_password("anything", "not-a-hash") is False


def test_verify_with_no_hash_is_false_and_still_does_work():
    with patch.object(passwords, "_hasher") as hasher:
        assert passwords.verify_password("x", None) is False
    hasher.verify.assert_called_once_with(passwords._DUMMY_HASH, "x")


# -------------------------------------------------------------------- login


def test_login_success_resets_failures(client):
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [[_login_row()], [_user_row(role="family")]]
        r = _login(client, "  DEV ")
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "family" and body["id"] == UID
    for forbidden in ("password_hash", "passwordHash", "failed_login_count", "locked_until"):
        assert forbidden not in body
    assert ex.call_args_list[0].kwargs["params"] == {"username": "dev"}
    update_sql = ex.call_args_list[1].args[0]
    assert "failed_login_count = 0" in update_sql
    assert "locked_until = NULL" in update_sql
    assert "last_seen_at = NOW()" in update_sql


def test_login_pending_user_succeeds_with_pending_role(client):
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [[_login_row()], [_user_row(role="pending")]]
        r = _login(client)
    assert r.status_code == 200
    assert r.json()["role"] == "pending"


def test_login_wrong_password_is_401_and_increments(client):
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [[_login_row()], [{"is_locked": False}]]
        r = _login(client, password="wrong password!!")
    assert r.status_code == 401
    assert r.json()["detail"] == "Wrong username or password"
    assert "failed_login_count + 1" in ex.call_args_list[1].args[0]
    assert ex.call_args_list[1].kwargs["params"] == {"id": UID}


def test_failure_statement_carries_the_lock_rule():
    sql = " ".join(auth._FAIL_SQL.split())
    assert ">= 5" in sql
    assert "NOW() + INTERVAL '15 minutes'" in sql
    # an expired lock restarts the count; a live lock is never touched
    assert "locked_until <= NOW() THEN 1" in sql
    assert "WHERE id = CAST(:id AS uuid) AND (locked_until IS NULL OR locked_until <= NOW())" in sql


def test_login_unknown_user_is_401_same_message(client):
    with patch("app.auth.execute_sql", return_value=[]) as ex, patch(
        "app.auth.verify_password", wraps=passwords.verify_password
    ) as vp:
        r = _login(client, "nobody")
    assert r.status_code == 401
    assert r.json()["detail"] == "Wrong username or password"
    assert ex.call_count == 1  # only the lookup: nothing to lock
    assert vp.call_count == 1 and vp.call_args.args[1] is None  # dummy verification


def test_login_bad_username_shape_gets_same_401_after_dummy_work(client):
    with patch("app.auth.execute_sql") as ex, patch(
        "app.auth.verify_password", wraps=passwords.verify_password
    ) as vp:
        r = _login(client, "a@b.com")
    assert r.status_code == 401
    assert r.json()["detail"] == "Wrong username or password"
    ex.assert_not_called()
    assert vp.call_count == 1 and vp.call_args.args[1] is None


def test_login_overlong_password_is_401_and_never_matches_its_prefix(client):
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [[_login_row()], [{"is_locked": False}]]
        r = _login(client, password=GOOD + "x" * 200)
    assert r.status_code == 401


def test_login_locked_after_5_failures_is_423(client):
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [[_login_row()], [{"is_locked": True}]]
        r = _login(client, password="wrong password!!")
    assert r.status_code == 423
    assert r.json()["detail"] == "Too many attempts. Try again in 15 minutes"


def test_login_locked_account_rejects_correct_password(client):
    with patch("app.auth.execute_sql") as ex, patch(
        "app.auth.verify_password", wraps=passwords.verify_password
    ) as vp:
        ex.side_effect = [[_login_row(is_locked=True)]]
        r = _login(client)  # correct password
    assert r.status_code == 423
    assert r.json()["detail"] == "Too many attempts. Try again in 15 minutes"
    assert ex.call_count == 1  # no UPDATE: count and lock are untouched
    assert vp.call_count == 1 and vp.call_args.args[1] == GOOD_HASH


def test_lock_that_appears_between_lookup_and_update_is_423(client):
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [[_login_row()], []]  # guarded UPDATE matched no row
        r = _login(client)
    assert r.status_code == 423


def test_lock_expires_after_15_minutes(client):
    # The lookup reports is_locked False once locked_until has passed, so the
    # correct password signs in and the success statement clears the lock.
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [[_login_row(is_locked=False)], [_user_row()]]
        r = _login(client)
    assert r.status_code == 200
    lookup_sql = " ".join(ex.call_args_list[0].args[0].split())
    assert "locked_until > NOW()" in lookup_sql
    assert "locked_until = NULL" in ex.call_args_list[1].args[0]


# ------------------------------------------------------------------- google


def _google(client, email="new@example.com"):
    return client.post(
        "/auth/google",
        json={"providerUserId": "g-1", "email": email, "fullName": "New Person"},
    )


@pytest.fixture
def _auth_off():
    with patch("app.auth.is_auth_disabled", return_value=True):
        yield


def test_google_new_user_is_pending(client, _auth_off, monkeypatch):
    monkeypatch.delenv("OWNER_EMAILS", raising=False)
    with patch("app.auth.execute_sql") as ex, patch("app.auth._notify_new_pending"):
        ex.return_value = [_user_row(role="pending", provider="google", inserted=True)]
        r = _google(client)
    assert r.status_code == 200 and r.json()["role"] == "pending"
    sql = " ".join(ex.call_args.args[0].split())
    assert "COALESCE(:role_override, 'pending')" in sql
    assert "'viewer'" not in sql
    assert "(xmax = 0) AS inserted" in sql
    assert ex.call_args.kwargs["params"]["role_override"] is None


def test_google_owner_email_promoted_even_if_pending(client, _auth_off, monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "boss@example.com")
    with patch("app.auth.execute_sql") as ex, patch(
        "app.auth._notify_new_pending"
    ) as notify, patch("app.identity.invalidate_viewer") as inv:
        ex.return_value = [_user_row(role="owner", provider="google", inserted=False)]
        r = _google(client, "Boss@Example.com")
    assert r.status_code == 200 and r.json()["role"] == "owner"
    assert ex.call_args.kwargs["params"]["role_override"] == "owner"
    assert "role = COALESCE(:role_override, app_users.role)" in " ".join(
        ex.call_args.args[0].split()
    )
    inv.assert_called_once_with(UID)
    notify.assert_not_called()


def test_google_new_pending_triggers_notify_once(client, _auth_off, monkeypatch):
    monkeypatch.delenv("OWNER_EMAILS", raising=False)
    with patch("app.auth.execute_sql") as ex, patch("app.auth._notify_new_pending") as notify:
        ex.return_value = [
            _user_row(
                role="pending",
                provider="google",
                inserted=True,
                full_name="New Person",
                email="new@example.com",
            )
        ]
        _google(client)
        ex.return_value = [_user_row(role="pending", provider="google", inserted=False)]
        _google(client)
        ex.return_value = [_user_row(role="guest", provider="google", inserted=False)]
        _google(client)
    notify.assert_called_once_with("New Person", "new@example.com")


def test_google_new_owner_does_not_notify(client, _auth_off, monkeypatch):
    monkeypatch.setenv("OWNER_EMAILS", "boss@example.com")
    with patch("app.auth.execute_sql") as ex, patch(
        "app.auth._notify_new_pending"
    ) as notify, patch("app.identity.invalidate_viewer"):
        ex.return_value = [_user_row(role="owner", provider="google", inserted=True)]
        _google(client, "boss@example.com")
    notify.assert_not_called()


def test_google_notify_failure_never_breaks_sign_in(client, _auth_off, monkeypatch):
    monkeypatch.delenv("OWNER_EMAILS", raising=False)
    with patch("app.auth.execute_sql") as ex, patch(
        "app.auth._notify_new_pending", side_effect=RuntimeError("discord down")
    ):
        ex.return_value = [_user_row(role="pending", provider="google", inserted=True)]
        r = _google(client)
    assert r.status_code == 200


def test_notify_new_pending_is_a_no_op():
    assert auth._notify_new_pending("n", "e@example.com") is None


# ----------------------------------------------------------------------- me


def test_me_returns_role(client):
    row = {"id": UID, "role": "family", "email": "a@b.com", "full_name": "Ann"}
    with patch("app.auth.execute_sql", return_value=[row]) as ex:
        r = client.get("/auth/me", headers={"X-App-User": UID})
    assert r.status_code == 200
    assert r.json() == {"id": UID, "role": "family", "email": "a@b.com", "fullName": "Ann"}
    assert "CAST(:id AS uuid)" in ex.call_args.args[0]
    assert ex.call_args.kwargs["params"] == {"id": UID}


def test_me_unknown_is_404(client):
    with patch("app.auth.execute_sql", return_value=[]):
        r = client.get("/auth/me", headers={"X-App-User": UID})
    assert r.status_code == 404


@pytest.mark.parametrize("headers", [{}, {"X-App-User": "not-a-uuid"}, {"X-App-User": "x OR 1=1"}])
def test_me_missing_or_malformed_header_is_404_without_query(client, headers):
    with patch("app.auth.execute_sql") as ex:
        r = client.get("/auth/me", headers=headers)
    assert r.status_code == 404
    ex.assert_not_called()
