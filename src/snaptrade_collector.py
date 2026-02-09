"""
SnapTrade Data Collector Module

Dedicated module for SnapTrade ETL operations with enhanced field extraction,
optional Parquet snapshots, and Supabase PostgreSQL writes.

SDK: Uses snaptrade-python-sdk (snaptrade_client.SnapTrade).
Auth: SNAPTRADE_CONSUMER_KEY + SNAPTRADE_CLIENT_ID for app auth.
      SNAPTRADE_USER_ID + SNAPTRADE_USER_SECRET for user-scoped calls.
Note: SNAPTRADE_CLIENT_SECRET is NOT used for API calls;
      it is only for webhook signature verification.

Environment Variables:
    REQUIRE_SNAPTRADE: If '1' pipeline aborts on failure. Default '0'.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

try:
    import pyarrow as pa
    import pyarrow.parquet as pq

    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False

try:
    from snaptrade_client import SnapTrade
except Exception as e:
    SnapTrade = None
    logging.warning(f"SnapTrade SDK import failed: {e}")

from src.config import settings

# Pipeline resiliency: when False (default), SnapTrade failures are non-fatal
REQUIRE_SNAPTRADE = os.environ.get("REQUIRE_SNAPTRADE", "0") == "1"

logger = logging.getLogger(__name__)

# Define directories
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"

# Create directories if they don't exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


class SnapTradeCollector:
    """SnapTrade data collection and ETL operations."""

    def __init__(self):
        """Initialize the SnapTrade collector."""
        self.client = None
        self.config = settings()
        self._initialize_client()

    def _initialize_client(self):
        """Initialize the SnapTrade client with credentials."""
        if SnapTrade is None:
            raise ImportError("SnapTrade SDK is not available")

        client_id = getattr(self.config, "SNAPTRADE_CLIENT_ID", "") or getattr(
            self.config, "snaptrade_client_id", ""
        )
        consumer_key = getattr(self.config, "SNAPTRADE_CONSUMER_KEY", "") or getattr(
            self.config, "snaptrade_consumer_key", ""
        )

        if not client_id or not consumer_key:
            raise ValueError("Missing SnapTrade credentials in environment variables")

        self.client = SnapTrade(client_id=client_id, consumer_key=consumer_key)
        logger.info("✅ SnapTrade client initialized successfully")

    def _get_user_credentials(self) -> Tuple[str, str]:
        """Get user credentials from config."""
        user_id = (
            getattr(self.config, "SNAPTRADE_USER_ID", "")
            or getattr(self.config, "snaptrade_user_id", "")
            or getattr(self.config, "userid", "")
        )
        user_secret = (
            getattr(self.config, "SNAPTRADE_USER_SECRET", "")
            or getattr(self.config, "snaptrade_user_secret", "")
            or getattr(self.config, "usersecret", "")
        )

        if not user_id or not user_secret:
            raise ValueError("Missing SnapTrade user credentials")

        return user_id, user_secret

    def log_credentials_debug_info(self) -> Dict[str, Any]:
        """
        Log debug-safe information about credentials without exposing secrets.
        Prints whether each SnapTrade env var is defined (never prints values).

        Returns:
            Dict with credential status info (safe to log)
        """
        client_id = getattr(self.config, "SNAPTRADE_CLIENT_ID", "") or getattr(
            self.config, "snaptrade_client_id", ""
        )
        consumer_key = getattr(self.config, "SNAPTRADE_CONSUMER_KEY", "") or getattr(
            self.config, "snaptrade_consumer_key", ""
        )
        user_id = (
            getattr(self.config, "SNAPTRADE_USER_ID", "")
            or getattr(self.config, "snaptrade_user_id", "")
            or getattr(self.config, "userid", "")
        )
        user_secret = (
            getattr(self.config, "SNAPTRADE_USER_SECRET", "")
            or getattr(self.config, "snaptrade_user_secret", "")
            or getattr(self.config, "usersecret", "")
        )
        # CLIENT_SECRET is ONLY for webhook verification, never for API calls
        client_secret = getattr(self.config, "SNAPTRADE_CLIENT_SECRET", "") or getattr(
            self.config, "snaptrade_client_secret", ""
        )

        debug_info = {
            "SNAPTRADE_CLIENT_ID": bool(client_id),
            "SNAPTRADE_CONSUMER_KEY": bool(consumer_key),
            "SNAPTRADE_USER_ID": bool(user_id),
            "SNAPTRADE_USER_SECRET": bool(user_secret),
            "SNAPTRADE_CLIENT_SECRET (webhook only)": bool(client_secret),
            "REQUIRE_SNAPTRADE": REQUIRE_SNAPTRADE,
            "app_keys_present": bool(client_id and consumer_key),
            "user_keys_present": bool(user_id and user_secret),
            "user_id_length": len(user_id) if user_id else 0,
            "client_id_length": len(client_id) if client_id else 0,
        }

        logger.info(f"🔐 SnapTrade credentials status: {debug_info}")
        return debug_info

    def verify_user_auth(self) -> Tuple[bool, str]:
        """
        Smoke test: verify user authentication by calling list_user_accounts.

        This is the lightest user-scoped call. If it returns 401, the user
        needs to re-link their brokerage or rotate SNAPTRADE_USER_SECRET.

        Returns:
            Tuple of (success: bool, message: str)
        """
        # Log debug info first (safe - no secrets exposed)
        self.log_credentials_debug_info()

        try:
            user_id, user_secret = self._get_user_credentials()
        except ValueError as e:
            return False, f"Missing user credentials: {e}"

        try:
            # Use list_user_accounts (lightest user-scoped call)
            response = self.client.account_information.list_user_accounts(
                user_id=user_id,
                user_secret=user_secret,
            )

            # If we get here without exception, auth is valid
            data, _ = self.safely_extract_response_data(response, "verify_user_auth")

            if data is not None:
                account_count = len(data) if isinstance(data, list) else 1
                logger.info(
                    f"✅ SnapTrade user auth verified ({account_count} accounts)"
                )
                return True, f"User authentication verified ({account_count} accounts)"
            else:
                return False, "Empty response from list_user_accounts"

        except Exception as e:
            error_str = str(e).lower()

            # Check for specific auth errors
            if "401" in error_str or "1076" in error_str or "unauthorized" in error_str:
                msg = (
                    "SnapTrade user auth failed – re-link user or rotate user secret. "
                    "(HTTP 401 / error 1076). "
                    "Check SNAPTRADE_USER_ID and SNAPTRADE_USER_SECRET are current."
                )
                logger.error(f"🔒 {msg}")
                return False, msg

            # Other errors
            msg = f"SnapTrade auth check failed: {e}"
            logger.error(msg)
            return False, msg

    def safely_extract_response_data(
        self, response, operation_name="API call", max_sample_items=3
    ) -> Tuple[Any, bool]:
        """
        Safely extract data from SnapTrade API response objects.

        Args:
            response: SnapTrade API response object
            operation_name: Name of the operation for logging
            max_sample_items: Maximum number of items to log as samples

        Returns:
            tuple: (data, is_list) where data is the extracted content and is_list indicates if it's a list
        """
        logger.info(f"🔍 Analyzing SnapTrade response for {operation_name}")

        # Check response type and available attributes
        response_type = type(response).__name__
        available_attrs = [
            attr
            for attr in ["parsed", "body", "data", "content"]
            if hasattr(response, attr)
        ]
        logger.info(
            f"Response type: {response_type}, Available attributes: {available_attrs}"
        )

        data = None
        data_source = None

        # Try to extract data from different possible attributes in order of preference
        for attr in ["parsed", "body", "data", "content"]:
            if hasattr(response, attr):
                candidate_data = getattr(response, attr)
                if candidate_data is not None:
                    data = candidate_data
                    data_source = attr
                    logger.info(f"✅ Data extracted from response.{attr}")
                    break

        if data is None:
            logger.warning(f"⚠️ No data found in response for {operation_name}")
            return None, False

        # Determine if data is a list and log sample
        is_list = isinstance(data, (list, tuple))
        data_length = len(data) if hasattr(data, "__len__") else "unknown"

        logger.info(
            f"Data type: {type(data).__name__}, Is list: {is_list}, Length: {data_length}"
        )

        # Log sample data safely
        try:
            if is_list and len(data) > 0:
                sample_size = min(max_sample_items, len(data))
                logger.info(f"📋 Sample data (first {sample_size} items):")
                for i in range(sample_size):
                    item = data[i]
                    if isinstance(item, dict):
                        item_keys = list(item.keys())[:10]
                        sample_values = {k: item.get(k) for k in item_keys[:3]}
                        logger.info(
                            f"  Item {i+1}: Keys({len(item)} total): {item_keys}"
                        )
                        logger.info(
                            f"           Sample values: {json.dumps(sample_values, default=str, indent=10)}"
                        )
                    else:
                        logger.info(f"  Item {i+1}: {item}")
            elif isinstance(data, dict):
                data_keys = list(data.keys())[:10]
                sample_values = {k: data.get(k) for k in data_keys[:5]}
                logger.info(f"📋 Dict response - Keys({len(data)} total): {data_keys}")
                logger.info(
                    f"Sample values: {json.dumps(sample_values, default=str, indent=2)}"
                )
            else:
                data_str = str(data)
                truncated_data = (
                    data_str[:500] + "..." if len(data_str) > 500 else data_str
                )
                logger.info(f"📋 Data sample: {truncated_data}")
        except Exception as e:
            logger.warning(f"⚠️ Could not log sample data: {e}")

        return data, is_list

    def extract_symbol_from_data(self, symbol_data) -> Optional[str]:
        """
        Extract a clean ticker string from SnapTrade symbol payload.

        Args:
            symbol_data: String or nested dictionary containing symbol information

        Returns:
            Cleaned ticker string if found, otherwise None
        """
        if isinstance(symbol_data, str):
            return symbol_data.strip()

        if not isinstance(symbol_data, dict):
            return None

        # Search priority (avoid 'id' until last)
        keys = [
            "raw_symbol",
            "symbol",
            "SYMBOL",
            "ticker",
            "Ticker",
            "universal_symbol_symbol",
            "instrument_symbol",
        ]

        def _search(d: dict):
            # Look at preferred keys first
            for k in keys:
                if k in d:
                    v = d[k]
                    if isinstance(v, str) and v.strip():
                        return v.strip()
                    if isinstance(v, dict):
                        found = _search(v)
                        if found:
                            return found

            # Scan other nested dicts
            for v in d.values():
                if isinstance(v, dict):
                    found = _search(v)
                    if found:
                        return found
            return None

        result = _search(symbol_data)
        if result:
            return result

        # Last resort: short "id" values that look like tickers, not UUIDs
        id_val = symbol_data.get("id")
        if isinstance(id_val, str) and "-" not in id_val and len(id_val) <= 5:
            return id_val.strip()

        return None

    def get_accounts(self) -> pd.DataFrame:
        """
        Get user accounts with enhanced field extraction.

        Returns:
            DataFrame with account information
        """
        if not self.client:
            logger.error("SnapTrade client not initialized")
            return pd.DataFrame()

        user_id, user_secret = self._get_user_credentials()

        response = self.client.account_information.list_user_accounts(
            user_id=user_id, user_secret=user_secret
        )

        data, is_list = self.safely_extract_response_data(
            response, "list_user_accounts"
        )

        if not data:
            logger.warning("No accounts data found")
            return pd.DataFrame()

        if not is_list:
            data = [data]

        accounts = []
        for account in data:
            try:
                # Extract last successful sync
                last_successful_sync = None
                try:
                    sync_status = account.get("sync_status", {})
                    if isinstance(sync_status, dict):
                        holdings = sync_status.get("holdings", {})
                        if isinstance(holdings, dict):
                            last_successful_sync = holdings.get("last_successful_sync")
                except (KeyError, TypeError, AttributeError):
                    pass

                # Extract total equity
                total_equity = None
                try:
                    balance = account.get("balance", {})
                    if isinstance(balance, dict):
                        total = balance.get("total", {})
                        if isinstance(total, dict):
                            total_equity = total.get("amount")
                except (KeyError, TypeError, AttributeError):
                    pass

                accounts.append(
                    {
                        "id": account.get("id"),
                        "brokerage_authorization": account.get(
                            "brokerage_authorization"
                        ),
                        "portfolio_group": account.get("portfolio_group"),
                        "name": account.get("name"),
                        "number": account.get("number"),
                        "institution_name": account.get("institution_name"),
                        "last_successful_sync": last_successful_sync,
                        "total_equity": total_equity,
                        "sync_timestamp": datetime.now(timezone.utc),
                    }
                )
            except Exception as e:
                logger.error(
                    f"Error processing account {account.get('id', 'unknown')}: {e}"
                )
                continue

        df = pd.DataFrame(accounts)
        logger.info(f"✅ Processed {len(df)} accounts")
        return df

    def get_balances(self, account_id: Optional[str] = None) -> pd.DataFrame:
        """
        Get account balances with currency breakdown.

        Args:
            account_id: Optional account ID filter

        Returns:
            DataFrame with balance information per currency
        """
        if not self.client:
            logger.error("SnapTrade client not initialized")
            return pd.DataFrame()

        user_id, user_secret = self._get_user_credentials()

        # Get account ID from config if not provided
        if not account_id:
            account_id = getattr(self.config, "ROBINHOOD_ACCOUNT_ID", "") or getattr(
                self.config, "robinhood_account_id", ""
            )

        if not account_id:
            raise ValueError("Account ID is required for balance retrieval")

        response = self.client.account_information.get_user_account_balance(
            account_id=account_id, user_id=user_id, user_secret=user_secret
        )

        data, is_list = self.safely_extract_response_data(
            response, "get_user_account_balance"
        )

        if not data:
            logger.warning("No balance data found")
            return pd.DataFrame()

        if not is_list:
            data = [data]

        balances = []
        snapshot_date = datetime.now(timezone.utc).date()

        for balance in data:
            try:
                currency = balance.get("currency", {})
                if isinstance(currency, dict):
                    balances.append(
                        {
                            "account_id": account_id,
                            "currency_code": currency.get("code"),
                            "currency_name": currency.get("name"),
                            "currency_id": currency.get("id"),
                            "cash": balance.get("cash"),
                            "buying_power": balance.get("buying_power"),
                            "snapshot_date": snapshot_date,
                            "sync_timestamp": datetime.now(timezone.utc),
                        }
                    )
            except Exception as e:
                logger.error(f"Error processing balance: {e}")
                continue

        df = pd.DataFrame(balances)
        logger.info(f"✅ Processed {len(df)} currency balances")
        return df

    def get_positions(self, account_id: Optional[str] = None) -> pd.DataFrame:
        """
        Get account positions with enhanced field extraction.

        Args:
            account_id: Optional account ID filter

        Returns:
            DataFrame with position information
        """
        if not self.client:
            logger.error("SnapTrade client not initialized")
            return pd.DataFrame()

        user_id, user_secret = self._get_user_credentials()

        # Get account ID from config if not provided
        if not account_id:
            account_id = getattr(self.config, "ROBINHOOD_ACCOUNT_ID", "") or getattr(
                self.config, "robinhood_account_id", ""
            )

        if not account_id:
            raise ValueError("Account ID is required for position retrieval")

        response = self.client.account_information.get_user_account_positions(
            account_id=account_id, user_id=user_id, user_secret=user_secret
        )

        data, is_list = self.safely_extract_response_data(
            response, "get_user_account_positions"
        )

        if not data:
            logger.warning("No positions data found")
            return pd.DataFrame()

        if not is_list:
            data = [data]

        positions = []
        for position in data:
            try:
                # Use enhanced position extraction
                enhanced_position = self.extract_position_data(position, account_id)
                enhanced_position["sync_timestamp"] = datetime.now(timezone.utc)
                positions.append(enhanced_position)
            except Exception as e:
                logger.error(f"Error processing position: {e}")
                continue

        df = pd.DataFrame(positions)
        if not df.empty:
            df = df.sort_values("equity", ascending=False)
        logger.info(f"✅ Processed {len(df)} positions")
        return df

    def get_orders(
        self, account_id: Optional[str] = None, state: str = "all", days: int = 365
    ) -> pd.DataFrame:
        """
        Get account orders with comprehensive field extraction.

        Args:
            account_id: Optional account ID filter
            state: Order state filter
            days: Number of days to look back

        Returns:
            DataFrame with order information
        """
        if not self.client:
            logger.error("SnapTrade client not initialized")
            return pd.DataFrame()

        user_id, user_secret = self._get_user_credentials()

        # Get account ID from config if not provided
        if not account_id:
            account_id = getattr(self.config, "ROBINHOOD_ACCOUNT_ID", "") or getattr(
                self.config, "robinhood_account_id", ""
            )

        if not account_id:
            raise ValueError("Account ID is required for order retrieval")

        response = self.client.account_information.get_user_account_orders(
            account_id=account_id,
            user_id=user_id,
            user_secret=user_secret,
            state=state,
            days=days,
        )

        data, is_list = self.safely_extract_response_data(
            response, "get_user_account_orders"
        )

        if not data:
            logger.warning("No orders data found")
            return pd.DataFrame()

        if not is_list:
            data = [data]

        orders = []
        for order in data:
            try:
                # Extract basic order fields
                brokerage_order_id = order.get("brokerage_order_id")
                status = order.get("status")

                # Map invalid status values to valid ones
                # SnapTrade sometimes returns "NONE" for pending orders
                if status == "NONE" or not status:
                    status = "PENDING"

                action = order.get("action")

                # Extract symbol (sometimes present as string)
                symbol = order.get("symbol")

                # Extract universal_symbol and canonical symbol
                universal_symbol = order.get("universal_symbol")
                canonical_symbol = None

                if isinstance(universal_symbol, dict):
                    # Try to extract symbol from universal_symbol.symbol.symbol
                    nested_symbol = universal_symbol.get("symbol", {})
                    if isinstance(nested_symbol, dict):
                        canonical_symbol = nested_symbol.get("symbol")

                    # Fallback to raw_symbol
                    if not canonical_symbol:
                        canonical_symbol = universal_symbol.get("raw_symbol")

                # Use string symbol as fallback
                if not canonical_symbol and isinstance(symbol, str):
                    canonical_symbol = symbol

                # Extract quote_universal_symbol and option_symbol
                quote_universal_symbol = order.get("quote_universal_symbol")
                option_symbol = order.get("option_symbol")

                # Extract quantities and prices
                total_quantity = order.get("total_quantity")
                open_quantity = order.get("open_quantity")
                canceled_quantity = order.get("canceled_quantity")
                filled_quantity = order.get("filled_quantity")
                execution_price = order.get("execution_price")
                limit_price = order.get("limit_price")
                stop_price = order.get("stop_price")

                # Extract order type and time in force
                order_type = order.get("order_type")
                time_in_force = order.get("time_in_force")

                # Extract timestamps
                time_placed = order.get("time_placed")
                time_updated = order.get("time_updated")
                time_executed = order.get("time_executed")
                expiry_date = order.get("expiry_date")

                # Extract child order IDs as Python list
                child_brokerage_order_ids = order.get("child_brokerage_order_ids", [])
                # Ensure it's a list, not a string
                if not isinstance(child_brokerage_order_ids, list):
                    child_brokerage_order_ids = []

                # Extract option-specific fields
                option_ticker = None
                option_expiry = None
                option_strike = None
                option_right = None

                if isinstance(option_symbol, dict):
                    option_ticker = option_symbol.get("ticker")
                    option_expiry = option_symbol.get("expiry")
                    option_strike = option_symbol.get("strike")
                    option_right = option_symbol.get("right")

                # Ensure child_brokerage_order_ids is proper JSON array or None
                if child_brokerage_order_ids and len(child_brokerage_order_ids) > 0:
                    child_orders_json = child_brokerage_order_ids
                else:
                    child_orders_json = (
                        None  # Use None instead of empty list to be explicit
                    )

                orders.append(
                    {
                        "brokerage_order_id": brokerage_order_id,
                        "status": status,
                        "symbol": canonical_symbol
                        or "Unknown",  # Use canonical normalized ticker
                        "action": action,
                        "total_quantity": (
                            float(total_quantity) if total_quantity else None
                        ),
                        "open_quantity": (
                            float(open_quantity) if open_quantity else None
                        ),
                        "canceled_quantity": (
                            float(canceled_quantity) if canceled_quantity else None
                        ),
                        "filled_quantity": (
                            float(filled_quantity) if filled_quantity else None
                        ),
                        "execution_price": (
                            float(execution_price) if execution_price else None
                        ),
                        "limit_price": float(limit_price) if limit_price else None,
                        "stop_price": float(stop_price) if stop_price else None,
                        "order_type": order_type,
                        "time_in_force": time_in_force,
                        "time_placed": time_placed,
                        "time_updated": time_updated,
                        "time_executed": time_executed,
                        "expiry_date": expiry_date,
                        "child_brokerage_order_ids": child_orders_json,  # Proper JSON or None
                        "option_ticker": option_ticker,
                        "option_expiry": option_expiry,
                        "option_strike": (
                            float(option_strike) if option_strike else None
                        ),
                        "option_right": option_right,
                        "account_id": account_id,
                        "sync_timestamp": datetime.now(timezone.utc),
                        # Removed unused fields: state, user_secret, parent_brokerage_order_id,
                        # quote_currency_code, diary (all were always NULL)
                    }
                )
            except Exception as e:
                logger.error(
                    f"Error processing order {order.get('brokerage_order_id', 'unknown')}: {e}"
                )
                continue

        df = pd.DataFrame(orders)
        logger.info(f"✅ Processed {len(df)} orders")
        return df

    # ------------------------------------------------------------------
    # Activities  (account-level, paginated)
    # ------------------------------------------------------------------

    def get_activities(
        self,
        account_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        activity_type: Optional[str] = None,
        page_size: int = 1000,
    ) -> pd.DataFrame:
        """
        Fetch account activities from SnapTrade (buys, sells, dividends, fees, etc.).

        Uses the preferred account-level endpoint:
            GET /accounts/{accountId}/activities
        which supports offset/limit pagination (default limit 1000).

        The deprecated user-level ``/activities`` endpoint is intentionally
        NOT used.

        Args:
            account_id: Account ID (defaults to ROBINHOOD_ACCOUNT_ID from .env).
            start_date: Inclusive start date (YYYY-MM-DD). Default: 90 days ago.
            end_date: Inclusive end date (YYYY-MM-DD). Default: today.
            activity_type: Optional type filter (BUY, SELL, DIVIDEND, etc.).
            page_size: Number of records per request (max/default 1000).

        Returns:
            DataFrame with activity records ready for DB upsert.
        """
        if not self.client:
            logger.error("SnapTrade client not initialized")
            return pd.DataFrame()

        user_id, user_secret = self._get_user_credentials()

        # Default account – required for account-level endpoint
        if not account_id:
            account_id = getattr(self.config, "ROBINHOOD_ACCOUNT_ID", "") or getattr(
                self.config, "robinhood_account_id", ""
            )

        if not account_id:
            raise ValueError("Account ID is required for activity retrieval")

        # Default date range: last 90 days
        from datetime import timedelta

        if not start_date:
            start_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime(
                "%Y-%m-%d"
            )
        if not end_date:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        logger.info(
            f"🔄 Fetching activities for account={account_id}, "
            f"range={start_date}..{end_date}, type={activity_type or 'ALL'}"
        )

        # ── Paginated fetch ──────────────────────────────────────────
        all_raw: List[Any] = []
        offset = 0

        while True:
            kwargs: Dict[str, Any] = {
                "account_id": account_id,
                "user_id": user_id,
                "user_secret": user_secret,
                "start_date": start_date,
                "end_date": end_date,
                "offset": offset,
                "limit": page_size,
            }
            if activity_type:
                kwargs["type"] = activity_type

            try:
                response = self.client.account_information.get_account_activities(
                    **kwargs
                )
            except Exception as e:
                logger.error(f"SnapTrade get_account_activities API error: {e}")
                break

            # PaginatedUniversalActivity → .data (list), .pagination (offset/limit/total)
            # The response object may expose data via .parsed, .body, .data, or .content.
            # We try each attribute to locate the list; pagination info lives alongside it.
            page_items: list = []
            total_available: Optional[int] = None

            # Prefer direct attribute access on well-typed SDK response
            if hasattr(response, "data") and isinstance(response.data, list):
                page_items = response.data
                pag = getattr(response, "pagination", None)
                if pag is not None:
                    total_available = getattr(pag, "total", None)
            else:
                # Fallback: use generic extractor (handles parsed/body/content)
                data, is_list = self.safely_extract_response_data(
                    response, f"get_account_activities (offset={offset})"
                )
                if isinstance(data, dict):
                    # dict with "data" + "pagination" keys
                    page_items = data.get("data", [])
                    pag_dict = data.get("pagination", {})
                    total_available = (
                        pag_dict.get("total") if isinstance(pag_dict, dict) else None
                    )
                elif isinstance(data, list):
                    page_items = data
                elif data is None:
                    page_items = []

            if not page_items:
                if offset == 0:
                    logger.warning("No activities data returned from SnapTrade")
                break

            all_raw.extend(page_items)
            fetched_so_far = len(all_raw)

            # Determine whether more pages exist
            if total_available is not None:
                logger.info(
                    f"   Page offset={offset}: {len(page_items)} items "
                    f"({fetched_so_far}/{total_available} total)"
                )
                if fetched_so_far >= total_available:
                    break
            else:
                # No total count available — stop when page is short
                logger.info(
                    f"   Page offset={offset}: {len(page_items)} items (no total)"
                )
                if len(page_items) < page_size:
                    break

            offset += page_size

        if not all_raw:
            return pd.DataFrame()

        # ── Parse each activity record ───────────────────────────────
        activities: List[Dict[str, Any]] = []
        for act in all_raw:
            try:
                # Normalise – SDK may give dict-like objects with .get()
                if not isinstance(act, dict):
                    act = dict(act) if hasattr(act, "__iter__") else vars(act)

                activity_id = act.get("id")
                if not activity_id:
                    logger.debug("Skipping activity with no id")
                    continue

                # Extract symbol – account-level activities may use a simpler
                # structure than the user-level endpoint; handle both.
                symbol_obj = act.get("symbol")
                extracted_symbol = None
                if isinstance(symbol_obj, dict):
                    inner = symbol_obj.get("symbol", {})
                    if isinstance(inner, dict):
                        extracted_symbol = inner.get("symbol") or inner.get(
                            "raw_symbol"
                        )
                    elif isinstance(inner, str):
                        extracted_symbol = inner
                    if not extracted_symbol:
                        extracted_symbol = symbol_obj.get("raw_symbol")
                elif isinstance(symbol_obj, str):
                    extracted_symbol = symbol_obj

                # Account-level endpoint has no nested .account — use param
                act_account = act.get("account")
                if isinstance(act_account, dict):
                    act_account_id = act_account.get("id", account_id)
                else:
                    act_account_id = account_id

                # Extract currency
                currency_obj = act.get("currency")
                currency_code = "USD"
                if isinstance(currency_obj, dict):
                    currency_code = currency_obj.get("code", "USD")
                elif isinstance(currency_obj, str):
                    currency_code = currency_obj

                activities.append(
                    {
                        "id": str(activity_id),
                        "account_id": str(act_account_id),
                        "activity_type": act.get("type"),
                        "trade_date": act.get("trade_date"),
                        "settlement_date": act.get("settlement_date"),
                        "amount": (
                            float(act["amount"])
                            if act.get("amount") is not None
                            else None
                        ),
                        "price": (
                            float(act["price"])
                            if act.get("price") is not None
                            else None
                        ),
                        "units": (
                            float(act["units"])
                            if act.get("units") is not None
                            else None
                        ),
                        "symbol": extracted_symbol,
                        "description": act.get("description"),
                        "currency": currency_code,
                        "fee": float(act.get("fee") or 0),
                        "fx_rate": (
                            float(act["fx_rate"])
                            if act.get("fx_rate") is not None
                            else None
                        ),
                        "external_reference_id": act.get("external_reference_id"),
                        "institution": act.get("institution"),
                        "option_type": act.get("option_type"),
                        "sync_timestamp": datetime.now(timezone.utc),
                    }
                )
            except Exception as e:
                logger.error(
                    f"Error processing activity {act.get('id', 'unknown')}: {e}"
                )
                continue

        df = pd.DataFrame(activities)
        logger.info(
            f"✅ Processed {len(df)} activities across {offset // page_size + 1} page(s)"
        )
        return df

    def upsert_symbols_table(self, symbols_data: List[Dict]) -> bool:
        """
        Upsert symbols into the symbols table with comprehensive field updates.

        Uses INSERT ... ON CONFLICT (id) DO UPDATE to backfill all symbol metadata.
        This ensures existing symbols get updated with new information while
        preventing duplicate entries.

        Args:
            symbols_data: List of symbol dictionaries with complete metadata

        Returns:
            True if successful, False otherwise
        """
        if not symbols_data:
            return True

        try:
            # Use unified database layer for symbols
            from src.db import execute_sql

            for symbol in symbols_data:
                # SnapTrade ingestion guard: only upsert when ticker is non-empty/known
                ticker = symbol.get("ticker")
                if not ticker or str(ticker).lower() in ("unknown", "none", ""):
                    logger.debug(f"⏭️ Skipping symbol with invalid ticker: {ticker}")
                    continue

                execute_sql(
                    """
                    INSERT INTO symbols (
                        id, ticker, raw_symbol, description, asset_type, type_code,
                        exchange_code, exchange_name, exchange_mic, figi_code,
                        logo_url, base_currency_code, is_supported,
                        is_quotable, is_tradable, created_at, updated_at
                    )
                    VALUES (
                        :id, :ticker, :raw_symbol, :description, :asset_type, :type_code,
                        :exchange_code, :exchange_name, :exchange_mic, :figi_code,
                        :logo_url, :base_currency_code, :is_supported,
                        :is_quotable, :is_tradable, :created_at, :updated_at
                    )
                    ON CONFLICT (ticker) DO UPDATE SET
                        id = COALESCE(EXCLUDED.id, symbols.id),
                        raw_symbol = COALESCE(EXCLUDED.raw_symbol, symbols.raw_symbol),
                        description = COALESCE(EXCLUDED.description, symbols.description),
                        asset_type = COALESCE(EXCLUDED.asset_type, symbols.asset_type),
                        type_code = COALESCE(EXCLUDED.type_code, symbols.type_code),
                        exchange_code = COALESCE(EXCLUDED.exchange_code, symbols.exchange_code),
                        exchange_name = COALESCE(EXCLUDED.exchange_name, symbols.exchange_name),
                        exchange_mic = COALESCE(EXCLUDED.exchange_mic, symbols.exchange_mic),
                        figi_code = COALESCE(EXCLUDED.figi_code, symbols.figi_code),
                        logo_url = COALESCE(EXCLUDED.logo_url, symbols.logo_url),
                        base_currency_code = COALESCE(EXCLUDED.base_currency_code, symbols.base_currency_code),
                        is_supported = EXCLUDED.is_supported,
                        is_quotable = EXCLUDED.is_quotable,
                        is_tradable = EXCLUDED.is_tradable,
                        updated_at = EXCLUDED.updated_at
                    """,
                    {
                        "id": symbol.get("id"),
                        "ticker": symbol.get("ticker"),
                        "raw_symbol": symbol.get("raw_symbol"),
                        "description": symbol.get("description"),
                        "asset_type": symbol.get("asset_type"),
                        "type_code": symbol.get("type_code"),
                        "exchange_code": symbol.get("exchange_code"),
                        "exchange_name": symbol.get("exchange_name"),
                        "exchange_mic": symbol.get("exchange_mic"),
                        "figi_code": symbol.get("figi_code"),
                        "logo_url": symbol.get("logo_url"),
                        "base_currency_code": symbol.get("base_currency_code"),
                        "is_supported": symbol.get("is_supported", True),
                        "is_quotable": symbol.get("is_quotable", True),
                        "is_tradable": symbol.get("is_tradable", True),
                        "created_at": symbol.get("created_at"),
                        "updated_at": symbol.get("updated_at"),
                    },
                )

            logger.info(f"✅ Upserted {len(symbols_data)} symbols to database")
            return True

        except Exception as e:
            logger.error(f"Error upserting symbols: {e}")
            return False

    def write_to_database(
        self,
        df: pd.DataFrame,
        table_name: str,
        conflict_columns: Optional[List[str]] = None,
    ) -> bool:
        """
        Write DataFrame to database with dual strategy.

        Args:
            df: DataFrame to write
            table_name: Target table name
            conflict_columns: Columns to use for conflict resolution

        Returns:
            True if successful, False otherwise
        """
        if df.empty:
            return True

        try:
            # Unified database approach with bulk operations and PostgreSQL compatibility
            from src.db import execute_sql, df_to_records

            # Convert DataFrame to dict records for bulk operation
            records = df_to_records(df)
            if not records:
                return True

            # Get column list from first record
            columns = [str(col) for col in records[0].keys()]
            column_list = ", ".join(columns)
            placeholders = ", ".join([f":{col}" for col in columns])

            if conflict_columns:
                # ON CONFLICT DO UPDATE with named placeholders
                conflict_cols = ", ".join(conflict_columns)
                update_set = ", ".join(
                    [
                        f"{col} = EXCLUDED.{col}"
                        for col in columns
                        if col not in conflict_columns
                    ]
                )
                sql = f"""
                    INSERT INTO {table_name} ({column_list})
                    VALUES ({placeholders})
                    ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_set}
                """
            else:
                # ON CONFLICT DO NOTHING with named placeholders
                sql = f"""
                    INSERT INTO {table_name} ({column_list})
                    VALUES ({placeholders})
                    ON CONFLICT DO NOTHING
                """

            # Execute bulk operation with list of dicts (SQLAlchemy 2.0 compatible)
            execute_sql(sql, records)

            logger.info(
                f"✅ Wrote {len(df)} records to Supabase {table_name} via unified database layer"
            )
            return True

        except Exception as e:
            logger.error(f"Error writing to {table_name}: {e}")
            return False

    def write_parquet_snapshot(
        self, df: pd.DataFrame, table_name: str
    ) -> Optional[Path]:
        """
        Write DataFrame to Parquet snapshot file.

        Args:
            df: DataFrame to write
            table_name: Table name for file naming

        Returns:
            Path to written file or None if failed
        """
        if not PYARROW_AVAILABLE:
            logger.warning("PyArrow not available, skipping Parquet snapshot")
            return None

        if df.empty:
            return None

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"snaptrade_{table_name}_{timestamp}.parquet"
            filepath = RAW_DIR / filename

            # Convert to PyArrow table and write with compression
            table = pa.Table.from_pandas(df)
            pq.write_table(table, filepath, compression="snappy")

            logger.info(f"📁 Wrote {len(df)} records to Parquet: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Error writing Parquet snapshot for {table_name}: {e}")
            return None

    def collect_all_data(
        self, write_parquet: bool = True, account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Collect all SnapTrade data types.

        Args:
            write_parquet: Whether to write Parquet snapshots
            account_id: Optional account ID filter

        Returns:
            Dictionary with collection results
        """
        results = {
            "success": True,
            "accounts": 0,
            "balances": 0,
            "positions": 0,
            "orders": 0,
            "activities": 0,
            "symbols": 0,
            "errors": [],
        }

        try:
            # Collect accounts
            logger.info("🔄 Collecting accounts...")
            accounts_df = self.get_accounts()
            if not accounts_df.empty:
                self.write_to_database(accounts_df, "accounts", conflict_columns=["id"])
                if write_parquet:
                    self.write_parquet_snapshot(accounts_df, "accounts")
                results["accounts"] = len(accounts_df)

            # Collect balances
            logger.info("🔄 Collecting balances...")
            balances_df = self.get_balances(account_id)
            if not balances_df.empty:
                # CRITICAL: PK order is (currency_code, snapshot_date, account_id) in live DB
                self.write_to_database(
                    balances_df,
                    "account_balances",
                    conflict_columns=["currency_code", "snapshot_date", "account_id"],
                )
                if write_parquet:
                    self.write_parquet_snapshot(balances_df, "balances")
                results["balances"] = len(balances_df)

            # Collect positions
            logger.info("🔄 Collecting positions...")
            positions_df = self.get_positions(account_id)
            if not positions_df.empty:
                # Validate positions have account_id before database write
                missing_account = positions_df["account_id"].isna().sum()
                if missing_account > 0:
                    logger.warning(
                        f"⚠️ {missing_account} positions missing account_id - skipping database write"
                    )
                    results["positions"] = 0
                    results["errors"].append(
                        f"Positions missing account_id: {missing_account}"
                    )
                else:
                    # Drop symbol metadata columns that belong in symbols table
                    # Positions table only stores symbol (ticker) and account_id as composite PK
                    positions_for_db = positions_df.drop(
                        columns=["raw_symbol", "type_code"], errors="ignore"
                    )

                    # FIXED: PK order is (symbol, account_id) in live DB - must match exactly
                    self.write_to_database(
                        positions_for_db,
                        "positions",
                        conflict_columns=["symbol", "account_id"],
                    )
                    if write_parquet:
                        self.write_parquet_snapshot(positions_df, "positions")
                    results["positions"] = len(positions_df)

                # Extract symbols from positions
                symbols_data = self._extract_symbols_from_positions(positions_df)
                if symbols_data:
                    self.upsert_symbols_table(symbols_data)
                    results["symbols"] += len(symbols_data)

            # Collect orders
            logger.info("🔄 Collecting orders...")
            orders_df = self.get_orders(account_id)
            if not orders_df.empty:
                # Validate orders have account_id before database write
                missing_account = orders_df["account_id"].isna().sum()
                if missing_account > 0:
                    logger.warning(
                        f"⚠️ {missing_account} orders missing account_id - skipping database write"
                    )
                    results["orders"] = 0
                    results["errors"].append(
                        f"Orders missing account_id: {missing_account}"
                    )
                else:
                    self.write_to_database(
                        orders_df, "orders", conflict_columns=["brokerage_order_id"]
                    )
                    if write_parquet:
                        self.write_parquet_snapshot(orders_df, "orders")
                    results["orders"] = len(orders_df)

                # Extract symbols from orders
                symbols_data = self._extract_symbols_from_orders(orders_df)
                if symbols_data:
                    self.upsert_symbols_table(symbols_data)
                    results["symbols"] += len(symbols_data)

            # Collect activities
            logger.info("🔄 Collecting activities...")
            try:
                activities_df = self.get_activities(account_id)
                if not activities_df.empty:
                    self.write_to_database(
                        activities_df, "activities", conflict_columns=["id"]
                    )
                    if write_parquet:
                        self.write_parquet_snapshot(activities_df, "activities")
                    results["activities"] = len(activities_df)
            except Exception as act_err:
                logger.warning(f"⚠️ Activities collection failed (non-fatal): {act_err}")
                results["errors"].append(f"Activities: {act_err}")

        except Exception as e:
            logger.error(f"Error in collect_all_data: {e}")
            results["success"] = False
            results["errors"].append(str(e))

        # Enforce REQUIRE_SNAPTRADE policy
        if not results["success"] and REQUIRE_SNAPTRADE:
            raise RuntimeError(
                f"SnapTrade collection failed and REQUIRE_SNAPTRADE=1: {results['errors']}"
            )

        logger.info(f"✅ Collection complete: {results}")
        return results

    def _extract_symbols_from_positions(self, positions_df: pd.DataFrame) -> List[Dict]:
        """Extract symbol metadata from positions DataFrame with complete field mapping."""
        symbols = []

        for _, row in positions_df.iterrows():
            try:
                symbol_val = str(row["symbol"]) if row["symbol"] is not None else None
                if symbol_val and symbol_val.lower() not in ("unknown", "none", ""):
                    # Use actual symbol_id from SnapTrade, not fake prefixed ID
                    symbol_id = row.get("symbol_id")
                    if not symbol_id:
                        # Fallback: use ticker as ID if symbol_id not available
                        symbol_id = row["symbol"]

                    symbol_data = {
                        "id": symbol_id,  # Actual SnapTrade symbol ID
                        "ticker": row["symbol"],  # Ticker (may have exchange suffix)
                        "raw_symbol": row.get("raw_symbol")
                        or row["symbol"],  # Plain ticker
                        "description": row.get("symbol_description"),
                        "asset_type": row.get("asset_type"),  # Like "Common Stock"
                        "type_code": row.get("type_code"),  # Like "cs", "etf"
                        "exchange_code": row.get("exchange_code"),
                        "exchange_name": row.get("exchange_name"),
                        "exchange_mic": row.get("mic_code"),
                        "figi_code": row.get("figi_code"),
                        "logo_url": row.get("logo_url"),
                        "base_currency_code": row.get("currency"),
                        "is_supported": True,
                        "is_quotable": True,
                        "is_tradable": True,
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                    symbols.append(symbol_data)
            except Exception as e:
                logger.warning(f"Error extracting symbol from position: {e}")
                continue

        return symbols

    def _extract_symbols_from_orders(self, orders_df: pd.DataFrame) -> List[Dict]:
        """Extract symbol metadata from orders DataFrame with complete field mapping."""
        import re

        symbols = []
        # UUID pattern to filter out invalid symbol IDs from SnapTrade API
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )

        for _, row in orders_df.iterrows():
            try:
                # Use symbol field (canonical normalized ticker)
                symbol_val = str(row["symbol"]) if row["symbol"] is not None else None

                # Skip invalid symbols: unknown, none, empty, or UUID-like strings
                if not symbol_val or symbol_val.lower() in ("unknown", "none", ""):
                    continue

                if uuid_pattern.match(symbol_val):
                    logger.debug(f"Skipping UUID-like symbol from order: {symbol_val}")
                    continue

                # For orders, we may not have full symbol metadata
                # Use the symbol as both ID and ticker if no symbol_id available
                symbol_data = {
                    "id": row[
                        "symbol"
                    ],  # Use ticker as ID for orders (will merge with position data on UPSERT)
                    "ticker": row["symbol"],
                    "raw_symbol": row["symbol"],  # Assume no suffix in orders
                    "is_supported": True,
                    "is_quotable": True,
                    "is_tradable": True,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
                symbols.append(symbol_data)
            except Exception as e:
                logger.warning(f"Error extracting symbol from order: {e}")
                continue

        return symbols

    # ==============================================================================
    # DATABASE POSITION QUERIES (moved from market_data.py for centralization)
    # ==============================================================================

    def get_stored_positions(self) -> pd.DataFrame:
        """Return all portfolio positions as a DataFrame from the latest sync in the database."""
        from src.db import execute_sql

        try:
            # Get positions from the most recent sync timestamp
            query = """
            SELECT symbol, quantity, equity, price, average_buy_price, asset_type, currency, sync_timestamp, calculated_equity
            FROM positions
            WHERE sync_timestamp = (SELECT MAX(sync_timestamp) FROM positions)
            ORDER BY equity DESC
            """
            result = execute_sql(query, fetch_results=True)
            if result:
                columns = [
                    "symbol",
                    "quantity",
                    "equity",
                    "price",
                    "average_buy_price",
                    "asset_type",
                    "currency",
                    "sync_timestamp",
                    "calculated_equity",
                ]
                return pd.DataFrame(result, columns=columns)
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error getting stored positions: {e}")
            return pd.DataFrame()

    def get_stored_position(self, symbol: str) -> pd.DataFrame:
        """Return the most recent stored position for the given symbol."""
        from src.db import execute_sql

        try:
            # Get the most recent position for this symbol
            query = """
            SELECT symbol, quantity, equity, price, average_buy_price, asset_type, currency, sync_timestamp, calculated_equity
            FROM positions
            WHERE symbol = :symbol AND sync_timestamp = (SELECT MAX(sync_timestamp) FROM positions WHERE symbol = :symbol)
            """
            result = execute_sql(query, {"symbol": symbol}, fetch_results=True)
            if result:
                columns = [
                    "symbol",
                    "quantity",
                    "equity",
                    "price",
                    "average_buy_price",
                    "asset_type",
                    "currency",
                    "sync_timestamp",
                    "calculated_equity",
                ]
                return pd.DataFrame(result, columns=columns)
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error getting stored position for {symbol}: {e}")
            return pd.DataFrame()

    def extract_symbol_from_order_data(self, order: Dict) -> str:
        """
        Extract clean symbol from SnapTrade order structure with enhanced fallback hierarchy.

        Priority:
        1. order.symbol (if string)
        2. order.universal_symbol.symbol.symbol
        3. order.universal_symbol.raw_symbol

        Args:
            order: Order data from SnapTrade API

        Returns:
            str: Extracted symbol or "UNKNOWN"
        """
        # 1. Try direct symbol field first (canonical normalized ticker)
        symbol_field = order.get("symbol")
        if isinstance(symbol_field, str) and symbol_field.strip():
            return symbol_field.strip()

        # 2. Try extracted_symbol for backward compatibility (if already processed)
        if order.get("extracted_symbol"):
            return str(order["extracted_symbol"]).strip()

        # 3. Try universal_symbol nested structure
        universal_symbol = order.get("universal_symbol", {})
        if isinstance(universal_symbol, dict):
            # Try symbol.symbol (nested structure)
            symbol_obj = universal_symbol.get("symbol", {})
            if isinstance(symbol_obj, dict):
                nested_symbol = symbol_obj.get("symbol")
                if nested_symbol and isinstance(nested_symbol, str):
                    return nested_symbol.strip()

            # 4. Fallback to raw_symbol
            raw_symbol = universal_symbol.get("raw_symbol")
            if raw_symbol and isinstance(raw_symbol, str):
                return raw_symbol.strip()

        # 5. Last resort: try nested symbol extraction from symbol field if it's a dict
        if isinstance(symbol_field, dict):
            nested_result = self.extract_symbol_from_data(symbol_field)
            if nested_result:
                return nested_result

        return "UNKNOWN"

    def extract_position_data(self, position: Dict, account_id: str) -> Dict:
        """
        Extract enhanced position data with nested symbol structure parsing.

        Args:
            position: Position data from SnapTrade API
            account_id: Account ID to associate with the position

        Returns:
            dict: Enhanced position data with extracted symbol info
        """
        # Extract symbol information from nested structure
        symbol_data = position.get("symbol", {})

        # Handle nested position.symbol.symbol.symbol structure
        extracted_symbol = "UNKNOWN"
        symbol_id = None
        symbol_description = ""
        raw_symbol = ""  # Plain symbol without exchange suffix
        asset_type = "Unknown"
        type_code = ""  # Asset type code from SnapTrade
        exchange_code = ""
        exchange_name = ""
        mic_code = ""
        figi_code = ""
        logo_url = ""
        is_quotable = True
        is_tradable = True

        if isinstance(symbol_data, dict):
            # Navigate nested symbol structure: position.symbol.symbol
            inner_symbol = symbol_data.get("symbol", {})
            if isinstance(inner_symbol, dict):
                # Extract from innermost symbol object
                innermost_symbol = inner_symbol.get("symbol")
                if innermost_symbol:
                    extracted_symbol = innermost_symbol  # This is the ticker
                    symbol_id = inner_symbol.get("id")  # Actual SnapTrade symbol ID
                    symbol_description = inner_symbol.get("description", "")
                    logo_url = inner_symbol.get("logo_url", "")
                    figi_code = inner_symbol.get("figi_code", "")

                    # Extract raw_symbol (plain ticker without exchange suffix)
                    raw_symbol = inner_symbol.get("raw_symbol", innermost_symbol)

                    # Extract asset type with code
                    type_info = inner_symbol.get("type", {})
                    if isinstance(type_info, dict):
                        type_code = type_info.get("code", "")  # Like "cs", "etf", etc.
                        asset_type = type_info.get("description") or type_info.get(
                            "code", "Unknown"
                        )

                    # Extract exchange information
                    exchange_info = inner_symbol.get("exchange", {})
                    if isinstance(exchange_info, dict):
                        exchange_code = exchange_info.get("code", "")
                        exchange_name = exchange_info.get("name", "")
                        mic_code = exchange_info.get("mic_code", "")
                else:
                    # Fallback to raw_symbol if nested structure incomplete
                    raw_symbol = symbol_data.get("raw_symbol", "")
                    extracted_symbol = raw_symbol or "UNKNOWN"
            else:
                # Simple string symbol
                extracted_symbol = str(symbol_data) if symbol_data else "UNKNOWN"
                raw_symbol = extracted_symbol

        # Calculate quantities - prefer units, fallback to fractional_units
        quantity = position.get("units")
        if quantity is None:
            quantity = position.get("fractional_units", 0)

        # Calculate equity if not provided
        price = position.get("price", 0)
        equity = position.get("equity")
        if equity is None and quantity and price:
            equity = float(quantity) * float(price)

        # Extract currency info
        currency_info = position.get("currency", {})
        currency_code = "USD"
        if isinstance(currency_info, dict):
            currency_code = currency_info.get("code", "USD")
        elif isinstance(currency_info, str):
            currency_code = currency_info

        return {
            "symbol": extracted_symbol,  # Ticker (may have exchange suffix)
            "symbol_id": symbol_id,  # Actual SnapTrade ID
            "raw_symbol": raw_symbol,  # Plain ticker without suffix
            "symbol_description": symbol_description,
            "quantity": quantity,
            "price": price,
            "equity": equity,
            "average_buy_price": position.get("average_purchase_price"),
            "open_pnl": position.get("open_pnl"),
            "asset_type": asset_type,  # Description like "Common Stock"
            "type_code": type_code,  # Code like "cs", "etf"
            "currency": currency_code,
            "logo_url": logo_url,
            "exchange_code": exchange_code,
            "exchange_name": exchange_name,
            "mic_code": mic_code,
            "figi_code": figi_code,
            # Removed redundant boolean fields: is_quotable, is_tradable (always true)
            "account_id": account_id,  # Use the provided account_id parameter
        }


if __name__ == "__main__":
    # Example usage
    collector = SnapTradeCollector()
    results = collector.collect_all_data(write_parquet=True)
    print(f"Collection results: {results}")
