"""
Pre-cleaning utilities for Discord messages.

Provides functions to:
- Detect and filter bot commands
- Detect bot responses
- Normalize text for NLP processing
- Apply alias mapping (company names → tickers)
"""

import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# ALIAS MAPPING - Company names to ticker symbols
# =============================================================================

# Case-insensitive mapping of company names, aliases, and common references to tickers.
# Applied before triage/parsing to help the LLM recognize entities.
ALIAS_MAP = {
    # Big Tech
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "waymo": "GOOGL",  # Alphabet subsidiary
    "youtube": "GOOGL",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "amazon": "AMZN",
    "meta": "META",
    "facebook": "META",
    "instagram": "META",
    "whatsapp": "META",
    "netflix": "NFLX",
    # Semiconductors
    "amd": "AMD",
    "intel": "INTC",
    "tsmc": "TSM",
    "taiwan semi": "TSM",
    "taiwan semiconductor": "TSM",
    "broadcom": "AVGO",
    "qualcomm": "QCOM",
    "micron": "MU",
    # Ride-sharing / Delivery
    "uber": "UBER",
    "lyft": "LYFT",
    "doordash": "DASH",
    # Social / Communications
    "snap": "SNAP",
    "snapchat": "SNAP",
    "twitter": "X",  # Now X Corp
    "x corp": "X",
    "discord": "DISCORD",  # Private but often mentioned
    "pinterest": "PINS",
    "reddit": "RDDT",
    # EV / Auto
    "rivian": "RIVN",
    "lucid": "LCID",
    "toyota": "TM",
    "ford": "F",
    "gm": "GM",
    "general motors": "GM",
    # Finance
    "robinhood": "HOOD",
    "coinbase": "COIN",
    "paypal": "PYPL",
    "square": "SQ",
    "block": "SQ",  # Renamed from Square
    "sofi": "SOFI",
    "affirm": "AFRM",
    "upstart": "UPST",
    # Healthcare
    "unitedhealth": "UNH",
    "pfizer": "PFE",
    "moderna": "MRNA",
    "eli lilly": "LLY",
    "novo nordisk": "NVO",
    # Retail
    "walmart": "WMT",
    "costco": "COST",
    # NOTE: "target" is ambiguous (could be price target or Target Corp)
    # Only map specific unambiguous variants:
    "target corp": "TGT",
    "target store": "TGT",
    "target stores": "TGT",
    "target retail": "TGT",
    # "amazon" already mapped above (Mega-cap section)
    # Cloud / Enterprise
    "salesforce": "CRM",
    "snowflake": "SNOW",
    "palantir": "PLTR",
    "pltr": "PLTR",  # Lowercase ticker commonly used without $
    "crowdstrike": "CRWD",
    "crwd": "CRWD",
    "datadog": "DDOG",
    "mongodb": "MDB",
    # Popular lowercase tickers (commonly used without $ prefix)
    "nvda": "NVDA",
    "aapl": "AAPL",
    "msft": "MSFT",
    "amzn": "AMZN",
    "googl": "GOOGL",
    "tsla": "TSLA",
    "hood": "HOOD",
    # "sofi" already mapped above (Fintech section)
    "afrm": "AFRM",
    "coin": "COIN",
    "mstr": "MSTR",
    "rklb": "RKLB",
    "rddt": "RDDT",
    "baba": "BABA",
    "crwv": "CRWV",
    "grab": "GRAB",
    "intc": "INTC",
    "avgo": "AVGO",
    # Crypto-related
    "bitcoin": "BTC",
    "btc": "BTC",
    "ethereum": "ETH",
    "eth": "ETH",
    "solana": "SOL",
    "cardano": "ADA",
    "dogecoin": "DOGE",
    "ripple": "XRP",
    "avalanche": "AVAX",
    # ETFs
    "spy": "SPY",
    "qqq": "QQQ",
    "arkk": "ARKK",
    "ark innovation": "ARKK",
    # Indexes (convert mentions to tradable symbols)
    "s&p": "SPY",
    "s&p 500": "SPY",
    "nasdaq": "QQQ",
}

# =============================================================================
# RESERVED SIGNAL WORDS - Trading terms that should NEVER become tickers
# =============================================================================
# These words look like tickers but are actually trading terminology.
# They should NOT be mapped even if they match a valid ticker symbol.
# The key distinction: these are "signal" words used in trade descriptions.

RESERVED_SIGNAL_WORDS = {
    # Price level terms (commonly confused with tickers)
    "tgt",  # Often used as "target" abbreviation, not Target Corp
    "pt",  # Price target
    "tp",  # Take profit
    "sl",  # Stop loss
    "be",  # Break even
    "r1",
    "r2",
    "r3",  # Resistance levels
    "s1",
    "s2",
    "s3",  # Support levels
    # Trading action terms
    "buy",
    "sell",
    "hold",
    "long",
    "short",
    "trim",
    "add",
    "exit",
    "entry",
    "stop",
    "limit",
    # Level descriptors
    "target",  # "price target" not Target Corp
    "support",
    "resistance",
    "breakout",
    "breakdown",
    "pivot",
    "range",
    "high",
    "low",
    "open",
    "close",
    # Time references
    "eod",  # End of day
    "eow",  # End of week
    "eom",  # End of month
    "ath",  # All time high
    "atl",  # All time low
    # Option terms
    "call",
    "calls",
    "put",
    "puts",
    "strike",
    "exp",
    "dte",
    "itm",
    "otm",
    "atm",
    # Common abbreviations
    "imo",
    "imho",
    "tbh",
    "fwiw",
    "yolo",
    "fomo",
    "hodl",
    "btfd",
    "dca",
    # Measurement/analysis
    "ta",  # Technical analysis
    "fa",  # Fundamental analysis
    "dd",  # Due diligence
    "er",  # Earnings report
    "eps",
    "pe",
    "ps",
    "pb",
    "rsi",
    "macd",
    "sma",
    "ema",
    "vwap",
}

# Compile regex patterns for efficient matching
# We use word boundaries to avoid partial matches (e.g., "google" in "googled")
_ALIAS_PATTERNS = {
    alias: re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
    for alias in ALIAS_MAP.keys()
}


def is_reserved_signal_word(word: str) -> bool:
    """
    Check if a word is a reserved trading signal word.

    Reserved words should NOT be converted to tickers even if they
    match valid ticker patterns, because they are trading terminology.

    Args:
        word: The word to check (case-insensitive)

    Returns:
        True if the word is reserved and should not become a ticker
    """
    return word.lower().strip() in RESERVED_SIGNAL_WORDS


def apply_alias_mapping(text: str, skip_reserved: bool = True) -> str:
    """
    Replace company names and aliases with $TICKER symbols.

    Uses word-boundary regex to avoid partial replacements.
    Case-insensitive matching. Only replaces if not already a ticker format.

    By default, skips reserved signal words (tgt, pt, target, etc.) to avoid
    false positives where trading terminology is mistaken for tickers.

    Args:
        text: Original message text
        skip_reserved: If True, skip words in RESERVED_SIGNAL_WORDS

    Returns:
        Text with aliases replaced by $TICKER format

    Examples:
        >>> apply_alias_mapping("super bullish uber business model")
        'super bullish $UBER business model'
        >>> apply_alias_mapping("Waymo exclusivity")
        '$GOOGL Waymo exclusivity'
        >>> apply_alias_mapping("$UBER is great")  # Already a ticker
        '$UBER is great'
        >>> apply_alias_mapping("price target 150")  # "target" is reserved
        'price target 150'
    """
    if not text:
        return text

    result = text

    # Sort aliases by length descending to match longer phrases first
    # e.g., "taiwan semiconductor" before "taiwan"
    sorted_aliases = sorted(ALIAS_MAP.keys(), key=len, reverse=True)

    for alias in sorted_aliases:
        # Skip reserved signal words if enabled
        if skip_reserved and is_reserved_signal_word(alias):
            continue

        pattern = _ALIAS_PATTERNS[alias]
        ticker = ALIAS_MAP[alias]

        # Find all matches
        matches = list(pattern.finditer(result))
        if not matches:
            continue

        # Replace from end to preserve indices
        for match in reversed(matches):
            start, end = match.start(), match.end()
            matched_text = result[start:end]

            # Check if already prefixed with $ (already a ticker)
            if start > 0 and result[start - 1] == "$":
                continue

            # Skip if the matched text itself is a reserved signal word
            if skip_reserved and is_reserved_signal_word(matched_text):
                continue

            # Replace with $TICKER
            result = result[:start] + f"${ticker}" + result[end:]
            logger.debug(f"Alias mapping: '{matched_text}' → '${ticker}'")

    return result


def extract_tickers_from_text(text: str) -> list:
    """
    Extract all $TICKER symbols from text (after alias mapping).

    Args:
        text: Text to extract tickers from

    Returns:
        List of ticker symbols (without $ prefix, uppercase)
    """
    if not text:
        return []

    ticker_pattern = re.compile(r"\$([A-Z]{1,6}(?:\.[A-Z]+)?)", re.IGNORECASE)
    matches = ticker_pattern.findall(text)
    return [t.upper() for t in matches]


def extract_candidate_tickers(text: str, include_context_check: bool = True) -> dict:
    """
    Deterministic ticker extraction that produces a candidate list for LLM.

    This is the CANONICAL function for extracting tickers before passing to the parser.
    It uses multiple strategies and filters to produce high-confidence candidates.

    Strategy:
    1. Extract explicit $TICKER patterns (highest confidence)
    2. Apply alias mapping to find company names
    3. Validate context for bare uppercase words (medium confidence)
    4. Filter out reserved signal words
    5. Deduplicate and rank by confidence

    Args:
        text: The message text to extract tickers from
        include_context_check: If True, validate bare tickers have trading context

    Returns:
        Dictionary with:
        - tickers: List of unique ticker symbols (uppercase, no $)
        - sources: Dict mapping each ticker to how it was found
        - confidence: Overall extraction confidence (0.0-1.0)

    Examples:
        >>> extract_candidate_tickers("Buy $AAPL, bullish on nvidia")
        {'tickers': ['AAPL', 'NVDA'], 'sources': {'AAPL': 'explicit', 'NVDA': 'alias'}, 'confidence': 0.95}
    """
    if not text:
        return {"tickers": [], "sources": {}, "confidence": 0.0}

    tickers = {}  # ticker -> source

    # Step 1: Extract explicit $TICKER patterns (highest confidence)
    explicit_pattern = re.compile(r"\$([A-Z]{1,6}(?:\.[A-Z]+)?)", re.IGNORECASE)
    for match in explicit_pattern.finditer(text):
        ticker = match.group(1).upper()
        if not is_reserved_signal_word(ticker):
            tickers[ticker] = "explicit"

    # Step 2: Apply alias mapping and extract newly added tickers
    mapped_text = apply_alias_mapping(text, skip_reserved=True)
    for match in explicit_pattern.finditer(mapped_text):
        ticker = match.group(1).upper()
        if ticker not in tickers and not is_reserved_signal_word(ticker):
            tickers[ticker] = "alias"

    # Step 3: Check for bare uppercase tokens that might be tickers
    # Only include if they pass context validation
    if include_context_check:
        bare_ticker_pattern = re.compile(r"\b([A-Z]{1,5})\b")
        for match in bare_ticker_pattern.finditer(text):
            potential = match.group(1)
            pos = match.start()

            # Skip if already found or reserved
            if potential in tickers:
                continue
            if is_reserved_signal_word(potential):
                continue
            if potential.lower() in EXCLUDED_WORDS:
                continue

            # Validate context
            if has_ticker_context(text, pos, potential):
                # Also verify it's in our known alias map values
                if potential in ALIAS_MAP.values():
                    tickers[potential] = "contextual"

    # Calculate confidence based on extraction sources
    if not tickers:
        confidence = 0.0
    elif all(s == "explicit" for s in tickers.values()):
        confidence = 1.0
    elif any(s == "explicit" for s in tickers.values()):
        confidence = 0.9
    else:
        confidence = 0.7

    return {
        "tickers": list(tickers.keys()),
        "sources": tickers,
        "confidence": confidence,
    }


def validate_llm_tickers(
    llm_tickers: list, candidate_tickers: list, strict: bool = True
) -> tuple:
    """
    Post-validate LLM-extracted tickers against the candidate list.

    This is a guardrail to prevent the LLM from hallucinating tickers
    that weren't in the original message.

    Args:
        llm_tickers: Tickers returned by the LLM parser
        candidate_tickers: Tickers from deterministic extraction
        strict: If True, drop any ticker not in candidates. If False, log warning but keep.

    Returns:
        Tuple of (validated_tickers, dropped_tickers)

    Examples:
        >>> validate_llm_tickers(['AAPL', 'FAKE'], ['AAPL', 'NVDA'])
        (['AAPL'], ['FAKE'])
    """
    if not llm_tickers:
        return [], []

    candidate_set = set(t.upper() for t in candidate_tickers)
    validated = []
    dropped = []

    for ticker in llm_tickers:
        ticker_upper = ticker.upper() if ticker else ""
        if not ticker_upper:
            continue

        if ticker_upper in candidate_set:
            validated.append(ticker_upper)
        elif is_reserved_signal_word(ticker_upper):
            logger.debug(f"LLM returned reserved signal word as ticker: {ticker}")
            dropped.append(ticker_upper)
        elif strict:
            logger.warning(f"LLM hallucinated ticker not in candidates: {ticker}")
            dropped.append(ticker_upper)
        else:
            logger.warning(f"LLM returned ticker not in candidates (keeping): {ticker}")
            validated.append(ticker_upper)

    return validated, dropped


# =============================================================================
# TICKER CONTEXT VALIDATION - Guard against false positives
# =============================================================================

# Action words that typically precede tickers in trading context
TICKER_CONTEXT_WORDS = {
    # Buy actions
    "buy",
    "bought",
    "buying",
    "purchase",
    "purchased",
    "long",
    "longing",
    "add",
    "added",
    "adding",
    "accumulate",
    "accumulated",
    "dca",
    "dcaing",
    "dcad",  # Dollar cost average
    # Sell actions
    "sell",
    "sold",
    "selling",
    "short",
    "shorting",
    "shorted",
    "trim",
    "trimmed",
    "trimming",
    "exit",
    "exited",
    "exiting",
    "dump",
    "dumped",
    "dumping",
    # Hold/watch actions
    "hold",
    "holding",
    "watch",
    "watching",
    "eyeing",
    "tracking",
    "bullish",
    "bearish",
    "neutral",
    # Analysis indicators
    "target",
    "targeting",
    "support",
    "resistance",
    "breakout",
    "entry",
    "stop",
    "stoploss",
}

# Generic words that should NOT be captured as tickers even if they match pattern
# These are common English words that happen to be 1-6 letters
EXCLUDED_WORDS = {
    # Common prepositions/articles
    "a",
    "an",
    "the",
    "to",
    "of",
    "in",
    "on",
    "at",
    "by",
    "for",
    "with",
    # Common verbs/nouns that look like tickers
    "it",
    "is",
    "be",
    "am",
    "are",
    "was",
    "were",
    "go",
    "get",
    "got",
    "me",
    "my",
    "you",
    "your",
    "we",
    "us",
    "he",
    "she",
    "him",
    "her",
    "can",
    "will",
    "may",
    "now",
    "then",
    "here",
    "there",
    # Trading terms that aren't tickers
    "call",
    "calls",
    "put",
    "puts",
    "long",
    "short",
    "buy",
    "sell",
    "up",
    "down",
    "low",
    "high",
    "top",
    "bottom",
    "dip",
    "rip",
    # Common abbreviations that aren't tickers
    "otc",
    "ipo",
    "etf",
    "atm",
    "otm",
    "itm",
    "dte",
    "eod",
    "eow",
    "fomo",
    "yolo",
    "btfd",
    "hodl",
    "moon",
    "pump",
    "dump",
    "ta",
    "dd",
    "er",
    "eps",
    "pe",
    "ps",
    "pb",
    "rsi",
    "macd",
    "sma",
    "ema",
}


def has_ticker_context(text: str, position: int, ticker: str) -> bool:
    """
    Check if a potential ticker at a given position has valid trading context.

    Validates that the ticker either:
    1. Has a $ prefix (explicit ticker format)
    2. Is preceded by a trading action word (buy, sell, etc.)
    3. Is followed by trading terminology (calls, puts, shares, etc.)

    Args:
        text: The full message text
        position: Character position where the potential ticker starts
        ticker: The potential ticker symbol (without $)

    Returns:
        True if the context suggests this is a real ticker mention
    """
    if not text or not ticker:
        return False

    ticker_upper = ticker.upper()

    # Exclude known non-tickers
    if ticker.lower() in EXCLUDED_WORDS:
        return False

    # Check for $ prefix (strongest signal)
    if position > 0 and text[position - 1] == "$":
        return True

    # Get surrounding context (50 chars before and after)
    start = max(0, position - 50)
    end = min(len(text), position + len(ticker) + 50)
    context = text[start:end].lower()

    # Check for action words before the ticker
    words_before = text[start:position].lower().split()
    if words_before:
        last_word = words_before[-1].rstrip(",.!?:;")
        if last_word in TICKER_CONTEXT_WORDS:
            return True

    # Check for trading terminology after the ticker
    words_after_text = text[position + len(ticker) : end].lower().strip()
    trading_suffixes = [
        "calls",
        "puts",
        "shares",
        "stock",
        "options",
        "longs",
        "shorts",
        "position",
        "positions",
    ]
    for suffix in trading_suffixes:
        if words_after_text.startswith(suffix):
            return True

    # Check if ticker is in known alias map (high confidence)
    if ticker.lower() in ALIAS_MAP or ticker_upper in ALIAS_MAP.values():
        return True

    # Default: require $ prefix for unknown tickers
    return False


def enrich_parsed_ideas_with_tickers(ideas: list, original_text: str) -> list:
    """
    Post-processing step to add missing tickers to parsed ideas.

    Applies alias mapping to detect company names that the LLM missed,
    then adds them to the ideas' symbols lists without overwriting existing tickers.

    Args:
        ideas: List of parsed idea dictionaries from the LLM
        original_text: The original message text (pre-mapping)

    Returns:
        The same ideas list with enriched symbol data
    """
    if not ideas or not original_text:
        return ideas

    # Apply alias mapping to get normalized text
    mapped_text = apply_alias_mapping(original_text)

    # Extract all tickers from the mapped text
    all_tickers = set(extract_tickers_from_text(mapped_text))

    if not all_tickers:
        return ideas

    # Enrich each idea with missing tickers
    for idea in ideas:
        existing_symbols = set(idea.get("symbols", []))
        primary = idea.get("primary_symbol")
        if primary:
            existing_symbols.add(primary)

        # Find tickers mentioned in this idea's text segment
        idea_text = idea.get("idea_text", "")
        if idea_text:
            # Apply mapping to the idea's specific text
            mapped_idea = apply_alias_mapping(idea_text)
            idea_tickers = set(extract_tickers_from_text(mapped_idea))

            # Add any missing tickers to the symbols list
            new_tickers = idea_tickers - existing_symbols
            if new_tickers:
                idea["symbols"] = list(existing_symbols | new_tickers)

                # If no primary_symbol, set the first new ticker
                if not primary and new_tickers:
                    idea["primary_symbol"] = sorted(new_tickers)[0]
                    logger.debug(
                        f"Enriched idea with primary_symbol: {idea['primary_symbol']}"
                    )

    return ideas


# =============================================================================
# SHORT ACTION WHITELIST - Valid brief action phrases that can stand alone
# =============================================================================

# Actions that can stand alone as complete ideas even if very short
# These are legitimate execution notes that should NOT be merged with neighbors
SHORT_ACTION_WHITELIST = {
    # Buy actions
    "buy",
    "bought",
    "buying",
    "long",
    "longing",
    # Sell actions
    "sell",
    "sold",
    "selling",
    "short",
    "shorting",
    "shorted",
    # Position management
    "trim",
    "trimmed",
    "trimming",
    "add",
    "added",
    "adding",
    "hedge",
    "hedged",
    "hedging",
    # Exit actions
    "exit",
    "exited",
    "exiting",
    "close",
    "closed",
    "closing",
    "dump",
    "dumped",
    "dumping",
    # Hold/watch (observation, not action)
    "hold",
    "holding",
    "watch",
    "watching",
}

# Minimum length for an idea to be considered "short"
MIN_IDEA_LENGTH = 20


def is_valid_short_action(text: str) -> bool:
    """
    Check if a short text represents a valid standalone action.

    A text is a valid short action if:
    1. It starts with an action verb from SHORT_ACTION_WHITELIST, AND
    2. It contains a ticker symbol ($XXX or in ALIAS_MAP)

    This allows brief trade commands like "Buy AAPL", "Sold $TSLA",
    "Trim nvidia" to stand alone as complete ideas even if under 20 chars.

    Args:
        text: The idea text to check

    Returns:
        True if this is a valid short action that should NOT be merged
    """
    if not text:
        return False

    text_stripped = text.strip()
    text_lower = text_stripped.lower()

    # Check 1: Starts with $TICKER (always valid)
    if text_stripped.startswith("$"):
        return True

    # Check 2: Starts with action verb
    first_word = text_lower.split()[0] if text_lower else ""
    first_word = first_word.rstrip(",.!?:;")  # Remove trailing punctuation

    if first_word not in SHORT_ACTION_WHITELIST:
        return False

    # Check 3: Contains a ticker (either $XXX or company name in ALIAS_MAP)
    # Apply alias mapping and check for tickers
    mapped_text = apply_alias_mapping(text_stripped)
    tickers = extract_tickers_from_text(mapped_text)

    if tickers:
        return True

    # Also check if any word (after the action) is a known ticker in ALIAS_MAP
    words = text_stripped.split()
    for word in words[1:]:  # Skip the action verb
        word_clean = word.strip("$,.!?:;()").upper()
        if word_clean in ALIAS_MAP.values():
            return True
        if word_clean.lower() in ALIAS_MAP:
            return True

    return False


def merge_short_ideas(ideas: list, min_length: int = MIN_IDEA_LENGTH) -> list:
    """
    Merge short idea fragments with adjacent related ideas.

    This post-processing step ensures that fragmentary ideas (under min_length
    characters) are combined with their context to form complete thoughts.

    Merge rules:
    1. Ideas starting with $TICKER or action verbs are NEVER merged (valid standalone)
    2. Short ideas merge with previous idea if same primary_symbol
    3. Short ideas merge with next idea if can't merge with previous
    4. Ideas that can't be safely merged are kept as-is (better than losing data)

    Args:
        ideas: List of parsed idea dictionaries
        min_length: Minimum idea_text length; shorter ideas may be merged

    Returns:
        List of ideas with short fragments merged into neighbors
    """
    if len(ideas) <= 1:
        return ideas

    result = []
    merge_count = 0
    skip_next = False

    for i, idea in enumerate(ideas):
        if skip_next:
            skip_next = False
            continue

        text = idea.get("idea_text", "")

        # Check if this is a valid short action (should NOT be merged)
        if is_valid_short_action(text):
            logger.debug(f"  Preserving valid short action: '{text[:50]}'")
            result.append(idea)
            continue

        # Long enough - keep as-is
        if len(text) >= min_length:
            result.append(idea)
            continue

        # Short idea - try to merge
        logger.debug(f"  Short idea detected: '{text}' ({len(text)} chars)")

        # Try to merge with previous idea (if same symbol or both sector)
        if result:
            prev = result[-1]
            prev_symbol = prev.get("primary_symbol")
            curr_symbol = idea.get("primary_symbol")

            # Merge if same symbol or both are sector/macro (null symbol)
            if prev_symbol == curr_symbol or (
                prev_symbol is None and curr_symbol is None
            ):
                prev["idea_text"] = f"{prev['idea_text']}; {text}"
                # Merge symbols lists
                prev_symbols = set(prev.get("symbols", []))
                curr_symbols = set(idea.get("symbols", []))
                prev["symbols"] = list(prev_symbols | curr_symbols)
                logger.info(f"  ✓ Merged short idea into previous: '{text}'")
                merge_count += 1
                continue

        # Try to merge with next idea
        if i + 1 < len(ideas):
            next_idea = ideas[i + 1]
            next_symbol = next_idea.get("primary_symbol")
            curr_symbol = idea.get("primary_symbol")

            if next_symbol == curr_symbol or (
                next_symbol is None and curr_symbol is None
            ):
                # Prepend to next idea and skip it in next iteration
                next_idea["idea_text"] = f"{text}; {next_idea['idea_text']}"
                # Merge symbols lists
                next_symbols = set(next_idea.get("symbols", []))
                curr_symbols = set(idea.get("symbols", []))
                next_idea["symbols"] = list(next_symbols | curr_symbols)
                logger.info(f"  ✓ Merged short idea into next: '{text}'")
                merge_count += 1
                result.append(next_idea)
                skip_next = True
                continue

        # Can't merge - keep as-is (better than losing data)
        logger.warning(f"  Could not merge short idea: '{text}'")
        result.append(idea)

    if merge_count > 0:
        logger.info(f"  Total merges: {merge_count} short ideas merged")

    return result


# =============================================================================
# PRICE LEVEL EXTRACTION - Lightweight regex-based detection
# =============================================================================

# Patterns to detect price mentions in trading messages
# These are intentionally simple and capture raw values without classification
_PRICE_PATTERNS = [
    # $147, $15.50, $1.76 (dollar sign followed by number, not a ticker like $AAPL)
    # Matches: $147, $15.50, $1.76 but NOT $AAPL (letters after $)
    re.compile(r"\$(\d+(?:\.\d+)?)(?!\w)"),
    # @15, @147.50 (at-sign for entries)
    re.compile(r"@(\d+(?:\.\d+)?)(?!\w)"),
    # 12ish, 150ish (approximate levels)
    re.compile(r"(\d+(?:\.\d+)?)ish\b", re.IGNORECASE),
    # around 15, near 147, above 150, below 12
    re.compile(
        r"\b(?:around|near|above|below|under|over)\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE
    ),
    # hold 150, target 170, aiming for 500 (action + number)
    re.compile(
        r"\b(?:hold|target|targeting|aiming\s+for|looking\s+for)\s+(\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    ),
]

# Range pattern: 93-105, $93-$105
_RANGE_PATTERN = re.compile(r"\$?(\d+(?:\.\d+)?)\s*[-–—]\s*\$?(\d+(?:\.\d+)?)")


def extract_price_mentions(text: str) -> dict:
    """
    Extract price mentions from text using simple regex patterns.

    This is a lightweight, deterministic alternative to LLM-based level extraction.
    Returns raw price values without classification (entry/stop/target).

    Args:
        text: Message text to extract prices from

    Returns:
        Dictionary with:
        - prices: List of unique float values detected
        - ranges: List of (low, high) tuples for range mentions
        - count: Total number of price mentions

    Examples:
        >>> extract_price_mentions("pickup @15 and set stop at $12ish")
        {'prices': [15.0, 12.0], 'ranges': [], 'count': 2}

        >>> extract_price_mentions("consolidation in $93-$105")
        {'prices': [], 'ranges': [(93.0, 105.0)], 'count': 1}

        >>> extract_price_mentions("Bounced off $147, target $170")
        {'prices': [147.0, 170.0], 'ranges': [], 'count': 2}
    """
    if not text:
        return {"prices": [], "ranges": [], "count": 0}

    prices = set()
    ranges = []

    # Extract ranges first (to avoid double-counting range endpoints)
    range_matches = _RANGE_PATTERN.findall(text)
    for low, high in range_matches:
        try:
            low_f, high_f = float(low), float(high)
            if low_f < high_f:  # Valid range
                ranges.append((low_f, high_f))
        except ValueError:
            continue

    # Remove range text to avoid double-matching
    text_no_ranges = _RANGE_PATTERN.sub("", text)

    # Extract individual prices
    for pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(text_no_ranges):
            try:
                value = float(match.group(1))
                # Filter out likely non-prices (very small or suspiciously large)
                if 0.5 <= value <= 100000:
                    prices.add(value)
            except (ValueError, IndexError):
                continue

    # Sort prices for consistent output
    sorted_prices = sorted(prices)

    return {
        "prices": sorted_prices,
        "ranges": ranges,
        "count": len(sorted_prices) + len(ranges),
    }


# Common bot command prefixes used in Discord
# NOTE: "$" is NOT included because $TICKER is a common way to mention stocks
# Messages starting with $AAPL, $TSLA, etc. are trading content, not bot commands
BOT_COMMAND_PREFIXES = ("!", "/", "?", ".", "-", ">>", ";;", "~")

# Ticker pattern to detect stock mentions (e.g., $AAPL, $BRK.B)
TICKER_PATTERN = re.compile(r"^\$[A-Z]{1,6}(?:\.[A-Z]+)?(?:\s|$)", re.IGNORECASE)

# Known bot usernames or patterns (case-insensitive)
BOT_NAME_PATTERNS = [
    r"bot$",
    r"^mee6$",
    r"^dyno$",
    r"^carl-bot$",
    r"^rythm$",
    r"^groovy$",
    r"^dank memer$",
    r"^trading.*bot$",
    r"^stock.*bot$",
]

# Compiled patterns for efficiency
_BOT_NAME_REGEX = [re.compile(p, re.IGNORECASE) for p in BOT_NAME_PATTERNS]


# =============================================================================
# SINGLE-SOURCE-OF-TRUTH: should_skip_message()
# =============================================================================

# This is the CANONICAL prefilter function. All code that writes to
# discord_parsed_ideas MUST use this function (or import it) to ensure
# consistent skip behavior across live parsing and batch processing.

SkipResult = tuple[bool, Optional[str]]  # (should_skip, reason)


def should_skip_message(
    text: str, message_meta: Optional[Dict[str, Any]] = None
) -> SkipResult:
    """
    Single-source-of-truth prefilter for all message parsing.

    This function MUST be used by:
    - openai_parser.process_message()
    - scripts/nlp/parse_messages.py
    - scripts/nlp/build_batch.py

    Any message that passes this check can be sent to LLM parsing.
    Any message that fails should be marked as 'skipped' in parse_status.

    Args:
        text: The raw message content
        message_meta: Optional dict with keys like 'author', 'is_bot', etc.
                     Used to check if message is from a bot user.

    Returns:
        Tuple of (should_skip: bool, reason: Optional[str])
        - (False, None) means message should be parsed
        - (True, "reason") means message should be skipped

    Examples:
        >>> should_skip_message("!help")
        (True, 'bot_command')
        >>> should_skip_message("https://x.com/foo")
        (True, 'url_only')
        >>> should_skip_message("AAPL looking good", {"author": "TradingBot"})
        (True, 'bot_response')
        >>> should_skip_message("AAPL looking good", {"author": "john"})
        (False, None)
    """
    # Check 1: Bot commands (!, /, etc.)
    if is_bot_command(text):
        return (True, "bot_command")

    # Check 2: URL-only messages
    if is_url_only(text):
        return (True, "url_only")

    # Check 3: Bot responses (requires metadata)
    if message_meta and is_bot_response(message_meta):
        return (True, "bot_response")

    # Check 4: Empty or whitespace-only
    if not text or not text.strip():
        return (True, "empty")

    # Passed all checks - message should be parsed
    return (False, None)


def is_bot_command(text: str) -> bool:
    """Check if text appears to be a bot command.

    Args:
        text: The message text to check

    Returns:
        True if the text starts with a common bot command prefix

    Examples:
        >>> is_bot_command("!help")
        True
        >>> is_bot_command("/roll 20")
        True
        >>> is_bot_command("!!chart AAPL")
        True
        >>> is_bot_command("I think AAPL is going up")
        False
    """
    if not text:
        return False

    stripped = text.strip()
    if not stripped:
        return False

    # Check for command prefixes (handles single and multiple prefix chars)
    if stripped.startswith(BOT_COMMAND_PREFIXES):
        # Skip past prefix characters to check if followed by a word
        idx = 0
        while idx < len(stripped) and stripped[idx] in "!/?.->~;":
            idx += 1
        # Must be followed by an alphanumeric character
        if idx < len(stripped) and stripped[idx].isalnum():
            return True

    return False


# URL pattern for detecting URL-only messages
_URL_ONLY_PATTERN = re.compile(
    r"^https?://\S+$",  # Matches http:// or https:// followed by non-whitespace
    re.IGNORECASE,
)


def is_url_only(text: str) -> bool:
    """Check if text is just a URL with no other content.

    URL-only messages cannot be parsed for trading ideas since the parser
    cannot access URL content. These should be filtered before triage to:
    1. Save LLM API calls
    2. Prevent model drift from incorrectly classifying URLs as actionable

    Args:
        text: The message text to check

    Returns:
        True if the text is only a URL (after stripping whitespace)

    Examples:
        >>> is_url_only("https://x.com/user/status/123")
        True
        >>> is_url_only("https://example.com")
        True
        >>> is_url_only("Check this out: https://example.com")
        False
        >>> is_url_only("https://example.com - great chart!")
        False
        >>> is_url_only("I think AAPL is going up")
        False
    """
    if not text:
        return False

    stripped = text.strip()
    if not stripped:
        return False

    # Check if entire message is just a URL
    return bool(_URL_ONLY_PATTERN.match(stripped))


def is_bot_response(row: Dict[str, Any]) -> bool:
    """Check if a message row appears to be from a bot.

    Args:
        row: A dictionary containing message data with 'author' key

    Returns:
        True if the message appears to be from a bot

    Examples:
        >>> is_bot_response({"author": "TradingBot"})
        True
        >>> is_bot_response({"author": "john_trader"})
        False
    """
    if not row:
        return False

    author = row.get("author", "")
    if not author:
        return False

    # Check against known bot patterns
    for pattern in _BOT_NAME_REGEX:
        if pattern.search(author):
            return True

    # Check for common bot indicators in author name
    author_lower = author.lower()
    if "[bot]" in author_lower or "(bot)" in author_lower:
        return True

    return False


def normalize_text(text: str, preserve_tickers: bool = True) -> str:
    """Normalize text for NLP processing.

    Performs the following normalizations:
    - Removes excessive whitespace
    - Normalizes line breaks
    - Removes zero-width characters
    - Optionally preserves $TICKER format
    - Removes Discord-specific formatting (bold, italic, code blocks)
    - Removes URLs
    - Removes user mentions (@user, <@123456>)
    - Removes channel mentions (#channel, <#123456>)
    - Removes role mentions (<@&123456>)
    - Removes emoji codes (:emoji:)
    - Removes custom Discord emojis (<:name:id>)

    Args:
        text: The text to normalize
        preserve_tickers: If True, preserve $TICKER format (default True)

    Returns:
        Normalized text string

    Examples:
        >>> normalize_text("  Hello   World  ")
        'Hello World'
        >>> normalize_text("Check out $AAPL! 🚀")
        'Check out $AAPL!'
    """
    if not text:
        return ""

    result = text

    # Remove zero-width characters
    result = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", result)

    # Remove URLs
    result = re.sub(r"https?://\S+", "", result)

    # Remove Discord mentions (users, channels, roles)
    result = re.sub(r"<@!?\d+>", "", result)  # User mentions
    result = re.sub(r"<#\d+>", "", result)  # Channel mentions
    result = re.sub(r"<@&\d+>", "", result)  # Role mentions

    # Remove custom Discord emojis
    result = re.sub(r"<a?:\w+:\d+>", "", result)

    # Remove standard emoji codes
    result = re.sub(r":\w+:", "", result)

    # Remove Discord formatting (preserve content)
    result = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", result)  # Bold italic
    result = re.sub(r"\*\*(.+?)\*\*", r"\1", result)  # Bold
    result = re.sub(r"\*(.+?)\*", r"\1", result)  # Italic
    result = re.sub(r"__(.+?)__", r"\1", result)  # Underline
    result = re.sub(r"~~(.+?)~~", r"\1", result)  # Strikethrough
    result = re.sub(r"\|\|(.+?)\|\|", r"\1", result)  # Spoiler

    # Remove code block markers but preserve content inside
    # Multi-line: ```python\ncode\n``` -> code (strips backticks and optional language specifier)
    result = re.sub(
        r"```(?:\w*\n)?([\s\S]*?)```", r"\1", result
    )  # Multi-line code blocks
    result = re.sub(r"`(.+?)`", r"\1", result)  # Inline code

    # Normalize line breaks
    result = re.sub(r"\r\n", "\n", result)
    result = re.sub(r"\r", "\n", result)

    # Collapse multiple newlines to single
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Normalize whitespace (preserve single newlines)
    result = re.sub(r"[ \t]+", " ", result)

    # Clean up whitespace around newlines
    result = re.sub(r" *\n *", "\n", result)

    # Strip leading/trailing whitespace
    result = result.strip()

    return result


def extract_meaningful_content(text: str, min_words: int = 3) -> Optional[str]:
    """Extract meaningful content from text, filtering noise.

    Args:
        text: The text to process
        min_words: Minimum word count to consider meaningful

    Returns:
        Cleaned text if meaningful, None otherwise
    """
    if not text:
        return None

    # Normalize first
    cleaned = normalize_text(text)

    # Check word count
    words = cleaned.split()
    if len(words) < min_words:
        return None

    # Check if it's mostly non-alphabetic
    alpha_chars = sum(1 for c in cleaned if c.isalpha())
    if alpha_chars < len(cleaned) * 0.3:  # Less than 30% alphabetic
        return None

    return cleaned


def is_noise_message(text: str) -> bool:
    """Check if a message is likely noise (reactions, short responses, etc.).

    Args:
        text: The message text to check

    Returns:
        True if the message appears to be noise
    """
    if not text:
        return True

    cleaned = normalize_text(text)

    # Empty after cleaning
    if not cleaned:
        return True

    # Very short messages
    if len(cleaned) < 10:
        return True

    # Single emoji or reaction
    if len(cleaned.split()) == 1:
        return True

    # Common noise patterns
    noise_patterns = [
        r"^(lol|lmao|haha|nice|wow|omg|damn|bruh|bro|yep|yeah|yes|no|ok|okay)$",
        r"^[\U0001F600-\U0001F64F]+$",  # Just emojis
        r"^\d+$",  # Just numbers
    ]

    for pattern in noise_patterns:
        if re.match(pattern, cleaned, re.IGNORECASE):
            return True

    return False
