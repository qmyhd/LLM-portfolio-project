"""
CSV Data Cleaner for LLM Portfolio Journal
==========================================

Provides robust CSV cleaning utilities to prevent SQL injection, parsing errors, 
and data corruption during database inserts.

Key features:
- Trims whitespace from column names and values
- Drops malformed rows with warnings
- Coerces numeric types safely
- Filters action columns to valid values
- Handles special characters (%, $, etc.) safely

This prevents common issues like:
- "Invalid action 'BBG...'" errors
- SQL parameter substitution failures with % characters  
- Numeric conversion errors breaking inserts
- Whitespace mismatches breaking equality checks
"""

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd

logger = logging.getLogger(__name__)

# Valid action types for orders table (prevents invalid action errors)
VALID_ACTIONS: Set[str] = {
    "buy", "sell", "buy_to_open", "sell_to_close", "buy_to_close", "sell_to_open",
    "market_buy", "market_sell", "limit_buy", "limit_sell", "stop_buy", "stop_sell",
    "dividend", "split", "transfer_in", "transfer_out", "deposit", "withdrawal"
}

# Columns that should be numeric (for safe coercion)
NUMERIC_COLUMNS: Dict[str, List[str]] = {
    "orders": ["quantity", "price", "total_quantity", "execution_price", "filled_quantity"],
    "positions": ["quantity", "price", "equity", "average_buy_price", "calculated_equity"],
    "discord_messages": ["num_chars", "num_words", "sentiment_score"]
}

# Required columns by table (for validation)
REQUIRED_COLUMNS: Dict[str, List[str]] = {
    "orders": ["symbol", "action", "quantity"],
    "positions": ["symbol", "quantity"],
    "discord_messages": ["message_id", "content", "channel", "author"]
}


class CSVCleaner:
    """Robust CSV cleaner that handles common data quality issues."""
    
    def __init__(self, table_name: str):
        """
        Initialize cleaner for a specific table.
        
        Args:
            table_name: Name of the target table (orders, positions, discord_messages)
        """
        self.table_name = table_name
        self.numeric_cols = NUMERIC_COLUMNS.get(table_name, [])
        self.required_cols = REQUIRED_COLUMNS.get(table_name, [])
        
    def clean_csv(self, csv_path: Path, output_path: Optional[Path] = None) -> pd.DataFrame:
        """
        Clean a CSV file and return sanitized DataFrame.
        
        Args:
            csv_path: Path to input CSV file
            output_path: Optional path to save cleaned CSV
            
        Returns:
            Cleaned pandas DataFrame
            
        Raises:
            FileNotFoundError: If CSV file doesn't exist
            ValueError: If critical columns are missing
        """
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
            
        logger.info(f"Cleaning CSV file: {csv_path}")
        
        # Load CSV with robust error handling
        try:
            df = pd.read_csv(
                csv_path,
                engine="python",  # More robust parsing
                on_bad_lines="warn",  # Warn but continue on malformed rows
                encoding="utf-8",
                low_memory=False
            )
        except Exception as e:
            logger.error(f"Failed to read CSV {csv_path}: {e}")
            raise
            
        original_rows = len(df)
        logger.info(f"Loaded {original_rows} rows from CSV")
        
        # Step 1: Clean column names (strip whitespace, normalize)
        df.columns = df.columns.str.strip().str.lower()
        
        # Step 2: Validate required columns exist
        missing_cols = [col for col in self.required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns for {self.table_name}: {missing_cols}")
            
        # Step 3: Clean string values (strip whitespace, handle nulls)
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].astype(str).str.strip()
            # Replace empty strings with None for cleaner nulls
            df[col] = df[col].replace('', None)
            df[col] = df[col].replace('nan', None)
            
        # Step 4: Clean numeric columns (safe coercion)
        for col in self.numeric_cols:
            if col in df.columns:
                df[col] = self._clean_numeric_column(df[col], col)
                
        # Step 5: Special cleaning by table type
        if self.table_name == "orders":
            df = self._clean_orders_table(df)
        elif self.table_name == "discord_messages":
            df = self._clean_discord_table(df)
        elif self.table_name == "positions":
            df = self._clean_positions_table(df)
            
        # Step 6: Drop rows with critical nulls
        before_dropna = len(df)
        df = df.dropna(subset=self.required_cols)
        after_dropna = len(df)
        
        if before_dropna > after_dropna:
            logger.warning(f"Dropped {before_dropna - after_dropna} rows with null required columns")
            
        # Step 7: Remove exact duplicates
        before_dedup = len(df)
        df = df.drop_duplicates()
        after_dedup = len(df)
        
        if before_dedup > after_dedup:
            logger.info(f"Removed {before_dedup - after_dedup} duplicate rows")
            
        logger.info(f"Cleaning complete: {original_rows} → {len(df)} rows ({len(df)/original_rows:.1%} retained)")
        
        # Save cleaned CSV if requested
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path, index=False, encoding="utf-8")
            logger.info(f"Saved cleaned CSV to: {output_path}")
            
        return df
        
    def _clean_numeric_column(self, series: pd.Series, col_name: str) -> pd.Series:
        """Safely convert a column to numeric, handling errors gracefully."""
        try:
            # Remove common non-numeric characters
            if series.dtype == 'object':
                # Remove currency symbols, commas, whitespace
                series = series.astype(str).str.replace(r'[\$,\s%]', '', regex=True)
                # Replace empty strings with NaN
                series = series.replace('', None)
                
            # Convert to numeric with error handling
            numeric_series = pd.to_numeric(series, errors='coerce')
            
            # Log conversion issues
            null_count = numeric_series.isnull().sum()
            if null_count > 0:
                logger.warning(f"Column '{col_name}': {null_count} values could not be converted to numeric")
                
            return numeric_series
            
        except Exception as e:
            logger.error(f"Error cleaning numeric column '{col_name}': {e}")
            return series
            
    def _clean_orders_table(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply orders-specific cleaning rules."""
        # Filter actions to valid set (prevents "Invalid action" errors)
        if 'action' in df.columns:
            original_actions = df['action'].nunique()
            df['action'] = df['action'].str.lower().str.strip()
            
            # Filter to valid actions only
            valid_mask = df['action'].isin(VALID_ACTIONS)
            invalid_count = (~valid_mask).sum()
            
            if invalid_count > 0:
                invalid_actions = df.loc[~valid_mask, 'action'].unique()
                logger.warning(f"Filtering {invalid_count} rows with invalid actions: {list(invalid_actions)}")
                
            df = df[valid_mask]
            
        # Clean symbol column (remove extra characters)
        if 'symbol' in df.columns:
            df['symbol'] = df['symbol'].str.upper().str.strip()
            # Remove non-alphabetic characters except dots (for symbols like BRK.B)
            df['symbol'] = df['symbol'].str.replace(r'[^A-Z.]', '', regex=True)
            
        # Ensure quantity is positive
        if 'quantity' in df.columns:
            df['quantity'] = df['quantity'].abs()
            
        return df
        
    def _clean_discord_table(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply Discord messages-specific cleaning rules."""
        # Clean message content (handle special characters safely)
        if 'content' in df.columns:
            # Normalize whitespace but preserve content
            df['content'] = df['content'].str.replace(r'\s+', ' ', regex=True).str.strip()
            
            # Truncate very long messages (prevents DB issues)
            MAX_CONTENT_LENGTH = 4000
            df['content'] = df['content'].str[:MAX_CONTENT_LENGTH]
            
        # Clean channel names
        if 'channel' in df.columns:
            df['channel'] = df['channel'].str.lower().str.strip()
            df['channel'] = df['channel'].str.replace(r'[^a-z0-9_-]', '', regex=True)
            
        # Ensure message_id is string
        if 'message_id' in df.columns:
            df['message_id'] = df['message_id'].astype(str)
            
        return df
        
    def _clean_positions_table(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply positions-specific cleaning rules."""
        # Clean symbol column
        if 'symbol' in df.columns:
            df['symbol'] = df['symbol'].str.upper().str.strip()
            df['symbol'] = df['symbol'].str.replace(r'[^A-Z.]', '', regex=True)
            
        # Ensure quantities are non-negative
        numeric_cols = ['quantity', 'equity', 'price', 'average_buy_price']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').abs()
                
        return df


def clean_csv_file(csv_path: Path, table_name: str, output_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Convenience function to clean a CSV file for a specific table.
    
    Args:
        csv_path: Path to input CSV file
        table_name: Target table name (orders, positions, discord_messages)
        output_path: Optional path to save cleaned CSV
        
    Returns:
        Cleaned pandas DataFrame
    """
    cleaner = CSVCleaner(table_name)
    return cleaner.clean_csv(csv_path, output_path)


def validate_cleaned_data(df: pd.DataFrame, table_name: str) -> bool:
    """
    Validate that cleaned data meets basic requirements.
    
    Args:
        df: Cleaned DataFrame
        table_name: Target table name
        
    Returns:
        True if validation passes, False otherwise
    """
    required_cols = REQUIRED_COLUMNS.get(table_name, [])
    
    # Check required columns exist
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        logger.error(f"Validation failed: missing columns {missing_cols}")
        return False
        
    # Check for empty DataFrame
    if len(df) == 0:
        logger.error("Validation failed: DataFrame is empty")
        return False
        
    # Check for nulls in required columns
    for col in required_cols:
        null_count = df[col].isnull().sum()
        if null_count > 0:
            logger.error(f"Validation failed: {null_count} nulls in required column '{col}'")
            return False
            
    # Table-specific validations
    if table_name == "orders" and 'action' in df.columns:
        invalid_actions = df[~df['action'].isin(VALID_ACTIONS)]['action'].unique()
        if len(invalid_actions) > 0:
            logger.error(f"Validation failed: invalid actions {list(invalid_actions)}")
            return False
            
    logger.info(f"Validation passed for {table_name} data: {len(df)} rows")
    return True


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python clean_csv.py <csv_path> <table_name> [output_path]")
        sys.exit(1)
        
    csv_path = Path(sys.argv[1])
    table_name = sys.argv[2]
    output_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    
    logging.basicConfig(level=logging.INFO)
    
    try:
        df = clean_csv_file(csv_path, table_name, output_path)
        if validate_cleaned_data(df, table_name):
            print(f"✅ Successfully cleaned {len(df)} rows for {table_name}")
        else:
            print("❌ Validation failed")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
