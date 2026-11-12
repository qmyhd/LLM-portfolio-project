"""Tests for app.access: the central role policy applied to every route."""

import inspect

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.access import (
    GUEST_WRITES,
    OWNER_ONLY_PREFIXES,
    enforce_access,
    required_role,
)
from app.auth import require_api_key
from app.identity import OWNER_VIEWER, PENDING_VIEWER, Viewer, resolve_viewer

PENDING_MSG = "This account is waiting for approval"
OWNER_MSG = "This action needs the owner"
OPEN_PREFIXES = ("/health", "/webhook", "/auth", "/docs", "/redoc", "/openapi.json")


@pytest.fixture
def app_obj():
    from app.main import app

    return app


@pytest.fixture
def client_as(app_obj):
    """Factory: TestClient whose caller resolves to the given role."""
    saved = dict(app_obj.dependency_overrides)

    def make(role: str) -> TestClient:
        viewer = {
            "pending": PENDING_VIEWER,
            "owner": OWNER_VIEWER,
        }.get(role, Viewer(f"{role}-id", role))
        app_obj.dependency_overrides[resolve_viewer] = lambda: viewer
        app_obj.dependency_overrides[require_api_key] = lambda: None
        return TestClient(app_obj, raise_server_exceptions=False)

    yield make
    app_obj.dependency_overrides.clear()
    app_obj.dependency_overrides.update(saved)


def _stub_handler(monkeypatch, app_obj, method, path, result):
    route = next(
        r
        for r in app_obj.routes
        if isinstance(r, APIRoute) and r.path == path and method in r.methods
    )
    if inspect.iscoroutinefunction(route.dependant.call):

        async def stub(**_):
            return result

    else:

        def stub(**_):
            return result

    monkeypatch.setattr(route.dependant, "call", stub)


@pytest.mark.parametrize(
    "method,path,query,expected",
    [
        ("GET", "/portfolio", {}, "guest"),
        ("GET", "/portfolio/equity-curve", {}, "owner"),
        ("GET", "/connections", {}, "owner"),
        ("GET", "/stocks/{ticker}/analysis", {"refresh": "true"}, "owner"),
        ("GET", "/stocks/{ticker}/analysis", {}, "guest"),
        ("GET", "/stocks/{ticker}/analysis", {"refresh": "false"}, "guest"),
        ("GET", "/stocks/{ticker}/analysis", {"refresh": "0"}, "guest"),
        ("GET", "/stocks/{ticker}/analysis", {"refresh": " YES "}, "owner"),
        ("GET", "/stocks/{ticker}/analysis", {"refresh": "1"}, "owner"),
        ("GET", "/stocks/{ticker}/analysis", {"refresh": "on"}, "owner"),
        ("POST", "/stocks/{ticker}/chat", {}, "guest"),
        ("POST", "/portfolio/sync", {}, "owner"),
        ("PUT", "/stocks/{ticker}/profile", {}, "owner"),
        ("DELETE", "/ideas/{idea_id}", {}, "owner"),
    ],
)
def test_required_role(method, path, query, expected):
    assert required_role(method, path, query) == expected


def test_owner_prefix_matches_on_boundary_only():
    assert required_role("GET", "/users", {}) == "owner"
    assert required_role("GET", "/users/{user_id}", {}) == "owner"
    assert required_role("GET", "/users-export", {}) == "guest"
    assert required_role("GET", "/connectionsx", {}) == "guest"
    assert required_role("GET", "/portfolio/equity-curves", {}) == "guest"


def _all_routes(app_obj):
    return [r for r in app_obj.routes if isinstance(r, APIRoute)]


def _enforced(route) -> bool:
    return any(d.call is enforce_access for d in route.dependant.dependencies)


def test_every_route_is_covered(app_obj):
    uncovered = [
        f"{sorted(r.methods)} {r.path}"
        for r in _all_routes(app_obj)
        if r.path != "/" and not r.path.startswith(OPEN_PREFIXES) and not _enforced(r)
    ]
    assert not uncovered, uncovered


def test_every_mutating_route_is_owner_or_listed(app_obj):
    for r in _all_routes(app_obj):
        if r.path.startswith(OPEN_PREFIXES):
            continue
        for m in r.methods - {"GET", "HEAD", "OPTIONS"}:
            assert required_role(m, r.path, {}) == "owner" or (m, r.path) in GUEST_WRITES, (
                m,
                r.path,
            )


def test_guest_writes_and_prefixes_exist_in_app(app_obj):
    paths = {(m, r.path) for r in _all_routes(app_obj) for m in r.methods}
    assert GUEST_WRITES <= paths
    assert "/connections" in OWNER_ONLY_PREFIXES


def test_unmatched_route_requires_owner():
    def make(role):
        viewer = Viewer("u", role)
        return Request({"type": "http", "method": "GET", "headers": [], "query_string": b""}), viewer

    import anyio
    from fastapi import HTTPException

    request, guest = make("guest")
    with pytest.raises(HTTPException) as exc:
        anyio.run(enforce_access, request, guest)
    assert (exc.value.status_code, exc.value.detail) == (403, OWNER_MSG)

    request, owner = make("owner")
    assert anyio.run(enforce_access, request, owner) is owner
    assert request.state.viewer is owner


SAMPLE = [
    ("GET", "/portfolio"),
    ("GET", "/stocks/AAPL/analysis"),
    ("GET", "/watchlist"),
    ("POST", "/stocks/AAPL/chat"),
    ("PUT", "/stocks/AAPL/profile"),
    ("GET", "/connections"),
]


@pytest.mark.parametrize("method,url", SAMPLE)
def test_pending_gets_403_everywhere(client_as, method, url):
    r = client_as("pending").request(method, url, json={} if method != "GET" else None)
    assert r.status_code == 403
    assert r.json()["detail"] == PENDING_MSG


@pytest.mark.parametrize("role", ["guest", "family"])
def test_guest_write_is_403(client_as, role):
    r = client_as(role).put("/stocks/AAPL/profile", json={})
    assert r.status_code == 403
    assert r.json()["detail"] == OWNER_MSG


@pytest.mark.parametrize("role", ["guest", "family"])
def test_owner_only_read_and_refresh_are_403(client_as, role):
    c = client_as(role)
    assert c.get("/connections").json()["detail"] == OWNER_MSG
    r = c.get("/stocks/AAPL/analysis?refresh=true")
    assert (r.status_code, r.json()["detail"]) == (403, OWNER_MSG)


@pytest.mark.parametrize("role", ["guest", "family", "owner"])
def test_chat_is_allowed_through_policy(client_as, app_obj, monkeypatch, role):
    _stub_handler(
        monkeypatch, app_obj, "POST", "/stocks/{ticker}/chat", {"response": "hi", "sources": []}
    )
    r = client_as(role).post("/stocks/AAPL/chat", json={"message": "hello"})
    assert r.status_code == 200
    assert r.json()["response"] == "hi"


def test_family_matches_guest(client_as, app_obj, monkeypatch):
    _stub_handler(monkeypatch, app_obj, "GET", "/watchlist", {})
    for role in ("guest", "family"):
        c = client_as(role)
        assert c.get("/watchlist").status_code != 403
        assert c.put("/stocks/AAPL/profile", json={}).status_code == 403
        assert c.get("/connections").status_code == 403


def test_owner_passes(client_as, app_obj, monkeypatch):
    # Stubbed handlers may fail response validation (500); the policy only
    # has to let the owner through, so assert "not refused" for these.
    _stub_handler(monkeypatch, app_obj, "GET", "/connections", [])
    _stub_handler(monkeypatch, app_obj, "GET", "/stocks/{ticker}/analysis", {})
    c = client_as("owner")
    assert c.get("/connections").status_code != 403
    assert c.get("/stocks/AAPL/analysis?refresh=true").status_code != 403
