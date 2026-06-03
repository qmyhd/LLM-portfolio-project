"""People (source credibility) API — profiles, tier ratings, and revisions.

Root-mounted router. Endpoints:
- POST   /people                  create a person (+ tiers, append revision)
- GET    /people                   list / prioritized review queue
- GET    /people/{id}              detail (+ tiers + linked identities)
- PUT    /people/{id}              update (replace tiers, append revision)
- DELETE /people/{id}              soft-archive
- GET    /people/{id}/revisions    saved-snapshot history
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import text

from src.db import execute_sql, transaction

logger = logging.getLogger(__name__)
router = APIRouter()


def _lock_key(key: str) -> int:
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _map(row) -> dict:
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


class PersonTierBody(BaseModel):
    categorySlug: str
    tier: str  # S/A/B/C/D
    muted: bool = False
    rationale: str | None = None


class PersonBody(BaseModel):
    fullName: str
    displayName: str | None = None
    role: str | None = None
    bio: str | None = None
    notes: str | None = None
    status: str = "active"
    tiers: list[PersonTierBody] = []


def _fetch_tiers(pid: int) -> list[dict]:
    rows = execute_sql(
        """
        SELECT category_slug, tier, muted, rationale
        FROM person_category_tiers
        WHERE person_id = :id
        ORDER BY category_slug
        """,
        params={"id": pid},
        fetch_results=True,
    ) or []
    out = []
    for r in rows:
        rd = _map(r)
        out.append({
            "categorySlug": rd.get("category_slug"),
            "tier": rd.get("tier"),
            "muted": bool(rd.get("muted")),
            "rationale": rd.get("rationale"),
        })
    return out


def _fetch_identities(pid: int) -> list[dict]:
    rows = execute_sql(
        """
        SELECT id, platform, platform_user_id, handle, match_status
        FROM source_identities
        WHERE person_id = :id
        ORDER BY platform, handle
        """,
        params={"id": pid},
        fetch_results=True,
    ) or []
    out = []
    for r in rows:
        rd = _map(r)
        out.append({
            "id": rd.get("id"),
            "platform": rd.get("platform"),
            "platformUserId": rd.get("platform_user_id"),
            "handle": rd.get("handle"),
            "matchStatus": rd.get("match_status"),
        })
    return out


def _person_detail(pid: int) -> dict:
    rows = execute_sql(
        """
        SELECT id, full_name, display_name, role, bio, notes, status, updated_at
        FROM people
        WHERE id = :id
        """,
        params={"id": pid},
        fetch_results=True,
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Person not found")
    rd = _map(rows[0])
    return {
        "id": rd.get("id"),
        "fullName": rd.get("full_name"),
        "displayName": rd.get("display_name"),
        "role": rd.get("role"),
        "bio": rd.get("bio"),
        "notes": rd.get("notes"),
        "status": rd.get("status"),
        "updatedAt": str(rd["updated_at"]) if rd.get("updated_at") else None,
        "tiers": _fetch_tiers(pid),
        "identities": _fetch_identities(pid),
    }


def _body_to_detail(pid: int, body: PersonBody) -> dict:
    return {
        "id": pid,
        "fullName": body.fullName,
        "displayName": body.displayName,
        "role": body.role,
        "bio": body.bio,
        "notes": body.notes,
        "status": body.status,
        "updatedAt": None,
        "tiers": [
            {"categorySlug": t.categorySlug, "tier": t.tier,
             "muted": t.muted, "rationale": t.rationale}
            for t in body.tiers
        ],
        "identities": [],
    }


def _insert_tiers(conn, pid: int, tiers: list[PersonTierBody]) -> None:
    for t in tiers:
        conn.execute(
            text(
                """
                INSERT INTO person_category_tiers
                    (person_id, category_slug, tier, muted, rationale)
                VALUES (:pid, :slug, :tier, :muted, :rationale)
                """
            ),
            {"pid": pid, "slug": t.categorySlug, "tier": t.tier,
             "muted": t.muted, "rationale": t.rationale},
        )


def _append_revision(conn, pid: int, body: PersonBody) -> None:
    conn.execute(
        text(
            """
            INSERT INTO person_revisions (person_id, snapshot_json)
            VALUES (:pid, CAST(:snap AS jsonb))
            """
        ),
        {"pid": pid, "snap": body.model_dump_json()},
    )


@router.post("/people")
async def create_person(body: PersonBody):
    with transaction() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO people (full_name, display_name, role, bio, notes, status)
                VALUES (:full_name, :display_name, :role, :bio, :notes, :status)
                RETURNING id
                """
            ),
            {"full_name": body.fullName, "display_name": body.displayName,
             "role": body.role, "bio": body.bio, "notes": body.notes,
             "status": body.status},
        )
        pid = row.fetchone()[0]
        _insert_tiers(conn, pid, body.tiers)
        _append_revision(conn, pid, body)
    return _body_to_detail(pid, body)


@router.get("/people")
async def list_people(
    status: str | None = Query(None),
    category: str | None = Query(None),
    tier: str | None = Query(None),
):
    params: dict = {}
    where = []
    join = ""
    if status == "archived":
        where.append("p.status = 'archived'")
    else:
        where.append("p.status != 'archived'")
    if category:
        join = "JOIN person_category_tiers pct ON pct.person_id = p.id "
        where.append("pct.category_slug = :category")
        params["category"] = category
        if tier:
            where.append("pct.tier = :tier")
            params["tier"] = tier
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = execute_sql(
        f"""
        SELECT p.id, p.full_name, p.display_name, p.role, p.status, p.updated_at,
               (NOT EXISTS (
                    SELECT 1 FROM person_category_tiers t WHERE t.person_id = p.id
                )
                OR EXISTS (
                    SELECT 1 FROM source_identities si
                    WHERE si.person_id = p.id AND si.match_status != 'confirmed'
                )) AS needs_attention
        FROM people p
        {join}{where_clause}
        ORDER BY needs_attention DESC, p.updated_at DESC
        """,
        params=params,
        fetch_results=True,
    ) or []
    people = []
    for r in rows:
        rd = _map(r)
        people.append({
            "id": rd.get("id"),
            "fullName": rd.get("full_name"),
            "displayName": rd.get("display_name"),
            "role": rd.get("role"),
            "status": rd.get("status"),
            "updatedAt": str(rd["updated_at"]) if rd.get("updated_at") else None,
            "needsAttention": bool(rd.get("needs_attention")),
        })
    return {"people": people}


@router.get("/people/{id}")
async def get_person(id: int = Path(...)):
    return _person_detail(id)


@router.put("/people/{id}")
async def update_person(id: int = Path(...), body: PersonBody = ...):  # noqa: B008
    lock = _lock_key(str(id))
    with transaction() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock})
        row = conn.execute(
            text(
                """
                UPDATE people SET
                    full_name = :full_name, display_name = :display_name,
                    role = :role, bio = :bio, notes = :notes, status = :status,
                    updated_at = NOW()
                WHERE id = :id
                RETURNING id
                """
            ),
            {"id": id, "full_name": body.fullName, "display_name": body.displayName,
             "role": body.role, "bio": body.bio, "notes": body.notes,
             "status": body.status},
        )
        if row.fetchone() is None:
            raise HTTPException(status_code=404, detail="Person not found")
        conn.execute(
            text("DELETE FROM person_category_tiers WHERE person_id = :id"),
            {"id": id},
        )
        _insert_tiers(conn, id, body.tiers)
        _append_revision(conn, id, body)
    return _person_detail(id)


@router.delete("/people/{id}")
async def delete_person(id: int = Path(...)):
    execute_sql(
        "UPDATE people SET status='archived', updated_at=NOW() WHERE id = :id",
        params={"id": id},
    )
    return {"status": "archived", "id": id}


@router.get("/people/{id}/revisions")
async def get_person_revisions(id: int = Path(...)):
    rows = execute_sql(
        """
        SELECT snapshot_json, created_at
        FROM person_revisions
        WHERE person_id = :id
        ORDER BY created_at DESC
        LIMIT 100
        """,
        params={"id": id},
        fetch_results=True,
    ) or []
    out = []
    for r in rows:
        rd = _map(r)
        out.append({
            "snapshot": rd.get("snapshot_json"),
            "createdAt": str(rd["created_at"]) if rd.get("created_at") else None,
        })
    return {"id": id, "revisions": out}
