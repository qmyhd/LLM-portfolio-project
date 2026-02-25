"""
Ideas API routes — unified ideas store (Discord + manual + transcribe).

Endpoints:
- GET    /ideas             — Paginated list with filters
- POST   /ideas             — Create a new idea
- PUT    /ideas/{id}        — Update an existing idea
- DELETE /ideas/{id}        — Delete an idea
- POST   /ideas/{id}/refine — AI auto-refine an idea
"""

import json
import logging
import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from src.db import execute_sql
from src.discord_ingest import compute_content_hash

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class IdeaOut(BaseModel):
    """Single idea response (camelCase for frontend)."""

    id: str
    symbol: Optional[str] = None
    symbols: list[str] = Field(default_factory=list)
    content: str
    source: str
    status: str
    tags: list[str] = Field(default_factory=list)
    originMessageId: Optional[str] = None
    contentHash: str
    createdAt: str
    updatedAt: str


class IdeasListResponse(BaseModel):
    """Paginated ideas list."""

    ideas: list[IdeaOut]
    total: int
    hasMore: bool


class CreateIdeaRequest(BaseModel):
    """Request body for creating an idea."""

    content: str
    symbol: Optional[str] = None
    symbols: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: str = "draft"
    source: str = "manual"


class UpdateIdeaRequest(BaseModel):
    """Request body for updating an idea (all fields optional)."""

    content: Optional[str] = None
    symbol: Optional[str] = None
    symbols: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None


class RefineResponse(BaseModel):
    """Auto-refine result."""

    refinedContent: str
    extractedSymbols: list[str]
    suggestedTags: list[str]
    changesSummary: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_idea(row) -> IdeaOut:
    """Convert a DB row to an IdeaOut model."""
    rd = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    return IdeaOut(
        id=str(rd["id"]),
        symbol=rd.get("symbol"),
        symbols=rd.get("symbols") or [],
        content=rd["content"],
        source=rd["source"],
        status=rd["status"],
        tags=rd.get("tags") or [],
        originMessageId=rd.get("origin_message_id"),
        contentHash=rd["content_hash"],
        createdAt=str(rd["created_at"]),
        updatedAt=str(rd["updated_at"]),
    )


_VALID_SOURCES = {"discord", "manual", "transcribe"}
_VALID_STATUSES = {"draft", "refined", "archived"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=IdeasListResponse)
async def list_ideas(
    symbol: Optional[str] = Query(None, description="Filter by primary symbol"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    source: Optional[str] = Query(None, description="Filter by source"),
    status: Optional[str] = Query(None, description="Filter by status"),
    q: Optional[str] = Query(None, description="Full-text search on content"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Get paginated ideas with optional filters."""
    try:
        # Build dynamic WHERE clauses
        conditions = []
        params: dict = {"limit": limit + 1, "offset": offset}

        if symbol:
            conditions.append("UPPER(symbol) = :symbol")
            params["symbol"] = symbol.upper()
        if tag:
            conditions.append(":tag = ANY(tags)")
            params["tag"] = tag.lower()
        if source:
            if source not in _VALID_SOURCES:
                raise HTTPException(status_code=400, detail=f"Invalid source: {source}")
            conditions.append("source = :source")
            params["source"] = source
        if status:
            if status not in _VALID_STATUSES:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
            conditions.append("status = :status")
            params["status"] = status
        if q:
            conditions.append("content ILIKE :q")
            params["q"] = f"%{q}%"

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        # Count total
        count_sql = f"SELECT COUNT(*) as cnt FROM user_ideas{where_clause}"
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        count_rows = execute_sql(count_sql, params=count_params, fetch_results=True)
        total = 0
        if count_rows:
            rd = dict(count_rows[0]._mapping) if hasattr(count_rows[0], "_mapping") else dict(count_rows[0])
            total = int(rd["cnt"])

        # Fetch ideas
        data_sql = f"""
            SELECT id, symbol, symbols, content, source, status, tags,
                   origin_message_id, content_hash, created_at, updated_at
            FROM user_ideas{where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        rows = execute_sql(data_sql, params=params, fetch_results=True)

        ideas_list = [_row_to_idea(row) for row in (rows or [])[:limit]]
        has_more = len(rows or []) > limit

        return IdeasListResponse(ideas=ideas_list, total=total, hasMore=has_more)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing ideas: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list ideas") from None


@router.post("", response_model=IdeaOut, status_code=201)
async def create_idea(request: CreateIdeaRequest):
    """Create a new idea."""
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    if request.source not in _VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"Invalid source: {request.source}")
    if request.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {request.status}")

    content_hash = compute_content_hash(request.content)
    symbol = request.symbol.upper() if request.symbol else None
    symbols = [s.upper() for s in request.symbols] if request.symbols else None

    try:
        rows = execute_sql(
            """
            INSERT INTO user_ideas (symbol, symbols, content, source, status, tags, content_hash)
            VALUES (:symbol, :symbols, :content, :source, :status, :tags, :content_hash)
            RETURNING id, symbol, symbols, content, source, status, tags,
                      origin_message_id, content_hash, created_at, updated_at
            """,
            params={
                "symbol": symbol,
                "symbols": symbols,
                "content": request.content.strip(),
                "source": request.source,
                "status": request.status,
                "tags": request.tags or None,
                "content_hash": content_hash,
            },
            fetch_results=True,
        )
        if rows:
            return _row_to_idea(rows[0])
        raise HTTPException(status_code=500, detail="Failed to create idea")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating idea: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create idea") from None


@router.put("/{idea_id}", response_model=IdeaOut)
async def update_idea(
    idea_id: UUID = Path(...),
    request: UpdateIdeaRequest = ...,
):
    """Update an existing idea (partial update)."""
    # Build SET clauses dynamically
    set_clauses = []
    params: dict = {"id": str(idea_id)}

    if request.content is not None:
        if not request.content.strip():
            raise HTTPException(status_code=400, detail="Content cannot be empty")
        set_clauses.append("content = :content")
        params["content"] = request.content.strip()
        # Re-compute hash when content changes
        set_clauses.append("content_hash = :content_hash")
        params["content_hash"] = compute_content_hash(request.content)
    if request.symbol is not None:
        set_clauses.append("symbol = :symbol")
        params["symbol"] = request.symbol.upper() if request.symbol else None
    if request.symbols is not None:
        set_clauses.append("symbols = :symbols")
        params["symbols"] = [s.upper() for s in request.symbols] if request.symbols else None
    if request.tags is not None:
        set_clauses.append("tags = :tags")
        params["tags"] = request.tags or None
    if request.status is not None:
        if request.status not in _VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {request.status}")
        set_clauses.append("status = :status")
        params["status"] = request.status

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        rows = execute_sql(
            f"""
            UPDATE user_ideas
            SET {', '.join(set_clauses)}
            WHERE id = :id
            RETURNING id, symbol, symbols, content, source, status, tags,
                      origin_message_id, content_hash, created_at, updated_at
            """,
            params=params,
            fetch_results=True,
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Idea not found")
        return _row_to_idea(rows[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating idea %s: %s", idea_id, e)
        raise HTTPException(status_code=500, detail="Failed to update idea") from None


@router.delete("/{idea_id}", status_code=204)
async def delete_idea(idea_id: UUID = Path(...)):
    """Delete an idea."""
    try:
        # Check existence first
        rows = execute_sql(
            "SELECT id FROM user_ideas WHERE id = :id",
            params={"id": str(idea_id)},
            fetch_results=True,
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Idea not found")

        execute_sql(
            "DELETE FROM user_ideas WHERE id = :id",
            params={"id": str(idea_id)},
            fetch_results=False,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting idea %s: %s", idea_id, e)
        raise HTTPException(status_code=500, detail="Failed to delete idea") from None


@router.post("/{idea_id}/refine", response_model=RefineResponse)
async def refine_idea(
    idea_id: UUID = Path(...),
    apply: bool = Query(False, description="Auto-apply refined content to the idea"),
):
    """
    AI auto-refine an idea using OpenAI.

    Returns refined content, extracted symbols, and suggested tags.
    If apply=true, updates the idea with the refined content.
    """
    # Fetch the idea
    rows = execute_sql(
        """
        SELECT id, content, symbol, symbols, tags, status
        FROM user_ideas WHERE id = :id
        """,
        params={"id": str(idea_id)},
        fetch_results=True,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Idea not found")

    rd = dict(rows[0]._mapping) if hasattr(rows[0], "_mapping") else dict(rows[0])
    original_content = rd["content"]

    try:
        from openai import OpenAI
        from src.retry_utils import hardened_retry

        @hardened_retry(max_retries=2, delay=2)
        def _call_openai(content: str) -> dict:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            completion = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL_REFINE", "gpt-4o-mini"),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a trading idea refinement assistant. Given a raw trading idea, "
                            "produce a JSON object with exactly these keys:\n"
                            '- "refinedContent": a clearer, more structured version of the idea '
                            "(keep the original meaning, improve clarity and structure)\n"
                            '- "extractedSymbols": array of stock ticker symbols mentioned or implied '
                            "(uppercase, e.g. [\"AAPL\", \"MSFT\"])\n"
                            '- "suggestedTags": array of relevant tags from this list: '
                            "[thesis, entry, exit, technical, fundamental, catalyst, earnings, "
                            "risk, conviction, question, options, momentum, value, growth]\n"
                            '- "changesSummary": one sentence describing what was improved\n\n'
                            "Return ONLY valid JSON, no markdown fences."
                        ),
                    },
                    {"role": "user", "content": content},
                ],
                max_tokens=1000,
                temperature=0.3,
            )
            raw = completion.choices[0].message.content or "{}"
            # Strip markdown fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
            return json.loads(raw)

        result = _call_openai(original_content)

        refined_content = result.get("refinedContent", original_content)
        extracted_symbols = [s.upper() for s in result.get("extractedSymbols", [])]
        suggested_tags = [t.lower() for t in result.get("suggestedTags", [])]
        changes_summary = result.get("changesSummary", "Refined for clarity.")

        # Auto-apply if requested
        if apply:
            new_hash = compute_content_hash(refined_content)
            execute_sql(
                """
                UPDATE user_ideas
                SET content = :content,
                    symbols = :symbols,
                    tags = :tags,
                    status = 'refined',
                    content_hash = :content_hash
                WHERE id = :id
                """,
                params={
                    "content": refined_content,
                    "symbols": extracted_symbols or None,
                    "tags": suggested_tags or None,
                    "content_hash": new_hash,
                    "id": str(idea_id),
                },
                fetch_results=False,
            )

        return RefineResponse(
            refinedContent=refined_content,
            extractedSymbols=extracted_symbols,
            suggestedTags=suggested_tags,
            changesSummary=changes_summary,
        )

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error("Failed to parse OpenAI refine response: %s", e)
        raise HTTPException(status_code=502, detail="AI returned invalid response") from None
    except Exception as e:
        logger.error("Error refining idea %s: %s", idea_id, e)
        raise HTTPException(status_code=500, detail="Failed to refine idea") from None
