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


def _mock_openai_seq(*contents):
    completions = []
    for c in contents:
        comp = MagicMock()
        comp.choices = [MagicMock(message=MagicMock(content=c))]
        completions.append(comp)
    client = MagicMock()
    client.chat.completions.create.side_effect = completions
    return client


@patch("app.routes.profiles.OpenAI")
def test_synthesize_no_issues_single_pass(mock_openai_cls, client):
    draft = json.dumps({"thesis": "Quality compounder.", "bullCase": "services",
                        "bearCase": "china", "catalysts": [{"text": "WWDC"}], "risks": [],
                        "conviction": 4, "levels": {"target": 240}})
    reflect = json.dumps({"issues_found": False, "critique": "ok"})
    mock_openai_cls.return_value = _mock_openai_seq(draft, reflect)
    r = client.post("/stocks/AAPL/profile/synthesize?bucket=long_term",
                    json={"autofill": {}, "answers": [{"field": "thesis", "answer": "compounder"}]})
    assert r.status_code == 200
    d = r.json()["draft"]
    assert d["thesis"].startswith("Quality")
    assert d["conviction"] == 4
    assert r.json()["reflectionApplied"] is False


@patch("app.routes.profiles.OpenAI")
def test_synthesize_rerefines_on_issues(mock_openai_cls, client):
    draft = json.dumps({"thesis": "v1", "conviction": 3, "levels": {"target": 999}})
    reflect = json.dumps({"issues_found": True, "critique": "hallucinated target 999"})
    fixed = json.dumps({"thesis": "v2 corrected", "conviction": 3, "levels": {}})
    mock_openai_cls.return_value = _mock_openai_seq(draft, reflect, fixed)
    r = client.post("/stocks/AAPL/profile/synthesize?bucket=swing",
                    json={"autofill": {}, "answers": []})
    assert r.status_code == 200
    assert r.json()["draft"]["thesis"] == "v2 corrected"
    assert r.json()["reflectionApplied"] is True
