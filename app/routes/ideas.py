"""
Ideas API routes — unified ideas store (Discord + manual + transcribe).

Endpoints:
- GET    /ideas              — Paginated list with filters
- POST   /ideas              — Create a new idea
- PUT    /ideas/{id}         — Update an existing idea
- DELETE /ideas/{id}         — Delete an idea
- POST   /ideas/{id}/refine  — AI auto-refine an idea
- GET    /ideas/{id}/context — Idea with parent Discord message + surrounding context
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query
from openai import OpenAI
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.db import execute_sql, transaction
from src.discord_ingest import compute_content_hash
from src.retry_utils import hardened_retry

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class IdeaOut(BaseModel):
    """Single idea response (camelCase for frontend)."""

    id: str
    symbol: str | None = None
    symbols: list[str] = Field(default_factory=list)
    content: str
    source: str
    status: str
    tags: list[str] = Field(default_factory=list)
    originMessageId: str | None = None
    title: str | None = None
    sourceUrl: str | None = None
    sourceCreatedAt: str | None = None
    author: str | None = None
    authorId: str | None = None
    platformMessageId: str | None = None
    threadKey: str | None = None
    sourceMetadata: dict[str, Any] = Field(default_factory=dict)
    reviewStatus: str = "unreviewed"
    reviewNotes: str | None = None
    attributedPersonId: int | None = None
    attributionKind: str = "self"
    filingType: str | None = None
    filingPeriod: str | None = None
    institutionName: str | None = None
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
    symbol: str | None = None
    symbols: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: str = "draft"
    source: str = "manual"
    title: str | None = None
    sourceUrl: str | None = None
    sourceCreatedAt: datetime | None = None
    author: str | None = None
    authorId: str | None = None
    platformMessageId: str | None = None
    threadKey: str | None = None
    sourceMetadata: dict[str, Any] = Field(default_factory=dict)
    reviewStatus: str = "unreviewed"
    reviewNotes: str | None = None
    attributedPersonId: int | None = None
    attributionKind: str = "self"
    filingType: str | None = None
    filingPeriod: str | None = None
    institutionName: str | None = None


class UpdateIdeaRequest(BaseModel):
    """Request body for updating an idea (all fields optional)."""

    content: str | None = None
    symbol: str | None = None
    symbols: list[str] | None = None
    tags: list[str] | None = None
    status: str | None = None
    title: str | None = None
    sourceUrl: str | None = None
    sourceCreatedAt: datetime | None = None
    author: str | None = None
    authorId: str | None = None
    platformMessageId: str | None = None
    threadKey: str | None = None
    sourceMetadata: dict[str, Any] | None = None
    reviewStatus: str | None = None
    reviewNotes: str | None = None
    attributedPersonId: int | None = None
    attributionKind: str | None = None
    filingType: str | None = None
    filingPeriod: str | None = None
    institutionName: str | None = None


class ImportMessage(BaseModel):
    """Normalized imported iMessage/timeline item."""

    content: str
    sentAt: datetime | None = None
    author: str | None = None
    authorId: str | None = None
    messageId: str | None = None
    threadKey: str | None = None
    symbols: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    sourceUrl: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportMessagesRequest(BaseModel):
    source: str = "imessage"
    threadKey: str | None = None
    defaultAuthor: str | None = None
    messages: list[ImportMessage]


class ImportMessagesResponse(BaseModel):
    imported: int
    skipped: int
    ideas: list[IdeaOut]


class TimelineResponse(BaseModel):
    ideas: list[IdeaOut]
    total: int


class ParsedIdeaCurationRequest(BaseModel):
    labels: list[str] | None = None
    primarySymbol: str | None = None
    symbols: list[str] | None = None
    ideaText: str | None = None
    ideaSummary: str | None = None
    direction: str | None = None
    action: str | None = None
    reviewStatus: str = "reviewed"
    reviewNotes: str | None = None
    attributedPersonId: int | None = None
    attributionKind: str | None = None
    thesisBucket: str | None = None
    filingType: str | None = None
    filingPeriod: str | None = None
    institutionName: str | None = None


class ParsedIdeaCurationResponse(BaseModel):
    id: str
    reviewStatus: str
    labels: list[str]
    primarySymbol: str | None = None
    symbols: list[str]
    attributionKind: str
    attributedPersonId: int | None = None
    thesisBucket: str | None = None


class RefineResponse(BaseModel):
    """Auto-refine result."""

    refinedContent: str
    extractedSymbols: list[str]
    suggestedTags: list[str]
    changesSummary: str
    reflectionApplied: bool = False


class ContextMessage(BaseModel):
    """Single Discord message in context window."""

    messageId: str
    content: str
    author: str
    sentAt: str
    channel: str
    isParent: bool = False


class IdeaContextResponse(BaseModel):
    """Idea with parent Discord message and surrounding context."""

    idea: IdeaOut
    parentMessage: ContextMessage | None = None
    contextMessages: list[ContextMessage] = []


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
        title=rd.get("title"),
        sourceUrl=rd.get("source_url"),
        sourceCreatedAt=str(rd["source_created_at"]) if rd.get("source_created_at") else None,
        author=rd.get("author"),
        authorId=rd.get("author_id"),
        platformMessageId=rd.get("platform_message_id"),
        threadKey=rd.get("thread_key"),
        sourceMetadata=rd.get("source_metadata") or {},
        reviewStatus=rd.get("review_status") or "unreviewed",
        reviewNotes=rd.get("review_notes"),
        attributedPersonId=rd.get("attributed_person_id"),
        attributionKind=rd.get("attribution_kind") or "self",
        filingType=rd.get("filing_type"),
        filingPeriod=rd.get("filing_period"),
        institutionName=rd.get("institution_name"),
        contentHash=rd["content_hash"],
        createdAt=str(rd["created_at"]),
        updatedAt=str(rd["updated_at"]),
    )


_VALID_SOURCES = {"discord", "manual", "transcribe", "imessage", "twitter", "x"}
_VALID_STATUSES = {"draft", "refined", "archived"}
_VALID_REVIEW_STATUSES = {"unreviewed", "reviewed", "needs_review"}
_VALID_ATTRIBUTION_KINDS = {"self", "external_person", "institution", "unknown"}


def _idea_select_columns() -> str:
    return """
        id, symbol, symbols, content, source, status, tags,
        origin_message_id, title, source_url, source_created_at, author, author_id,
        platform_message_id, thread_key, source_metadata, review_status, review_notes,
        attributed_person_id, attribution_kind, filing_type, filing_period,
        institution_name, content_hash, created_at, updated_at
    """


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=IdeasListResponse)
async def list_ideas(
    symbol: str | None = Query(None, description="Filter by primary symbol"),
    tag: str | None = Query(None, description="Filter by tag"),
    source: str | None = Query(None, description="Filter by source"),
    status: str | None = Query(None, description="Filter by status"),
    review_status: str | None = Query(None, description="Filter by review status"),
    thread_key: str | None = Query(None, description="Filter by source thread"),
    attribution_kind: str | None = Query(None, description="Filter by attribution kind"),
    q: str | None = Query(None, description="Full-text search on content"),
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
        if review_status:
            if review_status not in _VALID_REVIEW_STATUSES:
                raise HTTPException(status_code=400, detail=f"Invalid review status: {review_status}")
            conditions.append("review_status = :review_status")
            params["review_status"] = review_status
        if thread_key:
            conditions.append("thread_key = :thread_key")
            params["thread_key"] = thread_key
        if attribution_kind:
            if attribution_kind not in _VALID_ATTRIBUTION_KINDS:
                raise HTTPException(status_code=400, detail=f"Invalid attribution kind: {attribution_kind}")
            conditions.append("attribution_kind = :attribution_kind")
            params["attribution_kind"] = attribution_kind
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
            SELECT {_idea_select_columns()}
            FROM user_ideas{where_clause}
            ORDER BY COALESCE(source_created_at, created_at) DESC
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


@router.get("/timeline", response_model=TimelineResponse)
async def ideas_timeline(
    source: str | None = Query(None),
    thread_key: str | None = Query(None),
    author: str | None = Query(None),
    symbol: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """Chronological story/timeline view across imported and journal ideas."""
    conditions = []
    params: dict = {"limit": limit}
    if source:
        if source not in _VALID_SOURCES:
            raise HTTPException(status_code=400, detail=f"Invalid source: {source}")
        conditions.append("source = :source")
        params["source"] = source
    if thread_key:
        conditions.append("thread_key = :thread_key")
        params["thread_key"] = thread_key
    if author:
        conditions.append("author ILIKE :author")
        params["author"] = author
    if symbol:
        conditions.append("(UPPER(symbol) = :symbol OR :symbol = ANY(symbols))")
        params["symbol"] = symbol.upper()
    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    rows = execute_sql(
        f"""
        SELECT {_idea_select_columns()}
        FROM user_ideas{where_clause}
        ORDER BY COALESCE(source_created_at, created_at) ASC
        LIMIT :limit
        """,
        params=params,
        fetch_results=True,
    ) or []
    return TimelineResponse(ideas=[_row_to_idea(row) for row in rows], total=len(rows))


@router.post("/import/messages", response_model=ImportMessagesResponse, status_code=201)
async def import_messages(body: ImportMessagesRequest):
    """Import iMessage/X-style timeline messages into the unified ideas store."""
    if body.source not in {"imessage", "twitter", "x"}:
        raise HTTPException(status_code=400, detail="Import source must be imessage, twitter, or x")
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    imported: list[IdeaOut] = []
    skipped = 0
    for msg in body.messages:
        if not msg.content.strip():
            skipped += 1
            continue
        content_hash = compute_content_hash(msg.content)
        symbols = [s.upper().lstrip("$") for s in msg.symbols] or None
        symbol = symbols[0] if symbols else None
        thread_key = msg.threadKey or body.threadKey
        author = msg.author or body.defaultAuthor

        try:
            rows = execute_sql(
                f"""
                INSERT INTO user_ideas (
                    symbol, symbols, content, source, status, tags, content_hash,
                    source_url, source_created_at, author, author_id,
                    platform_message_id, thread_key, source_metadata,
                    review_status, attribution_kind
                )
                VALUES (
                    :symbol, :symbols, :content, :source, 'draft', :tags, :content_hash,
                    :source_url, :source_created_at, :author, :author_id,
                    :platform_message_id, :thread_key, CAST(:source_metadata AS jsonb),
                    'unreviewed', 'self'
                )
                ON CONFLICT DO NOTHING
                RETURNING {_idea_select_columns()}
                """,
                params={
                    "symbol": symbol,
                    "symbols": symbols,
                    "content": msg.content.strip(),
                    "source": body.source,
                    "tags": msg.tags or None,
                    "content_hash": content_hash,
                    "source_url": msg.sourceUrl,
                    "source_created_at": msg.sentAt,
                    "author": author,
                    "author_id": msg.authorId,
                    "platform_message_id": msg.messageId,
                    "thread_key": thread_key,
                    "source_metadata": json.dumps(msg.metadata or {}),
                },
                fetch_results=True,
            ) or []
            if rows:
                imported.append(_row_to_idea(rows[0]))
            else:
                skipped += 1
        except Exception as e:
            logger.warning("Skipped imported %s message %s: %s", body.source, msg.messageId, e)
            skipped += 1

    return ImportMessagesResponse(imported=len(imported), skipped=skipped, ideas=imported)


@router.put("/discord-parsed/{parsed_id}/curation", response_model=ParsedIdeaCurationResponse)
async def curate_discord_parsed_idea(
    parsed_id: UUID = Path(...),
    body: ParsedIdeaCurationRequest = ...,
):
    """Human-correct labels, attribution, and 13F bucketing for an NLP idea."""
    if body.reviewStatus not in _VALID_REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid review status: {body.reviewStatus}")
    if body.attributionKind is not None and body.attributionKind not in _VALID_ATTRIBUTION_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid attribution kind: {body.attributionKind}")

    set_clauses = ["review_status = :review_status"]
    params: dict = {"id": str(parsed_id), "review_status": body.reviewStatus}
    field_map = {
        "labels": ("labels", body.labels),
        "primary_symbol": ("primarySymbol", body.primarySymbol.upper() if body.primarySymbol else None),
        "symbols": ("symbols", [s.upper() for s in body.symbols] if body.symbols is not None else None),
        "idea_text": ("ideaText", body.ideaText),
        "idea_summary": ("ideaSummary", body.ideaSummary),
        "direction": ("direction", body.direction),
        "action": ("action", body.action),
        "review_notes": ("reviewNotes", body.reviewNotes),
        "attributed_person_id": ("attributedPersonId", body.attributedPersonId),
        "attribution_kind": ("attributionKind", body.attributionKind),
        "thesis_bucket": ("thesisBucket", body.thesisBucket),
        "filing_type": ("filingType", body.filingType),
        "filing_period": ("filingPeriod", body.filingPeriod),
        "institution_name": ("institutionName", body.institutionName),
    }
    for column, (field_name, value) in field_map.items():
        if field_name in body.model_fields_set:
            set_clauses.append(f"{column} = :{column}")
            params[column] = value

    rows = execute_sql(
        f"""
        UPDATE discord_parsed_ideas
        SET {', '.join(set_clauses)}
        WHERE id = :id
        RETURNING id, review_status, labels, primary_symbol, symbols,
                  attribution_kind, attributed_person_id, thesis_bucket
        """,
        params=params,
        fetch_results=True,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Parsed idea not found")
    rd = dict(rows[0]._mapping) if hasattr(rows[0], "_mapping") else dict(rows[0])
    return ParsedIdeaCurationResponse(
        id=str(rd["id"]),
        reviewStatus=rd.get("review_status") or "reviewed",
        labels=rd.get("labels") or [],
        primarySymbol=rd.get("primary_symbol"),
        symbols=rd.get("symbols") or [],
        attributionKind=rd.get("attribution_kind") or "self",
        attributedPersonId=rd.get("attributed_person_id"),
        thesisBucket=rd.get("thesis_bucket"),
    )


@router.post("", response_model=IdeaOut, status_code=201)
async def create_idea(request: CreateIdeaRequest):
    """Create a new idea."""
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    if request.source not in _VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"Invalid source: {request.source}")
    if request.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {request.status}")
    if request.reviewStatus not in _VALID_REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid review status: {request.reviewStatus}")
    if request.attributionKind not in _VALID_ATTRIBUTION_KINDS:
        raise HTTPException(status_code=400, detail=f"Invalid attribution kind: {request.attributionKind}")

    content_hash = compute_content_hash(request.content)
    symbol = request.symbol.upper() if request.symbol else None
    symbols = [s.upper() for s in request.symbols] if request.symbols else None

    try:
        rows = execute_sql(
            f"""
            INSERT INTO user_ideas (
                symbol, symbols, content, source, status, tags, content_hash,
                title, source_url, source_created_at, author, author_id,
                platform_message_id, thread_key, source_metadata, review_status,
                review_notes, attributed_person_id, attribution_kind, filing_type,
                filing_period, institution_name
            )
            VALUES (
                :symbol, :symbols, :content, :source, :status, :tags, :content_hash,
                :title, :source_url, :source_created_at, :author, :author_id,
                :platform_message_id, :thread_key, CAST(:source_metadata AS jsonb),
                :review_status, :review_notes, :attributed_person_id,
                :attribution_kind, :filing_type, :filing_period, :institution_name
            )
            RETURNING {_idea_select_columns()}
            """,
            params={
                "symbol": symbol,
                "symbols": symbols,
                "content": request.content.strip(),
                "source": request.source,
                "status": request.status,
                "tags": request.tags or None,
                "content_hash": content_hash,
                "title": request.title,
                "source_url": request.sourceUrl,
                "source_created_at": request.sourceCreatedAt,
                "author": request.author,
                "author_id": request.authorId,
                "platform_message_id": request.platformMessageId,
                "thread_key": request.threadKey,
                "source_metadata": json.dumps(request.sourceMetadata or {}),
                "review_status": request.reviewStatus,
                "review_notes": request.reviewNotes,
                "attributed_person_id": request.attributedPersonId,
                "attribution_kind": request.attributionKind,
                "filing_type": request.filingType,
                "filing_period": request.filingPeriod,
                "institution_name": request.institutionName,
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
    scalar_fields = {
        "title": ("title", request.title),
        "source_url": ("sourceUrl", request.sourceUrl),
        "source_created_at": ("sourceCreatedAt", request.sourceCreatedAt),
        "author": ("author", request.author),
        "author_id": ("authorId", request.authorId),
        "platform_message_id": ("platformMessageId", request.platformMessageId),
        "thread_key": ("threadKey", request.threadKey),
        "review_notes": ("reviewNotes", request.reviewNotes),
        "attributed_person_id": ("attributedPersonId", request.attributedPersonId),
        "filing_type": ("filingType", request.filingType),
        "filing_period": ("filingPeriod", request.filingPeriod),
        "institution_name": ("institutionName", request.institutionName),
    }
    fields_set = request.model_fields_set
    for column, (field_name, value) in scalar_fields.items():
        if field_name in fields_set:
            set_clauses.append(f"{column} = :{column}")
            params[column] = value
    if "sourceMetadata" in fields_set:
        set_clauses.append("source_metadata = CAST(:source_metadata AS jsonb)")
        params["source_metadata"] = json.dumps(request.sourceMetadata or {})
    if request.reviewStatus is not None:
        if request.reviewStatus not in _VALID_REVIEW_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid review status: {request.reviewStatus}")
        set_clauses.append("review_status = :review_status")
        params["review_status"] = request.reviewStatus
    if request.attributionKind is not None:
        if request.attributionKind not in _VALID_ATTRIBUTION_KINDS:
            raise HTTPException(status_code=400, detail=f"Invalid attribution kind: {request.attributionKind}")
        set_clauses.append("attribution_kind = :attribution_kind")
        params["attribution_kind"] = request.attributionKind

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        rows = execute_sql(
            f"""
            UPDATE user_ideas
            SET {', '.join(set_clauses)}
            WHERE id = :id
            RETURNING {_idea_select_columns()}
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
    AI auto-refine an idea using three-pass self-reflection:

    1. **Refine** — generate improved idea with structured fields
    2. **Reflect** — critique for hallucinated targets, ticker accuracy, direction support
    3. **Re-refine** — incorporate critique and fix (only if issues found)

    Returns refined content, extracted symbols, suggested tags, and whether
    reflection was applied.  If apply=true, updates the idea in-place.
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
        _refine_model = os.getenv("OPENAI_MODEL_REFINE", "gpt-4o-mini")

        def _strip_fences(raw: str) -> str:
            """Strip optional markdown code fences from LLM output."""
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            return raw.strip()

        # ------------------------------------------------------------------
        # Pass 1: Refine (existing behaviour)
        # ------------------------------------------------------------------
        @hardened_retry(max_retries=2, delay=2)
        def _call_openai_refine(content: str) -> dict:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            completion = client.chat.completions.create(
                model=_refine_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a trading idea refinement assistant. Given a raw trading idea, "
                            "produce a JSON object with exactly these keys:\n"
                            '- "refinedContent": a clearer, more structured version of the idea '
                            "(keep the original meaning, improve clarity and structure)\n"
                            '- "extractedSymbols": array of stock ticker symbols mentioned or implied '
                            '(uppercase, e.g. ["AAPL", "MSFT"])\n'
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
            return json.loads(_strip_fences(raw))

        # ------------------------------------------------------------------
        # Pass 2: Reflect — critique the refinement
        # ------------------------------------------------------------------
        @hardened_retry(max_retries=2, delay=2)
        def _call_openai_reflect(original: str, refined: str, symbols: list[str]) -> dict:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            completion = client.chat.completions.create(
                model=_refine_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a trading idea critique and reflection assistant. "
                            "Compare the ORIGINAL idea with the REFINED version and check for:\n"
                            "1. Hallucinated price targets — numbers/targets NOT present in the original\n"
                            "2. Ticker accuracy — are the extracted symbols actually mentioned or implied?\n"
                            "3. Direction support — does the original idea support the direction/sentiment "
                            "expressed in the refinement?\n\n"
                            "Return a JSON object with exactly these keys:\n"
                            '- "issues_found": boolean — true if any problems were detected\n'
                            '- "critique": string — brief explanation of issues (or confirmation of quality)\n'
                            '- "hallucinated_targets": array of strings — any price targets or numbers '
                            "added that were NOT in the original\n"
                            '- "ticker_verified": boolean — true if extracted symbols are accurate\n\n'
                            "Return ONLY valid JSON, no markdown fences."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"ORIGINAL IDEA:\n{original}\n\n"
                            f"REFINED VERSION:\n{refined}\n\n"
                            f"EXTRACTED SYMBOLS: {json.dumps(symbols)}"
                        ),
                    },
                ],
                max_tokens=500,
                temperature=0.2,
            )
            raw = completion.choices[0].message.content or "{}"
            return json.loads(_strip_fences(raw))

        # ------------------------------------------------------------------
        # Pass 3: Re-refine (only when issues found)
        # ------------------------------------------------------------------
        @hardened_retry(max_retries=2, delay=2)
        def _call_openai_rerefine(original: str, refined: str, critique: str) -> dict:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            completion = client.chat.completions.create(
                model=_refine_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a trading idea refinement assistant performing a CORRECTION pass. "
                            "A previous refinement was critiqued and issues were found.\n\n"
                            "Using the ORIGINAL idea and the CRITIQUE, produce a corrected JSON object "
                            "with exactly these keys:\n"
                            '- "refinedContent": corrected version that fixes the issues raised in the '
                            "critique while keeping the original meaning\n"
                            '- "extractedSymbols": corrected array of stock ticker symbols '
                            '(uppercase, e.g. ["AAPL"])\n'
                            '- "suggestedTags": array of relevant tags from this list: '
                            "[thesis, entry, exit, technical, fundamental, catalyst, earnings, "
                            "risk, conviction, question, options, momentum, value, growth]\n"
                            '- "changesSummary": one sentence describing what was corrected\n\n'
                            "Return ONLY valid JSON, no markdown fences."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"ORIGINAL IDEA:\n{original}\n\n"
                            f"PREVIOUS REFINEMENT:\n{refined}\n\n"
                            f"CRITIQUE:\n{critique}"
                        ),
                    },
                ],
                max_tokens=1000,
                temperature=0.3,
            )
            raw = completion.choices[0].message.content or "{}"
            return json.loads(_strip_fences(raw))

        # ------------------------------------------------------------------
        # Execute three-pass pipeline
        # ------------------------------------------------------------------
        result = _call_openai_refine(original_content)
        reflection_applied = False

        refined_content = result.get("refinedContent", original_content)
        extracted_symbols = [s.upper() for s in result.get("extractedSymbols", [])]

        # Pass 2: Reflect
        reflection = _call_openai_reflect(original_content, refined_content, extracted_symbols)
        logger.info(
            "Idea %s reflection: issues_found=%s, ticker_verified=%s",
            idea_id,
            reflection.get("issues_found"),
            reflection.get("ticker_verified"),
        )

        # Pass 3: Re-refine if issues were found
        if reflection.get("issues_found"):
            critique_text = reflection.get("critique", "Issues detected in refinement.")
            result = _call_openai_rerefine(original_content, refined_content, critique_text)
            reflection_applied = True
            logger.info("Idea %s re-refined after reflection critique", idea_id)

        refined_content = result.get("refinedContent", original_content)
        extracted_symbols = [s.upper() for s in result.get("extractedSymbols", [])]
        suggested_tags = [t.lower() for t in result.get("suggestedTags", [])]
        changes_summary = result.get("changesSummary", "Refined for clarity.")

        # Auto-apply if requested. Wrap in a transaction with an advisory
        # lock keyed on the idea_id so a double-click during the multi-second
        # 3-pass refine pipeline can't race two stale writes against each
        # other. The lock is xact-scoped — released automatically on COMMIT
        # or ROLLBACK.
        if apply:
            new_hash = compute_content_hash(refined_content)
            # idea_id is a UUID string; mask to a positive bigint for
            # pg_advisory_xact_lock(bigint). Same pattern used in
            # src/db.py::save_parsed_ideas_atomic.
            lock_key = hash(str(idea_id)) & 0x7FFFFFFFFFFFFFFF

            with transaction() as conn:
                conn.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": lock_key},
                )
                conn.execute(
                    text(
                        """
                        UPDATE user_ideas
                        SET content = :content,
                            symbols = :symbols,
                            tags = :tags,
                            status = 'refined',
                            content_hash = :content_hash
                        WHERE id = :id
                        """
                    ),
                    {
                        "content": refined_content,
                        "symbols": extracted_symbols or None,
                        "tags": suggested_tags or None,
                        "content_hash": new_hash,
                        "id": str(idea_id),
                    },
                )

        return RefineResponse(
            refinedContent=refined_content,
            extractedSymbols=extracted_symbols,
            suggestedTags=suggested_tags,
            changesSummary=changes_summary,
            reflectionApplied=reflection_applied,
        )

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error("Failed to parse OpenAI refine response: %s", e)
        raise HTTPException(status_code=502, detail="AI returned invalid response") from None
    except Exception as e:
        logger.error("Error refining idea %s: %s", idea_id, e)
        raise HTTPException(status_code=500, detail="Failed to refine idea") from None


@router.get("/{idea_id}/context", response_model=IdeaContextResponse)
async def get_idea_context(
    idea_id: str = Path(..., description="Idea UUID"),
    context_window: int = Query(5, ge=1, le=20, description="Messages before/after parent"),
):
    """Get idea with parent Discord message and surrounding context."""
    # 1. Fetch the idea
    idea_rows = execute_sql(
        "SELECT * FROM user_ideas WHERE id = :id",
        params={"id": idea_id}, fetch_results=True,
    )
    if not idea_rows:
        raise HTTPException(status_code=404, detail="Idea not found")

    idea = _row_to_idea(idea_rows[0])

    # 2. Fetch parent message
    parent_msg = None
    context_msgs: list[ContextMessage] = []

    if idea.originMessageId:
        msg_rows = execute_sql(
            "SELECT message_id, content, author, timestamp, channel "
            "FROM discord_messages WHERE message_id = :msg_id",
            params={"msg_id": idea.originMessageId}, fetch_results=True,
        )
        if msg_rows:
            mr = dict(msg_rows[0]._mapping)
            parent_msg = ContextMessage(
                messageId=mr["message_id"],
                content=mr["content"],
                author=mr["author"],
                sentAt=str(mr["timestamp"]),
                channel=mr["channel"],
                isParent=True,
            )

            # 3. Fetch surrounding messages from same channel
            ctx_rows = execute_sql(
                """
                (SELECT message_id, content, author, timestamp, channel
                 FROM discord_messages
                 WHERE channel = :channel AND timestamp <= :ts
                 ORDER BY timestamp DESC
                 LIMIT :before)
                UNION ALL
                (SELECT message_id, content, author, timestamp, channel
                 FROM discord_messages
                 WHERE channel = :channel AND timestamp > :ts
                 ORDER BY timestamp ASC
                 LIMIT :after)
                ORDER BY timestamp ASC
                """,
                params={
                    "channel": mr["channel"],
                    "ts": mr["timestamp"],
                    "before": context_window + 1,  # +1 to include parent
                    "after": context_window,
                },
                fetch_results=True,
            )
            for cr in (ctx_rows or []):
                cd = dict(cr._mapping)
                context_msgs.append(ContextMessage(
                    messageId=cd["message_id"],
                    content=cd["content"],
                    author=cd["author"],
                    sentAt=str(cd["timestamp"]),
                    channel=cd["channel"],
                    isParent=cd["message_id"] == idea.originMessageId,
                ))

    return IdeaContextResponse(
        idea=idea,
        parentMessage=parent_msg,
        contextMessages=context_msgs,
    )
