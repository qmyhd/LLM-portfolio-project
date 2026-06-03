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


# --------------------------- Phase D: quote CRUD --------------------------- #

def _quote_body(**over):
    b = {"videoId": "vid1", "videoUrl": "https://youtu.be/vid1",
         "quoteText": "hello world", "startSeconds": 12.5}
    b.update(over)
    return b


_QUOTE_ROW = {
    "id": 1, "video_id": "v", "video_url": "u", "video_title": None, "channel_name": None,
    "channel_url": None, "quote_text": "t", "start_seconds": 1.0, "end_seconds": None,
    "person_id": 7, "category_slug": "macro", "ticker": None, "stock_thesis_profile_id": None,
    "thesis_note": None, "tags": [], "notes": None, "status": "active",
    "saved_at": "2026-06-03T00:00:00+00:00", "updated_at": "2026-06-03T00:00:00+00:00",
    "person_name": "Sachs", "category_label": "Macro",
}


@patch("app.routes.videos.transaction")
def test_create_quote(mock_tx, client):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (1,)
    mock_tx.return_value.__enter__.return_value = conn
    r = client.post("/quotes", json=_quote_body(categorySlug="markets", ticker="aapl", tags=["macro"]))
    assert r.status_code == 200
    assert r.json()["id"] == 1
    bound = conn.execute.call_args.args[1]
    assert bound["quote_text"] == "hello world"
    assert bound["video_id"] == "vid1"
    assert float(bound["start_seconds"]) == 12.5
    assert bound["tags"] == ["macro"]


@patch("app.routes.videos.transaction")
def test_create_quote_defaults_tags_empty(mock_tx, client):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (2,)
    mock_tx.return_value.__enter__.return_value = conn
    r = client.post("/quotes", json=_quote_body())
    assert r.status_code == 200
    assert conn.execute.call_args.args[1]["tags"] == []


@patch("app.routes.videos.execute_sql")
def test_list_quotes_defaults_active(mock_sql, client):
    mock_sql.return_value = []
    client.get("/quotes")
    call = mock_sql.call_args
    sql = call.args[0]
    params = call.kwargs.get("params", {})
    assert "vq.status = :status" in sql
    assert params["status"] == "active"


@patch("app.routes.videos.execute_sql")
def test_list_quotes_filters(mock_sql, client):
    mock_sql.return_value = []
    client.get("/quotes?q=infl&person_id=7&category=macro&ticker=aapl&video_id=vid1&status=archived")
    call = mock_sql.call_args
    sql = call.args[0]
    params = call.kwargs["params"]
    assert "ILIKE :q" in sql and params["q"] == "%infl%"
    assert "vq.person_id = :person_id" in sql and params["person_id"] == 7
    assert "vq.category_slug = :category" in sql and params["category"] == "macro"
    assert "UPPER(vq.ticker) = UPPER(:ticker)" in sql and params["ticker"] == "aapl"
    assert "vq.video_id = :video_id" in sql and params["video_id"] == "vid1"
    assert params["status"] == "archived"


@patch("app.routes.videos.execute_sql")
def test_list_quotes_joins_labels(mock_sql, client):
    mock_sql.return_value = [_row(dict(_QUOTE_ROW))]
    r = client.get("/quotes")
    sql = mock_sql.call_args.args[0]
    assert "LEFT JOIN people" in sql and "credibility_categories" in sql
    item = r.json()["quotes"][0]
    assert item["personName"] == "Sachs" and item["categoryLabel"] == "Macro"
    assert item["videoId"] == "v" and item["quoteText"] == "t"


@patch("app.routes.videos.execute_sql")
def test_get_quote_detail(mock_sql, client):
    mock_sql.return_value = [_row(dict(_QUOTE_ROW))]
    r = client.get("/quotes/1")
    assert r.status_code == 200 and r.json()["id"] == 1


@patch("app.routes.videos.execute_sql")
def test_get_quote_404(mock_sql, client):
    mock_sql.return_value = []
    assert client.get("/quotes/999").status_code == 404


@patch("app.routes.videos.transaction")
def test_update_quote(mock_tx, client):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = (1,)
    mock_tx.return_value.__enter__.return_value = conn
    r = client.put("/quotes/1", json=_quote_body(quoteText="edited", notes="n"))
    assert r.status_code == 200
    bound = conn.execute.call_args.args[1]
    assert bound["quote_text"] == "edited" and bound["id"] == 1


@patch("app.routes.videos.transaction")
def test_update_quote_404(mock_tx, client):
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    mock_tx.return_value.__enter__.return_value = conn
    assert client.put("/quotes/999", json=_quote_body()).status_code == 404


@patch("app.routes.videos.execute_sql")
def test_delete_quote_soft_archive(mock_sql, client):
    mock_sql.return_value = [_row({"id": 1})]
    r = client.delete("/quotes/1")
    assert r.status_code == 200 and r.json()["status"] == "archived"
    sql = mock_sql.call_args.args[0]
    assert "archived" in sql and "DELETE FROM" not in sql.upper()


@patch("app.routes.videos.execute_sql")
def test_delete_quote_404(mock_sql, client):
    mock_sql.return_value = []
    assert client.delete("/quotes/999").status_code == 404
