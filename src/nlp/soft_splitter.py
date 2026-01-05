"""
Soft Splitter - Deterministic pre-split before LLM parsing.

This module provides Stage 1 of the two-stage splitting strategy:
1. Soft Split (this module): Cheap deterministic splitting
2. Semantic Split (LLM): One call per soft chunk returns ideas[]

The goal is to minimize LLM costs by:
- Sending short/medium messages as-is (no splitting below 1500 chars)
- Splitting long messages at natural boundaries
- Splitting multi-stock messages at ticker blocks
- Consolidating tiny chunks back together

CALL POLICY ALIGNMENT:
- Messages under 1500 chars: Send as single chunk (1 triage + 1 parse = 2 calls)
- Messages 1500-4000 chars: Split by sections, consolidate tiny chunks
- Messages over 4000 chars: Route to long-context model (1 parse = 1 call)
"""

import re
import logging
from typing import List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Thresholds for splitting decisions
# INCREASED: Previously 500, now 2500 to reduce chunk explosion
# A 2000-char message (~500 tokens) can easily be processed as a single chunk
SHORT_MESSAGE_THRESHOLD = 2500  # Characters - send as-is (prevents call explosion)
LONG_CHUNK_THRESHOLD = 3000  # Characters - consider ticker block split
MAX_CHUNK_SIZE = 4000  # Characters - hard limit per chunk (~1000 tokens)

# Minimum chunk size - chunks smaller than this should be consolidated
MIN_CHUNK_SIZE = 200  # Characters - tiny chunks get merged with neighbors

# Ticker pattern (matches $AAPL, $BRK.B, etc.)
TICKER_PATTERN = re.compile(r"\$([A-Z]{1,6}(?:\.[A-Z]+)?)", re.IGNORECASE)

# Section separator patterns (in order of preference)
SECTION_SEPARATORS = [
    r"\n\s*\n",  # Blank lines
    r"\n[-─═*]{3,}\n",  # Horizontal rules
    r"\n(?=\d+[.)]\s)",  # Numbered lists
    r"\n(?=[•●○◦▪▸]\s)",  # Bullet points
    r"\n(?=[-*+]\s)",  # Markdown lists
    r"\n(?=[A-Z]{2,}:)",  # Headers like "SUMMARY:", "TRADES:"
]


@dataclass
class SoftChunk:
    """A chunk produced by soft splitting."""

    text: str
    start_offset: int  # Character offset in original
    end_offset: int
    chunk_type: str  # 'full', 'section', 'ticker_block', 'hard_split'
    detected_tickers: List[str]  # Tickers found in this chunk


def extract_tickers(text: str) -> List[str]:
    """Extract all ticker symbols from text.

    Args:
        text: Message text to scan

    Returns:
        List of unique ticker symbols (uppercase, without $)
    """
    matches = TICKER_PATTERN.findall(text)
    # Deduplicate while preserving order
    seen = set()
    result = []
    for ticker in matches:
        upper = ticker.upper()
        if upper not in seen:
            seen.add(upper)
            result.append(upper)
    return result


def split_by_sections(text: str) -> List[Tuple[str, int, int]]:
    """Split text by structural elements (blank lines, bullets, etc.).

    Args:
        text: Message text to split

    Returns:
        List of (chunk_text, start_offset, end_offset) tuples
    """
    # Try each separator pattern in order
    for pattern in SECTION_SEPARATORS:
        parts = re.split(pattern, text)
        if len(parts) > 1:
            # Reconstruct with offsets
            chunks = []
            offset = 0
            for part in parts:
                part_stripped = part.strip()
                if part_stripped:  # Skip empty parts
                    start = text.find(part_stripped, offset)
                    end = start + len(part_stripped)
                    chunks.append((part_stripped, start, end))
                    offset = end
            if chunks:
                return chunks

    # No splitting happened - return as single chunk
    return [(text.strip(), 0, len(text))]


def split_by_ticker_blocks(text: str) -> List[Tuple[str, int, int, List[str]]]:
    """Split text by ticker mention patterns.

    Looks for patterns like:
    - "$AAPL: some analysis..." → split before new ticker
    - "NVDA - more analysis..." → split at ticker transitions

    Args:
        text: Message text to split

    Returns:
        List of (chunk_text, start_offset, end_offset, tickers) tuples
    """
    # Pattern for ticker at start of line/section
    ticker_start_pattern = re.compile(
        r"(?:^|\n)\s*\$?([A-Z]{1,6}(?:\.[A-Z]+)?)\s*[-:—]\s*",
        re.IGNORECASE | re.MULTILINE,
    )

    matches = list(ticker_start_pattern.finditer(text))

    if len(matches) < 2:
        # Not enough ticker blocks to split
        tickers = extract_tickers(text)
        return [(text.strip(), 0, len(text), tickers)]

    # Build chunks between ticker starts
    chunks = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunk_tickers = extract_tickers(chunk_text)
            chunks.append((chunk_text, start, end, chunk_tickers))

    return chunks if chunks else [(text.strip(), 0, len(text), extract_tickers(text))]


def hard_split(text: str, max_size: int = MAX_CHUNK_SIZE) -> List[Tuple[str, int, int]]:
    """Emergency split for very long chunks.

    Tries to split at sentence boundaries, falls back to word boundaries.

    Args:
        text: Text to split
        max_size: Maximum chunk size in characters

    Returns:
        List of (chunk_text, start_offset, end_offset) tuples
    """
    if len(text) <= max_size:
        return [(text, 0, len(text))]

    chunks = []
    offset = 0

    while offset < len(text):
        end = min(offset + max_size, len(text))

        if end < len(text):
            # Find a good break point (sentence end or word boundary)
            segment = text[offset:end]

            # Try sentence boundary
            for marker in [". ", "! ", "? ", "\n"]:
                last_sent = segment.rfind(marker)
                if last_sent > max_size // 2:  # At least half-way through
                    end = offset + last_sent + 1
                    break
            else:
                # Fall back to word boundary
                last_space = segment.rfind(" ")
                if last_space > max_size // 2:
                    end = offset + last_space

        chunk_text = text[offset:end].strip()
        if chunk_text:
            chunks.append((chunk_text, offset, end))
        offset = end

    return chunks


def consolidate_small_chunks(
    chunks: List[SoftChunk],
    min_size: int = MIN_CHUNK_SIZE,
    max_size: int = MAX_CHUNK_SIZE,
) -> List[SoftChunk]:
    """
    Consolidate tiny chunks back together to reduce API calls.

    Merges adjacent chunks that are smaller than min_size, as long as
    the combined chunk doesn't exceed max_size.

    Args:
        chunks: List of SoftChunk objects to consolidate
        min_size: Minimum desirable chunk size (default: MIN_CHUNK_SIZE)
        max_size: Maximum chunk size after consolidation (default: MAX_CHUNK_SIZE)

    Returns:
        Consolidated list of SoftChunk objects
    """
    if len(chunks) <= 1:
        return chunks

    consolidated = []
    i = 0

    while i < len(chunks):
        current = chunks[i]

        # If current chunk is already large enough, keep it as-is
        if len(current.text) >= min_size:
            consolidated.append(current)
            i += 1
            continue

        # Current chunk is small - try to merge with neighbors
        merged_text = current.text
        merged_start = current.start_offset
        merged_end = current.end_offset
        merged_tickers = set(current.detected_tickers)
        j = i + 1

        # Merge with subsequent small chunks until we hit min_size or max_size
        while j < len(chunks) and len(merged_text) < min_size:
            next_chunk = chunks[j]
            combined_len = (
                len(merged_text) + len(next_chunk.text) + 2
            )  # +2 for separator

            if combined_len > max_size:
                break  # Would exceed max size

            # Merge
            merged_text = merged_text + "\n\n" + next_chunk.text
            merged_end = next_chunk.end_offset
            merged_tickers.update(next_chunk.detected_tickers)
            j += 1

        # Create consolidated chunk
        consolidated.append(
            SoftChunk(
                text=merged_text,
                start_offset=merged_start,
                end_offset=merged_end,
                chunk_type="consolidated",
                detected_tickers=list(merged_tickers),
            )
        )
        i = j  # Skip the chunks we merged

    original_count = len(chunks)
    new_count = len(consolidated)
    if new_count < original_count:
        logger.debug(f"Consolidated {original_count} chunks → {new_count} chunks")

    return consolidated


def soft_split(text: str) -> List[SoftChunk]:
    """
    Perform deterministic pre-splitting before LLM call.

    Strategy:
    1. If message is short (< 1500 chars): send as-is (no splitting)
    2. If medium (1500-4000 chars): split by structure, then consolidate tiny chunks
    3. If long multi-stock: additionally split by ticker blocks
    4. If any chunk still too long: hard split at sentence boundaries
    5. Always consolidate tiny chunks (<200 chars) back together

    Args:
        text: The cleaned message text to split

    Returns:
        List of SoftChunk objects ready for LLM processing
    """
    if not text or not text.strip():
        return []

    text = text.strip()

    # Case 1: Short/medium message - send as-is (prevents call explosion)
    if len(text) < SHORT_MESSAGE_THRESHOLD:
        return [
            SoftChunk(
                text=text,
                start_offset=0,
                end_offset=len(text),
                chunk_type="full",
                detected_tickers=extract_tickers(text),
            )
        ]

    # Case 2: Medium message - split by structure
    section_chunks = split_by_sections(text)

    # Case 3: Check if any chunk is still long with multiple tickers
    final_chunks = []
    for chunk_text, start, end in section_chunks:
        if len(chunk_text) > LONG_CHUNK_THRESHOLD:
            tickers = extract_tickers(chunk_text)
            if len(tickers) > 1:
                # Multi-ticker long chunk - split by ticker blocks
                ticker_chunks = split_by_ticker_blocks(chunk_text)
                for tc_text, tc_start, tc_end, tc_tickers in ticker_chunks:
                    # Case 4: Hard split if still too long
                    if len(tc_text) > MAX_CHUNK_SIZE:
                        hard_chunks = hard_split(tc_text)
                        for hc_text, hc_start, hc_end in hard_chunks:
                            final_chunks.append(
                                SoftChunk(
                                    text=hc_text,
                                    start_offset=start + tc_start + hc_start,
                                    end_offset=start + tc_start + hc_end,
                                    chunk_type="hard_split",
                                    detected_tickers=extract_tickers(hc_text),
                                )
                            )
                    else:
                        final_chunks.append(
                            SoftChunk(
                                text=tc_text,
                                start_offset=start + tc_start,
                                end_offset=start + tc_end,
                                chunk_type="ticker_block",
                                detected_tickers=tc_tickers,
                            )
                        )
            else:
                # Long but single/few tickers - hard split if needed
                if len(chunk_text) > MAX_CHUNK_SIZE:
                    hard_chunks = hard_split(chunk_text)
                    for hc_text, hc_start, hc_end in hard_chunks:
                        final_chunks.append(
                            SoftChunk(
                                text=hc_text,
                                start_offset=start + hc_start,
                                end_offset=start + hc_end,
                                chunk_type="hard_split",
                                detected_tickers=extract_tickers(hc_text),
                            )
                        )
                else:
                    final_chunks.append(
                        SoftChunk(
                            text=chunk_text,
                            start_offset=start,
                            end_offset=end,
                            chunk_type="section",
                            detected_tickers=tickers,
                        )
                    )
        else:
            final_chunks.append(
                SoftChunk(
                    text=chunk_text,
                    start_offset=start,
                    end_offset=end,
                    chunk_type="section",
                    detected_tickers=extract_tickers(chunk_text),
                )
            )

    # CONSOLIDATION: Merge tiny chunks to reduce API calls
    # This prevents situations like "10 chunks × 2 calls = 20 API calls"
    if len(final_chunks) > 1:
        final_chunks = consolidate_small_chunks(final_chunks)

    return final_chunks


def estimate_llm_calls(text: str) -> int:
    """Estimate how many LLM calls will be needed for a message.

    Useful for cost estimation and progress reporting.

    Args:
        text: The message text

    Returns:
        Estimated number of LLM calls
    """
    chunks = soft_split(text)
    return len(chunks)


def summarize_splits(chunks: List[SoftChunk]) -> str:
    """Create a summary of the splitting result.

    Args:
        chunks: List of soft chunks

    Returns:
        Human-readable summary string
    """
    if not chunks:
        return "No chunks produced"

    total_chars = sum(len(c.text) for c in chunks)
    total_tickers = set()
    for c in chunks:
        total_tickers.update(c.detected_tickers)

    type_counts = {}
    for c in chunks:
        type_counts[c.chunk_type] = type_counts.get(c.chunk_type, 0) + 1

    lines = [
        f"Chunks: {len(chunks)}",
        f"Total chars: {total_chars}",
        f"Tickers: {', '.join(sorted(total_tickers)) or 'none'}",
        f"Types: {type_counts}",
    ]
    return " | ".join(lines)


# =============================================================================
# INTEGRATION WITH PRECLEAN
# =============================================================================


def prepare_for_parsing(
    text: str, skip_if_short: bool = False, min_length: int = 10
) -> List[SoftChunk]:
    """
    Prepare a message for LLM parsing.

    Combines preclean normalization with soft splitting.

    Args:
        text: Raw message text
        skip_if_short: Return empty list if message is very short
        min_length: Minimum length to process

    Returns:
        List of SoftChunk objects ready for LLM
    """
    from src.nlp.preclean import normalize_text, is_noise_message

    # Step 1: Normalize (preserves $tickers and numbers)
    normalized = normalize_text(text, preserve_tickers=True)

    # Step 2: Check for noise
    if is_noise_message(normalized):
        return []

    # Step 3: Check length
    if len(normalized) < min_length:
        if skip_if_short:
            return []
        # Return as single chunk anyway
        return [
            SoftChunk(
                text=normalized,
                start_offset=0,
                end_offset=len(normalized),
                chunk_type="full",
                detected_tickers=extract_tickers(normalized),
            )
        ]

    # Step 4: Soft split
    return soft_split(normalized)
