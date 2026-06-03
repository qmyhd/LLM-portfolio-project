from src.youtube import parse_video_id, parse_channel_key


def test_parse_video_id_watch():
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

def test_parse_video_id_short():
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ?t=30") == "dQw4w9WgXcQ"

def test_parse_video_id_shorts_embed_live():
    assert parse_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

def test_parse_video_id_invalid():
    assert parse_video_id("https://example.com/foo") is None
    assert parse_video_id("not a url") is None

def test_parse_channel_key_prefers_channel_id():
    assert parse_channel_key("https://www.youtube.com/channel/UCabc123DEF456ghiJKL789m") == "UCabc123DEF456ghiJKL789m"

def test_parse_channel_key_handle_best_effort():
    assert parse_channel_key("https://www.youtube.com/@PiersMorganUncensored") == "@PiersMorganUncensored"

def test_parse_channel_key_none():
    assert parse_channel_key(None) is None
    assert parse_channel_key("https://www.youtube.com/") is None


def test_fetch_transcript_success(monkeypatch):
    import src.youtube as yt
    monkeypatch.setattr(yt, "_get_transcript_raw",
                        lambda vid: [{"text": "hello", "start": 1.0, "duration": 2.0}])
    ok, segs, reason = yt.fetch_transcript("abc")
    assert ok is True and segs[0]["text"] == "hello" and reason is None

def test_fetch_transcript_unavailable(monkeypatch):
    import src.youtube as yt
    def _boom(vid):
        raise RuntimeError("TranscriptsDisabled")
    monkeypatch.setattr(yt, "_get_transcript_raw", _boom)
    ok, segs, reason = yt.fetch_transcript("abc")
    assert ok is False and segs == [] and isinstance(reason, str)
