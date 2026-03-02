"""
Tests for app/routes/ideas.py — unified ideas CRUD + refine.

All tests mock execute_sql and OpenAI — no external dependencies.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Create a test client with auth disabled."""
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from app.main import app
        with TestClient(app) as c:
            yield c


def _mock_row(data: dict):
    """Create a mock SQLAlchemy Row with _mapping attribute."""
    row = MagicMock()
    row._mapping = data
    return row


SAMPLE_UUID = str(uuid4())
SAMPLE_IDEA_ROW = {
    "id": SAMPLE_UUID,
    "symbol": "AAPL",
    "symbols": ["AAPL", "MSFT"],
    "content": "Buy AAPL on dip",
    "source": "manual",
    "status": "draft",
    "tags": ["thesis"],
    "origin_message_id": None,
    "content_hash": "abc123",
    "created_at": "2026-02-24T12:00:00+00:00",
    "updated_at": "2026-02-24T12:00:00+00:00",
}


# =========================================================================
# GET /ideas — List
# =========================================================================

class TestListIdeas:
    @patch("app.routes.ideas.execute_sql")
    def test_list_empty(self, mock_sql, client):
        """Empty list returns zero ideas."""
        mock_sql.side_effect = [
            [_mock_row({"cnt": 0})],  # count query
            [],  # data query
        ]
        resp = client.get("/ideas")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ideas"] == []
        assert data["total"] == 0
        assert data["hasMore"] is False

    @patch("app.routes.ideas.execute_sql")
    def test_list_with_ideas(self, mock_sql, client):
        """Returns ideas with correct structure."""
        mock_sql.side_effect = [
            [_mock_row({"cnt": 1})],
            [_mock_row(SAMPLE_IDEA_ROW)],
        ]
        resp = client.get("/ideas")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["ideas"]) == 1
        idea = data["ideas"][0]
        assert idea["id"] == SAMPLE_UUID
        assert idea["symbol"] == "AAPL"
        assert idea["symbols"] == ["AAPL", "MSFT"]
        assert idea["source"] == "manual"
        assert idea["status"] == "draft"

    @patch("app.routes.ideas.execute_sql")
    def test_list_filters_symbol(self, mock_sql, client):
        """Symbol filter is applied."""
        mock_sql.side_effect = [
            [_mock_row({"cnt": 1})],
            [_mock_row(SAMPLE_IDEA_ROW)],
        ]
        resp = client.get("/ideas?symbol=AAPL")
        assert resp.status_code == 200
        # Verify the SQL was called with UPPER symbol
        call_args = mock_sql.call_args_list[0]
        assert "UPPER(symbol) = :symbol" in call_args[0][0]
        assert call_args[1]["params"]["symbol"] == "AAPL"

    @patch("app.routes.ideas.execute_sql")
    def test_list_filters_source(self, mock_sql, client):
        """Source filter is applied."""
        mock_sql.side_effect = [
            [_mock_row({"cnt": 0})],
            [],
        ]
        resp = client.get("/ideas?source=discord")
        assert resp.status_code == 200

    def test_list_invalid_source(self, client):
        """Invalid source returns 400."""
        with patch("app.routes.ideas.execute_sql"):
            resp = client.get("/ideas?source=invalid")
            assert resp.status_code == 400

    def test_list_invalid_status(self, client):
        """Invalid status returns 400."""
        with patch("app.routes.ideas.execute_sql"):
            resp = client.get("/ideas?status=invalid")
            assert resp.status_code == 400


# =========================================================================
# POST /ideas — Create
# =========================================================================

class TestCreateIdea:
    @patch("app.routes.ideas.compute_content_hash", return_value="hash123")
    @patch("app.routes.ideas.execute_sql")
    def test_create_success(self, mock_sql, mock_hash, client):
        """Create idea returns 201 with correct data."""
        mock_sql.return_value = [_mock_row(SAMPLE_IDEA_ROW)]
        resp = client.post("/ideas", json={
            "content": "Buy AAPL on dip",
            "symbol": "AAPL",
            "symbols": ["AAPL", "MSFT"],
            "tags": ["thesis"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Buy AAPL on dip"
        assert data["source"] == "manual"

    @patch("app.routes.ideas.execute_sql")
    def test_create_empty_content_rejected(self, mock_sql, client):
        """Empty content returns 400."""
        resp = client.post("/ideas", json={"content": "   "})
        assert resp.status_code == 400

    @patch("app.routes.ideas.execute_sql")
    def test_create_invalid_source(self, mock_sql, client):
        """Invalid source returns 400."""
        resp = client.post("/ideas", json={"content": "test", "source": "invalid"})
        assert resp.status_code == 400

    @patch("app.routes.ideas.compute_content_hash", return_value="hash123")
    @patch("app.routes.ideas.execute_sql")
    def test_create_default_source(self, mock_sql, mock_hash, client):
        """Default source is 'manual'."""
        mock_sql.return_value = [_mock_row({**SAMPLE_IDEA_ROW, "source": "manual"})]
        resp = client.post("/ideas", json={"content": "test idea"})
        assert resp.status_code == 201
        # Verify source=manual was passed to SQL
        call_args = mock_sql.call_args
        assert call_args[1]["params"]["source"] == "manual"


# =========================================================================
# PUT /ideas/{id} — Update
# =========================================================================

class TestUpdateIdea:
    @patch("app.routes.ideas.compute_content_hash", return_value="newhash")
    @patch("app.routes.ideas.execute_sql")
    def test_update_content(self, mock_sql, mock_hash, client):
        """Update content re-computes content_hash."""
        updated_row = {**SAMPLE_IDEA_ROW, "content": "Updated content", "content_hash": "newhash"}
        mock_sql.return_value = [_mock_row(updated_row)]
        resp = client.put(f"/ideas/{SAMPLE_UUID}", json={"content": "Updated content"})
        assert resp.status_code == 200
        assert resp.json()["content"] == "Updated content"

    @patch("app.routes.ideas.execute_sql")
    def test_update_status(self, mock_sql, client):
        """Update status only."""
        updated_row = {**SAMPLE_IDEA_ROW, "status": "archived"}
        mock_sql.return_value = [_mock_row(updated_row)]
        resp = client.put(f"/ideas/{SAMPLE_UUID}", json={"status": "archived"})
        assert resp.status_code == 200

    @patch("app.routes.ideas.execute_sql")
    def test_update_not_found(self, mock_sql, client):
        """Non-existent idea returns 404."""
        mock_sql.return_value = []
        resp = client.put(f"/ideas/{SAMPLE_UUID}", json={"content": "test"})
        assert resp.status_code == 404

    def test_update_no_fields(self, client):
        """Empty update returns 400."""
        with patch("app.routes.ideas.execute_sql"):
            resp = client.put(f"/ideas/{SAMPLE_UUID}", json={})
            assert resp.status_code == 400

    @patch("app.routes.ideas.execute_sql")
    def test_update_invalid_status(self, mock_sql, client):
        """Invalid status returns 400."""
        resp = client.put(f"/ideas/{SAMPLE_UUID}", json={"status": "invalid"})
        assert resp.status_code == 400


# =========================================================================
# DELETE /ideas/{id}
# =========================================================================

class TestDeleteIdea:
    @patch("app.routes.ideas.execute_sql")
    def test_delete_success(self, mock_sql, client):
        """Delete returns 204."""
        mock_sql.side_effect = [
            [_mock_row({"id": SAMPLE_UUID})],  # existence check
            None,  # delete
        ]
        resp = client.delete(f"/ideas/{SAMPLE_UUID}")
        assert resp.status_code == 204

    @patch("app.routes.ideas.execute_sql")
    def test_delete_not_found(self, mock_sql, client):
        """Non-existent idea returns 404."""
        mock_sql.return_value = []
        resp = client.delete(f"/ideas/{SAMPLE_UUID}")
        assert resp.status_code == 404


# =========================================================================
# POST /ideas/{id}/refine
# =========================================================================

class TestRefineIdea:
    @patch("app.routes.ideas.execute_sql")
    def test_refine_not_found(self, mock_sql, client):
        """Non-existent idea returns 404."""
        mock_sql.return_value = []
        resp = client.post(f"/ideas/{SAMPLE_UUID}/refine")
        assert resp.status_code == 404

    @patch("app.routes.ideas.execute_sql")
    def test_refine_success(self, mock_sql, client):
        """Refine returns structured response."""
        import json

        # First call: fetch idea
        mock_sql.return_value = [_mock_row({
            "id": SAMPLE_UUID,
            "content": "Buy AAPL",
            "symbol": "AAPL",
            "symbols": ["AAPL"],
            "tags": [],
            "status": "draft",
        })]

        refine_result = {
            "refinedContent": "Consider buying AAPL on a pullback to the $180 support level.",
            "extractedSymbols": ["AAPL"],
            "suggestedTags": ["thesis", "entry", "technical"],
            "changesSummary": "Added price level and improved clarity.",
        }

        # Mock OpenAI
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content=json.dumps(refine_result)))
        ]
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_completion

        with patch.dict("os.environ", {"OPENAI_API_KEY": "fake-key"}), \
             patch("openai.OpenAI", return_value=mock_client_instance):
            resp = client.post(f"/ideas/{SAMPLE_UUID}/refine")

        assert resp.status_code == 200
        data = resp.json()
        assert data["refinedContent"] == refine_result["refinedContent"]
        assert data["extractedSymbols"] == ["AAPL"]
        assert "thesis" in data["suggestedTags"]
        assert data["changesSummary"] == refine_result["changesSummary"]

    @patch("app.routes.ideas.compute_content_hash", return_value="newhash")
    @patch("app.routes.ideas.execute_sql")
    def test_refine_with_apply(self, mock_sql, mock_hash, client):
        """Refine with apply=true updates the idea."""
        import json

        mock_sql.return_value = [_mock_row({
            "id": SAMPLE_UUID,
            "content": "Buy AAPL",
            "symbol": "AAPL",
            "symbols": ["AAPL"],
            "tags": [],
            "status": "draft",
        })]

        refine_result = {
            "refinedContent": "Refined AAPL thesis",
            "extractedSymbols": ["AAPL"],
            "suggestedTags": ["thesis"],
            "changesSummary": "Improved.",
        }

        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content=json.dumps(refine_result)))
        ]
        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_completion

        with patch.dict("os.environ", {"OPENAI_API_KEY": "fake-key"}), \
             patch("openai.OpenAI", return_value=mock_client_instance):
            resp = client.post(f"/ideas/{SAMPLE_UUID}/refine?apply=true")

        assert resp.status_code == 200
        # Verify UPDATE was called (second execute_sql call)
        assert mock_sql.call_count >= 2
        update_call = mock_sql.call_args_list[-1]
        assert "UPDATE user_ideas" in update_call[0][0]
        assert update_call[1]["params"]["content"] == "Refined AAPL thesis"


# =========================================================================
# GET /ideas/{id}/context — Context
# =========================================================================

class TestIdeaContext:
    @patch("app.routes.ideas.execute_sql")
    def test_returns_context_with_surrounding_messages(self, mock_sql, client):
        """GET /ideas/{id}/context returns parent message + surrounding context."""
        idea_row = {**SAMPLE_IDEA_ROW, "origin_message_id": "msg-123"}
        mock_sql.side_effect = [
            [_mock_row(idea_row)],  # idea query
            [_mock_row({  # parent message
                "message_id": "msg-123", "content": "Buy AAPL on the dip",
                "author": "qaisy", "timestamp": "2026-02-28T14:30:00",
                "channel": "trading-ideas",
            })],
            [  # context messages (±5)
                _mock_row({"message_id": "msg-121", "content": "Market opening strong",
                           "author": "user2", "timestamp": "2026-02-28T14:28:00", "channel": "trading-ideas"}),
                _mock_row({"message_id": "msg-122", "content": "Watching tech names",
                           "author": "qaisy", "timestamp": "2026-02-28T14:29:00", "channel": "trading-ideas"}),
                _mock_row({"message_id": "msg-123", "content": "Buy AAPL on the dip",
                           "author": "qaisy", "timestamp": "2026-02-28T14:30:00", "channel": "trading-ideas"}),
                _mock_row({"message_id": "msg-124", "content": "Good call",
                           "author": "user3", "timestamp": "2026-02-28T14:31:00", "channel": "trading-ideas"}),
            ],
        ]

        response = client.get(f"/ideas/{SAMPLE_UUID}/context")
        assert response.status_code == 200
        data = response.json()
        assert data["parentMessage"]["messageId"] == "msg-123"
        assert len(data["contextMessages"]) >= 3
        # Parent message should be marked
        parent_in_context = [m for m in data["contextMessages"] if m["isParent"]]
        assert len(parent_in_context) == 1

    @patch("app.routes.ideas.execute_sql")
    def test_idea_not_found_returns_404(self, mock_sql, client):
        """GET /ideas/{id}/context returns 404 for non-existent idea."""
        mock_sql.return_value = []
        response = client.get(f"/ideas/{SAMPLE_UUID}/context")
        assert response.status_code == 404

    @patch("app.routes.ideas.execute_sql")
    def test_idea_without_origin_message(self, mock_sql, client):
        """Ideas without origin_message_id return empty context."""
        idea_row = {**SAMPLE_IDEA_ROW, "origin_message_id": None}
        mock_sql.return_value = [_mock_row(idea_row)]
        response = client.get(f"/ideas/{SAMPLE_UUID}/context")
        assert response.status_code == 200
        data = response.json()
        assert data["parentMessage"] is None
        assert data["contextMessages"] == []
        assert data["idea"]["id"] == SAMPLE_UUID


# =========================================================================
# GET /portfolio/movers — Top movers
# =========================================================================

class TestMovers:
    @patch("app.routes.portfolio.get_previous_closes_batch", return_value={})
    @patch("app.routes.portfolio.get_latest_closes_batch", return_value={})
    @patch("app.routes.portfolio.execute_sql")
    def test_movers_empty(self, mock_sql, mock_latest, mock_prev, client):
        """No positions returns empty movers."""
        mock_sql.return_value = []
        resp = client.get("/portfolio/movers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["topGainers"] == []
        assert data["topLosers"] == []

    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_movers_with_positions(self, mock_sql, mock_latest, mock_prev, client):
        """Returns gainers and losers from positions."""
        mock_sql.return_value = [
            _mock_row({"symbol": "AAPL", "quantity": 10, "average_cost": 150.0, "snaptrade_price": 0}),
            _mock_row({"symbol": "TSLA", "quantity": 5, "average_cost": 200.0, "snaptrade_price": 0}),
        ]
        mock_latest.return_value = {"AAPL": 160.0, "TSLA": 190.0}
        mock_prev.return_value = {"AAPL": 155.0, "TSLA": 195.0}

        resp = client.get("/portfolio/movers?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "intraday"
        # AAPL gained, TSLA lost
        gainer_symbols = [g["symbol"] for g in data["topGainers"]]
        loser_symbols = [l["symbol"] for l in data["topLosers"]]
        assert "AAPL" in gainer_symbols
        assert "TSLA" in loser_symbols
