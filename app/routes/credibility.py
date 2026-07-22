"""Credibility config API — categories, tier multipliers, stock topic tags.

Root-mounted router. Endpoints:
- GET    /credibility/categories          list credibility categories
- PUT    /credibility/categories          upsert categories
- GET    /credibility/tier-multipliers    tier -> multiplier map
- PUT    /credibility/tier-multipliers    upsert tier multipliers
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, HTTPException
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


# (per-stock topic-tags routes removed — the stock_topic_tags feature was cut.)
