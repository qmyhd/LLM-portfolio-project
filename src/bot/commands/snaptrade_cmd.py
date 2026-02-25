"""
SnapTrade Data Commands

Discord bot commands for fetching and managing SnapTrade brokerage data.
Provides commands for manual data refresh, portfolio queries, and position analysis.

Uses the centralized UI system for consistent embed styling.
"""

import logging
from datetime import datetime, timezone

from discord.ext import commands
import discord

from src.bot.ui.embed_factory import (
    EmbedCategory,
    EmbedFactory,
    build_embed,
    format_money,
    format_pnl,
    format_percent,
    render_table,
    action_emoji,
)
from src.bot.ui.portfolio_view import PortfolioView
from src.bot.ui.portfolio_chart import (
    generate_portfolio_pie_chart,
    generate_portfolio_summary_stats,
)

logger = logging.getLogger(__name__)

# Track last refresh time to enable incremental fetching
_last_refresh_time = None
# NOTE: _auto_refresh_running removed — nightly-pipeline.timer is the canonical scheduler


def register(bot: commands.Bot, twitter_client=None):
    """Register SnapTrade commands with the bot."""

    @bot.command(name="fetch", aliases=["sync", "refresh"])
    async def fetch_snaptrade(ctx, data_type: str = "all"):
        """Sync data from your brokerage account.

        Usage:
            !fetch         - Sync all data (accounts, positions, orders)
            !fetch positions - Sync only positions
            !fetch orders    - Sync only orders
            !fetch balances  - Sync only account balances
        """
        global _last_refresh_time

        # Create loading embed
        status_msg = await ctx.send(
            embed=EmbedFactory.loading(
                title="Syncing Brokerage Data",
                description=f"Fetching **{data_type}** from SnapTrade...",
            )
        )

        try:
            from src.snaptrade_collector import SnapTradeCollector

            collector = SnapTradeCollector()
            start_time = datetime.now(timezone.utc)

            if data_type == "all":
                results = collector.collect_all_data(write_parquet=False)
            elif data_type == "positions":
                df = collector.get_positions()
                if not df.empty:
                    collector.write_to_database(
                        df, "positions", conflict_columns=["symbol", "account_id"]
                    )
                results = {"success": True, "positions": len(df)}
            elif data_type == "orders":
                df = collector.get_orders()
                if not df.empty:
                    collector.write_to_database(
                        df, "orders", conflict_columns=["brokerage_order_id"]
                    )
                results = {"success": True, "orders": len(df)}
            elif data_type == "balances":
                df = collector.get_balances()
                if not df.empty:
                    collector.write_to_database(
                        df,
                        "account_balances",
                        conflict_columns=[
                            "account_id",
                            "currency_code",
                            "snapshot_date",
                        ],
                    )
                results = {"success": True, "balances": len(df)}
            else:
                await status_msg.edit(
                    embed=EmbedFactory.error(
                        title="Invalid Data Type",
                        description=f"Unknown type: `{data_type}`",
                        error_details="Valid options: all, positions, orders, balances",
                    )
                )
                return

            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            _last_refresh_time = datetime.now(timezone.utc)

            if results.get("success"):
                # Build success embed with summary
                summary_lines = []
                if "accounts" in results:
                    summary_lines.append(f"🏦 **Accounts:** {results['accounts']}")
                if "positions" in results:
                    summary_lines.append(f"📊 **Positions:** {results['positions']}")
                if "orders" in results:
                    summary_lines.append(f"📜 **Orders:** {results['orders']}")
                if "balances" in results:
                    summary_lines.append(f"💰 **Balances:** {results['balances']}")
                if "symbols" in results:
                    summary_lines.append(f"🏷️ **Symbols:** {results['symbols']}")

                embed = EmbedFactory.success(
                    title="Sync Complete",
                    description=(
                        "\n".join(summary_lines) if summary_lines else "Data synced"
                    ),
                    footer_hint=f"⏱️ {elapsed:.1f}s • {_last_refresh_time.strftime('%H:%M UTC')}",
                )
                await status_msg.edit(embed=embed)
            else:
                errors = results.get("errors", ["Unknown error"])
                await status_msg.edit(
                    embed=EmbedFactory.warning(
                        title="Sync Completed with Errors",
                        description="\n".join(f"• {e}" for e in errors[:5]),
                    )
                )

        except ImportError as e:
            await status_msg.edit(
                embed=EmbedFactory.error(
                    title="SDK Not Available",
                    description="SnapTrade SDK not installed",
                    error_details=str(e),
                )
            )
        except Exception as e:
            logger.error(f"Error fetching SnapTrade data: {e}")
            await status_msg.edit(
                embed=EmbedFactory.error(
                    title="Sync Failed", error_details=str(e)[:300]
                )
            )

    @bot.command(name="portfolio", aliases=["positions", "holdings"])
    async def show_portfolio(
        ctx, filter_or_limit: str | None = None, limit: int | None = None
    ):
        """Show your current portfolio positions with P/L (interactive).

        Usage:
            !portfolio           - Interactive portfolio view (all positions)
            !portfolio 50        - Show up to 50 positions
            !portfolio winners   - Show only winning positions (sorted by P/L%)
            !portfolio losers    - Show only losing positions (sorted by P/L%)
            !portfolio winners 30 - Show top 30 winners

        Features:
            • Page through positions
            • Filter: All / Winners / Losers
            • Toggle P/L display: $ vs %
            • Live refresh button
        """
        try:
            from src.db import execute_sql

            # Parse arguments - handle both filter and limit in either order
            filter_mode = "all"
            effective_limit = 100  # Default limit

            if filter_or_limit is not None:
                # Check if it's a filter keyword
                if filter_or_limit.lower() in ["winners", "winner", "w"]:
                    filter_mode = "winners"
                elif filter_or_limit.lower() in ["losers", "loser", "l"]:
                    filter_mode = "losers"
                elif filter_or_limit.isdigit():
                    effective_limit = int(filter_or_limit)

            # Override limit if explicitly provided as second arg
            if limit is not None:
                effective_limit = limit

            result = execute_sql(
                """
                SELECT symbol, quantity, price, equity, average_buy_price, open_pnl
                FROM positions
                WHERE quantity > 0
                ORDER BY equity DESC
                LIMIT :limit
                """,
                params={"limit": effective_limit},
                fetch_results=True,
            )

            if not result:
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title="Portfolio",
                        description="No positions found.\nUse `!fetch` to sync data.",
                    )
                )
                return

            # Get last sync time
            sync_result = execute_sql(
                "SELECT MAX(sync_timestamp) FROM positions", fetch_results=True
            )
            last_sync = "Unknown"
            if sync_result and sync_result[0][0]:
                ts = sync_result[0][0]
                if hasattr(ts, "strftime"):
                    last_sync = ts.strftime("%Y-%m-%d %H:%M UTC")
                else:
                    last_sync = str(ts)[:16]

            # Transform to position dicts for PortfolioView
            positions_data = []
            for row in result:
                symbol, qty, price, equity, avg_price, pnl = row
                qty = qty or 0
                price = price or 0
                equity = equity or 0
                avg_price = avg_price or 0
                pnl = pnl or 0
                cost_basis = avg_price * qty
                pnl_pct = (
                    ((price - avg_price) / avg_price * 100) if avg_price > 0 else 0
                )

                positions_data.append(
                    {
                        "symbol": symbol or "N/A",
                        "quantity": qty,
                        "price": price,
                        "equity": equity,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "cost": cost_basis,
                    }
                )

            # Apply filter if specified via command argument
            if filter_mode == "winners":
                positions_data = [p for p in positions_data if p["pnl"] > 0]
                # Sort by P/L% descending for winners
                positions_data.sort(key=lambda x: x["pnl_pct"], reverse=True)
            elif filter_mode == "losers":
                positions_data = [p for p in positions_data if p["pnl"] < 0]
                # Sort by P/L% ascending for losers (worst first)
                positions_data.sort(key=lambda x: x["pnl_pct"])

            if not positions_data:
                filter_desc = {"all": "", "winners": "winning ", "losers": "losing "}
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title="Portfolio",
                        description=f"No {filter_desc[filter_mode]}positions found.\nUse `!fetch` to sync data or try a different filter.",
                    )
                )
                return

            # Create interactive view with pre-applied filter
            view = PortfolioView(
                positions_data,
                page_size=10,
                title=f"📊 Portfolio Positions (Last sync: {last_sync})",
                initial_filter=filter_mode,
            )
            await ctx.send(embed=view.build_embed(), view=view)

        except Exception as e:
            logger.error(f"Error showing portfolio: {e}")
            await ctx.send(
                embed=EmbedFactory.error("Portfolio Error", error_details=str(e)[:200])
            )

    @bot.command(name="piechart", aliases=["pie", "allocation", "breakdown"])
    async def show_portfolio_pie(ctx, top_n: int = 10):
        """Show a pie chart of your portfolio allocation by value.

        Usage:
            !piechart      - Top 10 positions by value (default)
            !pie 10        - Top 10 positions
            !allocation 25 - Top 25 positions

        Features:
            • Donut-style pie chart with Discord dark theme
            • Ticker symbols and company logos inside each slice
            • Aggregates smaller holdings into "Others"
            • Total portfolio value displayed in center
        """
        try:
            from src.db import execute_sql

            # Fetch all positions with value > 0
            result = execute_sql(
                """
                SELECT symbol, quantity, price, equity, average_buy_price, open_pnl
                FROM positions
                WHERE quantity > 0 AND equity > 0
                ORDER BY equity DESC
                """,
                fetch_results=True,
            )

            if not result:
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title="Portfolio Pie Chart",
                        description="No positions found.\nUse `!fetch` to sync your brokerage data first.",
                    )
                )
                return

            # Transform to position dicts
            positions_data = []
            for row in result:
                symbol, qty, price, equity, avg_price, pnl = row
                qty = qty or 0
                price = price or 0
                equity = equity or 0
                avg_price = avg_price or 0
                pnl = pnl or 0
                cost_basis = avg_price * qty
                pnl_pct = (
                    ((price - avg_price) / avg_price * 100) if avg_price > 0 else 0
                )

                positions_data.append(
                    {
                        "symbol": symbol or "N/A",
                        "quantity": qty,
                        "price": price,
                        "equity": equity,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "cost": cost_basis,
                    }
                )

            if not positions_data:
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title="Portfolio Pie Chart",
                        description="No positions with value found.",
                    )
                )
                return

            # Generate pie chart
            buffer, chart_filename = generate_portfolio_pie_chart(
                positions_data,
                top_n=top_n,
                title=f"Portfolio Top {min(top_n, len(positions_data))} Holdings by Value",
            )

            if buffer is None:
                await ctx.send(
                    embed=EmbedFactory.error(
                        title="Chart Generation Failed",
                        description="Could not generate pie chart.",
                    )
                )
                return

            # Generate summary stats
            stats = generate_portfolio_summary_stats(positions_data)

            # Create embed with chart
            file = discord.File(buffer, filename=chart_filename)

            # Build description - only positions count (Total Value and P/L removed, chart shows them)
            description = f"📊 **Positions:** {stats.get('num_positions', 0)} ({stats.get('num_winners', 0)} winners, {stats.get('num_losers', 0)} losers)"

            embed = build_embed(
                category=EmbedCategory.CHART,
                title="📊 Portfolio Allocation",
                description=description,
                image_url=f"attachment://{chart_filename}",
                footer_hint=f"Showing top {min(top_n, len(positions_data))} of {len(positions_data)} positions",
            )

            await ctx.send(embed=embed, file=file)

        except Exception as e:
            logger.error(f"Error generating portfolio pie chart: {e}")
            await ctx.send(
                embed=EmbedFactory.error(
                    title="Pie Chart Error", error_details=str(e)[:200]
                )
            )

    @bot.command(name="orders", aliases=["recent_orders", "trades"])
    async def show_recent_orders(ctx, symbol_or_limit: str = None, limit: int = 10):
        """Show your recent executed orders with card-style embeds.

        Usage:
            !orders              - Last 10 executed orders (card-style)
            !orders 20           - Last 20 executed orders
            !orders TSLA         - Executed orders for TSLA with position summary
            !orders nvidia       - Executed orders for NVDA (company name resolved)
            !orders AAPL 15      - Last 15 executed AAPL orders

        Features:
            • Card-style embed per order with action, price, qty
            • Only shows executed/filled orders (excludes pending/cancelled)
            • Execution dates in EST timezone (e.g., "Nov 13, 2025")
            • Position summary with company logo when filtering by symbol
            • Accepts company names (nvidia, tesla) or tickers (NVDA, TSLA)
            • Shows nearest Discord idea with 💡 timestamp
            • Price change since trade (current vs execution price)
            • Color-coded: green for buys, red for sells
            • Dividend reinvestments (<$2 buys) hidden from default view
              - Use !orders SYMBOL to see ALL orders including DRIP
              - DRIP orders are annotated with 🟡 when shown
        """
        try:
            from src.db import execute_sql
            from src.bot.formatting.orders_view import (
                OrderFormatter,
                format_money,
                format_pct,
                format_qty,
                normalize_side,
                get_order_color,
            )
            from src.bot.ui.symbol_resolver import resolve_symbol, get_symbol_info
            from src.bot.ui.logo_helper import get_logo_url
            from datetime import date, timedelta
            from src.price_service import get_latest_close

            # Parse arguments: determine if filtering by symbol or just limit
            ticker_filter = None
            company_description = None
            effective_limit = 10

            if symbol_or_limit is not None:
                if symbol_or_limit.isdigit():
                    # It's a limit number
                    effective_limit = int(symbol_or_limit)
                else:
                    # It's a ticker symbol or company name - resolve it
                    ticker_filter, company_description = resolve_symbol(symbol_or_limit)
                    effective_limit = limit  # Use second arg as limit

            # Build query based on filter - only show executed/filled orders
            executed_statuses = ("EXECUTED", "FILLED", "PARTIALLY_FILLED")
            if ticker_filter:
                # Filter by symbol - also handle option-style symbols
                result = execute_sql(
                    """
                    SELECT
                        o.symbol, o.action, o.status, o.order_type,
                        o.total_quantity, o.open_quantity, o.filled_quantity,
                        o.execution_price, o.limit_price, o.stop_price,
                        o.time_executed, o.time_placed, o.created_at, o.sync_timestamp,
                        o.brokerage_order_id,
                        o.option_ticker, o.option_expiry, o.option_strike, o.option_right
                    FROM orders o
                    WHERE (o.symbol = :ticker OR o.symbol LIKE :ticker_pattern)
                        AND UPPER(o.status) IN ('EXECUTED', 'FILLED', 'PARTIALLY_FILLED')
                    ORDER BY COALESCE(o.time_executed, o.time_placed, o.sync_timestamp) DESC
                    LIMIT :limit
                    """,
                    params={
                        "ticker": ticker_filter,
                        "ticker_pattern": f"{ticker_filter}%",
                        "limit": effective_limit,
                    },
                    fetch_results=True,
                )
            else:
                # All executed orders
                result = execute_sql(
                    """
                    SELECT
                        o.symbol, o.action, o.status, o.order_type,
                        o.total_quantity, o.open_quantity, o.filled_quantity,
                        o.execution_price, o.limit_price, o.stop_price,
                        o.time_executed, o.time_placed, o.created_at, o.sync_timestamp,
                        o.brokerage_order_id,
                        o.option_ticker, o.option_expiry, o.option_strike, o.option_right
                    FROM orders o
                    WHERE UPPER(o.status) IN ('EXECUTED', 'FILLED', 'PARTIALLY_FILLED')
                    ORDER BY COALESCE(o.time_executed, o.time_placed, o.sync_timestamp) DESC
                    LIMIT :limit
                    """,
                    params={"limit": effective_limit},
                    fetch_results=True,
                )

            if not result:
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title="Recent Executed Orders",
                        description=f"No executed orders found{f' for {ticker_filter}' if ticker_filter else ''}.\nUse `!fetch orders` to sync.",
                    )
                )
                return

            # Convert to dicts
            columns = [
                "symbol",
                "action",
                "status",
                "order_type",
                "total_quantity",
                "open_quantity",
                "filled_quantity",
                "execution_price",
                "limit_price",
                "stop_price",
                "time_executed",
                "time_placed",
                "created_at",
                "sync_timestamp",
                "brokerage_order_id",
                "option_ticker",
                "option_expiry",
                "option_strike",
                "option_right",
            ]
            orders = [dict(zip(columns, row, strict=False)) for row in result]

            # Get current prices for "price since trade" calculation
            symbols = list(set(o["symbol"] for o in orders if o["symbol"]))
            current_prices = {}

            # Try to get from positions first (use 'price' column, not 'current_price' which is NULL)
            if symbols:
                placeholders = ", ".join(f"'{s}'" for s in symbols)
                pos_result = execute_sql(
                    f"""
                    SELECT symbol, price, quantity, average_buy_price, equity, open_pnl
                    FROM positions
                    WHERE symbol IN ({placeholders})
                    """,
                    fetch_results=True,
                )
                if pos_result:
                    for row in pos_result:
                        sym, curr_price, qty, avg_price, equity, pnl = row
                        if curr_price:
                            current_prices[sym] = {
                                "current_price": float(curr_price),
                                "quantity": float(qty or 0),
                                "avg_price": float(avg_price) if avg_price else None,
                                "equity": float(equity or 0),
                                "pnl": float(pnl or 0),
                            }

            # Fallback to price_service (RDS ohlcv_daily) for missing prices
            missing = [s for s in symbols if s not in current_prices]
            if missing and len(missing) <= 5:  # Only fetch if small number
                try:
                    for sym in missing:
                        price = get_latest_close(sym)
                        if price:
                            current_prices[sym] = {"current_price": float(price)}
                except Exception:
                    pass  # Silently fail on price fetch

            embeds = []

            # Get logo URL for symbol filter (for thumbnail)
            logo_url = None
            if ticker_filter:
                logo_url = get_logo_url(ticker_filter)

            # Position Summary embed (when filtering by ticker)
            if ticker_filter and ticker_filter in current_prices:
                pos_data = current_prices[ticker_filter]
                qty = pos_data.get("quantity", 0)
                curr_price = pos_data.get("current_price", 0)
                avg_price = pos_data.get("avg_price")
                equity = pos_data.get("equity", 0)
                pnl = pos_data.get("pnl", 0)

                if qty > 0:
                    pnl_pct = (
                        ((curr_price - avg_price) / avg_price * 100)
                        if avg_price and avg_price > 0
                        else 0
                    )
                    pnl_emoji = "📈" if pnl >= 0 else "📉"

                    # Build title with company name if available
                    title = f"📊 {ticker_filter}"
                    if company_description:
                        title += f" — {company_description}"
                    title += " Position Summary"

                    summary_embed = discord.Embed(
                        title=title,
                        color=0x2ECC71 if pnl >= 0 else 0xE74C3C,
                    )

                    # Add logo as thumbnail
                    if logo_url:
                        summary_embed.set_thumbnail(url=logo_url)

                    summary_embed.add_field(
                        name="Shares", value=format_qty(qty), inline=True
                    )
                    summary_embed.add_field(
                        name="Avg Cost", value=format_money(avg_price), inline=True
                    )
                    summary_embed.add_field(
                        name="Current", value=format_money(curr_price), inline=True
                    )
                    summary_embed.add_field(
                        name="Market Value", value=format_money(equity), inline=True
                    )
                    summary_embed.add_field(
                        name="Unrealized P/L",
                        value=f"{format_money(pnl, include_sign=True)} ({format_pct(pnl_pct)})",
                        inline=True,
                    )
                    embeds.append(summary_embed)
                else:
                    # Position closed
                    title = f"📊 {ticker_filter}"
                    if company_description:
                        title += f" — {company_description}"

                    summary_embed = discord.Embed(
                        title=title,
                        description=f"Position: **Closed** (0 shares)\nCurrent price: {format_money(curr_price)}",
                        color=0x808080,
                    )
                    if logo_url:
                        summary_embed.set_thumbnail(url=logo_url)
                    embeds.append(summary_embed)
            elif ticker_filter:
                # No position data for this ticker
                title = f"📊 {ticker_filter}"
                if company_description:
                    title += f" — {company_description}"

                summary_embed = discord.Embed(
                    title=title,
                    description="No current position (may be closed or never held)",
                    color=0x808080,
                )
                if logo_url:
                    summary_embed.set_thumbnail(url=logo_url)
                embeds.append(summary_embed)

            # Order card embeds (up to 9, since Discord limit is 10 embeds)
            max_order_embeds = 9 if embeds else 10

            # Track dividend reinvestments filtered out for info message
            drip_count = 0
            orders_shown = 0

            for order in orders:
                if orders_shown >= max_order_embeds:
                    break

                symbol = order["symbol"] or "N/A"
                curr_price = current_prices.get(symbol, {}).get("current_price")
                formatter = OrderFormatter(order, current_price=curr_price)

                # Filter out dividend reinvestments from default view (no ticker filter)
                # When filtering by specific ticker, show ALL orders including reinvestments
                if not ticker_filter and formatter.is_dividend_reinvestment:
                    drip_count += 1
                    continue

                embed_data = formatter.to_embed_dict(include_idea=True)

                order_embed = discord.Embed(
                    title=embed_data["title"],
                    description=embed_data["description"],
                    color=embed_data["color"],
                )

                # Add company logo as thumbnail for professional appearance
                order_symbol = symbol.upper() if symbol and symbol != "N/A" else None
                if order_symbol and not order_symbol.startswith("Others"):
                    try:
                        order_logo_url = get_logo_url(order_symbol)
                        if order_logo_url:
                            order_embed.set_thumbnail(url=order_logo_url)
                    except Exception:
                        pass  # Skip logo on error

                # Add nearest Discord idea field if available
                if "idea_field" in embed_data:
                    idea = embed_data["idea_field"]
                    order_embed.add_field(
                        name=idea["name"],
                        value=idea["value"],
                        inline=idea.get("inline", False),
                    )

                order_embed.set_footer(text=embed_data["footer"])
                embeds.append(order_embed)
                orders_shown += 1

            # Check if we truncated (account for filtered orders)
            remaining_orders = len(orders) - orders_shown - drip_count
            footer_parts = []

            if remaining_orders > 0:
                footer_parts.append(
                    f"... and {remaining_orders} more orders. Use `!orders {effective_limit + 10}` to see more."
                )

            # Inform about filtered dividend reinvestments (only in default view)
            if drip_count > 0 and not ticker_filter:
                footer_parts.append(
                    f"*{drip_count} dividend reinvestment(s) hidden. Use `!orders SYMBOL` to see all orders for a ticker.*"
                )

            if footer_parts:
                note_embed = discord.Embed(
                    description="\n".join(footer_parts),
                    color=0x808080,
                )
                embeds.append(note_embed)

            # Send embeds (Discord allows up to 10 per message)
            await ctx.send(embeds=embeds[:10])

        except Exception as e:
            logger.error(f"Error showing orders: {e}")
            await ctx.send(
                embed=EmbedFactory.error("Orders Error", error_details=str(e)[:200])
            )

    @bot.command(name="movers", aliases=["gainers", "losers", "pnl"])
    async def show_movers(ctx):
        """Show top performers by Daily % Change and Daily $ Profit.

        Displays two sorted views:
        • By Daily % Change - Best/worst percentage moves
        • By Daily $ Profit - Biggest dollar winners/losers

        Uses yesterday's close from RDS ohlcv_daily (Databento).
        """
        from datetime import datetime, timezone, timedelta

        try:
            from src.db import execute_sql
            from src.price_service import get_previous_close, get_latest_close_batch

            # Track calculation time
            calc_time = datetime.now(timezone.utc)

            # Fetch positions with current prices (use 'price' column, not 'current_price')
            result = execute_sql(
                """
                SELECT
                    p.symbol,
                    p.quantity,
                    p.equity,
                    p.price
                FROM positions p
                WHERE p.quantity > 0
                """,
                fetch_results=True,
            )

            if not result:
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title="Portfolio Movers",
                        description="No positions found.\nUse `!fetch` to sync data.",
                    )
                )
                return

            # Get yesterday's date (market date)
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            # Handle weekends - get Friday's close
            if yesterday.weekday() == 6:  # Sunday
                yesterday = yesterday - timedelta(days=2)
            elif yesterday.weekday() == 5:  # Saturday
                yesterday = yesterday - timedelta(days=1)

            # Fetch yesterday's close from RDS ohlcv_daily for all symbols
            symbols = [row[0] for row in result]

            yesterday_prices = {}
            try:
                # Batch fetch previous closes from price_service
                for sym in symbols:
                    prev_close = get_previous_close(sym, today)
                    if prev_close:
                        yesterday_prices[sym] = prev_close
            except Exception as cache_err:
                logger.warning(f"Price service lookup error: {cache_err}")

            # Process positions with yesterday's close
            positions = []

            for row in result:
                symbol, qty, equity, current_price = row
                qty = float(qty or 0)
                equity = float(equity or 0)
                current_price = float(current_price or 0)

                # Get yesterday's close from price_service
                prev_close = yesterday_prices.get(symbol)

                if prev_close and prev_close > 0 and current_price > 0:
                    # Calculate daily metrics
                    daily_pct = ((current_price - prev_close) / prev_close) * 100
                    daily_dollar = (current_price - prev_close) * qty
                else:
                    daily_pct = 0.0
                    daily_dollar = 0.0
                    prev_close = current_price  # Use current as fallback

                positions.append(
                    {
                        "symbol": symbol,
                        "qty": qty,
                        "equity": equity,
                        "current_price": current_price,
                        "prev_close": prev_close or current_price,
                        "daily_pct": daily_pct,
                        "daily_dollar": daily_dollar,
                    }
                )

            # Create two sorted lists
            by_pct = sorted(positions, key=lambda x: x["daily_pct"], reverse=True)
            by_dollar = sorted(positions, key=lambda x: x["daily_dollar"], reverse=True)

            top_gainers_pct = [p for p in by_pct[:5] if p["daily_pct"] > 0]
            top_losers_pct = [p for p in by_pct[-5:][::-1] if p["daily_pct"] < 0]
            top_gainers_dollar = [p for p in by_dollar[:5] if p["daily_dollar"] > 0]
            top_losers_dollar = [
                p for p in by_dollar[-5:][::-1] if p["daily_dollar"] < 0
            ]

            # Build embed using design system
            embed = build_embed(
                category=EmbedCategory.MOVERS,
                title="📊 Portfolio Movers (Daily)",
                description=f"Sorted by **% Change** and **$ Profit**\n*Using {yesterday.strftime('%b %d')} close as baseline*",
            )

            # Top Gainers by % Change
            gainers_pct_text = []
            for p in top_gainers_pct:
                gainers_pct_text.append(
                    f"📈 **{p['symbol']}** +{p['daily_pct']:.2f}% (${p['prev_close']:.2f}→${p['current_price']:.2f})"
                )
            embed.add_field(
                name="📈 Top Gainers (% Change)",
                value=(
                    "\n".join(gainers_pct_text)
                    if gainers_pct_text
                    else "No gainers today"
                ),
                inline=True,
            )

            # Top Losers by % Change
            losers_pct_text = []
            for p in top_losers_pct:
                losers_pct_text.append(
                    f"📉 **{p['symbol']}** {p['daily_pct']:.2f}% (${p['prev_close']:.2f}→${p['current_price']:.2f})"
                )
            embed.add_field(
                name="📉 Top Losers (% Change)",
                value=(
                    "\n".join(losers_pct_text) if losers_pct_text else "No losers today"
                ),
                inline=True,
            )

            # Spacer for layout
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            # Top Gainers by $ Profit
            gainers_dollar_text = []
            for p in top_gainers_dollar:
                gainers_dollar_text.append(
                    f"💰 **{p['symbol']}** +${p['daily_dollar']:.2f} ({p['qty']:.0f} shares)"
                )
            embed.add_field(
                name="💰 Top Gainers ($ Profit)",
                value=(
                    "\n".join(gainers_dollar_text)
                    if gainers_dollar_text
                    else "No $ gainers today"
                ),
                inline=True,
            )

            # Top Losers by $ Loss
            losers_dollar_text = []
            for p in top_losers_dollar:
                losers_dollar_text.append(
                    f"💸 **{p['symbol']}** ${p['daily_dollar']:.2f} ({p['qty']:.0f} shares)"
                )
            embed.add_field(
                name="💸 Top Losers ($ Loss)",
                value=(
                    "\n".join(losers_dollar_text)
                    if losers_dollar_text
                    else "No $ losers today"
                ),
                inline=True,
            )

            # Summary footer with timestamps
            total_daily_dollar = sum(p["daily_dollar"] for p in positions)
            total_equity = sum(p["equity"] for p in positions)
            pnl_emoji = "📈" if total_daily_dollar >= 0 else "📉"

            # Calculate next update time (market open 9:30 AM ET or every hour during market hours)
            next_update = calc_time + timedelta(hours=1)

            embed.set_footer(
                text=(
                    f"{pnl_emoji} Daily P/L: {format_money(total_daily_dollar, include_sign=True)} • "
                    f"Portfolio: {format_money(total_equity)}\n"
                    f"⏰ Calculated: {calc_time.strftime('%H:%M:%S')} UTC • "
                    f"Next: ~{next_update.strftime('%H:%M')} UTC"
                )
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error showing movers: {e}")
            await ctx.send(
                embed=EmbedFactory.error("Movers Error", error_details=str(e)[:200])
            )

    @bot.command(name="status", aliases=["data_status", "db"])
    async def show_data_status(ctx):
        """Show data freshness and database statistics."""
        try:
            from src.db import execute_sql

            tables = [
                ("accounts", None, "🏦"),
                ("positions", "sync_timestamp", "📊"),
                ("orders", "sync_timestamp", "📜"),
                ("symbols", "updated_at", "🏷️"),
                ("discord_messages", "created_at", "💬"),
                ("discord_trading_clean", "processed_at", "🧹"),
                ("discord_market_clean", "processed_at", "📰"),
            ]

            # Build table data
            table_data = []
            total_rows = 0
            for table, ts_col, icon in tables:
                try:
                    count_result = execute_sql(
                        f"SELECT COUNT(*) FROM {table}", fetch_results=True
                    )
                    count = count_result[0][0] if count_result else 0
                    total_rows += count

                    last_updated = "—"
                    if ts_col and count > 0:
                        ts_result = execute_sql(
                            f"SELECT MAX({ts_col}) FROM {table}", fetch_results=True
                        )
                        if ts_result and ts_result[0][0]:
                            ts = ts_result[0][0]
                            if hasattr(ts, "strftime"):
                                last_updated = ts.strftime("%m/%d %H:%M")
                            else:
                                last_updated = str(ts)[:14]

                    table_data.append(
                        {
                            "icon": icon,
                            "table": table,
                            "count": count,
                            "updated": last_updated,
                        }
                    )
                except Exception:
                    table_data.append(
                        {
                            "icon": icon,
                            "table": table,
                            "count": 0,
                            "updated": "error",
                        }
                    )

            # Format as table
            table_text = render_table(
                headers=["", "Table", "Rows", "Updated"],
                rows=[
                    [d["icon"], d["table"], f"{d['count']:,}", d["updated"]]
                    for d in table_data
                ],
            )

            # Build embed
            global _last_refresh_time
            footer = (
                f"Last sync: {_last_refresh_time.strftime('%Y-%m-%d %H:%M UTC')}"
                if _last_refresh_time
                else "No sync this session • Use !fetch to sync"
            )

            embed = build_embed(
                category=EmbedCategory.STATS,
                title="Data Status",
                description=f"```\n{table_text}\n```",
                footer_hint=f"📊 Total rows: {total_rows:,} • {footer}",
            )

            await ctx.send(embed=embed)

        except Exception as e:
            logger.error(f"Error showing data status: {e}")
            await ctx.send(
                embed=EmbedFactory.error("Status Error", error_details=str(e)[:200])
            )

    # NOTE: Automatic background refresh (auto_on/auto_off) has been removed.
    # The canonical scheduler is the systemd nightly-pipeline.timer (1 AM daily).
    # Use !fetch for manual on-demand sync.
