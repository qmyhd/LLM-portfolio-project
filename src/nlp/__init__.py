"""
NLP processing modules for Discord message analysis.

CANONICAL PIPELINE (January 2026):
- OpenAI parser with structured outputs (openai_parser.py)
- Soft splitting for deterministic pre-split (soft_splitter.py)
- Pydantic schemas for structured outputs (schemas.py)
- Pre-cleaning utilities (preclean.py)

Model Strategy:
- gpt-5-nano: Quick triage (is this noise? which tickers?)
- gpt-5-mini: Main parser (ideas + labels + entities + levels)
- gpt-5.1: Escalation for low confidence or errors
- gpt-4.1: Long context for 13F filings and long messages
"""

# =============================================================================
# PRE-CLEANING (active)
# =============================================================================
from src.nlp.preclean import (
    is_bot_command,
    is_bot_response,
    is_url_only,
    should_skip_message,  # SSOT prefilter for all parsing
    normalize_text,
    is_noise_message,
    extract_meaningful_content,
)

# =============================================================================
# SCHEMAS (active)
# =============================================================================
from src.nlp.schemas import (
    ParsedIdea,
    MessageParseResult,
    TriageResult,
    Level,
    TradingLabel,
    TRADING_LABELS,
    CURRENT_PROMPT_VERSION,
    parsed_idea_to_db_row,
)

# =============================================================================
# SOFT SPLITTER (active)
# =============================================================================
from src.nlp.soft_splitter import (
    soft_split,
    prepare_for_parsing,
    extract_tickers,
    SoftChunk,
)

# =============================================================================
# OPENAI PARSER (active - canonical pipeline)
# =============================================================================
from src.nlp.openai_parser import (
    process_message,
    triage_message,
    parse_message,
    validate_openai_models,
    get_model_for_text,
    MODEL_TRIAGE,
    MODEL_MAIN,
    MODEL_ESCALATION,
    MODEL_LONG_CONTEXT,
    # Call tracking utilities (added for monitoring call explosion)
    CallStats,
    reset_call_stats,
    get_call_stats,
)


# =============================================================================
# EXPORTS
# =============================================================================
__all__ = [
    # Preclean (active)
    "is_bot_command",
    "is_bot_response",
    "is_url_only",
    "normalize_text",
    "is_noise_message",
    "extract_meaningful_content",
    # OpenAI Parser (canonical pipeline)
    "process_message",
    "triage_message",
    "parse_message",
    "validate_openai_models",
    "get_model_for_text",
    "MODEL_TRIAGE",
    "MODEL_MAIN",
    "MODEL_ESCALATION",
    "MODEL_LONG_CONTEXT",
    # Call tracking
    "CallStats",
    "reset_call_stats",
    "get_call_stats",
    # Schemas
    "ParsedIdea",
    "MessageParseResult",
    "TriageResult",
    "Level",
    "TradingLabel",
    "TRADING_LABELS",
    "CURRENT_PROMPT_VERSION",
    "parsed_idea_to_db_row",
    # Soft Splitter
    "soft_split",
    "prepare_for_parsing",
    "extract_tickers",
    "SoftChunk",
]
