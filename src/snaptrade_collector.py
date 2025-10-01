"""
SnapTrade Data Collector Module

Dedicated module for SnapTrade ETL operations with enhanced field extraction,
dual database writes, and optional Parquet snapshots.
"""

import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

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

logger = logging.getLogger(__name__)

# Define directories
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
DB_DIR = BASE_DIR / "data" / "database"

# Create directories if they don't exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)

# File paths
PRICE_DB = DB_DIR / "price_history.db"


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
                        "child_brokerage_order_ids": child_brokerage_order_ids,  # Pass as Python list
                        "option_ticker": option_ticker,
                        "option_expiry": option_expiry,
                        "option_strike": (
                            float(option_strike) if option_strike else None
                        ),
                        "option_right": option_right,
                        "account_id": account_id,
                        "sync_timestamp": datetime.now(timezone.utc),
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

    def upsert_symbols_table(self, symbols_data: List[Dict]) -> bool:
        """
        Upsert symbols into the symbols table.
        Only upserts symbols with valid (non-empty, not 'unknown') tickers.

        Args:
            symbols_data: List of symbol dictionaries

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
                    INSERT INTO symbols (id, ticker, description, asset_type, type_code, 
                                       exchange_code, exchange_name, exchange_mic, figi_code,
                                       raw_symbol, logo_url, base_currency_code, is_supported,
                                       is_quotable, is_tradable, created_at, updated_at)
                    VALUES (:id, :ticker, :description, :asset_type, :type_code, :exchange_code, 
                           :exchange_name, :exchange_mic, :figi_code, :raw_symbol, :logo_url, 
                           :base_currency_code, :is_supported, :is_quotable, :is_tradable, 
                           :created_at, :updated_at)
                    ON CONFLICT (ticker) DO UPDATE SET
                        id = EXCLUDED.id,
                        description = EXCLUDED.description,
                        updated_at = EXCLUDED.updated_at
                """,
                    {
                        "id": symbol.get("id"),
                        "ticker": symbol.get("ticker"),
                        "description": symbol.get("description"),
                        "asset_type": symbol.get("asset_type"),
                        "type_code": symbol.get("type_code"),
                        "exchange_code": symbol.get("exchange_code"),
                        "exchange_name": symbol.get("exchange_name"),
                        "exchange_mic": symbol.get("exchange_mic"),
                        "figi_code": symbol.get("figi_code"),
                        "raw_symbol": symbol.get("raw_symbol"),
                        "logo_url": symbol.get("logo_url"),
                        "base_currency_code": symbol.get("base_currency_code"),
                        "is_supported": symbol.get("is_supported"),
                        "is_quotable": symbol.get("is_quotable"),
                        "is_tradable": symbol.get("is_tradable"),
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
                self.write_to_database(
                    balances_df,
                    "account_balances",
                    conflict_columns=["account_id", "currency_code", "snapshot_date"],
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
                    self.write_to_database(
                        positions_df,
                        "positions",
                        conflict_columns=["account_id", "symbol"],
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

        except Exception as e:
            logger.error(f"Error in collect_all_data: {e}")
            results["success"] = False
            results["errors"].append(str(e))

        logger.info(f"✅ Collection complete: {results}")
        return results

    def _extract_symbols_from_positions(self, positions_df: pd.DataFrame) -> List[Dict]:
        """Extract symbol metadata from positions DataFrame."""
        symbols = []

        for _, row in positions_df.iterrows():
            try:
                symbol_val = str(row["symbol"]) if row["symbol"] is not None else None
                if symbol_val and symbol_val.lower() not in ("unknown", "none", ""):
                    symbol_data = {
                        "id": f"pos_{row['symbol']}",
                        "ticker": row[
                            "symbol"
                        ],  # Canonical ticker for conflict resolution
                        "description": row.get("symbol_description"),
                        "asset_type": row.get("asset_type"),
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
        """Extract symbol metadata from orders DataFrame."""
        symbols = []

        for _, row in orders_df.iterrows():
            try:
                # Use symbol field (canonical normalized ticker) instead of extracted_symbol
                symbol_val = str(row["symbol"]) if row["symbol"] is not None else None
                if symbol_val and symbol_val.lower() not in ("unknown", "none", ""):
                    symbol_data = {
                        "id": f"ord_{row['symbol']}",
                        "ticker": row[
                            "symbol"
                        ],  # Canonical ticker for conflict resolution
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

        Returns:
            dict: Enhanced position data with extracted symbol info
        """
        # Extract symbol information from nested structure
        symbol_data = position.get("symbol", {})

        # Handle nested position.symbol.symbol.symbol structure
        extracted_symbol = "UNKNOWN"
        symbol_id = None
        symbol_description = ""
        asset_type = "Unknown"
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
                    extracted_symbol = innermost_symbol
                    symbol_id = inner_symbol.get("id")
                    symbol_description = inner_symbol.get("description", "")
                    logo_url = inner_symbol.get("logo_url", "")
                    figi_code = inner_symbol.get("figi_code", "")

                    # Extract asset type
                    type_info = inner_symbol.get("type", {})
                    if isinstance(type_info, dict):
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
                    extracted_symbol = symbol_data.get("raw_symbol", "UNKNOWN")
            else:
                # Simple string symbol
                extracted_symbol = str(symbol_data) if symbol_data else "UNKNOWN"

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
            "symbol": extracted_symbol,
            "symbol_id": symbol_id,
            "symbol_description": symbol_description,
            "quantity": quantity,
            "price": price,
            "equity": equity,
            "average_buy_price": position.get("average_purchase_price"),
            "open_pnl": position.get("open_pnl"),
            "asset_type": asset_type,
            "currency": currency_code,
            "logo_url": logo_url,
            "exchange_code": exchange_code,
            "exchange_name": exchange_name,
            "mic_code": mic_code,
            "figi_code": figi_code,
            "is_quotable": is_quotable,
            "is_tradable": is_tradable,
            "account_id": account_id,  # Use the provided account_id parameter
        }


if __name__ == "__main__":
    # Example usage
    collector = SnapTradeCollector()
    results = collector.collect_all_data(write_parquet=True)
    print(f"Collection results: {results}")
