import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient

        from app.main import app
        with TestClient(app) as c:
            yield c


def _mock_openai(content: str):
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=content))]
    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


@patch("app.routes.profiles.OpenAI")
def test_interview_generates_questions(mock_openai_cls, client):
    payload = json.dumps({"questions": [
        {"field": "thesis", "question": "Why do you hold AAPL?"},
        {"field": "sell_trigger", "question": "What would make you sell?"},
        {"field": "conviction", "question": "Conviction 1-5 and why?"},
    ]})
    mock_openai_cls.return_value = _mock_openai(payload)
    r = client.post("/stocks/AAPL/profile/interview?bucket=long_term",
                    json={"autofill": {"trackRecord": {"tradeCount": 3}}, "answers": []})
    assert r.status_code == 200
    qs = r.json()["questions"]
    assert len(qs) == 3
    assert qs[0]["field"] == "thesis"
    assert r.json()["followUp"] is False
