#!/usr/bin/env python
"""
Test script to demonstrate the safer SnapTrade API response handling.
This shows how the safely_extract_response_data function works with different response types.
"""

import json
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

try:
    from src.snaptrade_collector import SnapTradeCollector

    SNAPTRADE_AVAILABLE = True
except ImportError as e:
    logger.warning(f"SnapTrade collector not available: {e}")
    SNAPTRADE_AVAILABLE = False


class MockResponse:
    """Mock SnapTrade response object for testing"""

    def __init__(self, body=None, parsed=None):
        self.body = body
        self.parsed = parsed


def test_safe_response_handling():
    """Test the safely_extract_response_data function with different response types"""

    if not SNAPTRADE_AVAILABLE:
        logger.error("❌ SnapTrade collector not available, skipping tests")
        return

    logger.info("🧪 Testing Safe Response Handling")
    logger.info("=" * 50)

    # Create a collector instance to access the method
    try:
        collector = SnapTradeCollector()
    except Exception as e:
        logger.error(f"❌ Cannot create SnapTrade collector: {e}")
        return

    # Test 1: Response with body containing a list
    logger.info("\n📋 Test 1: Response with body (list)")
    mock_positions = [
        {"symbol": {"raw_symbol": "AAPL"}, "units": 10, "price": 150.0},
        {"symbol": {"raw_symbol": "GOOGL"}, "units": 5, "price": 2800.0},
    ]
    response1 = MockResponse(body=mock_positions)
    data1, is_list1 = collector.safely_extract_response_data(
        response1, "test_positions"
    )
    print(f"Result: data length={len(data1) if data1 else 0}, is_list={is_list1}")

    # Test 2: Response with parsed attribute
    logger.info("\n📋 Test 2: Response with parsed attribute")
    mock_balance = {"total_value": 50000.0, "currency": "USD"}
    response2 = MockResponse(parsed=mock_balance)
    data2, is_list2 = collector.safely_extract_response_data(response2, "test_balance")
    print(f"Result: data type={type(data2).__name__}, is_list={is_list2}")

    # Test 3: Response with both body and parsed (parsed should take precedence)
    logger.info("\n📋 Test 3: Response with both body and parsed")
    response3 = MockResponse(body=mock_positions, parsed=mock_balance)
    data3, is_list3 = collector.safely_extract_response_data(response3, "test_priority")
    print(f"Result: Should use parsed - data type={type(data3).__name__}")

    # Test 4: Empty response
    logger.info("\n📋 Test 4: Empty response")
    response4 = MockResponse()
    data4, is_list4 = collector.safely_extract_response_data(response4, "test_empty")
    print(f"Result: data={data4}, is_list={is_list4}")

    # Test 5: Response with single dict item (not a list)
    logger.info("\n📋 Test 5: Single dict response")
    single_order = {"symbol": "TSLA", "quantity": 20, "price": 800.0}
    response5 = MockResponse(body=single_order)
    data5, is_list5 = collector.safely_extract_response_data(
        response5, "test_single_order"
    )
    print(f"Result: data type={type(data5).__name__}, is_list={is_list5}")

    logger.info("\n" + "=" * 50)
    logger.info("✅ Safe response handling tests completed!")


if __name__ == "__main__":
    test_safe_response_handling()
