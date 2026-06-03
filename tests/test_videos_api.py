from unittest.mock import MagicMock, patch

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


VALID = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@patch("app.routes.videos.fetch_transcript")
@patch("app.routes.videos.fetch_oembed")
def test_resolve_bad_url_400(mock_oembed, mock_tx, client):
    r = client.post("/videos/resolve", json={"url": "https://example.com/nope"})
    assert r.status_code == 400


@patch("app.routes.videos.execute_sql")
@patch("app.routes.videos.fetch_transcript")
@patch("app.routes.videos.fetch_oembed")
def test_resolve_available(mock_oembed, mock_tx, mock_sql, client):
    mock_oembed.return_value = {"title": "T", "author_name": "Chan",
                                "author_url": "https://www.youtube.com/@chan"}
    mock_tx.return_value = (True, [{"text": "hi", "start": 1.0, "duration": 2.0}], None)
    mock_sql.return_value = []  # no confirmed -> attempts suggested upsert
    r = client.post("/videos/resolve", json={"url": VALID})
    assert r.status_code == 200
    d = r.json()
    assert d["videoId"] == "dQw4w9WgXcQ"
    assert d["transcriptAvailable"] is True
    assert len(d["segments"]) == 1
    assert d["title"] == "T" and d["channelName"] == "Chan"


@patch("app.routes.videos.execute_sql")
@patch("app.routes.videos.fetch_transcript")
@patch("app.routes.videos.fetch_oembed")
def test_resolve_transcript_unavailable(mock_oembed, mock_tx, mock_sql, client):
    mock_oembed.return_value = {"title": "T", "author_name": "Chan",
                                "author_url": "https://www.youtube.com/@chan"}
    mock_tx.return_value = (False, [], "TranscriptsDisabled")
    mock_sql.return_value = []
    r = client.post("/videos/resolve", json={"url": VALID})
    assert r.status_code == 200
    d = r.json()
    assert d["transcriptAvailable"] is False
    assert d["segments"] == []
    assert d["reason"] == "TranscriptsDisabled"


@patch("app.routes.videos.execute_sql")
@patch("app.routes.videos.fetch_transcript")
@patch("app.routes.videos.fetch_oembed")
def test_resolve_oembed_failure_still_resolves(mock_oembed, mock_tx, mock_sql, client):
    mock_oembed.return_value = {}  # oEmbed failed
    mock_tx.return_value = (True, [{"text": "hi", "start": 0.0, "duration": 1.0}], None)
    mock_sql.return_value = []
    r = client.post("/videos/resolve", json={"url": VALID})
    assert r.status_code == 200
    d = r.json()
    assert d["title"] is None and d["channelName"] is None
    assert d["transcriptAvailable"] is True  # transcript still attempted


@patch("app.routes.videos.execute_sql")
@patch("app.routes.videos.fetch_transcript")
@patch("app.routes.videos.fetch_oembed")
def test_resolve_confirmed_identity(mock_oembed, mock_tx, mock_sql, client):
    mock_oembed.return_value = {"title": "T", "author_name": "Sachs Channel",
                                "author_url": "https://www.youtube.com/channel/UCabc123DEF456ghiJKL789m"}
    mock_tx.return_value = (True, [{"text": "hi", "start": 0.0, "duration": 1.0}], None)

    def _sql(query, params=None, fetch_results=False):
        if "confirmed" in query:
            return [_row({"person_id": 7, "full_name": "Jeffrey Sachs"})]
        return []
    mock_sql.side_effect = _sql

    r = client.post("/videos/resolve", json={"url": VALID})
    assert r.status_code == 200
    d = r.json()
    assert d["suggestedPersonId"] == 7
    assert d["suggestedPersonName"] == "Jeffrey Sachs"


@patch("app.routes.videos.execute_sql")
@patch("app.routes.videos.fetch_transcript")
@patch("app.routes.videos.fetch_oembed")
def test_resolve_unconfirmed_upserts_suggested(mock_oembed, mock_tx, mock_sql, client):
    mock_oembed.return_value = {"title": "T", "author_name": "New Chan",
                                "author_url": "https://www.youtube.com/channel/UCabc123DEF456ghiJKL789m"}
    mock_tx.return_value = (True, [], "empty transcript")
    calls = []

    def _sql(query, params=None, fetch_results=False):
        calls.append(query)
        return []  # no confirmed row
    mock_sql.side_effect = _sql

    r = client.post("/videos/resolve", json={"url": VALID})
    assert r.status_code == 200
    assert r.json()["suggestedPersonId"] is None
    assert any("INSERT INTO source_identities" in q for q in calls)
    # the suggested upsert must be ON CONFLICT DO NOTHING (never overwrite)
    assert any("ON CONFLICT" in q for q in calls if "INSERT INTO source_identities" in q)


@patch("app.routes.videos.execute_sql")
@patch("app.routes.videos.fetch_transcript")
@patch("app.routes.videos.fetch_oembed")
def test_resolve_no_channel_key_skips_identity(mock_oembed, mock_tx, mock_sql, client):
    # author_url with no /channel/UC and no @handle -> parse_channel_key None
    mock_oembed.return_value = {"title": "T", "author_name": "X",
                                "author_url": "https://www.youtube.com/"}
    mock_tx.return_value = (True, [{"text": "hi", "start": 0.0, "duration": 1.0}], None)
    r = client.post("/videos/resolve", json={"url": VALID})
    assert r.status_code == 200
    assert r.json()["suggestedPersonId"] is None
    mock_sql.assert_not_called()  # no key -> no DB identity work


@patch("app.routes.videos.execute_sql")
@patch("app.routes.videos.fetch_transcript")
@patch("app.routes.videos.fetch_oembed")
def test_resolve_db_error_does_not_500(mock_oembed, mock_tx, mock_sql, client):
    mock_oembed.return_value = {"title": "T", "author_name": "Chan",
                                "author_url": "https://www.youtube.com/@chan"}
    mock_tx.return_value = (True, [{"text": "hi", "start": 0.0, "duration": 1.0}], None)
    mock_sql.side_effect = RuntimeError("db down")
    r = client.post("/videos/resolve", json={"url": VALID})
    assert r.status_code == 200  # speaker resolution failure must not 500
    assert r.json()["suggestedPersonId"] is None
