#!/usr/bin/env python3
"""
Unit tests for NLP batch processing.

Tests:
1. Batch output JSONL parsing (Chat Completions format)
2. Custom ID parsing (message_id, chunk_index extraction)
3. Triple key (message_id, soft_chunk_index, local_idea_index) consistency
"""

import json
import unittest
from datetime import datetime, timezone
from typing import Dict, Any

import sys

sys.path.insert(0, str(__file__).rsplit("tests", 1)[0].rstrip("/\\"))

from src.nlp.schemas import MessageParseResult, ParsedIdea


class TestBatchOutputParsing(unittest.TestCase):
    """Test parsing of OpenAI Batch API output (Chat Completions format)."""

    # Sample batch output line - exactly as returned by OpenAI Batch API
    # This is the /v1/chat/completions format with json_schema response_format
    SAMPLE_BATCH_OUTPUT = {
        "id": "batch_req_abc123",
        "custom_id": "msg-1234567890123456789-chunk-0",
        "response": {
            "status_code": 200,
            "request_id": "req_xyz789",
            "body": {
                "id": "chatcmpl-9ABC123",
                "object": "chat.completion",
                "created": 1749425580,
                "model": "gpt-4o-mini-2024-07-18",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "ideas": [
                                        {
                                            "idea_text": "Bought AAPL calls at 185 strike",
                                            "idea_summary": "Long AAPL via call options at 185 strike",
                                            "primary_symbol": "AAPL",
                                            "symbols": ["AAPL"],
                                            "instrument": "option",
                                            "direction": "bullish",
                                            "action": "buy",
                                            "time_horizon": "swing",
                                            "trigger_condition": None,
                                            "levels": [{"kind": "entry", "value": 185}],
                                            "option_type": "call",
                                            "strike": 185.0,
                                            "expiry": None,
                                            "premium": None,
                                            "labels": ["OPTIONS", "TRADE_EXECUTION"],
                                            "label_scores": {
                                                "OPTIONS": 0.95,
                                                "TRADE_EXECUTION": 0.9,
                                            },
                                            "is_noise": False,
                                        }
                                    ],
                                    "context_summary": "User executed options trade on AAPL",
                                    "confidence": 0.92,
                                }
                            ),
                            "refusal": None,
                        },
                        "logprobs": None,
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 250,
                    "completion_tokens": 150,
                    "total_tokens": 400,
                },
                "system_fingerprint": "fp_abc123",
            },
        },
        "error": None,
    }

    def test_parse_batch_output_structure(self):
        """Test that batch output structure is correctly navigated."""
        response = self.SAMPLE_BATCH_OUTPUT

        # Navigate to content (same path as ingest_batch.py)
        body = response.get("response", {}).get("body", {})
        choices = body.get("choices", [])

        self.assertTrue(len(choices) > 0, "Should have at least one choice")

        content = choices[0].get("message", {}).get("content", "")
        self.assertIsInstance(content, str, "Content should be a JSON string")

        # Parse the content as JSON
        parsed = json.loads(content)
        self.assertIn("ideas", parsed, "Should have 'ideas' key")
        self.assertIn("confidence", parsed, "Should have 'confidence' key")

    def test_parse_into_message_parse_result(self):
        """Test parsing batch output into MessageParseResult schema."""
        response = self.SAMPLE_BATCH_OUTPUT

        # Extract content
        body = response.get("response", {}).get("body", {})
        choices = body.get("choices", [])
        content = choices[0].get("message", {}).get("content", "")

        # Parse into schema (same as ingest_batch.py)
        result = MessageParseResult.model_validate_json(content)

        self.assertIsInstance(result, MessageParseResult)
        self.assertEqual(len(result.ideas), 1)
        self.assertEqual(result.confidence, 0.92)
        self.assertEqual(result.context_summary, "User executed options trade on AAPL")

        # Verify idea details
        idea = result.ideas[0]
        self.assertEqual(idea.primary_symbol, "AAPL")
        self.assertEqual(idea.direction, "bullish")
        self.assertEqual(idea.action, "buy")
        self.assertIn("OPTIONS", idea.labels)

    def test_parse_custom_id(self):
        """Test custom_id parsing to extract message_id and chunk_index."""
        custom_id = self.SAMPLE_BATCH_OUTPUT["custom_id"]

        # Parse format: "msg-{message_id}-chunk-{chunk_index}"
        parts = custom_id.split("-")
        # Expected: ["msg", "1234567890123456789", "chunk", "0"]

        self.assertEqual(parts[0], "msg")
        self.assertEqual(parts[2], "chunk")

        message_id = str(parts[1])  # Always string
        chunk_index = int(parts[3])

        self.assertEqual(message_id, "1234567890123456789")
        self.assertEqual(chunk_index, 0)

    def test_triple_key_construction(self):
        """Test that triple key (message_id, soft_chunk_index, local_idea_index) is constructed correctly."""
        response = self.SAMPLE_BATCH_OUTPUT
        custom_id = response["custom_id"]

        # Parse custom_id
        parts = custom_id.split("-")
        message_id = str(parts[1])  # Always string
        soft_chunk_index = int(parts[3])  # This is the chunk index

        # Parse content
        body = response.get("response", {}).get("body", {})
        content = body["choices"][0]["message"]["content"]
        result = MessageParseResult.model_validate_json(content)

        # Build triple keys for each idea
        triple_keys = []
        for local_idea_index, idea in enumerate(result.ideas):
            if not idea.is_noise:
                triple_keys.append(
                    {
                        "message_id": str(message_id),  # Stored as TEXT in DB
                        "soft_chunk_index": soft_chunk_index,
                        "local_idea_index": local_idea_index,
                    }
                )

        # Verify we have exactly one triple key
        self.assertEqual(len(triple_keys), 1)

        # Verify the key values
        key = triple_keys[0]
        self.assertEqual(key["message_id"], "1234567890123456789")
        self.assertEqual(key["soft_chunk_index"], 0)
        self.assertEqual(key["local_idea_index"], 0)

    def test_error_response_handling(self):
        """Test handling of error responses in batch output."""
        error_response = {
            "id": "batch_req_error",
            "custom_id": "msg-9999999999999999999-chunk-0",
            "response": None,
            "error": {"code": "rate_limit_exceeded", "message": "Rate limit exceeded"},
        }

        # Verify error detection (same logic as ingest_batch.py)
        self.assertIsNotNone(error_response.get("error"))
        self.assertIsNone(error_response.get("response"))

    def test_multi_idea_local_indexing(self):
        """Test that local_idea_index is correctly assigned for multiple ideas."""
        multi_idea_content = {
            "ideas": [
                {
                    "idea_text": "Bullish on AAPL",
                    "idea_summary": "Positive outlook on Apple stock",
                    "primary_symbol": "AAPL",
                    "symbols": ["AAPL"],
                    "direction": "bullish",
                    "labels": ["SENTIMENT_CONVICTION"],
                    "is_noise": False,
                },
                {
                    "idea_text": "Bearish on MSFT",
                    "idea_summary": "Negative outlook on Microsoft stock",
                    "primary_symbol": "MSFT",
                    "symbols": ["MSFT"],
                    "direction": "bearish",
                    "labels": ["SENTIMENT_CONVICTION"],
                    "is_noise": False,
                },
                {
                    "idea_text": "Random noise",
                    "idea_summary": "Not actionable content",
                    "primary_symbol": None,
                    "symbols": [],
                    "direction": "neutral",  # Must be a valid enum value
                    "labels": [],
                    "is_noise": True,  # This is noise, should not get a key
                },
            ],
            "context_summary": "Mixed sentiment on tech",
            "confidence": 0.85,
        }

        result = MessageParseResult.model_validate(multi_idea_content)

        # Build local indices (filtering noise)
        local_indices = []
        for idx, idea in enumerate(result.ideas):
            if not idea.is_noise:
                local_indices.append(idx)

        # Should have 2 non-noise ideas with local indices 0 and 1
        self.assertEqual(len(local_indices), 2)
        self.assertEqual(local_indices[0], 0)
        self.assertEqual(local_indices[1], 1)


class TestBatchCustomIdFormats(unittest.TestCase):
    """Test various custom_id format edge cases."""

    def test_standard_format(self):
        """Test standard format: msg-{id}-chunk-{idx}"""
        custom_id = "msg-1234567890123456789-chunk-0"
        parts = custom_id.split("-")

        self.assertEqual(parts[0], "msg")
        self.assertEqual(int(parts[1]), 1234567890123456789)
        self.assertEqual(parts[2], "chunk")
        self.assertEqual(int(parts[3]), 0)

    def test_multi_chunk_format(self):
        """Test multi-chunk message format."""
        for chunk_idx in range(5):
            custom_id = f"msg-9876543210987654321-chunk-{chunk_idx}"
            parts = custom_id.split("-")

            self.assertEqual(int(parts[3]), chunk_idx)

    def test_large_message_id(self):
        """Test very large Discord snowflake IDs."""
        # Discord snowflakes can be up to 19 digits
        large_id = 1308158456789012345
        custom_id = f"msg-{large_id}-chunk-0"

        parts = custom_id.split("-")
        parsed_id = int(parts[1])

        self.assertEqual(parsed_id, large_id)


if __name__ == "__main__":
    unittest.main()
