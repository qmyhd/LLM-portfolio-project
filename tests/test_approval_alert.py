"""Discord alerts for sign-ins waiting for approval and for locked accounts."""

import logging
import re
import threading
import time
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.auth as auth
from app import passwords
from src import approval_alert as aa

TOKEN = "tok-SECRET-123"
CHANNEL = "123456789012345678"
ZW = "​"
UID = str(uuid.uuid4())
GOOD = "correct horse battery"
GOOD_HASH = passwords.hash_password(GOOD)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("APPROVAL_ALERT_CHANNEL_ID", CHANNEL)
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    aa._reset_counter()
    yield
    aa._reset_counter()


def _ok(status=200):
    return MagicMock(status_code=status)


def _body(post):
    return post.call_args.kwargs["json"]


# ------------------------------------------------------------------ approval


def test_sends_the_right_url_header_and_text():
    with patch("src.approval_alert.httpx.post", return_value=_ok()) as post:
        assert aa.send_approval_alert("Jo Smith", "jo@example.com") is True
    assert post.call_args.args[0] == f"https://discord.com/api/v10/channels/{CHANNEL}/messages"
    assert post.call_args.kwargs["headers"]["Authorization"] == f"Bot {TOKEN}"
    assert post.call_args.kwargs["timeout"] == 5
    assert _body(post)["content"] == (
        "New sign-in waiting for approval\n"
        f"Jo Smith · jo@{ZW}example.com\n"
        "Approve or decline: https://llmportfolio.app/settings/users"
    )
    assert _body(post)["allowed_mentions"] == {"parse": []}


def test_no_name_falls_back():
    with patch("src.approval_alert.httpx.post", return_value=_ok()) as post:
        aa.send_approval_alert(None, "jo@example.com")
    assert f"No name · jo@{ZW}example.com" in _body(post)["content"]


def test_any_2xx_is_success():
    with patch("src.approval_alert.httpx.post", return_value=_ok(204)):
        assert aa.send_approval_alert("a", "b@c.d") is True


@pytest.mark.parametrize("missing", ["DISCORD_BOT_TOKEN", "APPROVAL_ALERT_CHANNEL_ID"])
def test_missing_config_sends_nothing(monkeypatch, missing):
    monkeypatch.delenv(missing)
    with patch("src.approval_alert.httpx.post") as post:
        assert aa.send_approval_alert("a", "b@c.d") is False
    post.assert_not_called()


@pytest.mark.parametrize("bad", ["", "12ab", "../x", "123/456", " 123", "1.5"])
def test_channel_id_must_be_digits(monkeypatch, bad):
    monkeypatch.setenv("APPROVAL_ALERT_CHANNEL_ID", bad)
    with patch("src.approval_alert.httpx.post") as post:
        assert aa.send_approval_alert("a", "b@c.d") is False
    post.assert_not_called()


def test_403_returns_false_and_logs_status_only(caplog):
    with caplog.at_level(logging.DEBUG), patch(
        "src.approval_alert.httpx.post", return_value=_ok(403)
    ):
        assert aa.send_approval_alert("a", "b@c.d") is False
    assert "403" in caplog.text


def test_timeout_returns_false_without_raising(caplog):
    with caplog.at_level(logging.DEBUG), patch(
        "src.approval_alert.httpx.post", side_effect=httpx.ConnectTimeout("slow")
    ):
        assert aa.send_approval_alert("a", "b@c.d") is False
    assert "ConnectTimeout" in caplog.text


def test_token_never_appears_in_logs(caplog):
    err = httpx.ConnectError(f"boom Authorization: Bot {TOKEN}")
    with caplog.at_level(logging.DEBUG):
        with patch("src.approval_alert.httpx.post", side_effect=err):
            aa.send_approval_alert("a", "b@c.d")
        with patch("src.approval_alert.httpx.post", return_value=_ok(401)):
            aa.send_approval_alert("a", "b@c.d")
        with patch("src.approval_alert.httpx.post", return_value=_ok()):
            aa.send_approval_alert("a", "b@c.d")
    for rec in caplog.records:
        assert TOKEN not in rec.getMessage()
        assert TOKEN not in str(rec.__dict__)
        assert not rec.exc_info


# ----------------------------------------------------------------- frontend


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://example.org/", "https://example.org"),
        ("https://example.org", "https://example.org"),
        ("http://example.org", "https://llmportfolio.app"),
        ("javascript:alert(1)", "https://llmportfolio.app"),
        ("", "https://llmportfolio.app"),
    ],
)
def test_frontend_url(monkeypatch, value, expected):
    monkeypatch.setenv("FRONTEND_URL", value)
    with patch("src.approval_alert.httpx.post", return_value=_ok()) as post:
        aa.send_approval_alert("a", "b@c.d")
    assert _body(post)["content"].endswith(f"Approve or decline: {expected}/settings/users")


# ---------------------------------------------------------------- daily cap


def test_21st_alert_in_a_day_makes_no_request(caplog):
    with caplog.at_level(logging.WARNING), patch(
        "src.approval_alert.httpx.post", return_value=_ok()
    ) as post:
        results = [aa.send_approval_alert("a", f"u{i}@c.d") for i in range(23)]
    assert results[:20] == [True] * 20
    assert results[20:] == [False] * 3
    assert post.call_count == aa.MAX_ALERTS_PER_DAY == 20
    assert sum("cap" in r.getMessage().lower() for r in caplog.records) == 1


def test_cap_is_shared_by_both_alert_kinds():
    with patch("src.approval_alert.httpx.post", return_value=_ok()) as post:
        for i in range(10):
            aa.send_approval_alert("a", f"u{i}@c.d")
        for i in range(10):
            aa.send_lockout_alert(f"user{i}")
        assert aa.send_lockout_alert("one-more") is False
        assert aa.send_approval_alert("a", "x@c.d") is False
    assert post.call_count == 20


def test_counter_resets_on_a_new_day():
    with patch("src.approval_alert.httpx.post", return_value=_ok()) as post:
        with patch("src.approval_alert._today", return_value=date(2026, 11, 12)):
            for _ in range(20):
                aa.send_approval_alert("a", "b@c.d")
            assert aa.send_approval_alert("a", "b@c.d") is False
        with patch("src.approval_alert._today", return_value=date(2026, 11, 13)):
            assert aa.send_approval_alert("a", "b@c.d") is True
    assert post.call_count == 21


def test_today_uses_new_york_date():
    # 03:00 UTC on the 13th is still the evening of the 12th in New York.
    fake = datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)
    with patch("src.approval_alert._now_utc", return_value=fake):
        assert aa._today() == date(2026, 11, 12)


def test_today_falls_back_to_utc_without_tz_data():
    fake = datetime(2026, 11, 13, 3, 0, tzinfo=timezone.utc)
    with patch("src.approval_alert._now_utc", return_value=fake), patch(
        "src.approval_alert.ZoneInfo", side_effect=KeyError("no tz")
    ):
        assert aa._today() == date(2026, 11, 13)


def test_failed_send_still_counts_but_misconfig_does_not(monkeypatch):
    with patch("src.approval_alert.httpx.post", return_value=_ok(500)):
        aa.send_approval_alert("a", "b@c.d")
    assert aa._counter_state()[1] == 1
    monkeypatch.delenv("DISCORD_BOT_TOKEN")
    aa.send_approval_alert("a", "b@c.d")
    assert aa._counter_state()[1] == 1


# ---------------------------------------------------------------- sanitising


def test_everyone_is_neutralised():
    with patch("src.approval_alert.httpx.post", return_value=_ok()) as post:
        aa.send_approval_alert("@everyone @here", "a@b.c")
    text = _body(post)["content"]
    assert "@everyone" not in text and "@here" not in text
    assert f"@{ZW}everyone" in text
    assert _body(post)["allowed_mentions"] == {"parse": []}


def test_long_name_is_truncated_to_100():
    out = aa._clean("x" * 500)
    assert out == "x" * 100


def test_email_is_truncated_too():
    assert len(aa._clean("e" * 300 + "@x.com")) <= 100


def test_backticks_replaced():
    assert aa._clean("a`b```c") == "a'b'''c"


def test_newlines_and_control_chars_collapse_to_one_space():
    assert aa._clean("a\n\nb\r\nc\td\x00e\x1bf") == "a b c d e f"


def test_markdown_link_and_url_neutralised():
    out = aa._clean("[click](https://evil.example/x)")
    assert "](" not in out and "://" not in out
    assert f":/{ZW}/" in out and "] (" in out


def test_hostile_name_cannot_forge_lines_or_links():
    name = "A" * 450 + "\n@everyone `x` https://evil.example"
    with patch("src.approval_alert.httpx.post", return_value=_ok()) as post:
        aa.send_approval_alert(name, "a@b.c")
    assert len(_body(post)["content"].split("\n")) == 3
    hostile = "Bob\n@everyone `x` [y](https://evil.example) https://evil.example"
    with patch("src.approval_alert.httpx.post", return_value=_ok()) as post:
        aa.send_approval_alert(hostile, "a@b.c")
    text = _body(post)["content"]
    lines = text.split("\n")
    assert len(lines) == 3
    assert "@everyone" not in text and "`" not in text and "](" not in text
    assert "://" not in lines[1]  # the footer's own https link is ours
    assert re.search(r"@(?!​)", lines[1]) is None


# ------------------------------------------------------------------- lockout


def test_lockout_message_text_and_transport():
    with patch("src.approval_alert.httpx.post", return_value=_ok()) as post:
        assert aa.send_lockout_alert("jo.smith") is True
    assert post.call_args.args[0] == f"https://discord.com/api/v10/channels/{CHANNEL}/messages"
    assert post.call_args.kwargs["headers"]["Authorization"] == f"Bot {TOKEN}"
    assert post.call_args.kwargs["timeout"] == 5
    assert _body(post)["allowed_mentions"] == {"parse": []}
    assert _body(post)["content"] == (
        "Sign-in locked for 15 minutes\n"
        "Account: jo.smith\n"
        "5 wrong passwords in a row. If this wasn't you or someone you know, "
        "no action is needed; the lock clears by itself."
    )


def test_lockout_username_is_sanitised():
    with patch("src.approval_alert.httpx.post", return_value=_ok()) as post:
        aa.send_lockout_alert("x\n@everyone`" + "y" * 200)
    text = _body(post)["content"]
    assert len(text.split("\n")) == 3
    assert "@everyone" not in text and "`" not in text


def test_lockout_unconfigured_or_failing_never_raises(monkeypatch):
    with patch("src.approval_alert.httpx.post", side_effect=RuntimeError("x")):
        assert aa.send_lockout_alert("jo") is False
    monkeypatch.delenv("APPROVAL_ALERT_CHANNEL_ID")
    with patch("src.approval_alert.httpx.post") as post:
        assert aa.send_lockout_alert("jo") is False
    post.assert_not_called()


# -------------------------------------------------- auth wiring (background)


def test_notify_new_pending_returns_without_waiting():
    started, release = threading.Event(), threading.Event()

    def slow(name, email):
        started.set()
        release.wait(5)

    with patch("src.approval_alert.send_approval_alert", side_effect=slow):
        t0 = time.monotonic()
        auth._notify_new_pending("Jo", "jo@example.com")
        elapsed = time.monotonic() - t0
        assert started.wait(2)
        release.set()
    assert elapsed < 1


def test_notify_new_pending_passes_name_and_email():
    done = threading.Event()
    with patch(
        "src.approval_alert.send_approval_alert", side_effect=lambda *a: done.set()
    ) as send:
        auth._notify_new_pending("Jo", "jo@example.com")
        assert done.wait(2)
    send.assert_called_once_with("Jo", "jo@example.com")


def test_exception_inside_the_send_is_swallowed_and_logged(caplog):
    done = threading.Event()

    def boom(*a):
        try:
            raise RuntimeError("kaput")
        finally:
            done.set()

    with caplog.at_level(logging.WARNING), patch(
        "src.approval_alert.send_approval_alert", side_effect=boom
    ):
        auth._notify_new_pending("Jo", "jo@example.com")  # must not raise
        assert done.wait(2)
        for _ in range(50):  # let the thread finish logging
            if "alert failed" in caplog.text.lower():
                break
            time.sleep(0.02)
    assert "alert failed" in caplog.text.lower()


@pytest.fixture
def client():
    api = FastAPI()
    api.include_router(auth.router, prefix="/auth")
    return TestClient(api)


@pytest.fixture
def lock_alert():
    auth._rate_buckets.clear()
    auth._shadow_locks.clear()
    with patch("app.auth._notify_lockout") as notify:
        yield notify
    auth._rate_buckets.clear()
    auth._shadow_locks.clear()


def _login(client, username="dev"):
    return client.post("/auth/password", json={"username": username, "password": "wrong password!!"})


def _login_row(is_locked=False):
    return {"id": UID, "password_hash": GOOD_HASH, "is_locked": is_locked}


def test_lockout_alert_sent_once_when_the_lock_trips(client, lock_alert):
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [[_login_row()], [{"is_locked": True}]]
        r = _login(client)
    assert r.status_code == 423
    lock_alert.assert_called_once_with("dev")


def test_no_lockout_alert_for_an_ordinary_failure(client, lock_alert):
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [[_login_row()], [{"is_locked": False}]]
        assert _login(client).status_code == 401
    lock_alert.assert_not_called()


def test_no_lockout_alert_on_the_sixth_attempt(client, lock_alert):
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [
            [_login_row()],
            [{"is_locked": True}],  # 5th failure trips the lock
            [_login_row(is_locked=True)],  # 6th: already locked, no UPDATE
        ]
        assert _login(client).status_code == 423
        assert _login(client).status_code == 423
    lock_alert.assert_called_once_with("dev")


def test_no_lockout_alert_when_a_concurrent_request_tripped_it(client, lock_alert):
    with patch("app.auth.execute_sql") as ex:
        ex.side_effect = [[_login_row()], []]
        assert _login(client).status_code == 423
    lock_alert.assert_not_called()


def test_no_lockout_alert_for_unknown_username_shadow_lock(client, lock_alert):
    with patch("app.auth.execute_sql", return_value=[]):
        codes = [_login(client, "nobody").status_code for _ in range(6)]
    assert codes == [401, 401, 401, 401, 423, 423]
    lock_alert.assert_not_called()


def test_notify_lockout_runs_in_background_and_swallows_errors(caplog):
    done = threading.Event()

    def boom(u):
        try:
            raise RuntimeError("kaput")
        finally:
            done.set()

    with caplog.at_level(logging.WARNING), patch(
        "src.approval_alert.send_lockout_alert", side_effect=boom
    ):
        auth._notify_lockout("dev")
        assert done.wait(2)
        for _ in range(50):
            if "alert failed" in caplog.text.lower():
                break
            time.sleep(0.02)
    assert "alert failed" in caplog.text.lower()
