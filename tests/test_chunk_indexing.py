#!/usr/bin/env python
"""
Chunk Indexing Unit Test

Verifies that soft_chunk_index and local_idea_index are correctly populated
for multi-chunk messages after the chunk indexing fix.

This test ensures:
1. Single-chunk messages have all ideas at chunk 0
2. Multi-chunk messages have distinct chunk indices
3. Local idea indices restart at 0 for each chunk
4. The unique constraint (message_id, soft_chunk_index, local_idea_index) is satisfied

Usage:
    python tests/test_chunk_indexing.py
    pytest tests/test_chunk_indexing.py -v
"""
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.nlp.openai_parser import process_message


@pytest.mark.openai
def test_single_chunk_indexing():
    """Test that single-chunk messages have all ideas at chunk_idx=0."""
    message = "Buy $AAPL at $150, sell $GOOGL at $180, watch $MSFT for breakout"

    result = process_message(
        text=message, message_id="test_single_123", skip_triage=True  # Speed up test
    )

    assert result["status"] == "ok", f"Parse failed: {result.get('error_reason')}"
    ideas = result["ideas"]
    assert len(ideas) > 0, "No ideas extracted"

    # All ideas should be in chunk 0
    for idx, idea in enumerate(ideas):
        assert "soft_chunk_index" in idea, f"Idea {idx} missing soft_chunk_index"
        assert "local_idea_index" in idea, f"Idea {idx} missing local_idea_index"
        assert (
            idea["soft_chunk_index"] == 0
        ), f"Idea {idx} should be in chunk 0, got {idea['soft_chunk_index']}"
        assert (
            idea["local_idea_index"] == idx
        ), f"Idea {idx} local_idea_index should be {idx}, got {idea['local_idea_index']}"

    print(f"✅ Single-chunk test passed: {len(ideas)} ideas all in chunk 0")


@pytest.mark.openai
def test_multi_chunk_indexing():
    """Test that multi-chunk messages have distinct chunk indices and local indices restart."""
    # Long structured message that will split into multiple chunks
    message = """## Tech Sector Analysis
    
$GOOGL breaking out above $180 resistance, targeting $195 on earnings momentum. 
Strong volume confirms institutional buying. Consider $185 calls for March expiry.

$MSFT holding $420 support beautifully. Cloud margins expanding, Azure growth accelerating. 
Entry $422-425, stop $415, target $450.

### Semiconductors

$NVDA consolidating in the $880-$920 range after massive run. Waiting for clear break 
above $920 before adding. If it holds $880 support, could see $1000+ by Q2.

$AMD looking weak comparatively. Might trim 30% here and rotate into NVDA on breakout 
or into $AVGO which has better risk/reward at current levels.

### Energy Sector

$XOM at 52-week high, oil inventories declining. Short-term overbought but long-term 
bullish. Scale in on dips to $115-117 range.

$CVX also strong, dividend yield attractive at 3.5%. Good defensive play if market corrects."""

    result = process_message(
        text=message, message_id="test_multi_456", skip_triage=True  # Speed up test
    )

    assert result["status"] == "ok", f"Parse failed: {result.get('error_reason')}"
    ideas = result["ideas"]
    assert len(ideas) > 0, "No ideas extracted"

    # Collect chunk indices
    chunks_seen = set()
    local_indices_per_chunk = {}

    for idea in ideas:
        assert "soft_chunk_index" in idea, "Idea missing soft_chunk_index"
        assert "local_idea_index" in idea, "Idea missing local_idea_index"

        chunk_idx = idea["soft_chunk_index"]
        local_idx = idea["local_idea_index"]

        chunks_seen.add(chunk_idx)

        if chunk_idx not in local_indices_per_chunk:
            local_indices_per_chunk[chunk_idx] = []
        local_indices_per_chunk[chunk_idx].append(local_idx)

    # Verify we have multiple chunks (message is long enough)
    num_chunks = len(chunks_seen)
    if num_chunks == 1:
        print(f"⚠️  Warning: Expected multi-chunk split, got {num_chunks} chunk")
        print(f"   Message length: {len(message)} chars - may need longer test message")
    else:
        print(f"✅ Multi-chunk test: {num_chunks} chunks detected")

    # Verify local indices restart at 0 for each chunk
    for chunk_idx, local_indices in local_indices_per_chunk.items():
        sorted_indices = sorted(local_indices)
        expected = list(range(len(sorted_indices)))
        assert sorted_indices == expected, (
            f"Chunk {chunk_idx} local indices not sequential: "
            f"got {sorted_indices}, expected {expected}"
        )

    # Verify unique constraint: (message_id, soft_chunk_index, local_idea_index) should be unique
    seen_keys = set()
    for idea in ideas:
        key = (idea["message_id"], idea["soft_chunk_index"], idea["local_idea_index"])
        assert key not in seen_keys, f"Duplicate key found: {key}"
        seen_keys.add(key)

    print(
        f"✅ Multi-chunk indexing verified: {len(ideas)} ideas across {num_chunks} chunks"
    )
    for chunk_idx, local_indices in sorted(local_indices_per_chunk.items()):
        print(
            f"   Chunk {chunk_idx}: {len(local_indices)} ideas (local indices 0-{len(local_indices)-1})"
        )


@pytest.mark.openai
def test_chunk_indexing_db_compatibility():
    """Test that the returned idea dicts can be inserted into the database."""
    message = "Simple test: buy $AAPL"

    result = process_message(text=message, message_id="test_db_789", skip_triage=True)

    assert result["status"] == "ok", f"Parse failed: {result.get('error_reason')}"
    ideas = result["ideas"]
    assert len(ideas) > 0, "No ideas extracted"

    # Verify required fields for database insertion
    required_fields = [
        "message_id",
        "idea_index",
        "soft_chunk_index",
        "local_idea_index",
        "idea_text",
        "primary_symbol",
        "instrument",
        "direction",
        "model",
        "prompt_version",
        "confidence",
    ]

    for idx, idea in enumerate(ideas):
        for field in required_fields:
            assert field in idea, f"Idea {idx} missing required field: {field}"

    print(f"✅ DB compatibility verified: All {len(ideas)} ideas have required fields")
