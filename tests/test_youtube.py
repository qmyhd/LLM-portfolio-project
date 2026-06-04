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


def test_fetch_oembed_success(monkeypatch):
    import src.youtube as yt
    class _Resp:
        status_code = 200
        @staticmethod
        def json():
            return {"title": "Vid Title", "author_name": "Some Channel",
                    "author_url": "https://www.youtube.com/@somechannel"}
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
    out = yt.fetch_oembed("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert out["title"] == "Vid Title"
    assert out["author_name"] == "Some Channel"
    assert out["author_url"].endswith("@somechannel")

def test_fetch_oembed_non_200_returns_empty(monkeypatch):
    import src.youtube as yt
    class _Resp:
        status_code = 404
        @staticmethod
        def json():
            return {}
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
    assert yt.fetch_oembed("https://www.youtube.com/watch?v=x") == {}

def test_fetch_oembed_exception_returns_empty(monkeypatch):
    import src.youtube as yt
    def _boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr("requests.get", _boom)
    assert yt.fetch_oembed("https://www.youtube.com/watch?v=x") == {}


# --------- Phase: proxy support + RequestBlocked handling (hotfix) ---------

_PROXY_ENV = (
    "YOUTUBE_TRANSCRIPT_WEBSHARE_USERNAME",
    "YOUTUBE_TRANSCRIPT_WEBSHARE_PASSWORD",
    "YOUTUBE_TRANSCRIPT_WEBSHARE_LOCATIONS",
    "YOUTUBE_TRANSCRIPT_HTTP_PROXY",
    "YOUTUBE_TRANSCRIPT_HTTPS_PROXY",
)


def _clear_proxy_env(monkeypatch):
    for v in _PROXY_ENV:
        monkeypatch.delenv(v, raising=False)


def test_build_proxy_config_none(monkeypatch):
    import src.youtube as yt
    _clear_proxy_env(monkeypatch)
    assert yt._build_proxy_config() is None


def test_build_proxy_config_webshare(monkeypatch):
    import src.youtube as yt
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_TRANSCRIPT_WEBSHARE_USERNAME", "u")
    monkeypatch.setenv("YOUTUBE_TRANSCRIPT_WEBSHARE_PASSWORD", "p")
    monkeypatch.setenv("YOUTUBE_TRANSCRIPT_WEBSHARE_LOCATIONS", "us, de")
    cfg = yt._build_proxy_config()
    assert type(cfg).__name__ == "WebshareProxyConfig"


def test_build_proxy_config_generic(monkeypatch):
    import src.youtube as yt
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_TRANSCRIPT_HTTPS_PROXY", "https://user:pass@proxy.example:8080")
    cfg = yt._build_proxy_config()
    assert type(cfg).__name__ == "GenericProxyConfig"


def test_build_proxy_config_webshare_wins_over_generic(monkeypatch):
    import src.youtube as yt
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("YOUTUBE_TRANSCRIPT_WEBSHARE_USERNAME", "u")
    monkeypatch.setenv("YOUTUBE_TRANSCRIPT_WEBSHARE_PASSWORD", "p")
    monkeypatch.setenv("YOUTUBE_TRANSCRIPT_HTTPS_PROXY", "https://proxy.example:8080")
    assert type(yt._build_proxy_config()).__name__ == "WebshareProxyConfig"


def test_fetch_transcript_requestblocked_friendly_reason(monkeypatch):
    import src.youtube as yt

    class RequestBlocked(Exception):
        pass

    monkeypatch.setattr(yt, "_get_transcript_raw", lambda vid: (_ for _ in ()).throw(RequestBlocked("x")))
    ok, segs, reason = yt.fetch_transcript("abc")
    assert ok is False and segs == []
    assert "blocked transcript requests" in reason.lower()


def test_fetch_transcript_ipblocked_friendly_reason(monkeypatch):
    import src.youtube as yt

    class IpBlocked(Exception):
        pass

    monkeypatch.setattr(yt, "_get_transcript_raw", lambda vid: (_ for _ in ()).throw(IpBlocked("x")))
    _, _, reason = yt.fetch_transcript("abc")
    assert "blocked transcript requests" in reason.lower()


def test_fetch_transcript_generic_error_never_raises(monkeypatch):
    import src.youtube as yt

    monkeypatch.setattr(yt, "_get_transcript_raw", lambda vid: (_ for _ in ()).throw(ValueError("weird")))
    ok, segs, reason = yt.fetch_transcript("abc")
    assert ok is False and segs == [] and reason == "ValueError"
