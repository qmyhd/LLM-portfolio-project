"""
Access policy: one place that decides which role every API route needs.

`enforce_access` is attached to every router in `app/main.py` (except /auth and
/webhook). It resolves the caller with `resolve_viewer` and compares their role
with `required_role(method, route_path, query)`.

Policy:
1. pending                                  -> 403 (waiting for approval)
2. path under an OWNER_ONLY_PREFIXES entry  -> owner
3. GET / HEAD / OPTIONS                     -> guest, but a `refresh` that is not a clear no -> owner
4. any other method                         -> owner, unless listed in GUEST_WRITES

A route the policy cannot match (no route in scope) needs the owner.
"""

from collections.abc import Mapping

from fastapi import Depends, HTTPException, Request

from app.identity import ROLE_RANK, Viewer, resolve_viewer

GUEST_WRITES: frozenset[tuple[str, str]] = frozenset({("POST", "/stocks/{ticker}/chat")})
OWNER_ONLY_PREFIXES: tuple[str, ...] = (
    "/connections",
    "/users",
    "/debug",
    "/options",
    "/portfolio/equity-curve",
    "/portfolio/sync",
)
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# `refresh` is parsed by pydantic as a bool, which accepts more spellings than
# we could list (t, y, True, ...). So fail closed: only these values, or no
# parameter at all, mean "no refresh". Anything else, garbage included, is owner.
_FALSY = frozenset({"", "0", "false", "no", "off", "f", "n"})


def _under_prefix(route_path: str) -> bool:
    """True when route_path equals a prefix or sits below it (path boundary)."""
    return any(route_path == p or route_path.startswith(p + "/") for p in OWNER_ONLY_PREFIXES)


def _requests_refresh(query: Mapping[str, str | list[str]]) -> bool:
    """True unless `refresh` is absent or every occurrence is a clear "no"."""
    raw = query.get("refresh")
    if raw is None:
        return False
    values = [raw] if isinstance(raw, str) else list(raw)
    return any(str(v).strip().lower() not in _FALSY for v in values)


def required_role(
    method: str, route_path: str, query: Mapping[str, str | list[str]]
) -> str:
    """Return "guest" or "owner": the lowest role allowed to call this route."""
    method = method.upper()
    if _under_prefix(route_path):
        return "owner"
    if method in _READ_METHODS:
        return "owner" if _requests_refresh(query) else "guest"
    return "guest" if (method, route_path) in GUEST_WRITES else "owner"


async def enforce_access(
    request: Request, viewer: Viewer = Depends(resolve_viewer)
) -> Viewer:
    """FastAPI dependency: refuse the request unless the caller's role is enough."""
    if viewer.role == "pending":
        raise HTTPException(status_code=403, detail="This account is waiting for approval")

    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if route_path is None:
        needed = "owner"  # unknown route: never open
    else:
        # getlist: a repeated ?refresh=false&refresh=true must not slip through.
        query = {"refresh": request.query_params.getlist("refresh")}
        needed = required_role(request.method, route_path, query)

    if ROLE_RANK.get(viewer.role, 0) < ROLE_RANK[needed]:
        raise HTTPException(status_code=403, detail="This action needs the owner")

    request.state.viewer = viewer
    return viewer
