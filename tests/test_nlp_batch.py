"""
Tests for NLP batch processing.

Tests:
1. Batch output JSONL parsing (Chat Completions format)
2. Custom ID parsing (message_id, chunk_index extraction)
3. Triple key (message_id, soft_chunk_index, local_idea_index) consistency
"""

import json
import pytest

from src.nlp.schemas import MessageParseResult, ParsedIdea


# Sample batch output line - exactly as returned by OpenAI Batch API
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


class TestBatchOutputParsing:
    """Test parsing of OpenAI Batch API output (Chat Completions format)."""

    def test_parse_batch_output_structure(self):
        """Test that batch output structure is correctly navigated."""
        response = SAMPLE_BATCH_OUTPUT

        body = response.get("response", {}).get("body", {})
        choices = body.get("choices", [])

        assert len(choices) > 0, "Should have at least one choice"

        content = choices[0].get("message", {}).get("content", "")
        assert isinstance(content, str), "Content should be a JSON string"

        parsed = json.loads(content)
        assert "ideas" in parsed, "Should have 'ideas' key"
        assert "confidence" in parsed, "Should have 'confidence' key"

    def test_parse_into_message_parse_result(self):
        """Test parsing batch output into MessageParseResult schema."""
        response = SAMPLE_BATCH_OUTPUT

        body = response.get("response", {}).get("body", {})
        choices = body.get("choices", [])
        content = choices[0].get("message", {}).get("content", "")

        result = MessageParseResult.model_validate_json(content)

        assert isinstance(result, MessageParseResult)
        assert len(result.ideas) == 1
        assert result.confidence == pytest.approx(0.92)
        assert result.context_summary == "User executed options trade on AAPL"

        idea = result.ideas[0]
        assert idea.primary_symbol == "AAPL"
        assert idea.direction == "bullish"
        assert idea.action == "buy"
        assert "OPTIONS" in idea.labels

    def test_parse_custom_id(self):
        """Test custom_id parsing to extract message_id and chunk_index."""
        custom_id = SAMPLE_BATCH_OUTPUT["custom_id"]

        parts = custom_id.split("-")

        assert parts[0] == "msg"
        assert parts[2] == "chunk"

        message_id = str(parts[1])
        chunk_index = int(parts[3])

        assert message_id == "1234567890123456789"
        assert chunk_index == 0

    def test_triple_key_construction(self):
        """Test that triple key is constructed correctly."""
        response = SAMPLE_BATCH_OUTPUT
        custom_id = response["custom_id"]

        parts = custom_id.split("-")
        message_id = str(parts[1])
        soft_chunk_index = int(parts[3])

        body = response.get("response", {}).get("body", {})
        content = body["choices"][0]["message"]["content"]
        result = MessageParseResult.model_validate_json(content)

        triple_keys = []
        for local_idea_index, idea in enumerate(result.ideas):
            if not idea.is_noise:
                triple_keys.append(
                    {
                        "message_id": str(message_id),
                        "soft_chunk_index": soft_chunk_index,
                        "local_idea_index": local_idea_index,
                    }
                )

        assert len(triple_keys) == 1

        key = triple_keys[0]
        assert key["message_id"] == "1234567890123456789"
        assert key["soft_chunk_index"] == 0
        assert key["local_idea_index"] == 0

    def test_error_response_handling(self):
        """Test handling of error responses in batch output."""
        error_response = {
            "id": "batch_req_error",
            "custom_id": "msg-9999999999999999999-chunk-0",
            "response": None,
            "error": {"code": "rate_limit_exceeded", "message": "Rate limit exceeded"},
        }

        assert error_response.get("error") is not None
        assert error_response.get("response") is None

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
                    "direction": "neutral",
                    "labels": [],
                    "is_noise": True,
                },
            ],
            "context_summary": "Mixed sentiment on tech",
            "confidence": 0.85,
        }

        result = MessageParseResult.model_validate(multi_idea_content)

        local_indices = []
        for idx, idea in enumerate(result.ideas):
            if not idea.is_noise:
                local_indices.append(idx)

        assert len(local_indices) == 2
        assert local_indices[0] == 0
        assert local_indices[1] == 1


class TestBatchCustomIdFormats:
    """Test various custom_id format edge cases."""

    def test_standard_format(self):
        """Test standard format: msg-{id}-chunk-{idx}"""
        custom_id = "msg-1234567890123456789-chunk-0"
        parts = custom_id.split("-")

        assert parts[0] == "msg"
        assert int(parts[1]) == 1234567890123456789
        assert parts[2] == "chunk"
        assert int(parts[3]) == 0

    def test_multi_chunk_format(self):
        """Test multi-chunk message format."""
        for chunk_idx in range(5):
            custom_id = f"msg-9876543210987654321-chunk-{chunk_idx}"
            parts = custom_id.split("-")

            assert int(parts[3]) == chunk_idx

    def test_large_message_id(self):
        """Test very large Discord snowflake IDs."""
        large_id = 1308158456789012345
        custom_id = f"msg-{large_id}-chunk-0"

        parts = custom_id.split("-")
        parsed_id = int(parts[1])

        assert parsed_id == large_id
