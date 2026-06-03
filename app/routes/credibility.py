"""Credibility config API — categories, tier multipliers, stock topic tags.

Root-mounted router. Endpoints:
- GET    /credibility/categories          list credibility categories
- PUT    /credibility/categories          upsert categories
- GET    /credibility/tier-multipliers    tier -> multiplier map
- PUT    /credibility/tier-multipliers    upsert tier multipliers
- GET    /stocks/{ticker}/topic-tags      per-symbol category weights
- PUT    /stocks/{ticker}/topic-tags      replace per-symbol category weights
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import text

from src.db import execute_sql, transaction

logger = logging.getLogger(__name__)
router = APIRouter()

_VALID_TIERS = {"S", "A", "B", "C", "D"}


def _lock_key(key: str) -> int:
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _map(row) -> dict:
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


class CategoryBody(BaseModel):
    slug: str
    label: str
    description: str | None = None
    sortOrder: int = 0


class CategoriesBody(BaseModel):
    categories: list[CategoryBody]


class TierMultipliersBody(BaseModel):
    multipliers: dict[str, float]  # {tier: multiplier}


class TopicTagBody(BaseModel):
    categorySlug: str
    weight: float


class TopicTagsBody(BaseModel):
    tags: list[TopicTagBody]


# --------------------------------------------------------------------------- #
# Credibility categories
# --------------------------------------------------------------------------- #


@router.get("/credibility/categories")
async def get_categories():
    rows = execute_sql(
        """
        SELECT slug, label, description, sort_order
        FROM credibility_categories
        ORDER BY sort_order, slug
        """,
        fetch_results=True,
    ) or []
    categories = []
    for r in rows:
        rd = _map(r)
        categories.append({
            "slug": rd.get("slug"),
            "label": rd.get("label"),
            "description": rd.get("description"),
            "sortOrder": rd.get("sort_order"),
        })
    return {"categories": categories}


@router.put("/credibility/categories")
async def put_categories(body: CategoriesBody):
    with transaction() as conn:
        for c in body.categories:
            conn.execute(
                text(
                    """
                    INSERT INTO credibility_categories
                        (slug, label, description, sort_order)
                    VALUES (:slug, :label, :description, :sort_order)
                    ON CONFLICT (slug) DO UPDATE SET
                        label = EXCLUDED.label,
                        description = EXCLUDED.description,
                        sort_order = EXCLUDED.sort_order
                    """
                ),
                {"slug": c.slug, "label": c.label,
                 "description": c.description, "sort_order": c.sortOrder},
            )
    return {
        "categories": [
            {"slug": c.slug, "label": c.label,
             "description": c.description, "sortOrder": c.sortOrder}
            for c in body.categories
        ]
    }


# --------------------------------------------------------------------------- #
# Tier multipliers
# --------------------------------------------------------------------------- #


@router.get("/credibility/tier-multipliers")
async def get_tier_multipliers():
    rows = execute_sql(
        "SELECT tier, multiplier FROM tier_multipliers",
        fetch_results=True,
    ) or []
    multipliers = {}
    for r in rows:
        rd = _map(r)
        multipliers[rd.get("tier")] = float(rd.get("multiplier"))
    return {"multipliers": multipliers}


@router.put("/credibility/tier-multipliers")
async def put_tier_multipliers(body: TierMultipliersBody):
    for tier in body.multipliers:
        if tier not in _VALID_TIERS:
            raise HTTPException(status_code=400, detail=f"invalid tier '{tier}'")
    with transaction() as conn:
        for tier, mult in body.multipliers.items():
            conn.execute(
                text(
                    """
                    INSERT INTO tier_multipliers (tier, multiplier)
                    VALUES (:tier, :mult)
                    ON CONFLICT (tier) DO UPDATE SET
                        multiplier = EXCLUDED.multiplier
                    """
                ),
                {"tier": tier, "mult": mult},
            )
    return {"multipliers": body.multipliers}


# --------------------------------------------------------------------------- #
# Stock topic tags
# --------------------------------------------------------------------------- #


@router.get("/stocks/{ticker}/topic-tags")
async def get_topic_tags(ticker: str = Path(...)):
    symbol = ticker.upper()
    rows = execute_sql(
        """
        SELECT category_slug, weight
        FROM stock_topic_tags
        WHERE UPPER(symbol) = :symbol
        ORDER BY category_slug
        """,
        params={"symbol": symbol},
        fetch_results=True,
    ) or []
    tags = []
    for r in rows:
        rd = _map(r)
        tags.append({
            "categorySlug": rd.get("category_slug"),
            "weight": float(rd.get("weight")),
        })
    return {"symbol": symbol, "tags": tags}


@router.put("/stocks/{ticker}/topic-tags")
async def put_topic_tags(ticker: str = Path(...), body: TopicTagsBody = ...):  # noqa: B008
    for t in body.tags:
        if t.weight < 0:
            raise HTTPException(status_code=400, detail="weight must be >= 0")
    symbol = ticker.upper()
    lock = _lock_key(symbol)
    with transaction() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock})
        conn.execute(
            text("DELETE FROM stock_topic_tags WHERE UPPER(symbol) = :symbol"),
            {"symbol": symbol},
        )
        for t in body.tags:
            conn.execute(
                text(
                    """
                    INSERT INTO stock_topic_tags (symbol, category_slug, weight)
                    VALUES (:symbol, :slug, :weight)
                    """
                ),
                {"symbol": symbol, "slug": t.categorySlug, "weight": t.weight},
            )
    return {
        "symbol": symbol,
        "tags": [
            {"categorySlug": t.categorySlug, "weight": t.weight}
            for t in body.tags
        ],
    }
