"""
OpenAI Parser - LLM-based semantic parsing with structured outputs.

Uses OpenAI's Responses API with structured outputs to guarantee
valid JSON schema compliance for trading message analysis.

Model Strategy (Unified):
- gpt-5-mini: Triage, main parsing, and summary (unified for consistency)
- gpt-5.1: Long-context routing and escalation for complex cases

Thresholds (configurable via env):
- LONG_CONTEXT_THRESHOLD: 2000 chars / 500 tokens → route to gpt-5.1
- ESCALATION_THRESHOLD: 0.8 → below this confidence, escalate to gpt-5.1

CALL POLICY (to prevent call explosion):
- Triage: ONCE per message for short messages (<1500 chars)
- Triage: Once per chunk only for long messages (>1500 chars)
- Main parse: Once per soft chunk
- Escalation: Only on parse failure OR low confidence
- Summary: NOT implemented (ideas are self-contained)

Expected calls for typical messages:
- Short (<1500 chars): 1 triage + 1 parse = 2 calls
- Medium (1500-2000 chars): 1-2 chunks × (triage + parse) = 2-4 calls
- Long (>2000 chars): Route to gpt-5.1, 1 parse = 1 call

Version: 1.2.0 (unified models, env-based thresholds)
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, TypeVar, Union
from datetime import datetime, timezone

from openai import OpenAI
from openai.types.responses import Response

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

logger = logging.getLogger(__name__)


# =============================================================================
# CALL TRACKING (to prevent explosion)
# =============================================================================


@dataclass
class CallStats:
    """Track API call counts per message for monitoring and debugging."""

    soft_chunks: int = 0
    triage_calls: int = 0
    triage_retries: int = 0
    main_calls: int = 0
    escalation_calls: int = 0
    noise_chunks: int = 0

    @property
    def total_calls(self) -> int:
        """Total API calls made (excluding retries counted separately)."""
        return self.triage_calls + self.main_calls + self.escalation_calls

    def summary(self) -> str:
        """Return formatted summary for logging."""
        return (
            f"chunks={self.soft_chunks} calls_total={self.total_calls} "
            f"triage={self.triage_calls} main={self.main_calls} "
            f"escalation={self.escalation_calls} noise={self.noise_chunks}"
        )


# Thread-local stats for current message being processed
_current_stats: Optional[CallStats] = None


def reset_call_stats() -> CallStats:
    """Reset call stats for a new message. Returns the new stats object."""
    global _current_stats
    _current_stats = CallStats()
    return _current_stats


def get_call_stats() -> Optional[CallStats]:
    """Get current call stats (or None if not tracking)."""
    return _current_stats


def _track_triage_call(is_retry: bool = False) -> None:
    """Increment triage call counter."""
    if _current_stats is not None:
        if is_retry:
            _current_stats.triage_retries += 1
        else:
            _current_stats.triage_calls += 1


def _track_parse_call(is_escalation: bool = False) -> None:
    """Increment parse call counter."""
    if _current_stats is not None:
        if is_escalation:
            _current_stats.escalation_calls += 1
        else:
            _current_stats.main_calls += 1


# Module-level debug flag (set by CLI --debug-openai)
DEBUG_OPENAI = False


def set_debug_openai(enabled: bool) -> None:
    """Enable/disable verbose OpenAI response debugging."""
    global DEBUG_OPENAI
    DEBUG_OPENAI = enabled


class ParseFailure(Exception):
    """Raised when structured parsing fails after retries."""

    def __init__(self, message: str, raw_output: str = None):
        super().__init__(message)
        self.raw_output = raw_output


# TypeVar for generic parsed result extraction
T = TypeVar("T")


def _diagnose_response_failure(response: Response, result_type: type) -> str:
    """
    Log detailed diagnostics when structured parsing fails.

    Only logs at DEBUG level unless DEBUG_OPENAI is enabled (then also prints).

    Args:
        response: The OpenAI Response object
        result_type: Expected type that wasn't found

    Returns:
        Diagnostic string summarizing the failure
    """
    diag_parts = [f"Expected type: {result_type.__name__}"]

    # Check response.output
    if not response.output:
        diag_parts.append("response.output: None/empty")
    else:
        diag_parts.append(f"response.output: {len(response.output)} items")
        for i, item in enumerate(response.output[:3]):  # First 3 items
            item_type = type(item).__name__
            diag_parts.append(f"  output[{i}]: {item_type}")

            # Check content attribute
            content_list = getattr(item, "content", None)
            if content_list is None:
                diag_parts.append("    content: None")
            elif not content_list:
                diag_parts.append("    content: empty list")
            else:
                diag_parts.append(f"    content: {len(content_list)} items")
                for j, content in enumerate(content_list[:2]):
                    content_type = type(content).__name__
                    has_parsed = hasattr(content, "parsed")
                    parsed_val = getattr(content, "parsed", None)
                    parsed_type = type(parsed_val).__name__ if parsed_val else "None"
                    diag_parts.append(
                        f"      content[{j}]: {content_type}, "
                        f"has_parsed={has_parsed}, parsed_type={parsed_type}"
                    )

                    # Try to get text content for preview
                    text_content = getattr(content, "text", None)
                    if text_content:
                        preview = text_content[:400].replace("\n", " ")
                        diag_parts.append(f"      text_preview: {preview}...")

    diagnostic = "\n".join(diag_parts)

    # Always log at DEBUG level
    logger.debug(f"Parse failure diagnostics:\n{diagnostic}")

    # If DEBUG_OPENAI enabled, also print
    if DEBUG_OPENAI:
        print(f"\n[DEBUG_OPENAI] Parse failure for {result_type.__name__}:")
        print(diagnostic)
        print()

    return diagnostic


def _extract_parsed_result(response: Response, result_type: type[T]) -> Optional[T]:
    """
    Safely extract parsed result from OpenAI Response.

    Handles the union type complexity of response.output by checking
    for the content attribute dynamically. For reasoning models (gpt-5-*),
    the output may contain multiple items - we iterate through all to find
    the parsed result.

    Args:
        response: The OpenAI Response object
        result_type: Expected type of the parsed result (for type hints)

    Returns:
        The parsed result if found, None otherwise (with diagnostics logged)
    """
    if not response.output:
        _diagnose_response_failure(response, result_type)
        return None

    # Iterate through all output items to find the one with parsed content
    # Reasoning models return: [ResponseReasoningItem, ParsedResponseOutputMessage]
    for output_item in response.output:
        # Use getattr to safely access content (may not exist on all output types)
        content_list = getattr(output_item, "content", None)
        if not content_list:
            continue

        # Check each content item for parsed result
        for content in content_list:
            parsed = getattr(content, "parsed", None)
            if parsed is not None and isinstance(parsed, result_type):
                return parsed

    # Parsing failed - log diagnostics
    _diagnose_response_failure(response, result_type)
    return None


# =============================================================================
# CONFIGURATION
# =============================================================================

# Preferred model names (gpt-5.1 for main parsing quality, gpt-5-mini for triage/summary)
_PREFERRED_MODELS = {
    "triage": "gpt-5-mini-2025-08-07",
    "main": "gpt-5.1-2025-11-13",  # Upgraded for better parsing quality
    "escalation": "gpt-5.1-2025-11-13",
    "summary": "gpt-5-mini-2025-08-07",
    "long": "gpt-5.1-2025-11-13",
}

# Fallback models (use if preferred not available)
_FALLBACK_MODELS = {
    "triage": "gpt-4o-mini",
    "main": "gpt-4o-mini",
    "escalation": "gpt-4o",
    "summary": "gpt-4o-mini",
    "long": "gpt-4o",
}

# Active models (set after validation)
MODEL_TRIAGE = os.getenv("OPENAI_MODEL_TRIAGE", _PREFERRED_MODELS["triage"])
MODEL_MAIN = os.getenv("OPENAI_MODEL_MAIN", _PREFERRED_MODELS["main"])
MODEL_ESCALATION = os.getenv("OPENAI_MODEL_ESCALATION", _PREFERRED_MODELS["escalation"])
MODEL_SUMMARY = os.getenv("OPENAI_MODEL_SUMMARY", _PREFERRED_MODELS["summary"])
MODEL_LONG_CONTEXT = os.getenv("OPENAI_MODEL_LONG", _PREFERRED_MODELS["long"])

# Character/token thresholds for model routing (env-configurable)
# Based on user request: 500 tokens (~2000 chars) triggers long-context routing
LONG_CONTEXT_THRESHOLD = int(os.getenv("OPENAI_LONG_CONTEXT_THRESHOLD_CHARS", 2000))
LONG_CONTEXT_THRESHOLD_TOKENS = int(
    os.getenv("OPENAI_LONG_CONTEXT_THRESHOLD_TOKENS", 500)
)
HUGE_MESSAGE_THRESHOLD = 40000  # ~10k tokens - definitely needs long-context

# Confidence thresholds (env-configurable)
ESCALATION_THRESHOLD = float(os.getenv("OPENAI_ESCALATION_THRESHOLD", 0.8))
LOW_CONFIDENCE_WARNING = 0.4  # Below this, flag as uncertain

# Symbol density routing thresholds
# High symbol density triggers long-context model or digest mode
SYMBOL_DENSITY_THRESHOLD = 10  # ticker_count >= 10 triggers routing
MAX_IDEAS_PER_SOFT_CHUNK = 15  # Overflow behavior: truncate after this many
MAX_IDEA_TEXT_LENGTH = 500  # Truncate idea_text to this length

# Overflow behavior for high-density messages: "truncate" | "group_digest" | "escalate"
# - truncate: Keep first MAX_IDEAS_PER_SOFT_CHUNK ideas, discard rest
# - group_digest: Combine excess ideas into summary groups
# - escalate: Route to stronger model with increased output tokens
OPENAI_OVERFLOW_BEHAVIOR = os.getenv("OPENAI_OVERFLOW_BEHAVIOR", "truncate")

# Track validated models (populated by validate_openai_models)
_validated_models: Dict[str, str] = {}
_available_models: set = set()


# =============================================================================
# INSTRUMENT DETECTION & EXTRACTION HELPERS
# =============================================================================

# Strike pattern: matches "180c", "95p", "400c" (call/put shorthand)
STRIKE_PATTERN = re.compile(r"\b(\d+)([cCpP])\b")

# Options context: "calls for $1.35", "$180 call", "puts at 95"
OPTIONS_CONTEXT = re.compile(
    r"(calls?|puts?)\s*(?:for|at|@)?\s*\$?(\d+(?:\.\d+)?)", re.IGNORECASE
)

# Crypto symbols (common abbreviations)
CRYPTO_SYMBOLS = {
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "ADA",
    "DOGE",
    "AVAX",
    "DOT",
    "MATIC",
    "LINK",
}

# Crypto full names (case-insensitive matching)
CRYPTO_NAMES = {
    "bitcoin",
    "ethereum",
    "solana",
    "ripple",
    "cardano",
    "dogecoin",
    "avalanche",
    "polkadot",
    "polygon",
    "chainlink",
}

# Support/resistance keywords for price level classification
SUPPORT_KEYWORDS = ["support", "hold", "floor", "bounce", "bounced", "base", "bottom"]
RESISTANCE_KEYWORDS = [
    "resistance",
    "target",
    "ceiling",
    "move to",
    "move into",
    "into",
    "break",
    "breakout",
]


def detect_instrument_type(text: str, primary_symbol: Optional[str] = None) -> str:
    """
    Detect if text refers to option, crypto, or equity.

    Args:
        text: The idea text to analyze
        primary_symbol: The primary symbol if already extracted

    Returns:
        "option", "crypto", or "equity"

    Examples:
        >>> detect_instrument_type("AAPL 180c looking good")
        'option'
        >>> detect_instrument_type("Bitcoin hit ATH")
        'crypto'
        >>> detect_instrument_type("Bought NVDA shares")
        'equity'
    """
    text_lower = text.lower()

    # Check for options patterns
    if STRIKE_PATTERN.search(text):
        return "option"
    if OPTIONS_CONTEXT.search(text):
        return "option"
    if re.search(
        r"\b(calls?|puts?|strike|expiry|exp\b|0dte|dte\b|premium|spread|straddle|strangle|iron\s?condor)\b",
        text_lower,
    ):
        return "option"

    # Check for crypto
    if primary_symbol and primary_symbol.upper() in CRYPTO_SYMBOLS:
        return "crypto"
    for name in CRYPTO_NAMES:
        if name in text_lower:
            return "crypto"

    return "equity"


def extract_strike_info(text: str) -> Dict[str, Any]:
    """
    Extract strike price, option type, and premium from text.

    Handles multiple formats:
    - "180c", "95p" → strike + type
    - "$180 call", "$95 put" → strike + type
    - "for $1.76", "@ $1.35" → premium

    Args:
        text: The text to analyze

    Returns:
        Dict with optional keys: strike, option_type, premium

    Examples:
        >>> extract_strike_info("AAPL 180c")
        {'strike': 180, 'option_type': 'call'}
        >>> extract_strike_info("$95 put for $1.76")
        {'strike': 95.0, 'option_type': 'put', 'premium': 1.76}
    """
    info = {}

    # Pattern 1: 180c, 95p
    match = STRIKE_PATTERN.search(text)
    if match:
        info["strike"] = int(match.group(1))
        info["option_type"] = "call" if match.group(2).lower() == "c" else "put"

    # Pattern 2: $180 call, $95 put
    match = re.search(r"\$(\d+(?:\.\d+)?)\s*(calls?|puts?)", text, re.IGNORECASE)
    if match and "strike" not in info:
        info["strike"] = float(match.group(1))
        info["option_type"] = "call" if "call" in match.group(2).lower() else "put"

    # Extract premium: for $1.76, @ $1.35
    match = re.search(r"(?:for|at|@)\s*\$(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if match:
        premium_val = float(match.group(1))
        # Premiums typically < $50 (high strikes like $180 are not premiums)
        if premium_val < 50:
            info["premium"] = premium_val

    return info


def extract_price_levels(text: str) -> List[Dict[str, Any]]:
    """
    Extract support/resistance/target levels from text.

    Uses context keywords to classify level type.
    Handles single prices and ranges.

    Args:
        text: The text to analyze

    Returns:
        List of dicts with keys: kind, value (or low/high), qualifier

    Examples:
        >>> extract_price_levels("bounced off $147, needs to hold 150")
        [{'kind': 'support', 'value': 147.0}, {'kind': 'support', 'value': 150.0}]
        >>> extract_price_levels("next move into $170 area")
        [{'kind': 'resistance', 'value': 170.0, 'qualifier': 'area'}]
    """
    levels = []
    text_lower = text.lower()

    # Find price mentions with context (word before + price)
    # Pattern: optional word, optional $, number with optional decimal
    for match in re.finditer(r"(?:(\w+)\s+)?\$?(\d+(?:\.\d+)?)", text, re.IGNORECASE):
        context_word = (match.group(1) or "").lower()
        price_str = match.group(2)
        price = float(price_str)

        # Skip very small numbers (likely not prices)
        if price < 1:
            continue

        # Skip if this looks like a year (4 digits starting with 19 or 20)
        if len(price_str) == 4 and price_str.startswith(("19", "20")):
            continue

        # Classify based on context keywords
        kind = "unknown"
        if any(kw in context_word for kw in SUPPORT_KEYWORDS):
            kind = "support"
        elif any(kw in context_word for kw in RESISTANCE_KEYWORDS):
            kind = "resistance"
        elif any(
            kw in text_lower[max(0, match.start() - 20) : match.start()]
            for kw in SUPPORT_KEYWORDS
        ):
            kind = "support"
        elif any(
            kw in text_lower[max(0, match.start() - 20) : match.start()]
            for kw in RESISTANCE_KEYWORDS
        ):
            kind = "resistance"

        # Check for qualifiers (near, around, above, below)
        qualifier = None
        window_start = max(0, match.start() - 15)
        window_text = text_lower[window_start : match.end() + 15]
        for qual in ["near", "around", "above", "below", "area", "range"]:
            if qual in window_text:
                qualifier = qual
                break

        level_dict = {"kind": kind, "value": price}
        if qualifier:
            level_dict["qualifier"] = qualifier

        levels.append(level_dict)

    # Price ranges: $93-$105, 87-88
    for match in re.finditer(
        r"\$?(\d+(?:\.\d+)?)\s*-\s*\$?(\d+(?:\.\d+)?)", text, re.IGNORECASE
    ):
        low = float(match.group(1))
        high = float(match.group(2))

        # Skip non-price ranges
        if low < 1 or high < 1 or high <= low:
            continue

        levels.append({"kind": "range", "low": low, "high": high})

    return levels


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _get_label_description(label: str) -> str:
    """Get description for a label."""
    descriptions = {
        "TRADE_EXECUTION": "Completed or in-progress trades",
        "TRADE_PLAN": "Future trade intentions, setups, entry plans",
        "TECHNICAL_ANALYSIS": "Price levels, patterns, trend analysis",
        "FUNDAMENTAL_THESIS": "Business fundamentals, valuations",
        "CATALYST_NEWS": "News events, macro headlines",
        "EARNINGS": "Earnings-specific discussion",
        "INSTITUTIONAL_FLOW": "13F filings, fund moves, institutional activity",
        "OPTIONS": "Options trades, strikes, expiries",
        "RISK_MANAGEMENT": "Stops, sizing, hedges",
        "SENTIMENT_CONVICTION": "Strong opinions, high/low conviction",
        "PORTFOLIO_UPDATE": "Position updates, P/L reports",
        "QUESTION_REQUEST": "Asking for information or opinions",
        "RESOURCE_LINK": "External links, charts, data sources",
    }
    return descriptions.get(label, label)


def _build_parser_system_prompt() -> str:
    """Build the parser system prompt with label descriptions."""
    label_list = "\n".join(
        f"- {label}: {_get_label_description(label)}" for label in TRADING_LABELS
    )
    return f"""You are an expert trading message parser. Extract structured information from Discord trading messages.

## YOUR TASK
Parse the message into semantic "idea units". Each idea should:
1. Focus on ONE primary subject (a specific ticker, the market, or portfolio)
2. Contain a coherent thought (thesis, trade plan, news, analysis)
3. Be properly classified with labels from the taxonomy

## LABEL TAXONOMY (13 categories)
{label_list}

## EXTRACTION RULES

### Symbols
- primary_symbol: The MAIN ticker this idea focuses on (null for market/portfolio-wide)
- symbols[]: ALL tickers mentioned in this idea
- Use uppercase without $ (e.g., "AAPL" not "$AAPL")

### Instrument Type
Classify the asset type being discussed:
- equity: Stocks, shares, ETFs (default for most tickers)
- option: Options contracts (use with option_type, strike, expiry fields)
- crypto: Cryptocurrencies like BTC, ETH, SOL, DOGE
- index: Market indexes like SPX, VIX, NDX, DJI
- sector: Sector-level analysis (tech sector, energy, financials)
- event_contract: Prediction markets, election contracts, sports betting

### Direction
- bullish: Expecting price to go up
- bearish: Expecting price to go down
- neutral: No directional view
- mixed: Both bullish and bearish elements

### Action
- buy/sell/short: Direct trade actions
- trim/add: Partial position changes
- watch: Monitoring, no action yet
- hold: Maintaining current position
- hedge: Risk management trade

### Time Horizon
- scalp: Minutes to hours
- swing: Days to weeks
- long_term: Months to years
- unknown: Not specified

### Levels (CRITICAL - Extract ALL Price Points)
Scan the ENTIRE message for price levels. Look for:
- Dollar amounts: $147, $12, $170, $260
- At-price notation: @15, @$12
- Informal prices: 150, 180, 12ish, around 15
- Ranges: $93-$105, 600-630, low 600s

Classify each level by context:
- **entry**: "buy at", "pickup @", "get in around", "under $X"
- **stop**: "stop loss", "stop at", "can't go below", "cut if under"
- **target**: "targeting", "aiming for", "next move to", "upside to", "EOY target"
- **support**: "bounced off", "held", "floor at", "can't break"
- **resistance**: "needs to hold", "break above", "ceiling at", "resistance at"

Examples:
- "pickup like 4+ shares @15 and set a stop loss at $12ish" → entry=15, stop=12
- "Bounced off $147, if it can hold 150, target $170" → support=147, resistance=150, target=170
- "looking for a dip to $240, target $280 EOY" → entry=240, target=280
- "needs consolidation in $93-$105" → range with low=93, high=105
- "keep an eye on it under $260" → entry=260, qualifier="under"

Output format:
- kind: entry, target, support, resistance, stop
- value: Exact price if given (e.g., 220.50)
- low/high: For ranges (e.g., "low 600s" → low=600, high=630)
- qualifier: Modifiers like "near", "around", "above", "below", "ish"

### Options
If discussing options, extract:
- option_type: call or put
- strike: Strike price
- expiry: Expiration date (ISO format: YYYY-MM-DD)
- premium: Price paid if mentioned

### Multi-Idea Messages
If a message discusses multiple stocks with separate thoughts:
- Create separate idea units for each
- Each idea should have its own primary_symbol
- Keep related context together (e.g., price level + thesis = 1 idea)
- **CRITICAL**: Each idea_text MUST be self-contained with enough context to stand alone
- AVOID 1-5 word fragments like "trimmed NVDA" - instead use "trimmed NVDA position as part of semi rotation"
- If splitting a sentence, copy shared context into each resulting idea_text
- Minimum idea_text length: ~20 characters; merge fragments into surrounding ideas if too short

### is_noise
Set to true ONLY if the content is:
- Off-topic chatter
- Bot commands/responses
- Uninformative reactions
Most trading discussion is NOT noise.

## OUTPUT FORMAT
Return a structured JSON with:
- ideas[]: Array of ParsedIdea objects
- context_summary: Overall 1-3 sentence summary of the message
- confidence: Your confidence in the parse quality (0.0-1.0)"""


# =============================================================================
# SYSTEM PROMPTS
# =============================================================================

TRIAGE_SYSTEM_PROMPT = """You are a quick triage assistant for trading Discord messages.

Your job is to rapidly assess:
1. Is this message NOISE (bot output, spam, off-topic, single emoji/word)?
2. Does it contain ACTIONABLE trade content (entries, exits, analysis, insights)?
3. What ticker symbols are mentioned?

Be fast and accurate. Focus on identifying noise to skip and tickers to route.

IMPORTANT: Short technical opinions and market insights are NOT noise.
If a message contains specific technology, sector, or market terms and reads
as an insight or assertion, mark it as ACTIONABLE even without explicit tickers.

Noise examples:
- Bot commands (!help, /roll)
- Single word responses (lol, nice, wow)
- Off-topic conversation (personal chat, jokes, memes)
- Pure emoji reactions

Actionable examples:
- "AAPL looking strong at 180 resistance"
- "Bought NVDA calls yesterday"
- "Trimming my TSLA position"
- Technical analysis with levels
- Earnings plays
- Portfolio updates with tickers

Tech insights (ACTIONABLE, even without tickers):
- "AI inference costs are dropping fast"
- "The semiconductor cycle is turning"
- "Cloud margins are compressing"
- "Battery tech breakthrough could disrupt EVs"
- "Yield curve inversion signals recession"
- "Memory prices bottoming out"
- Short sector/macro observations with conviction"""


SUMMARY_SYSTEM_PROMPT = """You are a concise summarizer for trading messages.

Given the already-extracted ideas from a message, create:
1. A brief overall summary (1-2 sentences)
2. Key takeaways for each idea

Focus on actionable information: tickers, direction, levels, timeframe.
Be extremely concise - traders want quick reference."""


# =============================================================================
# CLIENT INITIALIZATION
# =============================================================================

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    """Get or create the OpenAI client."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        _client = OpenAI(api_key=api_key)
    return _client


def validate_openai_models() -> Dict[str, str]:
    """
    Validate OpenAI models at startup and configure fallbacks.

    Lists available models, checks if configured models exist,
    falls back to safe defaults if not, and logs final choices.

    Should be called once at application startup.

    Returns:
        Dict mapping role (triage, main, etc.) to actual model ID
    """
    global MODEL_TRIAGE, MODEL_MAIN, MODEL_ESCALATION, MODEL_SUMMARY, MODEL_LONG_CONTEXT
    global _validated_models, _available_models

    client = get_client()

    # List available models
    try:
        models_response = client.models.list()
        _available_models = {m.id for m in models_response.data}
        logger.info(f"OpenAI API returned {len(_available_models)} available models")
    except Exception as e:
        logger.warning(f"Failed to list OpenAI models: {e}")
        logger.warning("Using fallback models without validation")
        _available_models = set()

    # Model roles and their current configured values
    model_config = {
        "triage": (
            MODEL_TRIAGE,
            _PREFERRED_MODELS["triage"],
            _FALLBACK_MODELS["triage"],
        ),
        "main": (MODEL_MAIN, _PREFERRED_MODELS["main"], _FALLBACK_MODELS["main"]),
        "escalation": (
            MODEL_ESCALATION,
            _PREFERRED_MODELS["escalation"],
            _FALLBACK_MODELS["escalation"],
        ),
        "summary": (
            MODEL_SUMMARY,
            _PREFERRED_MODELS["summary"],
            _FALLBACK_MODELS["summary"],
        ),
        "long": (
            MODEL_LONG_CONTEXT,
            _PREFERRED_MODELS["long"],
            _FALLBACK_MODELS["long"],
        ),
    }

    validated = {}

    for role, (current, preferred, fallback) in model_config.items():
        chosen_model = current

        if _available_models:
            # Check if current model is available
            if current in _available_models:
                logger.info(f"✓ {role}: {current} (available)")
                chosen_model = current
            elif preferred in _available_models:
                logger.info(f"✓ {role}: {preferred} (preferred, available)")
                chosen_model = preferred
            elif fallback in _available_models:
                logger.warning(
                    f"⚠ {role}: {current} not available, using fallback {fallback}"
                )
                chosen_model = fallback
            else:
                # Last resort - use fallback anyway and hope for the best
                logger.warning(
                    f"⚠ {role}: Neither {current} nor {fallback} found, using {fallback}"
                )
                chosen_model = fallback
        else:
            # No model list available, use fallback to be safe
            logger.info(f"  {role}: Using {fallback} (no validation)")
            chosen_model = fallback

        validated[role] = chosen_model

    # Update global model variables
    MODEL_TRIAGE = validated["triage"]
    MODEL_MAIN = validated["main"]
    MODEL_ESCALATION = validated["escalation"]
    MODEL_SUMMARY = validated["summary"]
    MODEL_LONG_CONTEXT = validated["long"]

    _validated_models = validated

    # Log final configuration
    logger.info("=== OpenAI Model Configuration ===")
    logger.info(f"  Triage:     {MODEL_TRIAGE}")
    logger.info(f"  Main:       {MODEL_MAIN}")
    logger.info(f"  Escalation: {MODEL_ESCALATION}")
    logger.info(f"  Summary:    {MODEL_SUMMARY}")
    logger.info(f"  Long:       {MODEL_LONG_CONTEXT}")
    logger.info("==================================")

    return validated


def get_model_for_text(
    text: str, force_long: bool = False, ticker_count: int = 0
) -> str:
    """
    Determine which model to use based on text length and symbol density.

    Auto-routes huge messages (13F filings, mega posts) or high symbol density
    messages to long-context model.

    Args:
        text: The message text
        force_long: Force use of long-context model
        ticker_count: Number of ticker symbols detected in the message

    Returns:
        Model ID to use
    """
    text_len = len(text)
    approx_tokens = text_len // 4  # Rough estimate: 4 chars per token

    # Always log token estimate for monitoring
    logger.debug(
        f"Model routing: {text_len} chars (~{approx_tokens} tokens), "
        f"{ticker_count} tickers"
    )

    if force_long:
        logger.info(
            f"Forced long-context model: {text_len} chars (~{approx_tokens} tokens)"
        )
        return MODEL_LONG_CONTEXT

    # Route based on length
    if text_len >= HUGE_MESSAGE_THRESHOLD:
        logger.info(
            f"HUGE message: {text_len} chars (~{approx_tokens} tokens) - "
            f"routing to long-context model"
        )
        return MODEL_LONG_CONTEXT
    elif text_len >= LONG_CONTEXT_THRESHOLD:
        logger.info(
            f"Long message: {text_len} chars (~{approx_tokens} tokens) - "
            f"routing to long-context model"
        )
        return MODEL_LONG_CONTEXT

    # Route based on symbol density (high ticker count)
    if ticker_count >= SYMBOL_DENSITY_THRESHOLD:
        logger.info(
            f"High symbol density: {ticker_count} tickers, "
            f"{text_len} chars (~{approx_tokens} tokens) - "
            f"routing to long-context model"
        )
        return MODEL_LONG_CONTEXT

    return MODEL_MAIN


# =============================================================================
# TRIAGE (gpt-5-nano equivalent)
# =============================================================================


def _triage_attempt(
    client, text: str, is_retry: bool = False
) -> Optional[TriageResult]:
    """
    Single triage attempt. Returns None if parsing fails.
    Tracks API call for monitoring.
    """
    # Track this API call
    _track_triage_call(is_retry=is_retry)

    try:
        response = client.responses.parse(
            model=MODEL_TRIAGE,
            input=[
                {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            text_format=TriageResult,
        )
        return _extract_parsed_result(response, TriageResult)
    except Exception as e:
        logger.debug(f"Triage attempt failed: {e}")
        return None


def triage_message(text: str, allow_retry: bool = True) -> TriageResult:
    """
    Quick triage to determine if message should be fully parsed.

    Uses the cheapest model (gpt-5-nano equivalent) to:
    1. Detect noise (skip parsing)
    2. Check for actionable content
    3. Extract ticker mentions for routing

    Implements retry: if first attempt fails, retry once.
    If retry fails, raises ParseFailure (caller handles gracefully).

    **CRITICAL**: Applies alias mapping BEFORE sending to LLM to normalize company names.

    Args:
        text: The cleaned message text
        allow_retry: Whether to retry on failure (default True)

    Returns:
        TriageResult with is_noise, has_actionable_content, tickers_present

    Raises:
        ParseFailure: If triage fails after retry
    """
    from src.nlp.preclean import apply_alias_mapping

    # Apply alias mapping to normalize company names → tickers
    text = apply_alias_mapping(text)
    logger.debug(f"Triage input (after alias mapping): {text[:100]}...")

    client = get_client()

    # First attempt (tracked as non-retry)
    result = _triage_attempt(client, text, is_retry=False)
    if result is not None:
        return result

    logger.warning("Triage parsing returned unexpected format - retrying once")

    if not allow_retry:
        raise ParseFailure(
            "Triage parsing failed: structured output not returned",
            raw_output=None,
        )

    # Retry once (tracked as retry)
    result = _triage_attempt(client, text, is_retry=True)
    if result is not None:
        logger.info("Triage retry succeeded")
        return result

    # Both attempts failed - raise exception
    logger.error("Triage failed after retry")
    raise ParseFailure(
        "Triage parsing failed after retry: structured output not returned",
        raw_output=None,
    )


# =============================================================================
# MAIN PARSER (gpt-5-mini equivalent)
# =============================================================================


def parse_message(
    text: str, escalate: bool = False, long_context: bool = False
) -> Tuple[MessageParseResult, str]:
    """
    Parse a message into structured idea units.

    Uses structured outputs to guarantee valid JSON schema.
    Auto-routes to long-context model for huge messages.

    Implements hard-fail + escalation:
    - If extraction fails with main model, escalate to gpt-5.1
    - If escalation fails, raise ParseFailure (caller handles gracefully)

    **CRITICAL**:
    1. Applies alias mapping BEFORE sending to LLM to normalize company names.
    2. Extracts candidate_tickers BEFORE LLM to constrain ticker extraction.
    3. Post-validates LLM output to filter hallucinated tickers.

    Args:
        text: The cleaned message text
        escalate: If True, use the escalation model (gpt-5.1 equivalent)
        long_context: If True, force use of the long context model (gpt-4.1 equivalent)

    Returns:
        Tuple of (MessageParseResult, model_used)

    Raises:
        ParseFailure: If parsing fails after escalation
    """
    from src.nlp.preclean import (
        apply_alias_mapping,
        extract_candidate_tickers,
        validate_llm_tickers,
    )

    # Step 1: Extract candidate tickers BEFORE alias mapping
    # This gives us the "ground truth" tickers from the original text
    candidates = extract_candidate_tickers(text, include_context_check=True)
    candidate_tickers = candidates["tickers"]
    logger.debug(f"Candidate tickers: {candidate_tickers}")

    # Step 2: Apply alias mapping to normalize company names → tickers
    text = apply_alias_mapping(text)
    logger.debug(f"Parse input (after alias mapping): {text[:100]}...")

    # Step 3: Re-extract after alias mapping to catch new tickers
    post_alias = extract_candidate_tickers(text, include_context_check=False)
    for ticker in post_alias["tickers"]:
        if ticker not in candidate_tickers:
            candidate_tickers.append(ticker)

    logger.debug(f"Final candidate tickers: {candidate_tickers}")

    client = get_client()

    # Auto-detect if long context needed based on message length
    text_len = len(text)
    if text_len >= LONG_CONTEXT_THRESHOLD and not long_context:
        logger.info(
            f"Message length {text_len} chars - auto-routing to long-context model"
        )
        long_context = True

    # Select model and track API call
    if long_context:
        model = MODEL_LONG_CONTEXT
        _track_parse_call(is_escalation=False)  # Long-context counts as main
    elif escalate:
        model = MODEL_ESCALATION
        _track_parse_call(is_escalation=True)
    else:
        model = MODEL_MAIN
        _track_parse_call(is_escalation=False)

    logger.debug(
        f"Using model {model} for parsing (len={text_len}, escalate={escalate})"
    )

    # Build user prompt with candidate tickers hint (helps constrain LLM)
    user_content = f"Parse this trading message:\n\n{text}"
    if candidate_tickers:
        user_content += f"\n\n[HINT: Candidate tickers detected: {', '.join(candidate_tickers)}. Only use these tickers unless you're very confident about others.]"

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": _build_parser_system_prompt()},
                {"role": "user", "content": user_content},
            ],
            text_format=MessageParseResult,
        )

        # Extract parsed result using type-safe helper
        result = _extract_parsed_result(response, MessageParseResult)
        if result is not None:
            # Check for low confidence - escalate if not already
            if result.confidence < ESCALATION_THRESHOLD and not escalate:
                logger.info(f"Low confidence ({result.confidence:.2f}), escalating")
                return parse_message(text, escalate=True, long_context=long_context)

            return result, model

        # Extraction failed - escalate if not already
        if not escalate:
            logger.warning(
                "Parser returned unexpected format - escalating to stronger model"
            )
            return parse_message(text, escalate=True, long_context=long_context)

        # Already escalated and still failed - raise exception
        logger.error("Parse failed after escalation: structured output not returned")
        raise ParseFailure(
            "Parse failed after escalation: structured output not returned",
            raw_output=None,
        )

    except ParseFailure:
        # Re-raise ParseFailure from recursive escalation
        raise

    except Exception as e:
        logger.error(f"Parse failed with {model}: {e}")

        # Try escalation on error
        if not escalate:
            logger.info("Attempting escalation after exception")
            try:
                return parse_message(text, escalate=True, long_context=long_context)
            except ParseFailure:
                raise  # Escalation failed with ParseFailure
            except Exception as e2:
                logger.error(f"Escalation also failed with exception: {e2}")
                raise ParseFailure(
                    f"Parse failed after escalation: {e2}",
                    raw_output=None,
                ) from e2

        # Already escalated - raise ParseFailure
        raise ParseFailure(
            f"Parse failed with escalation model: {e}",
            raw_output=None,
        ) from e


# =============================================================================
# FULL PIPELINE
# =============================================================================


def process_message(
    text: str,
    message_id: Union[int, str],
    author_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    created_at: Optional[str] = None,
    skip_triage: bool = False,
    force_long_context: bool = False,
    message_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Full processing pipeline for a single message.

    Pipeline:
    1. Prefilter check (uses should_skip_message SSOT)
    2. Soft split (deterministic)
    3. Triage each chunk (optional, cheap)
    4. Parse non-noise chunks (main model)
    5. Escalate low-confidence results
    6. Return database-ready rows

    Call tracking: Logs summary at end showing API calls made.

    Args:
        text: Raw message text
        message_id: Database message ID
        author_id: Discord author ID (also used for bot detection if message_meta missing)
        channel_id: Discord channel ID
        created_at: Original message timestamp
        skip_triage: Skip triage step (useful for known-good messages)
        force_long_context: Use long context model (for 13F, long messages)
        message_meta: Optional dict with 'author', 'is_bot' for prefilter checks.
                     If not provided, will be constructed from author_id.

    Returns:
        Dict with:
        - status: 'ok', 'error', 'skipped', 'noise'
        - ideas: List of database-ready row dicts
        - model: Model used
        - error_reason: Error message if status='error'
        - call_stats: CallStats summary string
    """
    from src.nlp.soft_splitter import prepare_for_parsing, summarize_splits
    from src.nlp.preclean import should_skip_message

    # Initialize call tracking for this message
    stats = reset_call_stats()

    # Build message_meta if not provided (for SSOT prefilter check)
    if message_meta is None and author_id is not None:
        message_meta = {"author": author_id}

    # Step 0: SSOT prefilter check (bot commands, URL-only, bot responses)
    should_skip, skip_reason = should_skip_message(text, message_meta)
    if should_skip:
        logger.info(f"[msg={message_id}] CALLS: skipped ({skip_reason})")
        return {
            "status": "skipped",
            "ideas": [],
            "model": None,
            "error_reason": skip_reason,
            "call_stats": "skipped",
        }

    # Step 1: Preclean and soft split
    chunks = prepare_for_parsing(text)
    stats.soft_chunks = len(chunks)

    if not chunks:
        logger.info(
            f"[msg={message_id}] CALLS: {stats.summary()} (empty after preprocess)"
        )
        return {
            "status": "noise",
            "ideas": [],
            "model": MODEL_TRIAGE,
            "error_reason": "Empty after preprocessing",
            "call_stats": stats.summary(),
        }

    logger.debug(f"Soft split: {summarize_splits(chunks)}")

    all_ideas = []
    all_raw_json = []
    models_used = set()
    idea_index = 0
    noise_count = 0
    total_chunks = len(chunks)

    # OPTIMIZATION: For single-chunk messages, triage ONCE for whole message
    # This prevents call explosion on messages that soft-split into many chunks
    whole_message_is_noise = False
    if not skip_triage and total_chunks == 1:
        # Single chunk: normal per-chunk triage
        pass
    elif not skip_triage and total_chunks > 1:
        # Multiple chunks: triage entire message ONCE, not per-chunk
        # This reduces calls from (N triage + N parse) to (1 triage + N parse)
        try:
            # Sample triage on first 2000 chars of original text
            triage_sample = text[:2000] if len(text) > 2000 else text
            whole_triage = triage_message(triage_sample)
            if whole_triage.is_noise:
                logger.info(
                    f"Whole message triaged as noise: {whole_triage.skip_reason}"
                )
                logger.info(
                    f"[msg={message_id}] CALLS: {stats.summary()} (whole-message noise)"
                )
                return {
                    "status": "noise",
                    "ideas": [],
                    "model": MODEL_TRIAGE,
                    "error_reason": f"Whole message noise: {whole_triage.skip_reason}",
                    "call_stats": stats.summary(),
                }
            # Message passed triage - skip per-chunk triage
            skip_triage = True
            logger.debug("Whole-message triage passed - skipping per-chunk triage")
        except ParseFailure as e:
            logger.warning(
                f"Whole-message triage failed, falling back to per-chunk: {e}"
            )
            # Continue with per-chunk triage

    # Step 2-4: Process each chunk
    for chunk_idx, chunk in enumerate(chunks):
        # Track local idea index within this chunk
        local_idea_idx = 0

        # Step 2: Triage (optional, skipped if whole-message triage passed)
        if not skip_triage:
            try:
                triage = triage_message(chunk.text)
                if triage.is_noise:
                    logger.debug(f"Chunk triaged as noise: {triage.skip_reason}")
                    noise_count += 1
                    stats.noise_chunks += 1
                    continue
            except ParseFailure as e:
                logger.error(f"Triage failed after retry: {e}")
                logger.info(
                    f"[msg={message_id}] CALLS: {stats.summary()} (triage failed)"
                )
                return {
                    "status": "error",
                    "ideas": [],
                    "model": MODEL_TRIAGE,
                    "error_reason": f"Triage failed: {e}",
                    "call_stats": stats.summary(),
                }

        # Step 3: Parse
        try:
            # Use long context for very long chunks or if forced
            use_long = force_long_context or len(chunk.text) > 3000

            result, model = parse_message(
                chunk.text, escalate=False, long_context=use_long
            )
            models_used.add(model)

            # Store raw response for provenance
            raw_json = {
                "chunk_text": chunk.text,
                "chunk_type": chunk.chunk_type,
                "result": result.model_dump(),
            }
            all_raw_json.append(raw_json)

            # Convert ideas to database rows
            for idea in result.ideas:
                if not idea.is_noise:
                    row = parsed_idea_to_db_row(
                        idea=idea,
                        message_id=message_id,
                        idea_index=idea_index,
                        context_summary=result.context_summary,
                        model=model,
                        prompt_version=CURRENT_PROMPT_VERSION,
                        confidence=result.confidence,
                        raw_json=raw_json,
                        author_id=author_id,
                        channel_id=channel_id,
                        source_created_at=created_at,
                        soft_chunk_index=chunk_idx,
                        local_idea_index=local_idea_idx,
                    )
                    all_ideas.append(row)
                    idea_index += 1
                    local_idea_idx += 1

        except ParseFailure as e:
            # Explicit handling for structured output failures
            logger.error(f"Parse failed after retry/escalation: {e}")
            logger.info(f"[msg={message_id}] CALLS: {stats.summary()} (parse failed)")
            return {
                "status": "error",
                "ideas": [],
                "model": MODEL_MAIN,
                "error_reason": f"Parse failed: {e}",
                "call_stats": stats.summary(),
            }

        except Exception as e:
            # Unexpected errors (network, etc.)
            logger.error(f"Unexpected error parsing chunk: {e}")
            logger.info(
                f"[msg={message_id}] CALLS: {stats.summary()} (unexpected error)"
            )
            return {
                "status": "error",
                "ideas": [],
                "model": MODEL_MAIN,
                "error_reason": f"Unexpected error: {e}",
                "call_stats": stats.summary(),
            }

    # Update noise count in stats
    stats.noise_chunks = noise_count

    # Determine final status
    if not all_ideas:
        # Check if all chunks were noise (triage said skip all)
        if noise_count == total_chunks and total_chunks > 0:
            logger.info(f"[msg={message_id}] CALLS: {stats.summary()} (all noise)")
            return {
                "status": "noise",
                "ideas": [],
                "model": MODEL_TRIAGE,
                "error_reason": "All chunks triaged as noise",
                "call_stats": stats.summary(),
            }
        else:
            logger.info(f"[msg={message_id}] CALLS: {stats.summary()} (no ideas)")
            return {
                "status": "noise",
                "ideas": [],
                "model": ",".join(models_used) if models_used else MODEL_TRIAGE,
                "error_reason": "No non-noise ideas extracted",
                "call_stats": stats.summary(),
            }

    # =============================================================================
    # POST-PROCESSING: Merge short ideas and validate tickers
    # =============================================================================
    from src.nlp.preclean import (
        merge_short_ideas,
        extract_candidate_tickers,
        validate_llm_tickers,
    )

    # Step 5a: Merge short idea fragments with neighbors
    ideas_before = len(all_ideas)
    all_ideas = merge_short_ideas(all_ideas)
    ideas_after = len(all_ideas)
    if ideas_before != ideas_after:
        logger.info(f"Merged short ideas: {ideas_before} → {ideas_after}")

    # Step 5b: Re-number idea_index after merge
    for idx, idea in enumerate(all_ideas):
        idea["idea_index"] = idx

    # Step 5c: Validate tickers against deterministic extraction
    # Extract candidate tickers from the original full text
    candidates = extract_candidate_tickers(text, include_context_check=True)
    candidate_tickers = candidates["tickers"]

    for idea in all_ideas:
        # Validate primary_symbol
        if idea.get("primary_symbol"):
            validated, dropped = validate_llm_tickers(
                [idea["primary_symbol"]], candidate_tickers, strict=False
            )
            if dropped:
                logger.warning(
                    f"Dropping primary_symbol '{idea['primary_symbol']}' (not in candidates)"
                )
                idea["primary_symbol"] = validated[0] if validated else None

        # Validate symbols list
        if idea.get("symbols"):
            validated, dropped = validate_llm_tickers(
                idea["symbols"], candidate_tickers, strict=False
            )
            if dropped:
                logger.info(
                    f"Filtered {len(dropped)} hallucinated tickers from symbols list"
                )
            idea["symbols"] = validated

    # Success - log call summary
    logger.info(f"[msg={message_id}] CALLS: {stats.summary()} → {len(all_ideas)} ideas")

    return {
        "status": "ok",
        "ideas": all_ideas,
        "model": ",".join(models_used),
        "error_reason": None,
        "call_stats": stats.summary(),
    }


# =============================================================================
# BATCH API SUPPORT
# =============================================================================


def _make_schema_strict(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Make a JSON schema OpenAI Batch API strict-mode compliant.

    OpenAI's Batch API with strict=true requires:
    1. additionalProperties: false on ALL object definitions
    2. ALL properties listed in 'required' array (no optional fields)
    3. NO anyOf constructs - use type: ["string", "null"] instead
    4. $ref cannot have sibling properties - inline completely
    5. Remove 'default' values (OpenAI determines defaults)

    Pydantic's model_json_schema() doesn't satisfy these by default.

    Args:
        schema: The JSON schema dict to modify

    Returns:
        Modified schema compliant with OpenAI strict mode
    """
    import copy

    schema = copy.deepcopy(schema)

    # Extract $defs for reference resolution
    defs = schema.get("$defs", {})

    def _resolve_ref(ref_path: str) -> Optional[Dict[str, Any]]:
        """Resolve a $ref path like '#/$defs/Action' to its definition."""
        if ref_path.startswith("#/$defs/"):
            def_name = ref_path.split("/")[-1]
            return copy.deepcopy(defs.get(def_name))
        return None

    def _inline_ref(obj: Dict[str, Any]) -> Dict[str, Any]:
        """
        Inline $ref definitions. If $ref has sibling properties (description, default),
        merge them with the resolved definition. OpenAI strict mode doesn't allow
        $ref with any siblings.
        """
        if "$ref" not in obj:
            return obj

        ref_path = obj["$ref"]
        ref_def = _resolve_ref(ref_path)

        if not ref_def:
            return obj  # Can't resolve, leave as-is

        # Collect sibling properties (anything besides $ref)
        siblings = {k: v for k, v in obj.items() if k != "$ref"}

        # Merge: ref_def properties take precedence, but keep siblings as fallback
        # For description: prefer obj's description if present, else ref_def's
        result = ref_def.copy()
        for k, v in siblings.items():
            if k not in result:
                result[k] = v
            elif k == "description" and v:
                # Prefer the more specific description from the property
                result[k] = v

        return result

    def _convert_anyof_to_nullable(obj: Dict[str, Any]) -> Dict[str, Any]:
        """Convert anyOf with null to type array format, inlining $ref enums."""
        if "anyOf" not in obj:
            return obj

        anyof_items = obj["anyOf"]

        # Check if this is a nullable pattern: anyOf: [{...}, {type: null}]
        types = []
        null_present = False
        ref = None
        ref_def = None
        other_props = {}

        for item in anyof_items:
            if isinstance(item, dict):
                if item.get("type") == "null":
                    null_present = True
                elif "$ref" in item:
                    ref = item["$ref"]
                    ref_def = _resolve_ref(ref)
                elif "type" in item:
                    types.append(item.get("type"))
                    for k, v in item.items():
                        if k != "type":
                            other_props[k] = v

        if null_present and (types or ref):
            # Remove anyOf and rebuild
            del obj["anyOf"]

            if ref and ref_def:
                # Inline the referenced definition and make nullable
                if "enum" in ref_def:
                    obj["type"] = ["string", "null"]
                    obj["enum"] = ref_def["enum"] + [None]
                    if "description" in ref_def and "description" not in obj:
                        obj["description"] = ref_def["description"]
                else:
                    # Non-enum $ref - inline it
                    for k, v in ref_def.items():
                        if k not in obj:
                            obj[k] = v
            elif len(types) == 1:
                obj["type"] = [types[0], "null"]
                obj.update(other_props)
            else:
                obj["type"] = types + ["null"]
                obj.update(other_props)

        return obj

    def _make_strict(obj: Any) -> Any:
        if isinstance(obj, dict):
            # Step 1: Inline any standalone $ref fields
            obj = _inline_ref(obj)

            # Step 2: Convert anyOf nullable patterns
            obj = _convert_anyof_to_nullable(obj)

            # Step 3: If object type, make strict-compliant
            if obj.get("type") == "object":
                obj["additionalProperties"] = False
                if "properties" in obj:
                    obj["required"] = list(obj["properties"].keys())

            # Step 4: Remove 'default' (not allowed in strict mode)
            obj.pop("default", None)

            # Step 5: Recurse into all dict values
            for key, value in list(obj.items()):
                obj[key] = _make_strict(value)

        elif isinstance(obj, list):
            return [_make_strict(item) for item in obj]
        return obj

    return _make_strict(schema)


def build_batch_request(
    message_id: Union[int, str], text: str, chunk_index: int = 0
) -> Dict[str, Any]:
    """
    Build a single request for the OpenAI Batch API.

    Args:
        message_id: Database message ID (str or int, stored as string)
        text: Cleaned message text (single chunk)
        chunk_index: Index of this chunk within the message

    Returns:
        Dict in Batch API format
    """
    # Get Pydantic schema and make it strict-compliant for Batch API
    raw_schema = MessageParseResult.model_json_schema()
    strict_schema = _make_schema_strict(raw_schema)

    return {
        "custom_id": f"msg-{message_id}-chunk-{chunk_index}",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": MODEL_MAIN,
            "messages": [
                {"role": "system", "content": _build_parser_system_prompt()},
                {"role": "user", "content": f"Parse this trading message:\n\n{text}"},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "message_parse_result",
                    "schema": strict_schema,
                    "strict": True,
                },
            },
        },
    }


def parse_batch_response(
    response_line: Dict[str, Any],
) -> Tuple[int, int, Optional[MessageParseResult]]:
    """
    Parse a single line from batch output JSONL.

    Args:
        response_line: Parsed JSON from batch output

    Returns:
        Tuple of (message_id as string, chunk_index, parsed_result or None)
    """
    custom_id = response_line.get("custom_id", "")

    # Parse custom_id: "msg-123456-chunk-0"
    parts = custom_id.split("-")
    if len(parts) >= 4:
        message_id = str(parts[1])  # Always string
        chunk_index = int(parts[3])
    else:
        logger.error(f"Invalid custom_id format: {custom_id}")
        return "", 0, None

    # Check for error
    if response_line.get("error"):
        logger.error(f"Batch error for {custom_id}: {response_line['error']}")
        return message_id, chunk_index, None

    # Parse response body
    try:
        body = response_line.get("response", {}).get("body", {})
        choices = body.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            result = MessageParseResult.model_validate_json(content)
            return message_id, chunk_index, result
    except Exception as e:
        logger.error(f"Failed to parse batch response: {e}")

    return message_id, chunk_index, None


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def estimate_cost(text: str, include_triage: bool = True) -> Dict[str, float]:
    """
    Estimate token cost for processing a message.

    This is a rough estimate based on character counts.

    Args:
        text: Message text
        include_triage: Include triage step in estimate

    Returns:
        Dict with estimated input_tokens, output_tokens, cost_usd
    """
    from src.nlp.soft_splitter import soft_split

    chunks = soft_split(text)

    # Rough estimates (4 chars per token average)
    system_tokens = len(_build_parser_system_prompt()) // 4
    triage_tokens = len(TRIAGE_SYSTEM_PROMPT) // 4 if include_triage else 0

    input_tokens = 0
    output_tokens = 0

    for chunk in chunks:
        chunk_input = system_tokens + (len(chunk.text) // 4)
        chunk_output = 500  # Rough estimate for structured output

        if include_triage:
            input_tokens += triage_tokens + (len(chunk.text) // 4)
            output_tokens += 100  # Triage output

        input_tokens += chunk_input
        output_tokens += chunk_output

    # Cost estimates (gpt-4o-mini prices as placeholder)
    # Input: $0.15/1M tokens, Output: $0.60/1M tokens
    cost_usd = (input_tokens * 0.15 + output_tokens * 0.60) / 1_000_000

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "num_chunks": len(chunks),
    }
