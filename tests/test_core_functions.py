import json
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd

# Use absolute imports instead of sys.path manipulation
from src.data_collector import append_discord_message_to_csv
from src.message_cleaner import extract_ticker_symbols
from src.journal_generator import (
    create_journal_prompt,
    format_holdings_as_json,
    format_prices_as_json,
)


class TestTickerExtraction(unittest.TestCase):
    """Test cases for ticker extraction function"""

    def test_empty_text(self):
        """Test that empty text returns empty list"""
        self.assertEqual(extract_ticker_symbols(""), [])
        self.assertEqual(extract_ticker_symbols(None), [])

    def test_no_tickers(self):
        """Test text without tickers"""
        text = "This is a message without any ticker symbols."
        self.assertEqual(extract_ticker_symbols(text), [])

    def test_basic_tickers(self):
        """Test basic ticker extraction with proper format"""
        text = "$AAPL is a good stock, so is $MSFT."
        self.assertEqual(extract_ticker_symbols(text), ["$AAPL", "$MSFT"])

    def test_mid_line_tickers(self):
        """Test tickers appearing in the middle of text"""
        text = "I like how $AAPL is performing, and $NVDA too."
        self.assertEqual(extract_ticker_symbols(text), ["$AAPL", "$NVDA"])

    def test_ticker_with_numbers(self):
        """Test tickers with numbers are not included (per regex limit of A-Z)"""
        text = "$AAPL and $BRK.B and $123 and $ABC1"
        self.assertEqual(extract_ticker_symbols(text), ["$AAPL", "$BRK"])

    def test_duplicate_tickers(self):
        """Test duplicate tickers are only returned once"""
        text = "$AAPL is better than $MSFT, but $AAPL has more growth potential."
        self.assertEqual(extract_ticker_symbols(text), ["$AAPL", "$MSFT"])

    def test_ticker_length_limits(self):
        """Test ticker length limits (1-6 characters)"""
        text = "$A $AB $ABC $ABCD $ABCDE $ABCDEF $ABCDEFG"
        self.assertEqual(
            extract_ticker_symbols(text),
            ["$A", "$AB", "$ABC", "$ABCD", "$ABCDE", "$ABCDEF"],
        )

    def test_non_word_boundary(self):
        """Test tickers followed by non-word boundaries"""
        text = "$AAPL. $MSFT, $TSLA: $NVDA;"
        self.assertEqual(
            extract_ticker_symbols(text), ["$AAPL", "$MSFT", "$TSLA", "$NVDA"]
        )


class TestMessageAppend(unittest.TestCase):
    """Test cases for message append function"""

    def setUp(self):
        """Set up a temporary directory for test files"""
        self.temp_dir = tempfile.mkdtemp()
        self.csv_path = Path(self.temp_dir) / "test_messages.csv"

    def tearDown(self):
        """Clean up the temporary directory"""
        shutil.rmtree(self.temp_dir)

    def test_append_basic_message(self):
        """Test basic message append functionality"""
        message = "This is a test message."
        result = append_discord_message_to_csv(message, output_path=self.csv_path)

        # Check that the function returned the file path
        self.assertEqual(result, self.csv_path)

        # Check that the file exists
        self.assertTrue(self.csv_path.exists())

        # Read the file and check the content
        df = pd.read_csv(self.csv_path)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["content"], message)
        self.assertEqual(df.iloc[0]["num_chars"], len(message))
        self.assertEqual(df.iloc[0]["num_words"], 5)

    def test_append_message_with_tickers(self):
        """Test appending a message with ticker symbols"""
        message = "I like $AAPL and $MSFT stocks."
        tickers = ["$AAPL", "$MSFT"]
        append_discord_message_to_csv(
            message, tickers=tickers, output_path=self.csv_path
        )

        # Read the file and check the content
        df = pd.read_csv(self.csv_path)
        self.assertEqual(df.iloc[0]["tickers_detected"], "$AAPL, $MSFT")

    def test_append_multiple_messages(self):
        """Test appending multiple messages to the same file"""
        message1 = "First message"
        message2 = "Second message"

        append_discord_message_to_csv(message1, output_path=self.csv_path)
        append_discord_message_to_csv(message2, output_path=self.csv_path)

        # Read the file and check the content
        df = pd.read_csv(self.csv_path)
        self.assertEqual(len(df), 2)
        self.assertEqual(df.iloc[0]["content"], message1)
        self.assertEqual(df.iloc[1]["content"], message2)

    def test_sanitize_line_breaks(self):
        """Test that line breaks are properly sanitized"""
        message = "Line 1\nLine 2\r\nLine 3"
        append_discord_message_to_csv(message, output_path=self.csv_path)

        # Read the file and check the content
        df = pd.read_csv(self.csv_path)
        self.assertEqual(df.iloc[0]["content"], "Line 1 Line 2 Line 3")


class TestPromptBuilder(unittest.TestCase):
    """Test cases for prompt builder functions"""

    def test_format_holdings_as_json(self):
        """Test formatting holdings as JSON"""
        # Create sample positions DataFrame
        positions_df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "quantity": [10, 5],
                "equity": [1500, 1000],
                "price": [150, 200],
                "average_buy_price": [120, 180],
            }
        )

        # Format as JSON
        json_str = format_holdings_as_json(positions_df)

        # Parse the JSON string back to a dict
        holdings = json.loads(json_str)

        # Check structure
        self.assertIn("holdings", holdings)
        self.assertEqual(len(holdings["holdings"]), 2)

        # Check values
        aapl = holdings["holdings"][0]
        self.assertEqual(aapl["symbol"], "AAPL")
        self.assertEqual(aapl["quantity"], 10)
        self.assertEqual(aapl["equity"], 1500)

        # Test with empty DataFrame
        empty_df = pd.DataFrame()
        empty_json = format_holdings_as_json(empty_df)
        empty_holdings = json.loads(empty_json)
        self.assertEqual(empty_holdings["holdings"], [])

    def test_format_prices_as_json(self):
        """Test formatting prices as JSON with net change included"""
        # Create sample prices DataFrame
        prices_df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "price": [150, 200],
                "previous_close": [145, 205],
                "timestamp": ["2025-09-19", "2025-09-19"],
            }
        )

        # Format as JSON
        json_str = format_prices_as_json(prices_df)

        # Parse the JSON string back to a dict
        prices = json.loads(json_str)

        # Check structure
        self.assertIn("prices", prices)
        self.assertEqual(len(prices["prices"]), 2)

        # Check values and calculated fields
        aapl = prices["prices"][0]
        self.assertEqual(aapl["symbol"], "AAPL")
        self.assertEqual(aapl["price"], 150)
        self.assertEqual(aapl["previous_close"], 145)
        self.assertEqual(aapl["net_change"], 5)  # 150 - 145
        self.assertAlmostEqual(
            aapl["percent_change"], 3.4482758620689653
        )  # (150/145 - 1) * 100

        msft = prices["prices"][1]
        self.assertEqual(msft["net_change"], -5)  # 200 - 205
        self.assertAlmostEqual(
            msft["percent_change"], -2.4390243902439024
        )  # (200/205 - 1) * 100

        # Test with empty DataFrame
        empty_df = pd.DataFrame()
        empty_json = format_prices_as_json(empty_df)
        empty_prices = json.loads(empty_json)
        self.assertEqual(empty_prices["prices"], [])

    def test_create_journal_prompt(self):
        """Test journal prompt creation with all components"""
        # Create sample DataFrames
        positions_df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "quantity": [10, 5],
                "equity": [1500, 1000],
                "price": [150, 200],
                "average_buy_price": [120, 180],
            }
        )

        prices_df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "price": [150, 200],
                "previous_close": [145, 205],
                "timestamp": ["2025-09-19", "2025-09-19"],
            }
        )

        messages_df = pd.DataFrame(
            {
                "content": ["$AAPL looking good!", "$MSFT is overvalued"],
                "created_at": ["2025-09-19", "2025-09-19"],
                "tickers_detected": ["$AAPL", "$MSFT"],
            }
        )

        # Create prompt
        prompt = create_journal_prompt(positions_df, messages_df, prices_df)

        # Check that the prompt contains expected elements
        self.assertIn("<holdings>", prompt)
        self.assertIn("</holdings>", prompt)
        self.assertIn("<prices>", prompt)
        self.assertIn("</prices>", prompt)
        self.assertIn("$AAPL looking good!", prompt)
        self.assertIn("$MSFT is overvalued", prompt)

        # Test with empty DataFrames
        empty_prompt = create_journal_prompt(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        self.assertIn("N/A", empty_prompt)  # No messages should show N/A


if __name__ == "__main__":
    unittest.main()
