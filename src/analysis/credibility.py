"""Source-credibility resolver. Pure blend math + a DB-backed loader.

Implements docs/superpowers/specs/2026-06-03-source-credibility-layer-design.md §5.
Neutral by default: missing data anywhere resolves to a 1.0 (no-op) multiplier.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from src.db import execute_sql

logger = logging.getLogger(__name__)

CLAMP_LO = 0.30
CLAMP_HI = 1.50

# Spec §2 seed curve — used as a fallback if tier_multipliers is empty/unavailable.
DEFAULT_TIER_MULTIPLIERS: dict[str, float] = {"S": 1.35, "A": 1.15, "B": 1.00, "C": 0.75, "D": 0.45}


@dataclass
class CredibilityResult:
    multiplier: float = 1.0
    muted_out: bool = False                 # True iff every tagged category was muted -> 0.0
    person_id: Optional[int] = None
    person_name: Optional[str] = None
    tiers: dict[str, str] = field(default_factory=dict)   # category -> tier letter (explainability)


def _clamp(x: float) -> float:
    return max(CLAMP_LO, min(CLAMP_HI, x))


def blend_multiplier(
    *,
    tags: dict[str, float],
    tiers: dict[str, tuple[str, bool]],     # category -> (tier_letter, muted)
    multipliers: dict[str, float],
) -> CredibilityResult:
    """Spec §5 effective multiplier. tag weights are normalized here (read time)."""
    total_w = sum(w for w in tags.values() if w and w > 0)
    if total_w <= 0:
        return CredibilityResult(multiplier=1.0)

    num = 0.0
    used_tiers: dict[str, str] = {}
    for category, w in tags.items():
        if not w or w <= 0:
            continue
        entry = tiers.get(category)
        if entry is None:
            tier_mult = 1.0                  # untiered -> neutral term
        else:
            letter, muted = entry
            used_tiers[category] = letter
            tier_mult = 0.0 if muted else multipliers.get(letter, 1.0)
        num += w * tier_mult

    raw = num / total_w
    if raw == 0.0:                           # ALL tagged categories muted -> hard exclusion
        return CredibilityResult(multiplier=0.0, muted_out=True, tiers=used_tiers)
    return CredibilityResult(multiplier=_clamp(raw), tiers=used_tiers)


def _row_mapping(r):
    return r._mapping if hasattr(r, "_mapping") else r


class CredibilityResolver:
    """DB-backed, batched, fail-safe credibility lookup for a symbol's idea authors.

    Loading is best-effort: any failure leaves the resolver with empty data so
    every ``multiplier()`` call returns a neutral 1.0. The resolver NEVER raises.
    """

    def __init__(
        self,
        *,
        mults: dict[str, float],
        tags: dict[str, float],
        identity: dict[str, tuple[int, Optional[str]]],
        tiers: dict[int, dict[str, tuple[str, bool]]],
    ) -> None:
        self._mults = mults
        self._tags = tags
        self._identity = identity
        self._tiers = tiers

    @classmethod
    def for_ideas(cls, symbol: str, author_ids: list[str]) -> "CredibilityResolver":
        mults: dict[str, float] = {}
        tags: dict[str, float] = {}
        identity: dict[str, tuple[int, Optional[str]]] = {}
        tiers: dict[int, dict[str, tuple[str, bool]]] = {}

        try:
            # Dedupe + drop blanks/None FIRST. Coerce to str (DB may emit ints).
            ids: list[str] = []
            seen: set[str] = set()
            for a in author_ids or []:
                if a is None:
                    continue
                s = str(a)
                if not s or s in seen:
                    continue
                seen.add(s)
                ids.append(s)

            # 1. tier multipliers
            for r in execute_sql("SELECT tier, multiplier FROM tier_multipliers", params={}, fetch_results=True) or []:
                m = _row_mapping(r)
                mults[m["tier"]] = float(m["multiplier"])
            if not mults:
                mults = dict(DEFAULT_TIER_MULTIPLIERS)

            # 2. stock topic tags
            tag_rows = execute_sql(
                "SELECT category_slug, weight FROM stock_topic_tags WHERE UPPER(symbol) = :symbol",
                params={"symbol": symbol.upper()},
                fetch_results=True,
            ) or []
            for r in tag_rows:
                m = _row_mapping(r)
                tags[m["category_slug"]] = float(m["weight"])

            # 3. identities (only if we have ids — never emit IN ())
            if ids:
                placeholders = ", ".join(f":id{i}" for i in range(len(ids)))
                idp = {f"id{i}": v for i, v in enumerate(ids)}
                id_rows = execute_sql(
                    "SELECT si.platform_user_id, si.person_id, p.full_name "
                    "FROM source_identities si JOIN people p ON p.id = si.person_id "
                    "WHERE si.platform = 'discord' AND si.match_status = 'confirmed' "
                    f"AND si.platform_user_id IN ({placeholders})",
                    params=idp,
                    fetch_results=True,
                ) or []
                for r in id_rows:
                    m = _row_mapping(r)
                    identity[str(m["platform_user_id"])] = (int(m["person_id"]), m["full_name"])

            # 4. person category tiers (only if any person_ids found)
            person_ids = sorted({pid for pid, _ in identity.values()})
            if person_ids:
                placeholders = ", ".join(f":pid{i}" for i in range(len(person_ids)))
                pidp = {f"pid{i}": v for i, v in enumerate(person_ids)}
                tier_rows = execute_sql(
                    "SELECT person_id, category_slug, tier, muted FROM person_category_tiers "
                    f"WHERE person_id IN ({placeholders})",
                    params=pidp,
                    fetch_results=True,
                ) or []
                for r in tier_rows:
                    m = _row_mapping(r)
                    pid = int(m["person_id"])
                    tiers.setdefault(pid, {})[m["category_slug"]] = (m["tier"], bool(m["muted"]))
        except Exception:  # noqa: BLE001 — fail-safe: degrade to neutral, never raise
            logger.warning("CredibilityResolver.for_ideas failed; defaulting to neutral", exc_info=True)
            return cls(mults={}, tags={}, identity={}, tiers={})

        return cls(mults=mults, tags=tags, identity=identity, tiers=tiers)

    def multiplier(self, author_id: str) -> CredibilityResult:
        try:
            if not author_id or author_id not in self._identity:
                return CredibilityResult(multiplier=1.0)
            person_id, name = self._identity[author_id]
            person_tiers = self._tiers.get(person_id, {})
            res = blend_multiplier(tags=self._tags, tiers=person_tiers, multipliers=self._mults)
            res.person_id = person_id
            res.person_name = name
            return res
        except Exception:  # noqa: BLE001 — never raise; prefer neutral
            logger.warning("CredibilityResolver.multiplier failed; defaulting to neutral", exc_info=True)
            return CredibilityResult(multiplier=1.0)
