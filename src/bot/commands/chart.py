from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import discord
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from discord.ext import commands

from src.bot.ui.embed_factory import EmbedFactory, EmbedCategory, build_embed
from src.price_service import get_ohlcv

# Use absolute imports instead of sys.path manipulation
from src.db import get_connection
from src.position_analysis import (
    analyze_position_history,
    create_enhanced_chart_annotations,
    generate_position_report,
)

# Define constants to avoid repeating path math
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent  # Project root
DB_DIR = BASE_DIR / "data" / "database"
DB_PATH = DB_DIR / "price_history.db"
CHARTS_DIR = BASE_DIR / "charts"

# Create directories if they don't exist
CHARTS_DIR.mkdir(parents=True, exist_ok=True)


class FIFOPositionTracker:
    """
    FIFO (First In, First Out) position tracking system for calculating realized P/L.
    Maintains a queue of buy orders and processes sells against oldest purchases first.
    """

    def __init__(self):
        self.buy_queue: List[Tuple[float, float, datetime]] = (
            []
        )  # [(shares, price, date), ...]

    def add_buy(self, shares: float, price: float, date: datetime) -> None:
        """Add a buy order to the position queue"""
        self.buy_queue.append((shares, price, date))

    def process_sell(
        self, shares_sold: float, sell_price: float, _sell_date: datetime
    ) -> float:
        """
        Process a sell order using FIFO method and calculate realized P/L.

        Args:
            shares_sold: Number of shares being sold
            sell_price: Price per share for the sale
            _sell_date: Date of the sale (reserved for future use)

        Returns:
            Total realized P/L for the sale (positive = profit, negative = loss)
        """
        total_pnl = 0.0
        remaining_shares = shares_sold

        while remaining_shares > 0 and self.buy_queue:
            shares_available, buy_price, buy_date = self.buy_queue[0]

            if shares_available <= remaining_shares:
                # Use all shares from this buy lot
                pnl = (sell_price - buy_price) * shares_available
                total_pnl += pnl
                remaining_shares -= shares_available
                self.buy_queue.pop(0)  # Remove this lot completely
            else:
                # Partial sale from this buy lot
                pnl = (sell_price - buy_price) * remaining_shares
                total_pnl += pnl
                # Update the remaining shares in this lot
                self.buy_queue[0] = (
                    shares_available - remaining_shares,
                    buy_price,
                    buy_date,
                )
                remaining_shares = 0

        return total_pnl

    def get_current_position(self) -> float:
        """Get the total number of shares currently held"""
        return sum(shares for shares, _, _ in self.buy_queue)


# ── Discord Dark Style Constants ──────────────────────────────────────────
FIG_BG = "#1e1f22"  # outer window – Discord dark grey‑black
PANEL_BG = "#202225"  # chart panel (slightly lighter so grid is visible)
GRID = "#2a2d31"  # very muted grid lines
TXT = "#e0e0e0"  # off‑white labels

CANDLE_UP = "#3ba55d"  # Discord green
CANDLE_DOWN = "#ed4245"  # Discord red


# ── Discord Dark Style Factory ────────────────────────────────────────────
def discord_dark_style():
    mc = mpf.make_marketcolors(
        up=CANDLE_UP,
        down=CANDLE_DOWN,
        edge={"up": CANDLE_UP, "down": CANDLE_DOWN},
        wick={"up": CANDLE_UP, "down": CANDLE_DOWN},
        volume={"up": CANDLE_UP, "down": CANDLE_DOWN},
        ohlc={"up": CANDLE_UP, "down": CANDLE_DOWN},
    )
    rc = {
        "figure.facecolor": FIG_BG,
        "axes.facecolor": PANEL_BG,
        "grid.color": GRID,
        "grid.alpha": 0.25,
        "axes.grid": True,
        "axes.grid.axis": "both",
        "axes.edgecolor": TXT,
        "axes.labelcolor": TXT,
        "xtick.color": TXT,
        "ytick.color": TXT,
        "text.color": TXT,
    }
    return mpf.make_mpf_style(base_mpf_style="charles", marketcolors=mc, rc=rc)


# Available chart themes: discord (dark), yahoo (classic)
STYLES = {
    "discord": discord_dark_style(),
    "yahoo": mpf.make_mpf_style(base_mpf_style="yahoo"),  # Built-in yahoo style
}

# Period/interval mapping with moving averages
PERIOD_CONFIG = {
    "5d": {"interval": "30m", "mav": []},
    "1mo": {"interval": "1d", "mav": [20]},
    "3mo": {"interval": "1h", "mav": [21, 50]},
    "6mo": {"interval": "1d", "mav": [10, 21, 50]},
    "1y": {"interval": "1d", "mav": [21, 50, 100]},  # Can also use '5d'
    "2y": {"interval": "1wk", "mav": [4, 13, 26]},
    "10y": {"interval": "1mo", "mav": [6, 12, 24]},
    "max": {"interval": "3mo", "mav": [2, 4, 8]},
}


def get_moving_averages(period: str, interval: str) -> list:
    """
    Get moving averages based on period and interval combination.

    For intervals >= 1 day, specific moving averages are applied:
    - 1mo period & 1d intervals: mav=20
    - 1mo period & 1h interval: mav=70
    - 3mo period & 1h intervals: mav=(21,50)
    - 6mo period & 1d interval: mav=(10,21,50)
    - 1y and 1d int: mav=(21,50,100)
    - 2year period and 1wk: mav=(4,13,26)
    - 10y & 1mo: mav=(6,12,24)
    """
    # Handle specific period + interval combinations
    if period == "1mo" and interval == "1d":
        return [20]
    elif period == "1mo" and interval == "1h":
        return [70]
    elif period == "3mo" and interval == "1h":
        return [21, 50]
    elif period == "6mo" and interval == "1d":
        return [10, 21, 50]
    elif period == "1y" and interval == "1d":
        return [21, 50, 100]
    elif period == "2y" and interval == "1wk":
        return [4, 13, 26]
    elif period == "10y" and interval == "1mo":
        return [6, 12, 24]

    # Default cases for other combinations
    elif period == "5d":
        return []  # No moving averages for 5d period
    elif period == "max":
        return [2, 4, 8]  # Keep original max config

    # Fallback for any unspecified combinations
    return []


def get_chart_type(interval: str) -> str:
    """Determine chart type based on interval - always uses candlestick.

    Per user preference, we always use candlestick charts for better
    readability of OHLC data across all timeframes.
    """
    # Always use candlestick charts for all intervals
    return "candle"


def should_show_volume(period: str) -> bool:
    """Determine whether to show volume pane (only for periods >= 1 year)"""
    return period in ["1y", "2y", "10y", "max"]


def calculate_chart_date_range(period: str, end_date: Optional[datetime] = None):
    """Calculate the chart's date range based on the selected period

    Args:
        period: Time period string ('5d', '1mo', etc.)
        end_date: End date for the chart (default: current date)

    Returns:
        tuple: (start_date, end_date) as datetime objects
    """
    if end_date is None:
        end_date = datetime.now()

    # Special case: use April 1st as start date for 3mo period
    if period == "3mo":
        start_date = datetime(end_date.year, 4, 1)
        # If April 1st is in the future, use previous year
        if start_date > end_date:
            start_date = datetime(end_date.year - 1, 4, 1)
    else:
        # Standard period calculations
        if period == "5d":
            start_date = end_date - timedelta(days=5)
        elif period == "1mo":
            start_date = end_date - timedelta(days=30)
        elif period == "6mo":
            start_date = end_date - timedelta(days=180)
        elif period == "1y":
            start_date = end_date - timedelta(days=365)
        elif period == "2y":
            start_date = end_date - timedelta(days=730)
        elif period == "10y":
            start_date = end_date - timedelta(days=3650)
        elif period == "max":
            start_date = end_date - timedelta(days=7300)  # ~20 years for max
        else:
            # Default fallback
            start_date = end_date - timedelta(days=30)

    return start_date, end_date


def query_trade_data(
    symbol: str, start_date: datetime, end_date: datetime, min_trade: float = 0.0
):
    """Query trade data within the chart timeframe

    Args:
        symbol: Stock ticker symbol
        start_date: Start date for trade query
        end_date: End date for trade query
        min_trade: Minimum trade size threshold

    Returns:
        DataFrame containing trade data or empty DataFrame
    """
    try:
        conn = get_connection()

        # SQL query to select trade data using unified execute_sql
        query = """
        SELECT 
            symbol,
            action,
            time_executed as execution_date,
            execution_price,
            total_quantity,
            (execution_price * total_quantity) as trade_value
        FROM orders 
        WHERE symbol = :symbol 
        AND time_executed BETWEEN :start_date AND :end_date
        AND status = 'executed'
        AND (execution_price * total_quantity) >= :min_trade
        ORDER BY time_executed ASC
        """

        # Convert dates to strings for SQL query
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        # Use unified execute_sql instead of direct pd.read_sql_query
        from src.db import execute_sql

        result = execute_sql(
            query,
            {
                "symbol": symbol,
                "start_date": start_str,
                "end_date": end_str,
                "min_trade": min_trade,
            },
            fetch_results=True,
        )

        # Convert to DataFrame
        if result:
            columns = [
                "symbol",
                "action",
                "execution_date",
                "execution_price",
                "total_quantity",
                "trade_value",
            ]
            df = pd.DataFrame(result, columns=columns)

            # Convert execution_date to datetime if not empty
            if not df.empty and "execution_date" in df.columns:
                df["execution_date"] = pd.to_datetime(df["execution_date"])
        else:
            # Return empty DataFrame with proper column structure
            columns = [
                "symbol",
                "action",
                "execution_date",
                "execution_price",
                "total_quantity",
                "trade_value",
            ]
            df = pd.DataFrame(columns=columns)
            # Set execution_date column as datetime type for consistency
            df["execution_date"] = pd.to_datetime(df["execution_date"])

        return df

    except Exception as e:
        print(f"Error querying trade data: {e}")
        return pd.DataFrame()


def process_trade_markers(trade_data: pd.DataFrame, price_data: pd.DataFrame):
    """
    Process trade data and generate marker positions with FIFO P/L calculation.

    Args:
        trade_data: DataFrame containing trade information
        price_data: DataFrame containing OHLCV price data

    Returns:
        tuple: (addplot_list, label_data) for mplfinance chart and annotations
    """
    if trade_data.empty or price_data.empty:
        return [], []

    addplot_list = []
    label_data = []  # [(date, price, text, action), ...]

    # Create marker series aligned with price data index
    buy_markers = pd.Series(index=price_data.index, dtype=float)
    sell_markers = pd.Series(index=price_data.index, dtype=float)

    # Initialize FIFO position tracker
    fifo_tracker = FIFOPositionTracker()

    # Process trades chronologically (already ordered by time_executed ASC)
    for _, trade in trade_data.iterrows():
        trade_date = trade["execution_date"].date()
        action = trade["action"].lower()
        shares = float(trade["total_quantity"])
        price = float(trade["execution_price"])

        # Find the closest price data date
        price_dates = [idx.date() for idx in price_data.index]
        closest_date = min(price_dates, key=lambda x: abs((x - trade_date).days))
        closest_idx = None

        # Find the index corresponding to closest date
        for idx in price_data.index:
            if idx.date() == closest_date:
                closest_idx = idx
                break

        if closest_idx is not None:
            # Process the trade and generate label
            if action == "buy":
                # Add to FIFO tracker
                fifo_tracker.add_buy(shares, price, trade["execution_date"])

                # Position buy markers slightly below the low price
                # Find the integer position for this date
                idx_position = price_data.index.get_loc(closest_idx)
                low_price = price_data.iloc[idx_position]["Low"]
                marker_price = low_price * 0.995
                buy_markers.loc[closest_idx] = marker_price

                # Generate buy label: "shares @ $price"
                label_text = f"{shares:.0f} @ ${price:.2f}"
                label_data.append((closest_idx, marker_price, label_text, "buy"))

            elif action == "sell":
                # Calculate FIFO P/L
                realized_pnl = fifo_tracker.process_sell(
                    shares, price, trade["execution_date"]
                )

                # Position sell markers slightly above the high price
                # Find the integer position for this date
                idx_position = price_data.index.get_loc(closest_idx)
                high_price = price_data.iloc[idx_position]["High"]
                marker_price = high_price * 1.005
                sell_markers.loc[closest_idx] = marker_price

                # Generate sell label: "shares @ $price (+/-$P/L)"
                pnl_sign = "+" if realized_pnl >= 0 else ""
                label_text = (
                    f"{shares:.0f} @ ${price:.2f} ({pnl_sign}${realized_pnl:.2f})"
                )
                label_data.append((closest_idx, marker_price, label_text, "sell"))

    # Create addplot objects for markers
    if not buy_markers.dropna().empty:
        buy_plot = mpf.make_addplot(
            buy_markers,
            type="scatter",
            markersize=200,
            marker="^",
            color="#00c853",  # Green for buys
            alpha=0.8,
        )
        addplot_list.append(buy_plot)

    if not sell_markers.dropna().empty:
        sell_plot = mpf.make_addplot(
            sell_markers,
            type="scatter",
            markersize=200,
            marker="v",
            color="#ff1744",  # Red for sells
            alpha=0.8,
        )
        addplot_list.append(sell_plot)

    return addplot_list, label_data


def create_cost_basis_line(
    symbol: str, start_date: datetime, end_date: datetime, price_data: pd.DataFrame
):
    """
    Create cost basis line data for chart overlay using position analysis.

    Args:
        symbol: Stock ticker symbol
        start_date: Chart start date
        end_date: Chart end date
        price_data: DataFrame containing OHLCV price data

    Returns:
        tuple: (cost_basis_series, analysis_data) for chart overlay and metadata
    """
    try:
        # Get position analysis for the chart timeframe
        analysis = analyze_position_history(symbol, start_date, end_date)

        if "error" in analysis or not analysis.get("timeline_data", {}).get(
            "cost_basis_evolution"
        ):
            return None, None

        # Extract cost basis timeline
        cost_timeline = analysis["timeline_data"]["cost_basis_evolution"]

        if not cost_timeline:
            return None, None

        # Create cost basis series aligned with price data index
        cost_basis_series = pd.Series(index=price_data.index, dtype=float)

        # Fill cost basis values by finding closest dates
        current_cost_basis = 0.0

        for idx in price_data.index:
            if hasattr(idx, "date"):
                price_date = idx.date()
            else:
                price_date = pd.to_datetime(idx).date()

            # Find the most recent cost basis update before or on this date
            for cost_point in cost_timeline:
                cost_date = pd.to_datetime(cost_point["date"]).date()
                if cost_date <= price_date:
                    current_cost_basis = cost_point["avg_cost_basis"]
                else:
                    break

            # Only add cost basis if it's greater than 0 (position exists)
            if current_cost_basis > 0:
                cost_basis_series.at[idx] = current_cost_basis

        # Clean up the series (remove NaN values while keeping structure)
        cost_basis_series = cost_basis_series.dropna()

        if cost_basis_series.empty:
            return None, None

        return cost_basis_series, analysis

    except Exception as e:
        print(f"Error creating cost basis line: {e}")
        return None, None


def create_chart_directory(symbol: str) -> Path:
    """
    Create and return the directory path for storing charts organized by symbol.

    Args:
        symbol: Stock ticker symbol

    Returns:
        Path object for the chart directory
    """
    # Create charts directory structure: charts/{symbol}/ using the constant
    charts_dir = CHARTS_DIR / symbol.upper()
    charts_dir.mkdir(parents=True, exist_ok=True)
    return charts_dir


def generate_chart_filename(symbol: str, period: str, interval: str, theme: str) -> str:
    """
    Generate a unique chart filename with timestamp.

    Args:
        symbol: Stock ticker symbol
        period: Time period
        interval: Data interval
        theme: Chart theme

    Returns:
        Formatted filename string
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{symbol}_{period}_{interval}_{theme}_{timestamp}.png"


def register(bot: commands.Bot):
    @bot.command(name="chart")
    async def create_chart(
        ctx,
        symbol: Optional[str] = None,
        period: str = "1mo",
        theme: str = "yahoo",
        min_trade: float = 0.0,
        interval: Optional[str] = None,
    ):
        """
        Create a stock chart with trade annotations and cost-basis lines.

        **Usage:**
        `!chart SYMBOL [period] [theme] [min_trade] [interval]`

        **Parameters:**
        • symbol - Stock ticker (required), e.g. AAPL, TSLA
        • period - Time period: 5d, 1mo, 3mo, 6mo, 1y, 2y, 10y, max
        • theme  - Chart style: yahoo (classic), discord (dark)
        • min_trade - Minimum trade size filter (default: 0)
        • interval - Override interval: 1d, 5d, 1wk, 1mo, 3mo

        **Period → Default Interval → Moving Averages:**
        • 5d  → 1d interval (no MAs)
        • 1mo → 1d interval (20-day MA)
        • 3mo → 1d interval (21, 50 MAs)
        • 6mo → 1d interval (10, 21, 50 MAs)
        • 1y  → 1d interval (21, 50, 100 MAs)
        • 2y  → 1wk interval (4, 13, 26 week MAs)

        **Data Source:**
        • All OHLCV data from Databento (Supabase ohlcv_daily)
        • Daily bars only (no intraday data)

        **Features:**
        • 📈 Candlestick charts for all timeframes
        • 📊 Volume bars for periods ≥1 year
        • 🔺🔻 Trade markers (buy/sell) with FIFO P/L
        • 🟡 Cost-basis line from positions
        """
        # Argument validation
        if symbol is None:
            await ctx.send(
                "❌ **Error**: Symbol is required!\n\n"
                "**Usage Examples:**\n"
                "`!chart AAPL` - 1mo chart with yahoo theme\n"
                "`!chart TSLA 3mo` - 3 month chart\n"
                "`!chart NVDA 1y discord` - 1 year dark theme\n"
                "`!chart AAPL 1y yahoo 0.0 5d` - 1y with 5-day interval\n\n"
                "**Periods:** 5d, 1mo, 3mo, 6mo, 1y, 2y, 10y, max\n"
                "**Themes:** yahoo (classic), discord (dark)\n"
                "**Intervals:** 1d, 5d, 1wk, 1mo, 3mo\n\n"
                "📊 **Data Source:** Databento (daily bars only)"
            )
            return

        # Convert symbol to uppercase
        symbol = symbol.upper()

        # Validate period
        if period not in PERIOD_CONFIG:
            await ctx.send(
                f"❌ **Error**: Invalid period '{period}'\n\n"
                "**Available periods:** " + ", ".join(PERIOD_CONFIG.keys())
            )
            return

        # Validate theme
        if theme not in STYLES:
            await ctx.send(
                f"❌ **Error**: Invalid theme '{theme}'\n\n"
                "**Available themes:** " + ", ".join(STYLES.keys())
            )
            return

        # Get configuration for this period
        config = PERIOD_CONFIG[period]
        base_interval = config["interval"]

        # Use custom interval if provided and valid, otherwise use default
        valid_intervals = ["30m", "1h", "1d", "5d", "1wk", "1mo", "3mo"]
        if interval and interval in valid_intervals:
            final_interval = interval
            # Recalculate moving averages for custom interval
            mav = get_moving_averages(period, final_interval)
        else:
            final_interval = base_interval
            # Use default moving averages from config
            mav = config["mav"] if config["mav"] else None
            if interval:  # User provided invalid interval
                await ctx.send(
                    f"⚠️ **Warning**: Invalid interval '{interval}', using default '{base_interval}' for {period} period"
                )

        # Determine chart settings
        chart_type = get_chart_type(final_interval)
        show_volume = should_show_volume(period)
        style = STYLES[theme]

        # Create organized chart directory and generate unique filename
        chart_dir = create_chart_directory(symbol)
        chart_filename = generate_chart_filename(symbol, period, final_interval, theme)
        chart_filepath = chart_dir / chart_filename

        # Variables for metadata tracking
        trade_count = 0
        chart_saved_successfully = False

        try:
            # Send typing indicator
            async with ctx.typing():
                # Calculate date range for trade data querying
                start_date, end_date = calculate_chart_date_range(period)

                # Fetch price data from Supabase ohlcv_daily (Databento source)
                data = None
                data_source = "databento"

                try:
                    # Fetch OHLCV from price_service (Supabase ohlcv_daily)
                    data = get_ohlcv(symbol, start_date.date(), end_date.date())

                    if data is not None and not data.empty:
                        # Ensure index is sorted (critical for mplfinance)
                        data = data.sort_index()

                        # Verify OHLC columns exist and are numeric
                        required_cols = ["Open", "High", "Low", "Close"]
                        for col in data.columns:
                            data[col] = pd.to_numeric(data[col], errors="coerce")

                        # Drop rows with NaN in critical OHLC columns
                        data = data.dropna(subset=required_cols)

                except Exception as price_error:
                    print(f"Price service error for {symbol}: {price_error}")
                    data = None

                # Final check - if still no data, send error
                if data is None or data.empty:
                    await ctx.send(
                        f"❌ **Market Data Error**: Could not find price data for **{symbol}**\n"
                        f"• Symbol may be invalid or delisted\n"
                        f"• Market may be closed for this symbol\n"
                        f"• No cached data available\n"
                        f"• Try checking the symbol spelling or using a different symbol"
                    )
                    return

                # Query trade data for overlays
                trade_data = query_trade_data(symbol, start_date, end_date, min_trade)
                trade_count = len(trade_data) if not trade_data.empty else 0

                # Process trade markers with FIFO P/L calculation
                addplot_list, label_data = process_trade_markers(trade_data, data)

                # Create cost basis line if position data exists
                cost_basis_series, position_analysis = create_cost_basis_line(
                    symbol, start_date, end_date, data
                )
                if cost_basis_series is not None and not cost_basis_series.empty:
                    # Add cost basis line to addplot_list
                    cost_basis_plot = mpf.make_addplot(
                        cost_basis_series,
                        type="line",
                        color="#FFD700",  # Gold color for cost basis
                        width=2,
                        linestyle="--",  # Dashed line
                        alpha=0.8,
                        secondary_y=False,
                    )
                    addplot_list.append(cost_basis_plot)

                # Prepare plot arguments
                # Build title with data source indicator
                title_suffix = " [cached]" if data_source == "cached" else ""
                plot_kwargs = {
                    "type": chart_type,
                    "style": style,
                    "volume": show_volume,
                    "returnfig": True,  # Get figure and axes for custom annotations
                    "figsize": (12, 8),
                    "title": f"{symbol} - {period.upper()} Chart ({theme} theme){title_suffix}",
                }

                # Add moving averages if specified
                if mav:
                    plot_kwargs["mav"] = mav

                # Add trade markers if available
                if addplot_list:
                    plot_kwargs["addplot"] = addplot_list

                # Plot chart and get figure/axes
                fig, axes = mpf.plot(data, **plot_kwargs)

                # Add text annotations for trade labels
                if label_data and len(axes) > 0:
                    # Get the main price chart axis (usually axes[0])
                    ax = axes[0] if hasattr(axes, "__len__") else axes

                    for date_idx, y_pos, text, action in label_data:
                        # Convert pandas timestamp to matplotlib date number
                        x_pos = date_idx.to_pydatetime()

                        # Position labels based on action
                        if action == "buy":
                            # Position below the marker
                            va = "top"
                            y_offset = -0.002  # Small negative offset
                        else:  # sell
                            # Position above the marker
                            va = "bottom"
                            y_offset = 0.002  # Small positive offset

                        # Add text annotation with semi-transparent background
                        ax.annotate(
                            text,
                            xy=(x_pos, y_pos + (y_pos * y_offset)),
                            xytext=(0, 0),  # No additional offset
                            textcoords="offset points",
                            ha="center",
                            va=va,
                            fontsize=8,
                            fontweight="bold",
                            color="white",
                            bbox=dict(
                                boxstyle="round,pad=0.3",
                                facecolor="black",
                                alpha=0.7,
                                edgecolor="none",
                            ),
                        )

                # Add enhanced annotations from position analysis
                if position_analysis and len(axes) > 0:
                    enhanced_annotations = create_enhanced_chart_annotations(
                        position_analysis
                    )
                    ax = axes[0] if hasattr(axes, "__len__") else axes

                    for annotation in enhanced_annotations:
                        if annotation.get("date") and annotation.get("text"):
                            try:
                                # Convert date to datetime if needed
                                ann_date = pd.to_datetime(
                                    annotation["date"]
                                ).to_pydatetime()

                                # Position annotation at top of chart
                                y_max = ax.get_ylim()[1]
                                y_pos = y_max * 0.95  # 95% from bottom

                                # Color based on annotation type
                                color = (
                                    "#FFD700"
                                    if annotation.get("type") == "cost_basis"
                                    else "#00c853"
                                )
                                if (
                                    annotation.get("type") == "total_pnl"
                                    and annotation.get("value", 0) < 0
                                ):
                                    color = "#ff1744"  # Red for negative P/L

                                ax.annotate(
                                    annotation["text"],
                                    xy=(ann_date, y_pos),
                                    xytext=(0, 10),
                                    textcoords="offset points",
                                    ha="center",
                                    va="bottom",
                                    fontsize=7,
                                    color=color,
                                    bbox=dict(
                                        boxstyle="round,pad=0.2",
                                        facecolor=color,
                                        alpha=0.3,
                                        edgecolor=color,
                                    ),
                                )
                            except Exception as ann_error:
                                print(f"Error adding annotation: {ann_error}")
                                continue

                # Save the figure with enhanced error handling
                try:
                    fig.savefig(chart_filepath, dpi=100, bbox_inches="tight")
                    chart_saved_successfully = True
                    plt.close(fig)  # Close the figure to free memory
                except Exception as save_error:
                    plt.close(fig)  # Ensure figure is closed even on error
                    await ctx.send(
                        f"❌ **File System Error**: Failed to save chart for **{symbol}**\n"
                        f"• Error: {str(save_error)}\n"
                        f"• Check disk space and file permissions\n"
                        f"• Chart directory: {chart_dir}"
                    )
                    return

                # Prepare response message with trade info and chart metadata
                trade_info = ""
                if not trade_data.empty:
                    buy_trades = trade_data[trade_data["action"].str.lower() == "buy"]
                    sell_trades = trade_data[trade_data["action"].str.lower() == "sell"]
                    total_trades = len(trade_data)
                    if total_trades > 0:
                        trade_info = (
                            f" | 🔺{len(buy_trades)} buys, 🔻{len(sell_trades)} sells"
                        )
                        if len(label_data) > 0:
                            trade_info += " | P/L calculated"

                # Add position analysis info if available
                position_info = ""
                if position_analysis and "position_summary" in position_analysis:
                    summary = position_analysis["position_summary"]
                    if summary.get("current_shares", 0) > 0:
                        position_info = (
                            f" | 📈 Pos: {summary['current_shares']:.0f} shares"
                        )
                        if (
                            cost_basis_series is not None
                            and not cost_basis_series.empty
                        ):
                            position_info += " | 💰 Cost basis line shown"

                # Add chart metadata info
                chart_info = f" | Saved: {chart_filename}"

                # Send chart with enhanced messaging
                file = discord.File(chart_filepath, filename=chart_filename)
                embed = build_embed(
                    category=EmbedCategory.CHART,
                    title=f"{symbol} - {period.upper()} Chart",
                    description=f"Theme: {theme}{trade_info}{position_info}",
                    image_url=f"attachment://{chart_filename}",
                    footer_hint=f"Saved: {chart_filename}",
                )
                await ctx.send(embed=embed, file=file)

        except Exception as e:
            await ctx.send(
                embed=EmbedFactory.error(
                    title=f"Chart Error: {symbol}",
                    description=str(e),
                    error_details="Please check the symbol and try again.",
                )
            )

        finally:
            # Clean up temporary files (keep organized charts in directory)
            # Only remove if chart was saved successfully to the organized directory
            if chart_saved_successfully and chart_filepath.exists():
                # Chart is saved in organized directory structure, no cleanup needed
                pass
            else:
                # If there was an error and a temporary file exists, clean it up
                temp_chart_path = (
                    Path(chart_filename) if "chart_filename" in locals() else None
                )
                if temp_chart_path and temp_chart_path.exists():
                    try:
                        temp_chart_path.unlink()
                    except Exception:
                        pass  # Ignore cleanup errors

    @bot.command(name="position")
    async def analyze_position(ctx, symbol: Optional[str] = None, period: str = "1y"):
        """
        Analyze position history and performance for a stock symbol.

        Args:
            symbol: Stock ticker symbol (required)
            period: Analysis period (1mo, 3mo, 6mo, 1y, 2y, max)
        """
        if symbol is None:
            await ctx.send(
                embed=EmbedFactory.error(
                    title="Missing Symbol",
                    description="Symbol is required!",
                    error_details="Usage Examples:\n`!position AAPL` - 1 year position analysis\n`!position TSLA 6mo` - 6 month position analysis",
                )
            )
            return

        # Convert symbol to uppercase
        symbol = symbol.upper()

        # Validate period
        valid_periods = ["1mo", "3mo", "6mo", "1y", "2y", "max"]
        if period not in valid_periods:
            await ctx.send(
                embed=EmbedFactory.error(
                    title="Invalid Period",
                    description=f"Invalid period '{period}'",
                    error_details="Available periods: " + ", ".join(valid_periods),
                )
            )
            return

        try:
            async with ctx.typing():
                # Calculate date range for analysis
                start_date, end_date = calculate_chart_date_range(period)

                # Generate position report
                report = generate_position_report(symbol, start_date, end_date)

                # Check if report indicates an error or no data
                if report.startswith("❌"):
                    await ctx.send(
                        embed=EmbedFactory.create(
                            title=f"No Position Data Found for {symbol}",
                            description=(
                                f"• No trades found in the {period} period\n"
                                f"• Use `!chart {symbol}` to see price movement\n"
                                f"• Try a longer period if you have older trades"
                            ),
                            category=EmbedCategory.WARNING,
                        )
                    )
                    return

                # Send the position analysis report
                # Parse the report title from the first line if possible, or use generic
                lines = report.strip().split("\n")
                title = (
                    lines[0].replace("**", "").strip()
                    if lines
                    else f"Position Analysis: {symbol}"
                )
                content = "\n".join(lines[1:]) if len(lines) > 1 else report

                await ctx.send(
                    embed=EmbedFactory.create(
                        title=title, description=content, category=EmbedCategory.CHART
                    )
                )

                # Also provide a suggestion for chart viewing
                await ctx.send(
                    f"💡 **Tip**: Use `!chart {symbol} {period}` to see the visual chart with trade markers and cost basis line!"
                )

        except Exception as e:
            await ctx.send(
                f"❌ **Error analyzing position for {symbol}**\n"
                f"• Error: {str(e)}\n"
                f"• Please check the symbol and try again"
            )
