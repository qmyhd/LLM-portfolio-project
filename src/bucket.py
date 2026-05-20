"""
Account strategy bucket utilities.

A "bucket" classifies a brokerage account by trading strategy. Stored on
`accounts.bucket` (added in schema migration 069). Used to filter
positions, trades, activities, orders, and risk by strategy.

Buckets:
- long_term: taxable buy-and-hold (e.g., the current Robinhood account)
- swing: multi-day to multi-week positions
- day: intraday
- retirement: IRA / Roth IRA / 401k — tax-advantaged
- other: uncategorized / fallback for new connections

Historical queries JOIN against the *current* bucket on `accounts`
(retroactive labeling), so reassigning an account immediately re-labels
its position/trade history. This is intentional — simpler model, no
per-row bucket history.
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, Query

BucketName = Literal["long_term", "swing", "day", "retirement", "other"]

VALID_BUCKETS: frozenset[str] = frozenset(
    {"long_term", "swing", "day", "retirement", "other"}
)

# Sentinel for "no filter" in query params. Accepted alongside missing /
# empty / None so the frontend can be explicit.
ALL_BUCKETS_SENTINEL = "all"


def validate_bucket(bucket: str | None) -> str | None:
    """Normalize and validate a bucket query parameter.

    Returns the normalized bucket name, or None when no filter should be
    applied (input was None, empty, or 'all'). Raises HTTPException(400)
    for any other unrecognized value so endpoints can use this directly
    without an extra try/except.
    """
    if not bucket:
        return None
    normalized = bucket.strip().lower()
    if normalized in ("", ALL_BUCKETS_SENTINEL):
        return None
    if normalized not in VALID_BUCKETS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid bucket '{bucket}'. "
                f"Must be one of: {sorted(VALID_BUCKETS)} or 'all'."
            ),
        )
    return normalized


def bucket_filter_sql(
    bucket: str | None,
    alias: str = "acc",
) -> tuple[str, dict[str, str]]:
    """Build a SQL AND clause + params dict for filtering by bucket.

    Args:
        bucket: A *validated* bucket name (output of validate_bucket), or
            None for no filter.
        alias: SQL alias of the `accounts` table in the outer query.

    Returns:
        (fragment, params). The fragment is the empty string when no filter
        is needed, so callers can always concatenate without conditionals:

            clause, bp = bucket_filter_sql(bucket, alias="acc")
            sql = f\"\"\"
                SELECT ...
                FROM positions p
                JOIN accounts acc ON acc.id = p.account_id
                WHERE p.quantity > 0
                  AND COALESCE(acc.connection_status, 'connected') != 'deleted'
                  {clause}
            \"\"\"
            execute_sql(sql, params={**existing, **bp}, fetch_results=True)
    """
    if not bucket:
        return "", {}
    return f" AND {alias}.bucket = :bucket ", {"bucket": bucket}


# Reusable FastAPI Query parameter declaration. Use as:
#     bucket: str | None = BucketQuery
BucketQuery = Query(
    None,
    description=(
        "Filter by strategy bucket. One of: long_term, swing, day, "
        "retirement, other, or 'all' / omitted for no filter."
    ),
    examples=["long_term", "swing", "all"],
)
