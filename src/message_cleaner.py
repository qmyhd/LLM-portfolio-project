"""
Discord Message Cleaning Module

Centralized module for cleaning Discord messages with ticker extraction,
sentiment analysis, and deduplication. Supports both Parquet and database output.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, Literal

import pandas as pd
from src.nlp.sentiment import sentiment_score


logger = logging.getLogger(__name__)


# Centralized table mapping for channel types
# Note: "general" redirects to trading as the default behavior
CHANNEL_TYPE_TO_TABLE = {
    "general": "discord_trading_clean",  # Redirect to trading (default)
    "trading": "discord_trading_clean",
    "market": "discord_market_clean",
}


def get_table_name_for_channel_type(channel_type: str) -> str:
    """Get the database table name for a given channel type.

    Args:
        channel_type: The type of Discord channel

    Returns:
        Database table name for the channel type

    Raises:
        ValueError: If channel_type is not recognized
    """
    normalized_type = channel_type.lower().strip()

    if normalized_type not in CHANNEL_TYPE_TO_TABLE:
        raise ValueError(
            f"Unknown channel type '{channel_type}'. "
            f"Valid types: {list(CHANNEL_TYPE_TO_TABLE.keys())}"
        )

    return CHANNEL_TYPE_TO_TABLE[normalized_type]


def extract_ticker_symbols(text: str | None) -> List[str]:
    """Extract ticker symbols from text, matching $TICKER format anywhere in the text.

    Args:
        text: The text to extract ticker symbols from

    Returns:
        List of unique ticker symbols in order of appearance

    Examples:
        >>> extract_ticker_symbols("I bought $AAPL and $MSFT!")
        ['$AAPL', '$MSFT']
        >>> extract_ticker_symbols("Check $BRK.B today")
        ['$BRK.B']
    """
    if not text:
        return []

    # Pattern matches $TICKER format with optional class share suffix (.A, .B, etc.)
    # - \$ matches literal dollar sign
    # - [A-Z]{1,6} matches 1-6 uppercase letters (ticker symbol)
    # - (?:\.[A-Z]+)? optionally matches period + uppercase letters (class shares like BRK.B)
    pattern = r"\$[A-Z]{1,6}(?:\.[A-Z]+)?"
    matches = re.findall(
        pattern, text.upper()
    )  # Convert to uppercase for case-insensitive matching

    # Remove duplicates while preserving order
    unique_tickers = []
    for ticker in matches:
        if ticker not in unique_tickers:
            unique_tickers.append(ticker)

    return unique_tickers


def extract_unprefixed_tickers(
    text: str | None, known_tickers: set[str] | None = None
) -> List[str]:
    """Extract bare ticker symbols without $ prefix from trading context.

    Detects tickers mentioned without $ prefix in contexts like "AAPL calls",
    "buying MSFT", "NVDA puts", etc. Requires trading context words nearby
    to reduce false positives.

    Args:
        text: The text to extract ticker symbols from
        known_tickers: Optional set of known valid tickers to match against

    Returns:
        List of unique ticker symbols (without $ prefix) in order of appearance

    Examples:
        >>> extract_unprefixed_tickers("AAPL calls looking good")
        ['AAPL']
        >>> extract_unprefixed_tickers("buying NVDA and MSFT puts")
        ['NVDA', 'MSFT']
    """
    if not text:
        return []

    # Common trading context words that indicate nearby word might be a ticker
    trading_context = {
        "calls",
        "puts",
        "options",
        "shares",
        "stock",
        "stocks",
        "buy",
        "buying",
        "bought",
        "sell",
        "selling",
        "sold",
        "long",
        "short",
        "bullish",
        "bearish",
        "neutral",
        "entry",
        "exit",
        "trim",
        "add",
        "added",
        "trimmed",
        "hold",
        "holding",
        "watch",
        "watching",
        "scalp",
        "scalping",
        "swing",
        "swinging",
        "day",
        "trade",
        "trading",
        "position",
        "target",
        "stop",
        "pt",
        "sl",
        "lotto",
        "lottos",
        "yolo",
        "fd",
        "fds",
        "leaps",
        "weeklies",
        "monthlies",
        "exp",
        "expiry",
        "strike",
        "itm",
        "otm",
        "atm",
        "premium",
        "iv",
        "delta",
        "earnings",
        "er",
        "guidance",
        "beat",
        "miss",
        "eps",
        "revenue",
    }

    # Default known tickers (common large caps) if none provided
    default_tickers = {
        "AAPL",
        "MSFT",
        "GOOG",
        "GOOGL",
        "AMZN",
        "META",
        "NVDA",
        "TSLA",
        "AMD",
        "INTC",
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
        "VIX",
        "UVXY",
        "TQQQ",
        "SQQQ",
        "ARKK",
        "COIN",
        "GME",
        "AMC",
        "PLTR",
        "SOFI",
        "NIO",
        "RIVN",
        "F",
        "GM",
        "BA",
        "JPM",
        "BAC",
        "GS",
        "MS",
        "WFC",
        "C",
        "V",
        "MA",
        "DIS",
        "NFLX",
        "CRM",
        "ORCL",
        "IBM",
        "CSCO",
        "PYPL",
        "SQ",
        "SHOP",
        "ROKU",
        "SNAP",
        "PINS",
        "TWTR",
        "UBER",
        "LYFT",
        "ABNB",
        "DASH",
        "ZM",
        "DOCU",
        "CRWD",
        "NET",
        "DDOG",
        "SNOW",
        "MDB",
        "U",
        "RBLX",
        "HOOD",
        "UPST",
        "AFRM",
        "PATH",
        "OPEN",
        "LCID",
        "FSR",
        "XOM",
        "CVX",
        "OXY",
        "BP",
        "SHEL",
        "COP",
        "SLB",
        "HAL",
        "VLO",
        "MPC",
        "PFE",
        "MRNA",
        "JNJ",
        "ABBV",
        "LLY",
        "UNH",
        "CVS",
        "WMT",
        "TGT",
        "COST",
        "HD",
        "LOW",
        "MCD",
        "SBUX",
        "NKE",
        "LULU",
        "GPS",
        "ANF",
    }

    tickers_to_check = known_tickers if known_tickers else default_tickers

    text_upper = text.upper()
    words = re.findall(r"\b[A-Z]{1,5}\b", text_upper)
    text_lower = text.lower()

    found_tickers = []

    # Check if any trading context words are in the text
    has_trading_context = any(ctx in text_lower for ctx in trading_context)

    if not has_trading_context:
        return []

    for word in words:
        if word in tickers_to_check and word not in found_tickers:
            # Additional check: word should be near a trading context word
            # Find position of word in text
            word_pattern = rf"\b{word}\b"
            match = re.search(word_pattern, text_upper)
            if match:
                # Check surrounding 50 characters for context
                start = max(0, match.start() - 50)
                end = min(len(text_lower), match.end() + 50)
                surrounding = text_lower[start:end]

                if any(ctx in surrounding for ctx in trading_context):
                    found_tickers.append(word)

    return found_tickers


def upsert_symbol_alias(
    ticker: str,
    alias: str,
    source: Literal["discord", "snaptrade", "manual"] = "discord",
) -> bool:
    """
    Upsert a symbol alias to the symbol_aliases table.

    Records ticker variants/aliases for improved symbol resolution.
    Uses ON CONFLICT to avoid duplicates per (alias, source).

    Args:
        ticker: Canonical ticker symbol (e.g., 'AAPL')
        alias: Variant/alias (e.g., '$AAPL', 'Apple', 'apple inc')
        source: Source of the alias - 'discord', 'snaptrade', or 'manual'

    Returns:
        True if successful, False otherwise

    Example:
        >>> upsert_symbol_alias('AAPL', '$AAPL', 'discord')
        True
        >>> upsert_symbol_alias('GOOGL', 'waymo', 'manual')
        True
    """
    if not ticker or not alias:
        return False

    try:
        from src.db import execute_sql

        execute_sql(
            """
            INSERT INTO symbol_aliases (ticker, alias, source, updated_at)
            VALUES (:ticker, :alias, :source, NOW())
            ON CONFLICT (alias, source)
            DO UPDATE SET
                ticker = EXCLUDED.ticker,
                updated_at = NOW()
            """,
            params={
                "ticker": ticker.upper().strip(),
                "alias": alias.strip(),
                "source": source,
            },
        )
        logger.debug(f"Upserted symbol alias: {alias} -> {ticker} ({source})")
        return True

    except Exception as e:
        logger.warning(f"Failed to upsert symbol alias {alias} -> {ticker}: {e}")
        return False


def upsert_ticker_aliases_from_text(
    text: str,
    source: Literal["discord", "snaptrade", "manual"] = "discord",
) -> int:
    """
    Extract tickers from text and upsert their aliases.

    Captures both $TICKER and bare TICKER formats, recording them
    as aliases for the canonical ticker symbol.

    Args:
        text: Text to extract tickers from
        source: Source of the aliases

    Returns:
        Number of aliases upserted

    Example:
        >>> upsert_ticker_aliases_from_text("$AAPL and MSFT looking good", "discord")
        2  # Upserted '$AAPL' -> 'AAPL' and 'MSFT' -> 'MSFT'
    """
    if not text:
        return 0

    count = 0

    # Extract $TICKER format
    prefixed_tickers = extract_ticker_symbols(text)
    for ticker_with_prefix in prefixed_tickers:
        # Extract canonical ticker (remove $ prefix)
        canonical = ticker_with_prefix.lstrip("$").upper()
        # Record both the prefixed version and canonical
        if upsert_symbol_alias(canonical, ticker_with_prefix, source):
            count += 1

    # Extract unprefixed tickers (bare symbols in trading context)
    unprefixed = extract_unprefixed_tickers(text)
    for ticker in unprefixed:
        canonical = ticker.upper()
        if upsert_symbol_alias(canonical, ticker, source):
            count += 1

    return count


def parse_trading_intent(text: str | None) -> Dict[str, Any]:
    """Parse trading intent from message text.

    Analyzes message to extract trading direction, stance, timeframe,
    confidence level, and whether rationale is provided.

    Args:
        text: Message text to analyze

    Returns:
        Dict with keys:
            - direction: "bullish", "bearish", or "neutral"
            - stance: "enter", "add", "trim", "exit", "watch", or None
            - timeframe: "scalp", "day", "swing", "long_term", or None
            - confidence: "high", "medium", "low", or None
            - has_rationale: bool indicating if reasoning is provided

    Examples:
        >>> parse_trading_intent("Very bullish on AAPL, adding more calls")
        {'direction': 'bullish', 'stance': 'add', 'timeframe': None, ...}
    """
    result: Dict[str, Any] = {
        "direction": "neutral",
        "stance": None,
        "timeframe": None,
        "confidence": None,
        "has_rationale": False,
    }

    if not text:
        return result

    text_lower = text.lower()

    # Direction indicators
    bullish_words = {
        "bullish",
        "bull",
        "long",
        "calls",
        "call",
        "buy",
        "buying",
        "bought",
        "moon",
        "mooning",
        "rocket",
        "rip",
        "ripping",
        "breakout",
        "breaking out",
        "green",
        "pump",
        "pumping",
        "up",
        "higher",
        "upside",
        "rally",
        "rallying",
        "bounce",
        "bouncing",
        "support",
        "holding",
        "accumulate",
        "accumulating",
        "bid",
        "bids",
        "demand",
        "strong",
        "strength",
        "bottom",
        "bottoming",
    }
    bearish_words = {
        "bearish",
        "bear",
        "short",
        "puts",
        "put",
        "sell",
        "selling",
        "sold",
        "dump",
        "dumping",
        "drill",
        "drilling",
        "crash",
        "crashing",
        "tank",
        "tanking",
        "red",
        "down",
        "lower",
        "downside",
        "fade",
        "fading",
        "breakdown",
        "breaking down",
        "resistance",
        "weak",
        "weakness",
        "top",
        "topping",
        "distribution",
        "distributing",
        "ask",
        "asks",
        "supply",
    }

    bull_count = sum(1 for w in bullish_words if w in text_lower)
    bear_count = sum(1 for w in bearish_words if w in text_lower)

    if bull_count > bear_count:
        result["direction"] = "bullish"
    elif bear_count > bull_count:
        result["direction"] = "bearish"

    # Stance indicators
    stance_patterns = {
        "enter": [r"\benter", r"\bopening", r"\bnew position", r"\binitiat"],
        "add": [r"\badd", r"\badding", r"\baverage", r"\bscaling in"],
        "trim": [
            r"\btrim",
            r"\btrimming",
            r"\btaking profit",
            r"\breduc",
            r"\bscaling out",
        ],
        "exit": [r"\bexit", r"\bclos", r"\bsold all", r"\bout of", r"\bflat\b"],
        "watch": [r"\bwatch", r"\beye", r"\bmonitor", r"\bwaiting", r"\bsideline"],
    }

    for stance, patterns in stance_patterns.items():
        if any(re.search(p, text_lower) for p in patterns):
            result["stance"] = stance
            break

    # Timeframe indicators
    timeframe_patterns = {
        "scalp": [r"\bscalp", r"\bquick", r"\bin.{0,10}out", r"\bfast\b"],
        "day": [
            r"\bday\s*trade",
            r"\bintraday",
            r"\btoday",
            r"\b0dte",
            r"\bsame.{0,5}day",
        ],
        "swing": [r"\bswing", r"\bfew days", r"\bweek", r"\bhold.{0,10}days"],
        "long_term": [
            r"\blong.{0,5}term",
            r"\binvest",
            r"\bleaps",
            r"\bmonths",
            r"\byears",
        ],
    }

    for timeframe, patterns in timeframe_patterns.items():
        if any(re.search(p, text_lower) for p in patterns):
            result["timeframe"] = timeframe
            break

    # Confidence indicators
    high_confidence = [
        r"\bvery\b",
        r"\bextremely",
        r"\bsuper\b",
        r"\bconfident",
        r"\bconviction",
        r"\ball.?in",
        r"\byolo",
        r"\bslam",
        r"\bload",
        r"\bheavy",
        r"\bmax\b",
    ]
    low_confidence = [
        r"\bmaybe",
        r"\bmight",
        r"\bcould",
        r"\bpossibly",
        r"\bnot sure",
        r"\bsmall\b",
        r"\btiny",
        r"\blotto",
        r"\bgamble",
        r"\brisky",
    ]

    high_count = sum(1 for p in high_confidence if re.search(p, text_lower))
    low_count = sum(1 for p in low_confidence if re.search(p, text_lower))

    if high_count > low_count:
        result["confidence"] = "high"
    elif low_count > high_count:
        result["confidence"] = "low"
    elif high_count > 0 or low_count > 0:
        result["confidence"] = "medium"

    # Rationale detection (looking for "because", "since", reasoning patterns)
    rationale_patterns = [
        r"\bbecause\b",
        r"\bsince\b",
        r"\bdue to\b",
        r"\btherefore\b",
        r"\bthink\s+that",
        r"\bbelieve\b",
        r"\bexpect",
        r"\blooking\s+at",
        r"\bbased\s+on",
        r"\bgiven\b",
        r"\bconsidering",
        r"\breason",
        r"\btechnical",
        r"\bfundamental",
        r"\bchart",
        r"\bpattern",
        r"\bsupport\s+at",
        r"\bresistance\s+at",
        r"\bbreaking\b",
    ]

    result["has_rationale"] = any(re.search(p, text_lower) for p in rationale_patterns)

    return result


def clean_text(text: str) -> str:
    """Clean and normalize text content.

    Args:
        text: Raw text content to clean

    Returns:
        Cleaned text with URLs, mentions, markdown, and extra whitespace removed
    """
    if not isinstance(text, str):
        return ""

    # Remove URLs
    # Note: dash is escaped (\-) to prevent [$-_] being interpreted as a character range
    text = re.sub(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$\-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
        "",
        text,
    )

    # Remove Discord mentions and channels
    text = re.sub(r"<@!?\d+>", "", text)
    text = re.sub(r"<#\d+>", "", text)

    # Remove markdown formatting while preserving the text content
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # Italic: *text* or _text_
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    # Inline code: `text`
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Code blocks: ```text```
    text = re.sub(r"```[\s\S]*?```", "", text)

    # Remove extra whitespace but preserve question/exclamation marks
    text = " ".join(text.split())

    return text.strip()


def calculate_sentiment(text: str) -> float:
    """Calculate sentiment score for text.

    Args:
        text: Text to analyze sentiment for

    Returns:
        Sentiment polarity score (-1.0 to 1.0)
    """
    if not isinstance(text, str) or not text.strip():
        return 0.0

    try:
        return sentiment_score(text)
    except Exception as e:
        logger.warning(f"Error calculating sentiment for text '{text[:50]}...': {e}")
        return 0.0


def extract_tweet_urls(text: str) -> List[str]:
    """Extract Twitter/X URLs from text.

    Args:
        text: Text containing potential tweet URLs

    Returns:
        List of found tweet URLs
    """
    if not isinstance(text, str):
        return []

    # Pattern for Twitter/X URLs
    twitter_pattern = r"https?://(?:twitter\.com|x\.com)/\w+/status/\d+"
    urls = re.findall(twitter_pattern, text)
    return urls


def clean_messages(
    messages: Union[pd.DataFrame, List[Dict[str, Any]]],
    channel_type: str = "trading",
    deduplication_key: str = "message_id",
) -> pd.DataFrame:
    """Clean a list or DataFrame of Discord messages.

    Args:
        messages: Raw messages as DataFrame or list of dicts
        channel_type: Type of channel ("trading" or "market", default: "trading") for specialized processing
        deduplication_key: Column name to use for deduplication

    Returns:
        Cleaned DataFrame with standardized columns
    """
    # ========== SCHEMA NORMALIZATION (PRE-PROCESSING) ==========
    # If input is a list of dicts, normalize each dict's schema BEFORE creating DataFrame
    if isinstance(messages, list):
        normalized_messages = []
        for msg in messages:
            normalized_msg = msg.copy()

            # Map alternate column names
            if "message_id" not in normalized_msg and "id" in normalized_msg:
                normalized_msg["message_id"] = normalized_msg["id"]

            if "author" not in normalized_msg and "author_name" in normalized_msg:
                normalized_msg["author"] = normalized_msg["author_name"]

            if "created_at" not in normalized_msg and "timestamp" in normalized_msg:
                normalized_msg["created_at"] = normalized_msg["timestamp"]

            # Fill missing required fields with defaults
            if "message_id" not in normalized_msg:
                # Generate unique ID from content hash or timestamp
                import hashlib

                content_str = str(normalized_msg.get("content", "")) + str(
                    pd.Timestamp.now(tz="UTC")
                )
                normalized_msg["message_id"] = hashlib.md5(
                    content_str.encode()
                ).hexdigest()[:16]

            if "author" not in normalized_msg:
                normalized_msg["author"] = "system"

            if "channel" not in normalized_msg:
                normalized_msg["channel"] = "unknown"

            if "created_at" not in normalized_msg:
                normalized_msg["created_at"] = pd.Timestamp.now(tz="UTC")

            if "content" not in normalized_msg:
                normalized_msg["content"] = ""

            # Serialize non-scalar attachments
            if "attachments" in normalized_msg:
                val = normalized_msg["attachments"]
                if val is not None and isinstance(val, (list, dict)):
                    try:
                        normalized_msg["attachments"] = json.dumps(val)
                    except (TypeError, ValueError):
                        normalized_msg["attachments"] = str(val)

            normalized_messages.append(normalized_msg)

        df = pd.DataFrame(normalized_messages)
        logger.info("Normalized schema for list of message dicts")
    else:
        df = messages.copy()

    if df.empty:
        logger.info("No messages to clean")
        return pd.DataFrame()

    logger.info(f"Starting to clean {len(df)} messages for {channel_type} channel")

    # ========== SCHEMA NORMALIZATION (POST-DATAFRAME) ==========
    # Handle DataFrames that may have alternate column names
    if "message_id" not in df.columns and "id" in df.columns:
        df["message_id"] = df["id"]
        logger.info("Mapped 'id' column to 'message_id'")

    if "author" not in df.columns and "author_name" in df.columns:
        df["author"] = df["author_name"]
        logger.info("Mapped 'author_name' column to 'author'")

    if "created_at" not in df.columns and "timestamp" in df.columns:
        df["created_at"] = df["timestamp"]
        logger.info("Mapped 'timestamp' column to 'created_at'")

    # ========== HANDLE NON-SCALAR ATTACHMENTS ==========
    # Convert list/dict attachments to JSON strings for database compatibility
    if "attachments" in df.columns:

        def serialize_attachments(val):
            if val is None or (isinstance(val, str) and not val):
                return None
            if isinstance(val, (list, dict)):
                try:
                    return json.dumps(val)
                except (TypeError, ValueError) as e:
                    logger.warning(f"Error serializing attachments: {e}")
                    return str(val)
            return val

        df["attachments"] = df["attachments"].apply(serialize_attachments)
        logger.info("Serialized non-scalar attachments to JSON strings")

    # ========== GRACEFUL REQUIRED COLUMN HANDLING ==========
    # Check for required columns and fill with safe defaults if missing
    required_columns = ["message_id", "content", "author", "channel", "created_at"]
    missing_columns = [col for col in required_columns if col not in df.columns]

    if missing_columns:
        logger.warning(
            f"Missing required columns: {missing_columns}. Filling with defaults."
        )

        # Fill missing columns with safe defaults
        for col in missing_columns:
            if col == "message_id":
                # Generate unique IDs if missing (use index + timestamp)
                df[col] = (
                    df.index.astype(str)
                    + "_"
                    + pd.Timestamp.now(tz="UTC").strftime("%Y%m%d%H%M%S")
                )
                logger.warning("Generated placeholder message_id values")
            elif col == "content":
                df[col] = ""
                logger.warning("Set missing content to empty string")
            elif col == "author":
                df[col] = "system"
                logger.warning("Set missing author to 'system'")
            elif col == "channel":
                df[col] = "unknown"
                logger.warning("Set missing channel to 'unknown'")
            elif col == "created_at":
                df[col] = pd.Timestamp.now(tz="UTC")
                logger.warning("Set missing created_at to current timestamp")

        # If we have no valid data after filling, return empty DataFrame
        if df.empty or (df["content"].fillna("").str.strip() == "").all():
            logger.warning(
                "No valid message content after schema normalization. Returning empty DataFrame."
            )
            return pd.DataFrame()

    # Track extra columns that should be preserved (like attachments, is_reply, reply_to_id)
    extra_columns_to_preserve = [
        "attachments",
        "is_reply",
        "reply_to_id",
        "mentions",
        "reactions",
    ]
    present_extra_columns = [
        col for col in extra_columns_to_preserve if col in df.columns
    ]

    # ========== DEDUPLICATION (WITHIN-BATCH) ==========
    # Remove duplicate message_ids within the current batch
    # This handles edge cases where the same message appears multiple times in input
    # Primary deduplication happens at insert time (discord_messages has unique constraint)
    # This is a secondary safety measure for the cleaning pipeline
    original_count = len(df)
    df = df.drop_duplicates(subset=[deduplication_key]).copy()
    if len(df) < original_count:
        logger.info(
            f"Removed {original_count - len(df)} duplicate messages within batch "
            f"(duplicate {deduplication_key} values)"
        )

    # Parse timestamp
    if "timestamp" not in df.columns and "created_at" in df.columns:
        df["timestamp"] = df["created_at"]

    try:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    except Exception as e:
        logger.warning(f"Error parsing timestamps: {e}")
        df["timestamp"] = pd.Timestamp.now(tz="UTC")

    # Text cleaning
    df["cleaned_content"] = df["content"].fillna("").astype(str).apply(clean_text)

    # Sentiment analysis
    df["sentiment"] = df["cleaned_content"].apply(calculate_sentiment)

    # Ticker symbol extraction
    df["tickers"] = df["content"].fillna("").astype(str).apply(extract_ticker_symbols)
    df["tickers_str"] = df["tickers"].apply(lambda x: ", ".join(x) if x else "")

    # Tweet URL extraction
    df["tweet_urls"] = df["content"].fillna("").astype(str).apply(extract_tweet_urls)
    df["tweet_urls_str"] = df["tweet_urls"].apply(lambda x: ", ".join(x) if x else "")

    # Additional features
    df["char_len"] = df["content"].fillna("").astype(str).str.len()
    df["word_len"] = df["content"].fillna("").astype(str).str.split().str.len()
    df["is_command"] = (
        df["content"].fillna("").astype(str).str.startswith("!", na=False)
    )

    # Channel-specific processing
    if channel_type.lower() == "trading":
        # Additional trading-specific features could go here
        df["has_tickers"] = df["tickers"].apply(lambda x: len(x) > 0)
        df["ticker_count"] = df["tickers"].apply(len)

    # Sort by timestamp - ensure DataFrame return
    df = df.sort_values("timestamp").copy()

    # Standardize column names for output
    standard_columns = [
        "message_id",
        "timestamp",
        "channel",
        "author",
        "content",
        "cleaned_content",
        "sentiment",
        "tickers",
        "tickers_str",
        "tweet_urls",
        "tweet_urls_str",
        "char_len",
        "word_len",
        "is_command",
    ]

    # Add trading-specific columns if applicable
    if channel_type.lower() == "trading":
        standard_columns.extend(["has_tickers", "ticker_count"])

    # ========== PRESERVE EXTRA COLUMNS ==========
    # Add any extra columns that were present in the input (attachments, is_reply, etc.)
    for extra_col in present_extra_columns:
        if extra_col not in standard_columns and extra_col in df.columns:
            standard_columns.append(extra_col)
            logger.debug(f"Preserving extra column: {extra_col}")

    # Only keep columns that exist - ensure DataFrame return
    available_columns = [col for col in standard_columns if col in df.columns]

    # Ensure we always return a DataFrame, never a Series
    if available_columns:
        # Use double brackets to ensure DataFrame return even with single column
        result_df = df[available_columns].copy()
    else:
        # If no columns available, return empty DataFrame with proper structure
        result_df = pd.DataFrame()

    # Final safeguard: ensure we're returning a DataFrame
    if not isinstance(result_df, pd.DataFrame):
        logger.warning("Converting non-DataFrame result to DataFrame")
        result_df = pd.DataFrame(result_df)

    logger.info(f"Successfully cleaned {len(result_df)} messages")
    return result_df


def save_to_parquet(
    df: pd.DataFrame,
    file_path: Union[str, Path],
    compression: Literal["snappy", "gzip", "brotli", "lz4", "zstd"] = "snappy",
) -> bool:
    """Save cleaned DataFrame to Parquet file.

    Args:
        df: Cleaned DataFrame to save
        file_path: Path to save the Parquet file
        compression: Compression method to use

    Returns:
        True if successful, False otherwise
    """
    try:
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        df.to_parquet(file_path, compression=compression, index=False)
        logger.info(f"Saved {len(df)} messages to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving to Parquet: {e}")
        return False


def append_to_parquet(
    df: pd.DataFrame,
    file_path: Union[str, Path],
    compression: Literal["snappy", "gzip", "brotli", "lz4", "zstd"] = "snappy",
    deduplication_key: str = "message_id",
) -> bool:
    """Append cleaned DataFrame to existing Parquet file with deduplication.

    Args:
        df: New DataFrame to append
        file_path: Path to existing Parquet file
        compression: Compression method to use
        deduplication_key: Column to use for deduplication

    Returns:
        True if successful, False otherwise
    """
    try:
        file_path = Path(file_path)

        if file_path.exists():
            # Load existing data
            existing_df = pd.read_parquet(file_path)
            # Combine and deduplicate
            combined_df = pd.concat([existing_df, df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(
                subset=[deduplication_key], keep="last"
            )
            combined_df = (
                combined_df.sort_values("timestamp")
                if "timestamp" in combined_df.columns
                else combined_df
            )
        else:
            combined_df = df

        return save_to_parquet(combined_df, file_path, compression)
    except Exception as e:
        logger.error(f"Error appending to Parquet: {e}")
        return False


def save_to_database(
    df: pd.DataFrame,
    table_name: str,
    connection,
    if_exists: Literal["append", "replace", "fail"] = "append",
) -> bool:
    """Save cleaned DataFrame to database table using psycopg named parameters.

    Args:
        df: Cleaned DataFrame to save
        table_name: Name of the database table
        connection: Database connection object (currently unused - execute_sql manages its own)
        if_exists: How to behave if table exists ('append', 'replace', 'fail')

    Returns:
        True if successful, False otherwise

    Note:
        The connection parameter is currently unused because execute_sql() manages
        its own transactions via engine.begin(). It's kept for API compatibility
        and potential future use with connection pooling optimizations.

    Table-specific column mappings:
        - discord_trading_clean: has 'stock_mentions' column for tickers
        - discord_market_clean: does NOT have 'stock_mentions' column
    """
    try:
        # Prepare DataFrame for database insertion
        db_df = df.copy()

        # Column mapping depends on table type
        # discord_trading_clean has stock_mentions, discord_market_clean does not
        is_trading_table = table_name == "discord_trading_clean"

        # Filter for trading channel: Only allow specific author
        if is_trading_table:
            # Filter rows where author is 'qmy.y' (ID: 419660638881579028)
            # We use the username as it's readily available in the DataFrame
            if "author" in db_df.columns:
                original_count = len(db_df)
                db_df = db_df[db_df["author"] == "qmy.y"]
                if len(db_df) < original_count:
                    logger.info(
                        f"Filtered {original_count - len(db_df)} messages from other authors for {table_name}"
                    )

                if db_df.empty:
                    logger.info(
                        f"No messages from author 'qmy.y' to insert into {table_name}"
                    )
                    return True

        # Define valid columns for each table (matching actual DB schema)
        VALID_COLUMNS_MARKET = {
            "message_id",
            "author",
            "content",
            "sentiment",
            "cleaned_content",
            "timestamp",
        }
        VALID_COLUMNS_TRADING = {
            "message_id",
            "author",
            "content",
            "sentiment",
            "cleaned_content",
            "stock_mentions",
            "timestamp",
        }

        # Column renaming
        if is_trading_table:
            # For trading table: rename tickers_str to stock_mentions
            if "tickers_str" in db_df.columns:
                db_df = db_df.rename(columns={"tickers_str": "stock_mentions"})
            valid_columns = VALID_COLUMNS_TRADING
        else:
            valid_columns = VALID_COLUMNS_MARKET

        # Filter to only valid columns that exist in both DataFrame and DB schema
        available_valid = [col for col in db_df.columns if col in valid_columns]

        if not available_valid:
            logger.error(
                f"No valid columns to insert into {table_name}. "
                f"DataFrame has: {list(db_df.columns)}, "
                f"Valid columns are: {valid_columns}"
            )
            return False

        db_df = db_df[available_valid].copy()

        # Ensure timestamp is properly formatted as string for consistency
        if "timestamp" in db_df.columns:
            # Convert timestamp column to string format safely
            try:
                db_df["timestamp"] = db_df["timestamp"].apply(
                    lambda x: (
                        pd.to_datetime(x, errors="coerce").strftime("%Y-%m-%d %H:%M:%S")
                        if pd.notna(pd.to_datetime(x, errors="coerce"))
                        else str(x)
                    )
                )
            except Exception:
                # Fallback: keep as string if conversion fails
                db_df["timestamp"] = db_df["timestamp"].astype(str)

        # Use proper psycopg named parameters for PostgreSQL
        from src.db import execute_sql

        # Build column list for INSERT statement with named placeholders
        columns = list(db_df.columns)
        columns_str = ", ".join(columns)
        placeholders = ", ".join([f":{col}" for col in columns])

        # Build INSERT with ON CONFLICT for idempotency
        if table_name in ["discord_market_clean", "discord_trading_clean"]:
            insert_sql = f"""
            INSERT INTO {table_name} ({columns_str})
            VALUES ({placeholders})
            ON CONFLICT (message_id) DO UPDATE SET
                {", ".join([f"{col} = EXCLUDED.{col}" for col in columns if col != "message_id"])}
            """
        else:
            insert_sql = f"""
            INSERT INTO {table_name} ({columns_str})
            VALUES ({placeholders})
            ON CONFLICT DO NOTHING
            """

        # Execute bulk insert using named parameters
        records = db_df.to_dict("records")
        execute_sql(insert_sql, records)

        logger.info(f"Saved {len(db_df)} messages to database table {table_name}")
        return True
    except Exception as e:
        logger.error(f"Error saving to database: {e}")
        return False


def process_messages_for_channel(
    messages: Union[pd.DataFrame, List[Dict[str, Any]]],
    channel_name: str,
    channel_type: str = "trading",
    output_dir: Optional[Union[str, Path]] = None,
    database_connection=None,
    save_parquet: bool = True,
    save_database: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Complete processing pipeline for Discord messages.

    Args:
        messages: Raw messages to process
        channel_name: Name of the Discord channel
        channel_type: Type of channel ("trading" or "market", default: "trading")
        output_dir: Directory to save Parquet files
        database_connection: Database connection (currently unused - kept for API compatibility)
        save_parquet: Whether to save to Parquet file
        save_database: Whether to save to database

    Returns:
        Tuple of (cleaned DataFrame, processing stats)
    """
    start_time = datetime.now()

    # Clean the messages
    cleaned_df = clean_messages(messages, channel_type)

    if cleaned_df.empty:
        return cleaned_df, {
            "success": True,
            "channel": channel_name,
            "processed_count": 0,
            "message": "No messages to process",
        }

    success_flags = {"parquet": True, "database": True}

    # Save to Parquet if requested
    if save_parquet and output_dir:
        output_dir = Path(output_dir)
        parquet_file = output_dir / f"discord_msgs_clean_{channel_name}.parquet"
        success_flags["parquet"] = append_to_parquet(cleaned_df, parquet_file)

    # Save to database if requested
    if save_database and database_connection:
        # Use centralized table mapping
        table_name = get_table_name_for_channel_type(channel_type)
        success_flags["database"] = save_to_database(
            cleaned_df, table_name, database_connection
        )

    processing_time = datetime.now() - start_time

    stats = {
        "success": all(success_flags.values()),
        "channel": channel_name,
        "channel_type": channel_type,
        "processed_count": len(cleaned_df),
        "processing_time_seconds": processing_time.total_seconds(),
        "parquet_saved": success_flags["parquet"],
        "database_saved": success_flags["database"],
        "avg_sentiment": cleaned_df["sentiment"].mean() if len(cleaned_df) > 0 else 0.0,
        "total_tickers": sum(len(tickers) for tickers in cleaned_df["tickers"]),
        "unique_tickers": len(
            set(ticker for tickers in cleaned_df["tickers"] for ticker in tickers)
        ),
    }

    logger.info(f"Processing complete for {channel_name}: {stats}")
    return cleaned_df, stats


if __name__ == "__main__":
    # Example usage and testing
    logging.basicConfig(level=logging.INFO)

    # Test with sample data
    sample_messages = [
        {
            "message_id": "1",
            "content": "Just bought $AAPL and $MSFT! 🚀",
            "author": "trader1",
            "channel": "trading",
            "created_at": "2025-09-19T10:00:00Z",
        },
        {
            "message_id": "2",
            "content": "Check out this tweet: https://twitter.com/user/status/123456",
            "author": "user2",
            "channel": "general",
            "created_at": "2025-09-19T11:00:00Z",
        },
    ]

    cleaned_df = clean_messages(sample_messages, "trading")
    print(f"Cleaned {len(cleaned_df)} messages")
    print(
        cleaned_df[["message_id", "cleaned_content", "sentiment", "tickers_str"]].head()
    )
