"""Users API (owner only): list accounts, change roles, add and remove password accounts.

Mounted at /users. `app.access` makes everything under /users owner-only and
stores the caller on `request.state.viewer`.

Endpoints:
- GET    /users                      all accounts, pending first
- POST   /users                      create a password account
- PATCH  /users/{user_id}            change a role
- DELETE /users/{user_id}            delete an account
- POST   /users/{user_id}/password   reset a password account's password

The "at least one owner must remain" rule lives inside the same SQL statement
as the change. The statement first locks every owner row (`FOR UPDATE`), so a
second request that would remove the other owner waits, then re-reads the
owners that are left and is refused.

Nothing here logs an email, username, password or hash.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.auth import _owner_emails
from app.identity import invalidate_viewer
from app.passwords import (
    check_password_rules,
    hash_password,
    normalize_username,
)
from src.db import execute_sql

logger = logging.getLogger(__name__)
router = APIRouter()

Role = Literal["pending", "guest", "family", "owner"]

GOOGLE_OWNER_MSG = "Owner access for Google accounts comes from OWNER_EMAILS"
SELF_MSG = "You can't change your own access"
LAST_OWNER_MSG = "At least one owner must remain"
NOT_FOUND_MSG = "User not found"
USERNAME_TAKEN_MSG = "That username is taken"
PICK_ROLE_MSG = "Pick guest, family or owner"
GOOGLE_PASSWORD_MSG = "Google accounts sign in with Google"
PROMOTE_MSG = "Create a new password account with the Owner role instead"
OWNER_EMAIL_MSG = (
    "This account is an owner through OWNER_EMAILS. Remove the email there first"
)

_COLUMNS = "id, provider, provider_user_id, email, full_name, avatar_url, role, created_at, last_seen_at"

# Locks every owner row for the rest of the statement's transaction. Rows that
# stop being owners while we wait are dropped when the lock is granted.
_OWNERS_CTE = "WITH owners AS (SELECT id FROM app_users WHERE role = 'owner' ORDER BY id FOR UPDATE)"
_OTHER_OWNER_LEFT = "(SELECT count(*) FROM owners WHERE id <> CAST(:id AS uuid)) >= 1"


class RoleBody(BaseModel):
    role: Role


class CreateUserBody(BaseModel):
    username: str
    password: str
    role: Role


class PasswordBody(BaseModel):
    password: str


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _row_to_user(row, caller_id: str | None) -> dict:
    rd = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    uid = str(rd["id"])
    is_password = rd["provider"] == "password"
    return {
        "id": uid,
        "provider": rd["provider"],
        "username": rd["provider_user_id"] if is_password else None,
        "email": rd["email"],
        "fullName": rd.get("full_name"),
        "avatarUrl": rd.get("avatar_url"),
        "role": rd["role"],
        "createdAt": _iso(rd.get("created_at")),
        "lastSeenAt": _iso(rd.get("last_seen_at")),
        "isSelf": caller_id is not None and uid == caller_id,
    }


def _caller_id(request: Request) -> str | None:
    viewer = getattr(request.state, "viewer", None)
    return getattr(viewer, "user_id", None)


def _parse_id(user_id: str) -> str:
    """Canonical uuid string, or 404 without touching the database."""
    try:
        return str(uuid.UUID(user_id))
    except ValueError:
        raise HTTPException(status_code=404, detail=NOT_FOUND_MSG) from None


def _fetch(uid: str):
    rows = execute_sql(
        f"SELECT {_COLUMNS} FROM app_users WHERE id = CAST(:id AS uuid)",
        params={"id": uid},
        fetch_results=True,
    )
    return rows[0] if rows else None


def _refuse_owner_email(user: dict) -> None:
    """A Google owner listed in OWNER_EMAILS is promoted again at next sign-in."""
    if user["provider"] == "google" and user["email"].strip().lower() in _owner_emails():
        raise HTTPException(status_code=400, detail=OWNER_EMAIL_MSG)


def _refuse_self(request: Request, uid: str) -> None:
    if _caller_id(request) == uid:
        raise HTTPException(status_code=400, detail=SELF_MSG)


def _log(request: Request, target: str, action: str) -> None:
    logger.info("users: %s changed %s: %s", _caller_id(request), target, action)


@router.get("")
async def list_users(request: Request):
    rows = execute_sql(
        f"""
        SELECT {_COLUMNS}
        FROM app_users
        ORDER BY (role = 'pending') DESC, last_seen_at DESC
        """,
        fetch_results=True,
    ) or []
    caller = _caller_id(request)
    users = [_row_to_user(r, caller) for r in rows]
    return {
        "users": users,
        "pendingCount": sum(1 for u in users if u["role"] == "pending"),
    }


@router.post("", status_code=201)
def create_user(request: Request, body: CreateUserBody):
    if body.role == "pending":
        raise HTTPException(status_code=400, detail=PICK_ROLE_MSG)
    try:
        username = normalize_username(body.username)
        check_password_rules(body.password, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    rows = execute_sql(
        f"""
        INSERT INTO app_users
            (provider, provider_user_id, email, full_name, password_hash, role)
        VALUES ('password', :username, :email, :full_name, :hash, :role)
        ON CONFLICT DO NOTHING
        RETURNING {_COLUMNS}
        """,
        params={
            "username": username,
            "email": f"{username}@local",
            "full_name": username,
            "hash": hash_password(body.password),
            "role": body.role,
        },
        fetch_results=True,
    )
    if not rows:
        raise HTTPException(status_code=409, detail=USERNAME_TAKEN_MSG)
    user = _row_to_user(rows[0], _caller_id(request))
    invalidate_viewer(user["id"])
    _log(request, user["id"], f"created password account as {body.role}")
    return user


@router.patch("/{user_id}")
async def change_role(request: Request, user_id: str, body: RoleBody):
    uid = _parse_id(user_id)
    _refuse_self(request, uid)
    current = _fetch(uid)
    if current is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)
    existing = _row_to_user(current, _caller_id(request))
    before = existing["role"]
    caller = _caller_id(request)
    if before == body.role:
        return existing
    _refuse_owner_email(existing)
    if body.role == "owner":
        # A password account's length can't be checked here, so owners are
        # only created through POST /users, which enforces the owner minimum.
        raise HTTPException(
            status_code=400,
            detail=GOOGLE_OWNER_MSG if existing["provider"] == "google" else PROMOTE_MSG,
        )

    rows = execute_sql(
        f"""
        {_OWNERS_CTE}
        UPDATE app_users SET role = :role
        WHERE id = CAST(:id AS uuid)
          AND :role <> 'owner'
          AND (role <> 'owner' OR {_OTHER_OWNER_LEFT})
        RETURNING {_COLUMNS}
        """,
        params={"id": uid, "role": body.role},
        fetch_results=True,
    )
    if not rows:
        # No row changed: the user vanished, or this would have left no owner.
        if _fetch(uid) is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)
        raise HTTPException(status_code=400, detail=LAST_OWNER_MSG)
    invalidate_viewer(uid)
    _log(request, uid, f"role {before} -> {body.role}")
    return _row_to_user(rows[0], caller)


@router.delete("/{user_id}", status_code=204)
async def delete_user(request: Request, user_id: str):
    uid = _parse_id(user_id)
    _refuse_self(request, uid)
    current = _fetch(uid)
    if current is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)
    _refuse_owner_email(_row_to_user(current, None))
    rows = execute_sql(
        f"""
        {_OWNERS_CTE}
        DELETE FROM app_users
        WHERE id = CAST(:id AS uuid)
          AND (role <> 'owner' OR {_OTHER_OWNER_LEFT})
        RETURNING id
        """,
        params={"id": uid},
        fetch_results=True,
    )
    if not rows:
        if _fetch(uid) is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)
        raise HTTPException(status_code=400, detail=LAST_OWNER_MSG)
    invalidate_viewer(uid)
    _log(request, uid, "deleted")
    return Response(status_code=204)


@router.post("/{user_id}/password", status_code=204)
def reset_password(request: Request, user_id: str, body: PasswordBody):
    uid = _parse_id(user_id)
    current = _fetch(uid)
    if current is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)
    existing = _row_to_user(current, _caller_id(request))
    if existing["provider"] != "password":
        raise HTTPException(status_code=400, detail=GOOGLE_PASSWORD_MSG)
    try:
        check_password_rules(body.password, existing["role"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    try:
        check_password_rules(body.password, "owner")
        owner_ok = True
    except ValueError:
        owner_ok = False

    # The role is re-checked in the UPDATE: it may have changed since the read.
    rows = execute_sql(
        """
        UPDATE app_users
        SET password_hash = :hash, failed_login_count = 0, locked_until = NULL
        WHERE id = CAST(:id AS uuid) AND provider = 'password'
          AND (role <> 'owner' OR :owner_ok)
        RETURNING id
        """,
        params={"id": uid, "hash": hash_password(body.password), "owner_ok": owner_ok},
        fetch_results=True,
    )
    if not rows:
        if _fetch(uid) is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)
        try:
            check_password_rules(body.password, "owner")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        raise HTTPException(status_code=404, detail=NOT_FOUND_MSG)
    invalidate_viewer(uid)
    _log(request, uid, "password reset")
    return Response(status_code=204)
