"""Human curation must survive reparses.

Covers the three layers of protection:
- POST /sentiment/reparse excludes messages with reviewed idea rows
- save_parsed_ideas_atomic (src.db) freezes reviewed messages
- GET /ideas/discord-parsed lists parsed ideas for the review queue
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

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


# ---------------------------------------------------------------------------
# POST /sentiment/reparse
# ---------------------------------------------------------------------------


@patch("app.routes.sentiment.execute_sql")
def test_reparse_mode1_skips_reviewed_messages(mock_sql, client):
    # Call order: reviewed-check, delete, update
    mock_sql.side_effect = [
        [("123",)],  # message 123 has reviewed ideas
        [],  # delete returns no rows
        [("456",)],  # update flips 456 to pending
    ]

    resp = client.post("/sentiment/reparse", json={"messageIds": ["123", "456"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["skippedReviewed"] == 1
    assert body["reset"] == 1
    # The delete and update must only see the non-reviewed id
    delete_params = mock_sql.call_args_list[1].kwargs["params"]
    update_params = mock_sql.call_args_list[2].kwargs["params"]
    assert delete_params["ids"] == ["456"]
    assert update_params["ids"] == ["456"]


@patch("app.routes.sentiment.execute_sql")
def test_reparse_mode1_all_reviewed_touches_nothing(mock_sql, client):
    mock_sql.side_effect = [[("123",), ("456",)]]

    resp = client.post("/sentiment/reparse", json={"messageIds": ["123", "456"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["reset"] == 0
    assert body["deletedParsedIdeas"] == 0
    assert body["skippedReviewed"] == 2
    # Only the reviewed-check ran — no delete, no update
    assert mock_sql.call_count == 1


@patch("app.routes.sentiment.execute_sql")
def test_reparse_mode2_excludes_reviewed_and_reports_count(mock_sql, client):
    mock_sql.side_effect = [
        [(3,)],  # count of reviewed-and-skipped messages
        [],  # delete
        [],  # update
    ]

    resp = client.post("/sentiment/reparse", json={"resetStatuses": ["error"]})

    assert resp.status_code == 200
    assert resp.json()["skippedReviewed"] == 3
    delete_query = mock_sql.call_args_list[1].args[0]
    update_query = mock_sql.call_args_list[2].args[0]
    assert "NOT EXISTS" in delete_query
    assert "NOT EXISTS" in update_query
    assert "review_status <> 'unreviewed'" in delete_query


# ---------------------------------------------------------------------------
# save_parsed_ideas_atomic (canonical writer in src.db)
# ---------------------------------------------------------------------------


def _mock_transaction(conn):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=ctx)


def test_atomic_writer_freezes_reviewed_message():
    from src.db import save_parsed_ideas_atomic

    conn = MagicMock()
    # The review-check SELECT finds a reviewed row
    conn.execute.return_value.fetchone.return_value = (1,)

    with patch("src.db.transaction", _mock_transaction(conn)):
        inserted = save_parsed_ideas_atomic(
            "12345", [{"idea_text": "new parse that must be discarded"}], status="ok", prompt_version="v1.2"
        )

    assert inserted == 0
    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert not any("DELETE" in q for q in executed), "curated rows must not be deleted"
    assert not any("INSERT" in q for q in executed), "new parse must be discarded"
    assert any("parse_status = 'ok'" in q for q in executed), (
        "message must be marked ok so it doesn't loop as pending"
    )


def test_atomic_writer_normal_path_still_replaces():
    from src.db import save_parsed_ideas_atomic

    conn = MagicMock()
    # No reviewed rows for this message
    conn.execute.return_value.fetchone.return_value = None

    with patch("src.db.transaction", _mock_transaction(conn)):
        inserted = save_parsed_ideas_atomic(
            "12345", [{"idea_text": "fresh parse", "message_id": "12345"}], status="ok", prompt_version="v1.2"
        )

    assert inserted == 1
    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any("DELETE" in q for q in executed)
    assert any("INSERT" in q for q in executed)


# ---------------------------------------------------------------------------
# GET /ideas/discord-parsed (review queue listing)
# ---------------------------------------------------------------------------


def _parsed_row(**overrides):
    base = {
        "id": str(uuid4()),
        "message_id": "999",
        "idea_text": "NVDA looks strong into earnings",
        "idea_summary": "Bullish NVDA earnings play",
        "primary_symbol": "NVDA",
        "symbols": ["NVDA"],
        "labels": ["EARNINGS_PLAY"],
        "direction": "bullish",
        "action": "buy",
        "is_noise": False,
        "confidence": 0.91,
        "parsed_at": "2026-07-01T10:00:00+00:00",
        "review_status": "unreviewed",
        "review_notes": None,
        "attribution_kind": "self",
        "attributed_person_id": None,
        "thesis_bucket": None,
        "filing_type": None,
        "filing_period": None,
        "institution_name": None,
        "message_content": "NVDA looks strong into earnings, adding calls",
        "message_author": "qais",
        "message_channel": "trades",
        "message_created_at": "2026-07-01T09:59:00+00:00",
    }
    base.update(overrides)
    return base


@patch("app.routes.ideas.execute_sql")
def test_list_parsed_ideas_for_review(mock_sql, client):
    mock_sql.side_effect = [
        [(1,)],  # count
        [_row(_parsed_row())],  # page
    ]

    resp = client.get("/ideas/discord-parsed?review_status=unreviewed&symbol=nvda")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["primarySymbol"] == "NVDA"
    assert item["reviewStatus"] == "unreviewed"
    assert item["messageAuthor"] == "qais"
    # Symbol filter is upper-cased and passed through
    count_params = mock_sql.call_args_list[0].kwargs["params"]
    assert count_params["symbol"] == "NVDA"


def test_list_parsed_ideas_rejects_bad_review_status(client):
    resp = client.get("/ideas/discord-parsed?review_status=bogus")
    assert resp.status_code == 400
