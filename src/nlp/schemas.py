"""
Pydantic schemas for OpenAI structured outputs.

Defines the data models for LLM-based semantic parsing of trading messages.
Used with OpenAI's Responses API for guaranteed JSON schema compliance.

Version: 1.0.0
"""

from datetime import date
from enum import Enum
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field


# =============================================================================
# ENUMS - Type-safe value constraints
# =============================================================================


class ParseStatus(str, Enum):
    """
    Deterministic lifecycle for message parsing.

    State Transitions:
        pending → ok       : Ideas extracted successfully
        pending → noise    : Triage detected noise (no meaningful content)
        pending → error    : Parsing failed (API error, validation error)
        pending → skipped  : Pre-filtered (bot command, empty content, too short)

    Notes:
        - All messages start as 'pending'
        - Each terminal state is mutually exclusive
        - 'noise' vs 'skipped': noise = LLM decided, skipped = rule-based filter
        - 'error' always has error_reason populated
    """

    PENDING = "pending"
    OK = "ok"
    NOISE = "noise"
    ERROR = "error"
    SKIPPED = "skipped"


class InstrumentType(str, Enum):
    """Asset class types."""

    EQUITY = "equity"
    OPTION = "option"
    CRYPTO = "crypto"
    INDEX = "index"
    SECTOR = "sector"
    EVENT_CONTRACT = "event_contract"


class Direction(str, Enum):
    """Sentiment/position direction."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class Action(str, Enum):
    """Trading action types."""

    BUY = "buy"
    SELL = "sell"
    TRIM = "trim"
    ADD = "add"
    WATCH = "watch"
    HOLD = "hold"
    SHORT = "short"
    HEDGE = "hedge"
    NONE = "none"


class TimeHorizon(str, Enum):
    """Trading timeframe."""

    SCALP = "scalp"
    SWING = "swing"
    LONG_TERM = "long_term"
    UNKNOWN = "unknown"


class LevelKind(str, Enum):
    """Price level types."""

    ENTRY = "entry"
    TARGET = "target"
    SUPPORT = "support"
    RESISTANCE = "resistance"
    STOP = "stop"


class OptionType(str, Enum):
    """Option contract type."""

    CALL = "call"
    PUT = "put"


# =============================================================================
# TRADING LABELS - 13 category multi-label taxonomy
# =============================================================================


class TradingLabel(str, Enum):
    """
    13-category taxonomy for trading Discord messages.

    These labels are designed to support:
    - Filtering for specific content types
    - Building training datasets
    - Summarization and search
    """

    # Trade execution & planning
    TRADE_EXECUTION = "TRADE_EXECUTION"  # Did/doing a trade
    TRADE_PLAN = "TRADE_PLAN"  # Will do / setup / entry plan

    # Analysis types
    TECHNICAL_ANALYSIS = "TECHNICAL_ANALYSIS"  # Levels, patterns, trend
    FUNDAMENTAL_THESIS = "FUNDAMENTAL_THESIS"  # Business/value thesis

    # Market events
    CATALYST_NEWS = "CATALYST_NEWS"  # News, macro event, headline
    EARNINGS = "EARNINGS"  # Earnings-specific
    INSTITUTIONAL_FLOW = "INSTITUTIONAL_FLOW"  # 13F filings, fund moves

    # Trade mechanics
    OPTIONS = "OPTIONS"  # Calls/puts/strikes/expiries
    RISK_MANAGEMENT = "RISK_MANAGEMENT"  # Stop, sizing, hedges

    # Sentiment & updates
    SENTIMENT_CONVICTION = "SENTIMENT_CONVICTION"  # "Overvalued af", high confidence
    PORTFOLIO_UPDATE = "PORTFOLIO_UPDATE"  # Positions, P/L, "I'm out"

    # Information seeking
    QUESTION_REQUEST = "QUESTION_REQUEST"  # Asking for info/opinion
    RESOURCE_LINK = "RESOURCE_LINK"  # Chart links, tweets, data


# List of all label values for validation
TRADING_LABELS = [label.value for label in TradingLabel]


# =============================================================================
# STRUCTURED OUTPUT MODELS
# =============================================================================


class Level(BaseModel):
    """
    A price level extracted from the message.

    Handles various formats:
    - Exact: "at 220" → value=220
    - Range: "low 600s" → low=600, high=630, qualifier="low"
    - Approximate: "near 115" → value=115, qualifier="near"
    """

    kind: LevelKind = Field(
        description="Type of price level: entry, target, support, resistance, stop"
    )
    value: Optional[float] = Field(None, description="Exact price value if specified")
    low: Optional[float] = Field(
        None, description="Lower bound for range (e.g., 'low 600s' → 600)"
    )
    high: Optional[float] = Field(
        None, description="Upper bound for range (e.g., 'low 600s' → 630)"
    )
    qualifier: Optional[str] = Field(
        None,
        description="Modifier like 'near', 'around', 'above', 'below', 'low', 'high'",
    )


class ParsedIdea(BaseModel):
    """
    A single semantic idea unit extracted from a trading message.

    Each idea should focus on ONE primary subject when possible.
    If multiple stocks appear in one sentence, they can be in symbols[]
    but primary_symbol should be the main focus.
    """

    # Core content
    idea_text: str = Field(
        max_length=500,
        description="The exact text segment for this idea (quote from message, max 500 chars)",
    )
    idea_summary: str = Field(
        max_length=200,
        description="Brief 1-2 sentence summary of this idea's key point (max 200 chars)",
    )

    # Subject identification
    primary_symbol: Optional[str] = Field(
        None,
        description="Main ticker symbol this idea focuses on (e.g., 'AAPL'). Null for market/portfolio-wide ideas.",
    )
    symbols: List[str] = Field(
        default_factory=list, description="All ticker symbols mentioned in this idea"
    )
    instrument: InstrumentType = Field(
        InstrumentType.EQUITY,
        description="Asset type: equity, option, crypto, index, sector, event_contract",
    )

    # Direction & action
    direction: Direction = Field(
        Direction.NEUTRAL,
        description="Sentiment direction: bullish, bearish, neutral, mixed",
    )
    action: Optional[Action] = Field(
        None,
        description="Intended trade action: buy, sell, trim, add, watch, hold, short, hedge",
    )
    time_horizon: TimeHorizon = Field(
        TimeHorizon.UNKNOWN,
        description="Trading timeframe: scalp, swing, long_term, unknown",
    )
    trigger_condition: Optional[str] = Field(
        None,
        description="Condition for trade entry, e.g., 'if breaks 220', 'on pullback near 115'",
    )

    # Price levels
    levels: List[Level] = Field(
        default_factory=list,
        description="Price levels: entry, target, support, resistance, stop",
    )

    # Options-specific
    option_type: Optional[OptionType] = Field(
        None, description="Option type if this is an options trade: call or put"
    )
    strike: Optional[float] = Field(None, description="Option strike price")
    expiry: Optional[str] = Field(
        None, description="Option expiry date in ISO format (YYYY-MM-DD)"
    )
    premium: Optional[float] = Field(None, description="Option premium/price paid")

    # Classification
    labels: List[str] = Field(
        default_factory=list,
        description="Multi-label classification from the 13-category taxonomy",
    )
    is_noise: bool = Field(
        False, description="Whether this content is noise/non-actionable"
    )


class MessageParseResult(BaseModel):
    """
    Complete parsing result for a Discord message.

    A message can contain multiple ideas[], each with its own
    subject, labels, and extracted entities.
    """

    ideas: List[ParsedIdea] = Field(
        description="List of semantic idea units extracted from the message"
    )
    context_summary: str = Field(
        description="Overall summary of the entire message context (1-3 sentences)"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall confidence in the parsing quality (0.0-1.0)",
    )


class TriageResult(BaseModel):
    """
    Quick triage result from gpt-5-nano.

    Used to determine if a message should be fully parsed
    or skipped as noise.
    """

    is_noise: bool = Field(
        description="True if message is noise (bot output, spam, off-topic)"
    )
    has_actionable_content: bool = Field(
        description="True if message contains actionable trade content"
    )
    tickers_present: List[str] = Field(
        default_factory=list, description="Ticker symbols detected in the message"
    )
    skip_reason: Optional[str] = Field(
        None, description="Reason for skipping if is_noise=True"
    )


# =============================================================================
# DATABASE INSERT HELPERS
# =============================================================================


def parsed_idea_to_db_row(
    idea: ParsedIdea,
    message_id: Union[int, str],
    idea_index: int,
    context_summary: str,
    model: str,
    prompt_version: str,
    confidence: float,
    raw_json: Dict[str, Any],
    author_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    source_created_at: Optional[str] = None,
    soft_chunk_index: int = 0,
    local_idea_index: int = 0,
) -> Dict[str, Any]:
    """
    Convert a ParsedIdea to a database row dict for discord_parsed_ideas.

    Args:
        idea: The parsed idea from LLM
        message_id: Source message ID
        idea_index: Index of this idea within the message (global counter)
        context_summary: Overall message summary
        model: LLM model used
        prompt_version: Prompt version
        confidence: Overall parse confidence
        raw_json: Full LLM response
        author_id: Discord author ID
        channel_id: Discord channel ID
        source_created_at: Original message timestamp
        soft_chunk_index: Index of the soft chunk this idea came from (0-based)
        local_idea_index: Index of the idea within its soft chunk (0-based)

    Returns:
        Dict ready for database insertion
    """
    # Convert levels to JSONB-compatible format
    levels_json = [
        {
            "kind": level.kind.value,
            "value": level.value,
            "low": level.low,
            "high": level.high,
            "qualifier": level.qualifier,
        }
        for level in idea.levels
    ]

    # Build label_scores (placeholder - can be enhanced)
    label_scores = {label: 1.0 for label in idea.labels}

    return {
        "message_id": message_id,
        "idea_index": idea_index,
        "soft_chunk_index": soft_chunk_index,
        "local_idea_index": local_idea_index,
        "idea_text": idea.idea_text,
        "idea_summary": idea.idea_summary,
        "context_summary": context_summary,
        "primary_symbol": idea.primary_symbol.upper() if idea.primary_symbol else None,
        "symbols": [s.upper() for s in idea.symbols],
        "instrument": idea.instrument.value if idea.instrument else None,
        "direction": idea.direction.value if idea.direction else None,
        "action": idea.action.value if idea.action else None,
        "time_horizon": idea.time_horizon.value if idea.time_horizon else "unknown",
        "trigger_condition": idea.trigger_condition,
        "levels": levels_json,
        "option_type": idea.option_type.value if idea.option_type else None,
        "strike": idea.strike,
        "expiry": idea.expiry,
        "premium": idea.premium,
        "labels": idea.labels,
        "label_scores": label_scores,
        "is_noise": idea.is_noise,
        "author_id": author_id,
        "channel_id": channel_id,
        "model": model,
        "prompt_version": prompt_version,
        "confidence": confidence,
        "raw_json": raw_json,
        "source_created_at": source_created_at,
    }


# =============================================================================
# PROMPT VERSION TRACKING
# =============================================================================

# v1.0: Initial parser prompt
# v1.1: Enhanced levels extraction with explicit patterns and examples (Dec 2025)
CURRENT_PROMPT_VERSION = "v1.1"
