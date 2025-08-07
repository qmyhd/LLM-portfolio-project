#!/usr/bin/env python3
"""
Direct Supabase Data Writers
Provides functions to write data directly to Supabase from Discord, SnapTrade, and price APIs.
"""

import logging
import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
import sys

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from src.db import get_sync_engine
from sqlalchemy import text

logger = logging.getLogger(__name__)

class DirectSupabaseWriter:
    """Direct writer for real-time data to Supabase."""
    
    def __init__(self):
        self.engine = get_sync_engine()
    
    def write_position_data(self, positions_data: List[Dict]) -> bool:
        """
        Write position data directly to Supabase.
        
        Args:
            positions_data: List of position dictionaries from SnapTrade
            
        Returns:
            bool: Success status
        """
        if not positions_data:
            logger.warning("No position data to write")
            return False
        
        try:
            sync_timestamp = datetime.now().isoformat()
            
            with self.engine.begin() as conn:
                # Clear existing positions for this sync
                conn.execute(
                    text("DELETE FROM positions WHERE user_id = :user_id"),
                    {"user_id": "default_user"}
                )
                
                # Insert new positions
                for position in positions_data:
                    conn.execute(text("""
                        INSERT INTO positions (
                            symbol, quantity, equity, price, average_buy_price,
                            type, currency, sync_timestamp, user_id, updated_at
                        ) VALUES (
                            :symbol, :quantity, :equity, :price, :average_buy_price,
                            :type, :currency, :sync_timestamp, :user_id, :updated_at
                        )
                    """), {
                        "symbol": position.get('symbol', 'UNKNOWN'),
                        "quantity": float(position.get('quantity', 0)),
                        "equity": float(position.get('equity', 0)),
                        "price": float(position.get('price', 0)),
                        "average_buy_price": float(position.get('average_buy_price', 0)),
                        "type": position.get('type', 'Unknown'),
                        "currency": position.get('currency', 'USD'),
                        "sync_timestamp": sync_timestamp,
                        "user_id": "default_user",
                        "updated_at": datetime.now()
                    })
                
                logger.info(f"✅ Wrote {len(positions_data)} positions to Supabase")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to write positions to Supabase: {e}")
            return False
    
    def write_order_data(self, orders_data: List[Dict]) -> bool:
        """
        Write order data directly to Supabase with proper SnapTrade schema mapping.
        
        Args:
            orders_data: List of order dictionaries from SnapTrade
            
        Returns:
            bool: Success status
        """
        if not orders_data:
            logger.warning("No order data to write")
            return False
        
        try:
            with self.engine.begin() as conn:
                for order in orders_data:
                    # Extract core order fields
                    brokerage_order_id = str(order.get('brokerage_order_id', '')).strip()
                    if not brokerage_order_id:
                        brokerage_order_id = f"order_{datetime.now().timestamp()}"
                    
                    # Extract symbol from nested structure
                    symbol = self._extract_symbol_from_order(order)
                    
                    # Map SnapTrade fields to database schema
                    order_data = {
                        "brokerage_order_id": brokerage_order_id,
                        "status": str(order.get('status', 'UNKNOWN')).upper(),
                        "symbol": symbol,
                        "action": str(order.get('action', 'UNKNOWN')).upper(),
                        "total_quantity": self._safe_decimal(order.get('total_quantity')),
                        "filled_quantity": self._safe_decimal(order.get('filled_quantity')),
                        "execution_price": self._safe_decimal(order.get('execution_price')),
                        "limit_price": self._safe_decimal(order.get('limit_price')),
                        "stop_price": self._safe_decimal(order.get('stop_price')),
                        "order_type": order.get('order_type'),
                        "time_in_force": order.get('time_in_force'),
                        "time_placed": self._safe_timestamp(order.get('time_placed')),
                        "time_updated": self._safe_timestamp(order.get('time_updated')),
                        "time_executed": self._safe_timestamp(order.get('time_executed')),
                        "universal_symbol": json.dumps(order.get('universal_symbol')) if order.get('universal_symbol') else None,
                        "option_symbol": json.dumps(order.get('option_symbol')) if order.get('option_symbol') else None,
                        "quote_currency": order.get('quote_currency', 'USD'),
                        "user_id": "default_user",
                        "created_at": datetime.now()
                    }
                    
                    # Upsert order (insert or update if exists)
                    conn.execute(text("""
                        INSERT INTO orders (
                            brokerage_order_id, status, symbol, action,
                            total_quantity, filled_quantity, execution_price, limit_price, stop_price,
                            order_type, time_in_force, time_placed, time_updated, time_executed,
                            universal_symbol, option_symbol, quote_currency, user_id, created_at
                        ) VALUES (
                            :brokerage_order_id, :status, :symbol, :action,
                            :total_quantity, :filled_quantity, :execution_price, :limit_price, :stop_price,
                            :order_type, :time_in_force, :time_placed, :time_updated, :time_executed,
                            :universal_symbol, :option_symbol, :quote_currency, :user_id, :created_at
                        )
                        ON CONFLICT (brokerage_order_id) DO UPDATE SET
                            status = EXCLUDED.status,
                            filled_quantity = EXCLUDED.filled_quantity,
                            time_updated = EXCLUDED.time_updated,
                            time_executed = EXCLUDED.time_executed,
                            updated_at = CURRENT_TIMESTAMP
                    """), order_data)
                
                logger.info(f"✅ Wrote {len(orders_data)} orders to Supabase")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to write orders to Supabase: {e}")
            return False
    
    def write_discord_message(self, message_data: Dict) -> bool:
        """
        Write a single Discord message directly to Supabase.
        
        Args:
            message_data: Discord message dictionary
            
        Returns:
            bool: Success status
        """
        try:
            with self.engine.begin() as conn:
                # Upsert message (handle duplicates gracefully)
                conn.execute(text("""
                    INSERT INTO discord_messages (
                        message_id, author, content, channel, timestamp,
                        author_id, num_chars, num_words, sentiment_score,
                        tickers_detected, tweet_urls, is_reply, reply_to_id,
                        mentions, user_id, created_at
                    ) VALUES (
                        :message_id, :author, :content, :channel, :timestamp,
                        :author_id, :num_chars, :num_words, :sentiment_score,
                        :tickers_detected, :tweet_urls, :is_reply, :reply_to_id,
                        :mentions, :user_id, :created_at
                    )
                    ON CONFLICT (message_id) DO UPDATE SET
                        content = EXCLUDED.content,
                        sentiment_score = EXCLUDED.sentiment_score,
                        tickers_detected = EXCLUDED.tickers_detected,
                        updated_at = CURRENT_TIMESTAMP
                """), {
                    "message_id": str(message_data.get('message_id', '')),
                    "author": str(message_data.get('author', '')),
                    "content": str(message_data.get('content', '')),
                    "channel": str(message_data.get('channel', '')),
                    "timestamp": message_data.get('timestamp', datetime.now().isoformat()),
                    "author_id": self._safe_int(message_data.get('author_id')),
                    "num_chars": len(str(message_data.get('content', ''))),
                    "num_words": len(str(message_data.get('content', '')).split()),
                    "sentiment_score": self._safe_decimal(message_data.get('sentiment_score')),
                    "tickers_detected": str(message_data.get('tickers_detected', '')),
                    "tweet_urls": str(message_data.get('tweet_urls', '')),
                    "is_reply": bool(message_data.get('is_reply', False)),
                    "reply_to_id": self._safe_int(message_data.get('reply_to_id')),
                    "mentions": str(message_data.get('mentions', '')),
                    "user_id": "default_user",
                    "created_at": datetime.now()
                })
                
                logger.debug(f"✅ Wrote Discord message {message_data.get('message_id')} to Supabase")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to write Discord message to Supabase: {e}")
            return False
    
    def write_price_data(self, price_data: List[Dict]) -> bool:
        """
        Write real-time price data to Supabase.
        
        Args:
            price_data: List of price dictionaries
            
        Returns:
            bool: Success status
        """
        if not price_data:
            logger.warning("No price data to write")
            return False
        
        try:
            with self.engine.begin() as conn:
                # Create realtime_prices table if it doesn't exist
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS realtime_prices (
                        id SERIAL PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        price DECIMAL(18,6) NOT NULL,
                        previous_close DECIMAL(18,6),
                        abs_change DECIMAL(18,6),
                        percent_change DECIMAL(8,4),
                        timestamp TIMESTAMPTZ NOT NULL,
                        user_id TEXT DEFAULT 'default_user',
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_realtime_prices_symbol ON realtime_prices(symbol);
                    CREATE INDEX IF NOT EXISTS idx_realtime_prices_timestamp ON realtime_prices(timestamp);
                """))
                
                # Insert price data
                for price in price_data:
                    conn.execute(text("""
                        INSERT INTO realtime_prices (
                            symbol, price, previous_close, abs_change, percent_change,
                            timestamp, user_id, created_at
                        ) VALUES (
                            :symbol, :price, :previous_close, :abs_change, :percent_change,
                            :timestamp, :user_id, :created_at
                        )
                    """), {
                        "symbol": price.get('symbol', 'UNKNOWN'),
                        "price": self._safe_decimal(price.get('price')),
                        "previous_close": self._safe_decimal(price.get('previous_close')),
                        "abs_change": self._safe_decimal(price.get('abs_change')),
                        "percent_change": self._safe_decimal(price.get('percent_change')),
                        "timestamp": self._safe_timestamp(price.get('timestamp')) or datetime.now(),
                        "user_id": "default_user",
                        "created_at": datetime.now()
                    })
                
                logger.info(f"✅ Wrote {len(price_data)} price records to Supabase")
                return True
                
        except Exception as e:
            logger.error(f"❌ Failed to write price data to Supabase: {e}")
            return False
    
    def _extract_symbol_from_order(self, order: Dict) -> str:
        """Extract clean symbol from SnapTrade order structure."""
        # Try extracted_symbol first
        if order.get('extracted_symbol'):
            return str(order['extracted_symbol']).strip()
        
        # Try direct symbol field
        symbol_data = order.get('symbol', {})
        if isinstance(symbol_data, str):
            return symbol_data.strip()
        
        # Try nested symbol extraction
        if isinstance(symbol_data, dict):
            for key in ['symbol', 'raw_symbol', 'ticker', 'SYMBOL']:
                if symbol_data.get(key):
                    return str(symbol_data[key]).strip()
        
        # Try universal_symbol
        universal_symbol = order.get('universal_symbol', {})
        if isinstance(universal_symbol, dict):
            for key in ['symbol', 'raw_symbol', 'ticker']:
                if universal_symbol.get(key):
                    return str(universal_symbol[key]).strip()
        
        return 'UNKNOWN'
    
    def _safe_decimal(self, value) -> Optional[float]:
        """Safely convert to decimal/float."""
        if value is None or value == '' or str(value).strip() == '':
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    def _safe_int(self, value) -> Optional[int]:
        """Safely convert to integer."""
        if value is None or value == '' or str(value).strip() == '':
            return None
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return None
    
    def _safe_timestamp(self, value):
        """Safely convert to timestamp."""
        if value is None or value == '':
            return None
        try:
            import pandas as pd
            return pd.to_datetime(value)
        except (ValueError, TypeError):
            return None

# Global instance for use throughout the application
supabase_writer = DirectSupabaseWriter()

# Convenience functions for easy imports
def write_positions_to_supabase(positions_data: List[Dict]) -> bool:
    """Write positions data directly to Supabase."""
    return supabase_writer.write_position_data(positions_data)

def write_orders_to_supabase(orders_data: List[Dict]) -> bool:
    """Write orders data directly to Supabase."""
    return supabase_writer.write_order_data(orders_data)

def write_discord_message_to_supabase(message_data: Dict) -> bool:
    """Write Discord message directly to Supabase."""
    return supabase_writer.write_discord_message(message_data)

def write_prices_to_supabase(price_data: List[Dict]) -> bool:
    """Write price data directly to Supabase."""
    return supabase_writer.write_price_data(price_data)
