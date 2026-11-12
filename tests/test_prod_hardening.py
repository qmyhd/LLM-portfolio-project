"""Tests for the pre-boot hardening pass (11/10/2026).

Covers: ENVIRONMENT defaults to production, the API refuses to start without
its key, docs are off outside development, chat input caps, the webhook log
no longer leaks signature prefixes, and the 13F loader's bound parameters.
"""

import base64
import hashlib
import hmac
import logging
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

import app.auth as auth

# ---------------------------------------------------------------------------
# ENVIRONMENT default + fail-closed startup
# ---------------------------------------------------------------------------


def _env(**overrides):
    """Patch os.environ with the auth-relevant vars cleared, then overrides."""
    base = {"ENVIRONMENT": "", "DISABLE_AUTH": "", "API_SECRET_KEY": ""}
    base.update(overrides)
    return patch.dict("os.environ", base)


def test_environment_defaults_to_production():
    with _env():
        assert auth.get_environment() == "production"
        assert auth.is_development() is False


def test_missing_key_without_explicit_dev_does_not_disable_auth():
    # The old default ("development") turned auth OFF here. It must stay on.
    with _env():
        assert auth.is_auth_disabled() is False


def test_explicit_development_without_key_still_disables_auth():
    with _env(ENVIRONMENT="development"):
        assert auth.is_auth_disabled() is True


def test_disable_auth_flag_still_works():
    with _env(DISABLE_AUTH="true"):
        assert auth.is_auth_disabled() is True


def test_assert_auth_configured_refuses_without_key():
    with _env():
        with pytest.raises(RuntimeError, match="Refusing to start"):
            auth.assert_auth_configured()


def test_assert_auth_configured_passes_with_key():
    with _env(API_SECRET_KEY="k"):
        auth.assert_auth_configured()  # no raise


def test_assert_auth_configured_passes_when_disabled():
    with _env(DISABLE_AUTH="true"):
        auth.assert_auth_configured()  # no raise


def test_get_api_secret_key_has_no_default_outside_development():
    with _env():
        with pytest.raises(RuntimeError):
            auth.get_api_secret_key()


def test_app_startup_fails_closed_without_key():
    from fastapi.testclient import TestClient

    from app.main import app

    with _env():
        with pytest.raises(RuntimeError, match="Refusing to start"):
            with TestClient(app):
                pass


def test_app_starts_and_demands_key_in_production_mode():
    from fastapi.testclient import TestClient

    from app.main import app

    with _env(API_SECRET_KEY="test-secret-key"):
        with TestClient(app) as c:
            assert c.get("/portfolio").status_code == 401
            ok = c.get("/health")
            assert ok.status_code == 200


# ---------------------------------------------------------------------------
# Docs hidden outside development
# ---------------------------------------------------------------------------


def test_docs_disabled_unless_development():
    from fastapi.testclient import TestClient

    import app.main as main

    if main._docs_enabled:
        pytest.skip("ENVIRONMENT=development in this shell; docs are on by design")
    with _env(DISABLE_AUTH="true"):
        with TestClient(main.app) as c:
            for path in ("/docs", "/redoc", "/openapi.json"):
                assert c.get(path).status_code == 404, path
            assert "docs" not in c.get("/").json()


# ---------------------------------------------------------------------------
# Chat input caps
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as c:
            yield c


def test_chat_rejects_oversized_message_before_calling_openai(client):
    from app.routes.chat import CHAT_MESSAGE_MAX_CHARS

    with patch("app.routes.chat.OpenAI") as openai_cls:
        r = client.post(
            "/stocks/AAPL/chat",
            json={"message": "x" * (CHAT_MESSAGE_MAX_CHARS + 1)},
        )
    assert r.status_code == 422
    openai_cls.assert_not_called()


def test_chat_rejects_oversized_context(client):
    from app.routes.chat import CHAT_CONTEXT_MAX_CHARS

    with patch("app.routes.chat.OpenAI") as openai_cls:
        r = client.post(
            "/stocks/AAPL/chat",
            json={"message": "hi", "context": "c" * (CHAT_CONTEXT_MAX_CHARS + 1)},
        )
    assert r.status_code == 422
    openai_cls.assert_not_called()


def test_chat_error_does_not_leak_exception_text(client):
    with (
        patch("app.routes.chat.get_latest_close", return_value=None),
        patch("app.routes.chat.execute_sql", return_value=[]),
        patch("app.routes.chat.OpenAI", side_effect=Exception("sk-SECRET internal")),
    ):
        r = client.post("/stocks/AAPL/chat", json={"message": "hi"})
    assert r.status_code == 500
    assert "SECRET" not in r.text


# ---------------------------------------------------------------------------
# Webhook log
# ---------------------------------------------------------------------------


def test_webhook_mismatch_log_has_no_signature_prefix(caplog):
    from app.routes import webhook

    secret = "test-client-secret"
    body = b'{"type":"ACCOUNT_HOLDINGS_UPDATED"}'
    expected = base64.b64encode(
        hmac.new(secret.encode(), body, hashlib.sha256).digest()
    ).decode()

    with patch.object(
        webhook, "settings", return_value=SimpleNamespace(SNAPTRADE_CLIENT_SECRET=secret)
    ):
        with caplog.at_level(logging.WARNING):
            assert webhook.verify_webhook_signature(body, "not-the-signature") is False

    assert expected[:12] not in caplog.text
    assert "not-the-sig" not in caplog.text


# ---------------------------------------------------------------------------
# 13F loader
# ---------------------------------------------------------------------------


def _holdings_df():
    return pd.DataFrame(
        [
            {
                "cusip": "037833100'); DROP TABLE positions; --",
                "ticker": "AAPL",
                "issuer": "O'Reilly Apple",
                "value_x1000": 12.5,
                "shares": 100,
                "share_type": "SH",
                "put_call": "PUT",
            }
        ]
    )


def test_build_holding_params_keeps_values_out_of_sql():
    from src.etl.sec_13f_parser import (
        INSTITUTIONAL_HOLDINGS_INSERT_SQL,
        build_holding_params,
    )

    rows = build_holding_params(_holdings_df(), "123", "Fund X", "2026-09-30")
    assert rows[0]["cusip"].startswith("037833100'")
    assert rows[0]["value_usd"] == 12_500
    assert rows[0]["is_put"] is True and rows[0]["is_call"] is False
    assert "DROP" not in INSTITUTIONAL_HOLDINGS_INSERT_SQL


def test_insert_holdings_uses_bound_params():
    from src.etl import sec_13f_parser

    with patch("src.db.execute_sql") as ex:
        n = sec_13f_parser.insert_holdings(_holdings_df(), "123", "Fund X", "2026-09-30")
    assert n == 1
    sql, kwargs = ex.call_args.args[0], ex.call_args.kwargs
    assert sql == sec_13f_parser.INSTITUTIONAL_HOLDINGS_INSERT_SQL
    assert kwargs["params"]["company_name"] == "O'Reilly Apple"


def test_generate_sql_inserts_escapes_every_string_field():
    from src.etl.sec_13f_parser import generate_sql_inserts

    (stmt,) = generate_sql_inserts(_holdings_df(), "123", "Fund X", "2026-09-30")
    # The quote inside the CUSIP is doubled, so it can't close the literal.
    assert "'037833100''); DROP TABLE positions; --'" in stmt
    assert "'O''Reilly Apple'" in stmt
