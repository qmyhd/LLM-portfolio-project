"""
Unit tests for ticker context validation and enrichment functions.

Tests the following from src/nlp/preclean.py:
- has_ticker_context() - Validates ticker mentions have proper context
- enrich_parsed_ideas_with_tickers() - Post-processing enrichment
- EXCLUDED_WORDS - Generic words that shouldn't be captured as tickers
- TICKER_CONTEXT_WORDS - Action words that validate ticker context
"""

import pytest
from src.nlp.preclean import (
    has_ticker_context,
    enrich_parsed_ideas_with_tickers,
    extract_tickers_from_text,
    apply_alias_mapping,
    EXCLUDED_WORDS,
    TICKER_CONTEXT_WORDS,
)


class TestHasTickerContext:
    """Tests for has_ticker_context() validation function."""

    def test_dollar_prefix_always_valid(self):
        """Ticker with $ prefix should always be valid."""
        text = "I'm watching $AAPL today"
        # Position is 13 (after the $)
        assert has_ticker_context(text, 14, "AAPL") is True

    def test_action_word_before_validates(self):
        """Action word before ticker should validate it."""
        text = "Just bought NVDA at 120"
        # Position of NVDA is 12
        assert has_ticker_context(text, 12, "NVDA") is True

    def test_selling_action_validates(self):
        """Sell action words should validate ticker."""
        text = "Sold some TSLA this morning"
        assert has_ticker_context(text, 10, "TSLA") is True

    def test_trimming_action_validates(self):
        """Trim action should validate ticker."""
        text = "Trimmed my AMZN position"
        assert has_ticker_context(text, 11, "AMZN") is True

    def test_trading_suffix_validates(self):
        """Trading terminology after ticker should validate it."""
        text = "Looking at SPY calls for Friday"
        assert has_ticker_context(text, 11, "SPY") is True

    def test_shares_suffix_validates(self):
        """'shares' after ticker validates it."""
        text = "Added 100 MSFT shares today"
        # "Added" is an action word, so this validates
        assert has_ticker_context(text, 10, "MSFT") is True

    def test_excluded_words_rejected(self):
        """Common English words should be rejected."""
        for word in ["the", "can", "buy", "sell", "it", "up", "down"]:
            text = f"I {word} this stock"
            assert has_ticker_context(text, 2, word) is False

    def test_trading_jargon_excluded(self):
        """Trading jargon shouldn't be captured as tickers."""
        excluded_jargon = ["fomo", "yolo", "hodl", "moon", "pump"]
        for jargon in excluded_jargon:
            text = f"Total {jargon} trade"
            assert has_ticker_context(text, 6, jargon) is False

    def test_known_alias_validates(self):
        """Tickers in ALIAS_MAP should validate."""
        text = "nvidia is looking good"
        # "nvidia" is in ALIAS_MAP
        assert has_ticker_context(text, 0, "nvidia") is True

    def test_no_context_no_prefix_rejected(self):
        """Unknown ticker without context or $ should be rejected."""
        text = "I think XYZ is interesting"
        assert has_ticker_context(text, 8, "XYZ") is False

    def test_bullish_bearish_context(self):
        """Bullish/bearish should provide context."""
        text = "Bullish on META"
        assert has_ticker_context(text, 11, "META") is True

    def test_empty_inputs(self):
        """Empty inputs should return False."""
        assert has_ticker_context("", 0, "AAPL") is False
        assert has_ticker_context("test", 0, "") is False
        assert has_ticker_context(None, 0, "AAPL") is False


class TestEnrichParsedIdeas:
    """Tests for enrich_parsed_ideas_with_tickers() function."""

    def test_adds_missing_ticker_from_company_name(self):
        """Should add ticker when company name is in text but not parsed."""
        ideas = [
            {
                "idea_text": "Selling some Amazon today",
                "symbols": [],
                "primary_symbol": None,
            }
        ]
        result = enrich_parsed_ideas_with_tickers(ideas, "Selling some Amazon today")

        assert "AMZN" in result[0]["symbols"]
        assert result[0]["primary_symbol"] == "AMZN"

    def test_preserves_existing_symbols(self):
        """Should not overwrite existing symbols."""
        ideas = [
            {
                "idea_text": "Buying AAPL and selling Amazon",
                "symbols": ["AAPL"],
                "primary_symbol": "AAPL",
            }
        ]
        result = enrich_parsed_ideas_with_tickers(
            ideas, "Buying AAPL and selling Amazon"
        )

        assert "AAPL" in result[0]["symbols"]
        assert "AMZN" in result[0]["symbols"]
        assert result[0]["primary_symbol"] == "AAPL"  # Unchanged

    def test_multiple_company_names(self):
        """Should handle multiple company names."""
        ideas = [
            {
                "idea_text": "Nvidia and Crowdstrike looking strong",
                "symbols": [],
                "primary_symbol": None,
            }
        ]
        result = enrich_parsed_ideas_with_tickers(
            ideas, "Nvidia and Crowdstrike looking strong"
        )

        assert "NVDA" in result[0]["symbols"]
        assert "CRWD" in result[0]["symbols"]

    def test_lowercase_ticker_enrichment(self):
        """Should handle lowercase ticker abbreviations."""
        ideas = [
            {
                "idea_text": "selling pltr and nvda",
                "symbols": [],
                "primary_symbol": None,
            }
        ]
        result = enrich_parsed_ideas_with_tickers(ideas, "selling pltr and nvda")

        assert "PLTR" in result[0]["symbols"]
        assert "NVDA" in result[0]["symbols"]

    def test_empty_ideas_returns_empty(self):
        """Should handle empty ideas list."""
        result = enrich_parsed_ideas_with_tickers([], "Some text with $AAPL")
        assert result == []

    def test_empty_text_returns_unchanged(self):
        """Should return unchanged ideas if text is empty."""
        ideas = [{"idea_text": "test", "symbols": ["AAPL"], "primary_symbol": "AAPL"}]
        result = enrich_parsed_ideas_with_tickers(ideas, "")
        assert result == ideas

    def test_none_inputs(self):
        """Should handle None inputs gracefully."""
        assert enrich_parsed_ideas_with_tickers(None, "text") is None
        assert enrich_parsed_ideas_with_tickers([], None) == []


class TestExtractTickersIntegration:
    """Integration tests for the full extraction flow."""

    def test_full_flow_company_to_ticker(self):
        """Test full flow from company name to extracted ticker."""
        text = "Trimmed my Nvidia position, added to Amazon"

        # Step 1: Apply alias mapping
        mapped = apply_alias_mapping(text)
        assert "$NVDA" in mapped
        assert "$AMZN" in mapped

        # Step 2: Extract tickers
        tickers = extract_tickers_from_text(mapped)
        assert "NVDA" in tickers
        assert "AMZN" in tickers

    def test_mixed_format_extraction(self):
        """Test extraction with mixed formats ($TICKER and company names)."""
        text = "Buying $AAPL and selling nvidia"
        mapped = apply_alias_mapping(text)
        tickers = extract_tickers_from_text(mapped)

        assert "AAPL" in tickers
        assert "NVDA" in tickers

    def test_case_10_regression(self):
        """Regression test for Case 10 (company names not mapped)."""
        text = "selling of some pltr, crowdstrike and amazon to trim at relative highs"
        mapped = apply_alias_mapping(text)

        # All should be mapped now
        assert "$CRWD" in mapped
        assert "$AMZN" in mapped
        assert "$PLTR" in mapped or "PLTR" in mapped  # Either mapped or uppercase


class TestExcludedWords:
    """Tests for the EXCLUDED_WORDS set."""

    def test_common_prepositions_excluded(self):
        """Common prepositions should be in excluded list."""
        prepositions = ["a", "an", "the", "to", "of", "in", "on"]
        for word in prepositions:
            assert word in EXCLUDED_WORDS, f"'{word}' should be excluded"

    def test_trading_terms_excluded(self):
        """Trading terms that look like tickers should be excluded."""
        terms = ["call", "put", "long", "short", "buy", "sell"]
        for term in terms:
            assert term in EXCLUDED_WORDS, f"'{term}' should be excluded"

    def test_common_abbreviations_excluded(self):
        """Common trading abbreviations should be excluded."""
        abbrevs = ["otc", "ipo", "etf", "dte", "eod"]
        for abbrev in abbrevs:
            assert abbrev in EXCLUDED_WORDS, f"'{abbrev}' should be excluded"


class TestTickerContextWords:
    """Tests for the TICKER_CONTEXT_WORDS set."""

    def test_buy_actions_included(self):
        """Buy actions should be in context words."""
        buy_actions = ["buy", "bought", "buying", "add", "added", "long"]
        for action in buy_actions:
            assert action in TICKER_CONTEXT_WORDS, f"'{action}' should be context word"

    def test_sell_actions_included(self):
        """Sell actions should be in context words."""
        sell_actions = ["sell", "sold", "selling", "trim", "short"]
        for action in sell_actions:
            assert action in TICKER_CONTEXT_WORDS, f"'{action}' should be context word"

    def test_analysis_words_included(self):
        """Analysis words should be in context words."""
        analysis = ["bullish", "bearish", "target", "support", "resistance"]
        for word in analysis:
            assert word in TICKER_CONTEXT_WORDS, f"'{word}' should be context word"


# =============================================================================
# SHORT ACTION WHITELIST TESTS
# =============================================================================


class TestIsValidShortAction:
    """Tests for is_valid_short_action() function."""

    def test_buy_with_ticker_is_valid(self):
        """'Buy AAPL' should be a valid short action."""
        from src.nlp.preclean import is_valid_short_action

        assert is_valid_short_action("Buy AAPL") is True

    def test_sold_with_dollar_ticker_is_valid(self):
        """'Sold $TSLA' should be a valid short action."""
        from src.nlp.preclean import is_valid_short_action

        assert is_valid_short_action("Sold $TSLA") is True

    def test_trim_with_company_name_is_valid(self):
        """'Trim nvidia' should be valid (company name maps to ticker)."""
        from src.nlp.preclean import is_valid_short_action

        assert is_valid_short_action("Trim nvidia") is True

    def test_hedge_with_ticker_is_valid(self):
        """'Hedge $SPY' should be valid."""
        from src.nlp.preclean import is_valid_short_action

        assert is_valid_short_action("Hedge $SPY") is True

    def test_starts_with_dollar_ticker_is_valid(self):
        """'$AAPL looking good' should be valid (starts with ticker)."""
        from src.nlp.preclean import is_valid_short_action

        assert is_valid_short_action("$AAPL looking good") is True

    def test_action_without_ticker_is_invalid(self):
        """'Buy some shares' without ticker should be invalid."""
        from src.nlp.preclean import is_valid_short_action

        assert is_valid_short_action("Buy some shares") is False

    def test_no_action_no_ticker_is_invalid(self):
        """'good point' should be invalid."""
        from src.nlp.preclean import is_valid_short_action

        assert is_valid_short_action("good point") is False

    def test_empty_string_is_invalid(self):
        """Empty string should be invalid."""
        from src.nlp.preclean import is_valid_short_action

        assert is_valid_short_action("") is False

    def test_watch_with_ticker_is_valid(self):
        """'Watch AMZN' should be valid."""
        from src.nlp.preclean import is_valid_short_action

        assert is_valid_short_action("Watch AMZN") is True


class TestMergeShortIdeas:
    """Tests for merge_short_ideas() function."""

    def test_single_idea_unchanged(self):
        """Single idea should be returned unchanged."""
        from src.nlp.preclean import merge_short_ideas

        ideas = [{"idea_text": "Short text", "primary_symbol": "AAPL"}]
        result = merge_short_ideas(ideas)
        assert len(result) == 1
        assert result[0]["idea_text"] == "Short text"

    def test_valid_short_action_not_merged(self):
        """Valid short action should NOT be merged."""
        from src.nlp.preclean import merge_short_ideas

        ideas = [
            {
                "idea_text": "Long analysis about market conditions",
                "primary_symbol": None,
            },
            {"idea_text": "Buy $AAPL", "primary_symbol": "AAPL"},  # Valid short action
            {
                "idea_text": "Another long piece of analysis here",
                "primary_symbol": None,
            },
        ]
        result = merge_short_ideas(ideas)
        assert len(result) == 3  # All three preserved
        assert "Buy $AAPL" in result[1]["idea_text"]

    def test_short_fragment_merged_with_previous(self):
        """Short fragment without action should merge with previous."""
        from src.nlp.preclean import merge_short_ideas

        ideas = [
            {
                "idea_text": "Looking at semiconductor sector rotation",
                "primary_symbol": None,
                "symbols": [],
            },
            {
                "idea_text": "Good point",
                "primary_symbol": None,
                "symbols": [],
            },  # Short, no action
        ]
        result = merge_short_ideas(ideas)
        assert len(result) == 1
        assert "Good point" in result[0]["idea_text"]
        assert "semiconductor" in result[0]["idea_text"]

    def test_short_fragment_merged_with_next(self):
        """Short fragment as first idea should merge with next."""
        from src.nlp.preclean import merge_short_ideas

        ideas = [
            {
                "idea_text": "Hmm",
                "primary_symbol": "AAPL",
                "symbols": ["AAPL"],
            },  # Short, no action
            {
                "idea_text": "AAPL looking strong at 180 resistance level",
                "primary_symbol": "AAPL",
                "symbols": ["AAPL"],
            },
        ]
        result = merge_short_ideas(ideas)
        assert len(result) == 1
        assert "Hmm" in result[0]["idea_text"]
        assert "180" in result[0]["idea_text"]

    def test_different_symbols_not_merged(self):
        """Short ideas with different symbols should NOT be merged."""
        from src.nlp.preclean import merge_short_ideas

        ideas = [
            {
                "idea_text": "AAPL is strong",
                "primary_symbol": "AAPL",
                "symbols": ["AAPL"],
            },
            {
                "idea_text": "Nice",
                "primary_symbol": "TSLA",
                "symbols": ["TSLA"],
            },  # Short but different symbol
        ]
        result = merge_short_ideas(ideas)
        assert len(result) == 2  # Can't merge different symbols

    def test_preserves_symbols_on_merge(self):
        """Merged ideas should combine their symbols lists."""
        from src.nlp.preclean import merge_short_ideas

        ideas = [
            {
                "idea_text": "Looking at tech plays",
                "primary_symbol": None,
                "symbols": ["AAPL"],
            },
            {
                "idea_text": "Good",
                "primary_symbol": None,
                "symbols": ["NVDA"],
            },  # Short, will merge
        ]
        result = merge_short_ideas(ideas)
        assert len(result) == 1
        assert "AAPL" in result[0]["symbols"]
        assert "NVDA" in result[0]["symbols"]


class TestShortActionWhitelist:
    """Tests for the SHORT_ACTION_WHITELIST set."""

    def test_buy_actions_in_whitelist(self):
        """Buy-related actions should be in whitelist."""
        from src.nlp.preclean import SHORT_ACTION_WHITELIST

        buy_actions = ["buy", "bought", "buying", "long", "longing"]
        for action in buy_actions:
            assert (
                action in SHORT_ACTION_WHITELIST
            ), f"'{action}' should be in whitelist"

    def test_sell_actions_in_whitelist(self):
        """Sell-related actions should be in whitelist."""
        from src.nlp.preclean import SHORT_ACTION_WHITELIST

        sell_actions = ["sell", "sold", "selling", "short", "shorting"]
        for action in sell_actions:
            assert (
                action in SHORT_ACTION_WHITELIST
            ), f"'{action}' should be in whitelist"

    def test_position_management_in_whitelist(self):
        """Position management actions should be in whitelist."""
        from src.nlp.preclean import SHORT_ACTION_WHITELIST

        mgmt_actions = ["trim", "add", "hedge", "exit", "close"]
        for action in mgmt_actions:
            assert (
                action in SHORT_ACTION_WHITELIST
            ), f"'{action}' should be in whitelist"
