"""Tests for the self-reflection pattern in idea refinement."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def client():
    """Create test client with auth disabled."""
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from app.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c


@pytest.fixture
def mock_idea_row():
    """Mock DB row for a user_ideas record."""
    row = MagicMock()
    row._mapping = {
        "id": str(uuid4()),
        "content": "I think AAPL is going up because earnings were strong",
        "symbol": "AAPL",
        "symbols": ["AAPL"],
        "tags": ["earnings"],
        "status": "draft",
    }
    return row


@pytest.mark.openai
def test_refine_with_reflection_no_issues(client, mock_idea_row):
    """When reflect finds no issues, only 2 OpenAI calls are made (refine + reflect)."""
    refine_result = json.dumps({
        "refinedContent": "AAPL bullish thesis: Strong Q1 earnings beat with 15% revenue growth.",
        "extractedSymbols": ["AAPL"],
        "suggestedTags": ["earnings", "growth"],
        "changesSummary": "Structured the thesis with specific metrics.",
    })
    reflect_result = json.dumps({
        "issues_found": False,
        "critique": "No issues found. The refinement accurately represents the original idea.",
        "hallucinated_targets": [],
        "ticker_verified": True,
    })

    mock_openai = MagicMock()
    call_count = [0]

    def make_response(content):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        return resp

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        messages = kwargs.get("messages", [])
        system_msg = messages[0]["content"] if messages else ""
        if "critique" in system_msg.lower() or "reflect" in system_msg.lower():
            return make_response(reflect_result)
        return make_response(refine_result)

    mock_openai.return_value.chat.completions.create.side_effect = side_effect

    with patch("app.routes.ideas.execute_sql", return_value=[mock_idea_row]), \
         patch("app.routes.ideas.OpenAI", mock_openai):
        resp = client.post(f"/ideas/{mock_idea_row._mapping['id']}/refine")

    assert resp.status_code == 200
    data = resp.json()
    assert data["refinedContent"] == "AAPL bullish thesis: Strong Q1 earnings beat with 15% revenue growth."
    assert data["reflectionApplied"] is False
    assert call_count[0] == 2  # refine + reflect, no re-refine


@pytest.mark.openai
def test_refine_with_reflection_has_issues(client, mock_idea_row):
    """When reflect finds issues, 3 OpenAI calls are made (refine + reflect + re-refine)."""
    refine_result = json.dumps({
        "refinedContent": "AAPL bullish: Target price $250 based on DCF model.",
        "extractedSymbols": ["AAPL"],
        "suggestedTags": ["thesis", "value"],
        "changesSummary": "Added price target.",
    })
    reflect_result = json.dumps({
        "issues_found": True,
        "critique": "Hallucinated price target of $250 — original idea had no price target.",
        "hallucinated_targets": ["$250"],
        "ticker_verified": True,
    })
    rerefine_result = json.dumps({
        "refinedContent": "AAPL bullish thesis: Strong earnings suggest continued upside potential.",
        "extractedSymbols": ["AAPL"],
        "suggestedTags": ["thesis", "earnings"],
        "changesSummary": "Removed hallucinated price target, kept original meaning.",
    })

    mock_openai = MagicMock()
    call_count = [0]

    def make_response(content):
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = content
        return resp

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        messages = kwargs.get("messages", [])
        system_msg = messages[0]["content"] if messages else ""
        if "critique" in system_msg.lower() or "reflect" in system_msg.lower():
            return make_response(reflect_result)
        if call_count[0] == 3:  # Third call is re-refine
            return make_response(rerefine_result)
        return make_response(refine_result)

    mock_openai.return_value.chat.completions.create.side_effect = side_effect

    with patch("app.routes.ideas.execute_sql", return_value=[mock_idea_row]), \
         patch("app.routes.ideas.OpenAI", mock_openai):
        resp = client.post(f"/ideas/{mock_idea_row._mapping['id']}/refine")

    assert resp.status_code == 200
    data = resp.json()
    assert "hallucinated" not in data["refinedContent"].lower()
    assert data["reflectionApplied"] is True
    assert call_count[0] == 3
