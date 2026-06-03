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
