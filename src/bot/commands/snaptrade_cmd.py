"""
SnapTrade Data Commands

Discord bot commands for fetching and managing SnapTrade brokerage data.
Provides commands for manual data refresh, portfolio queries, and position analysis.

Uses the centralized UI system for consistent embed styling.
"""

import logging
from datetime import datetime, timezone

from discord.ext import commands, tasks
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
_auto_refresh_running = False


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
    async def show_portfolio_pie(ctx, top_n: int = 17):
        """Show a pie chart of your portfolio allocation by value.

        Usage:
            !piechart      - Top 17 positions by value (default)
            !pie 10        - Top 10 positions
            !allocation 25 - Top 25 positions

        Features:
            • Donut-style pie chart with Discord dark theme
            • Shows position values and percentages
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

            # Build description with summary stats
            description_lines = [
                f"💰 **Total Value:** ${stats.get('total_equity', 0):,.2f}",
                f"📊 **Positions:** {stats.get('num_positions', 0)} ({stats.get('num_winners', 0)} winners, {stats.get('num_losers', 0)} losers)",
            ]

            total_pnl = stats.get("total_pnl", 0)
            pnl_emoji = "📈" if total_pnl >= 0 else "📉"
            pnl_sign = "+" if total_pnl >= 0 else ""
            description_lines.append(
                f"{pnl_emoji} **Total P/L:** {pnl_sign}${total_pnl:,.2f} ({pnl_sign}{stats.get('overall_pnl_pct', 0):.1f}%)"
            )

            embed = build_embed(
                category=EmbedCategory.CHART,
                title="📊 Portfolio Allocation",
                description="\n".join(description_lines),
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
    async def show_recent_orders(ctx, limit: int = 15):
        """Show your recent orders with enhanced analytics.

        Usage:
            !orders      - Last 15 orders with P/L analysis
            !orders 30   - Last 30 orders

        Displays:
            • Order action (BUY/SELL) with execution price
            • Realized P/L % (for SELL orders against avg cost)
            • Position % of current holdings
            • Portfolio weight (% of total equity)
            • Execution date and time
        """
        try:
            from src.db import execute_sql
            from datetime import date, timedelta

            # Enhanced query - join with positions to get avg_price and current holdings
            result = execute_sql(
                """
                SELECT 
                    o.symbol, o.action, o.status, 
                    o.total_quantity, o.open_quantity, o.filled_quantity,
                    o.execution_price, o.limit_price, o.stop_price,
                    o.time_executed, o.time_placed, o.sync_timestamp,
                    p.average_buy_price, p.quantity as position_qty, p.equity as position_equity
                FROM orders o
                LEFT JOIN positions p ON o.symbol = p.symbol
                ORDER BY COALESCE(o.time_executed, o.time_placed, o.sync_timestamp) DESC
                LIMIT :limit
                """,
                params={"limit": limit},
                fetch_results=True,
            )

            if not result:
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title="Recent Orders",
                        description="No orders found.\nUse `!fetch orders` to sync.",
                    )
                )
                return

            # Get total portfolio equity for weight calculation
            portfolio_result = execute_sql(
                "SELECT COALESCE(SUM(equity), 0) FROM positions WHERE quantity > 0",
                fetch_results=True,
            )
            total_portfolio_equity = (
                float(portfolio_result[0][0]) if portfolio_result else 0
            )

            # Process orders
            processed_orders = []
            today_executed_count = 0
            open_pending_count = 0
            total_realized_pnl = 0.0

            today = date.today()

            for row in result:
                (
                    symbol,
                    action,
                    status,
                    total_qty,
                    open_qty,
                    filled_qty,
                    exec_price,
                    limit_price,
                    stop_price,
                    time_exec,
                    time_placed,
                    sync_ts,
                    avg_buy_price,
                    position_qty,
                    position_equity,
                ) = row

                # Determine effective date
                effective_date = time_exec or time_placed or sync_ts

                # Quantity Logic
                status_upper = (status or "").upper()
                if status_upper in ["EXECUTED", "PARTIALLY_FILLED", "FILLED"]:
                    qty = filled_qty if filled_qty is not None else total_qty
                    if effective_date and effective_date.date() == today:
                        today_executed_count += 1
                else:
                    qty = open_qty if open_qty is not None else total_qty
                    if status_upper in ["OPEN", "PENDING"]:
                        open_pending_count += 1

                # Fallback if qty is 0 or None
                if not qty:
                    qty = total_qty or 0

                # Price Logic
                price = exec_price or limit_price or stop_price
                price = float(price) if price is not None else None
                qty = float(qty)
                avg_buy_price = float(avg_buy_price) if avg_buy_price else None
                position_qty = float(position_qty) if position_qty else 0
                position_equity = float(position_equity) if position_equity else 0

                # Calculate Realized P/L % (for SELL orders)
                realized_pnl_pct = None
                realized_pnl_dollar = None
                action_upper = (action or "").upper()
                if (
                    action_upper == "SELL"
                    and price
                    and avg_buy_price
                    and avg_buy_price > 0
                ):
                    realized_pnl_pct = ((price - avg_buy_price) / avg_buy_price) * 100
                    realized_pnl_dollar = (price - avg_buy_price) * qty
                    total_realized_pnl += realized_pnl_dollar

                # Calculate position % (order qty vs current position qty)
                position_pct = None
                if position_qty > 0:
                    position_pct = (qty / position_qty) * 100

                # Calculate portfolio weight
                portfolio_weight = None
                if total_portfolio_equity > 0 and price:
                    order_value = price * qty
                    portfolio_weight = (order_value / total_portfolio_equity) * 100

                processed_orders.append(
                    {
                        "symbol": symbol or "N/A",
                        "action": action_upper or "N/A",
                        "status": status_upper or "N/A",
                        "qty": qty,
                        "price": price,
                        "avg_price": avg_buy_price,
                        "date": effective_date,
                        "realized_pnl_pct": realized_pnl_pct,
                        "realized_pnl_dollar": realized_pnl_dollar,
                        "position_pct": position_pct,
                        "portfolio_weight": portfolio_weight,
                    }
                )

            def format_order_line(o):
                """Format a single order line with enhanced analytics."""
                emoji = action_emoji(o["action"])

                # Format Price
                price_str = f"${o['price']:.2f}" if o["price"] is not None else "-"

                # Format Date with time if available
                if o["date"]:
                    if hasattr(o["date"], "strftime"):
                        date_str = o["date"].strftime("%m/%d %H:%M")
                    else:
                        date_str = str(o["date"])[:14]
                else:
                    date_str = "??"

                # Build main line
                main_line = f"{emoji} **{o['symbol']}** {o['action']} {o['qty']:.1f} @ {price_str}"

                # Build analytics line
                analytics = []

                # Average cost basis (for context)
                if o["avg_price"]:
                    analytics.append(f"Avg: ${o['avg_price']:.2f}")

                # Realized P/L % (only for SELL)
                if o["realized_pnl_pct"] is not None:
                    pnl_emoji = "📈" if o["realized_pnl_pct"] >= 0 else "📉"
                    pnl_str = f"{o['realized_pnl_pct']:+.1f}%"
                    if o["realized_pnl_dollar"] is not None:
                        pnl_str += f" (${o['realized_pnl_dollar']:+,.0f})"
                    analytics.append(f"{pnl_emoji}P/L: {pnl_str}")

                # Position percentage
                if o["position_pct"] is not None:
                    analytics.append(f"Pos: {o['position_pct']:.0f}%")

                # Portfolio weight
                if o["portfolio_weight"] is not None:
                    analytics.append(f"Wt: {o['portfolio_weight']:.1f}%")

                # Combine lines
                result_line = f"{main_line} ({o['status']} {date_str})"
                if analytics:
                    result_line += f"\n   └ {' • '.join(analytics)}"

                return result_line

            # Summary Header with realized P/L
            summary_parts = [
                f"📅 **Today:** {today_executed_count} executed, {open_pending_count} open/pending"
            ]
            if total_realized_pnl != 0:
                pnl_emoji = "📈" if total_realized_pnl >= 0 else "📉"
                summary_parts.append(
                    f"{pnl_emoji} **Realized P/L:** ${total_realized_pnl:+,.2f}"
                )
            summary = " • ".join(summary_parts)

            # Build description (may need multiple embeds for long lists)
            order_lines = [format_order_line(o) for o in processed_orders]
            description = f"{summary}\n\n" + "\n".join(order_lines)

            # Truncate if too long for embed
            if len(description) > 4000:
                description = description[:3997] + "..."

            embed = build_embed(
                category=EmbedCategory.ORDERS,
                title="Recent Orders",
                description=description,
            )

            embed.set_footer(
                text="💡 Use !fetch orders to sync • 🟢 BUY 🔴 SELL • P/L calculated vs avg cost"
            )
            await ctx.send(embed=embed)

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

        Uses yesterday's close from daily_prices or yfinance fallback.
        """
        from datetime import datetime, timezone, timedelta

        try:
            from src.db import execute_sql
            import yfinance as yf

            # Track calculation time
            calc_time = datetime.now(timezone.utc)

            # Fetch positions with current prices
            result = execute_sql(
                """
                SELECT
                    p.symbol,
                    p.quantity,
                    p.equity,
                    p.current_price
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

            # Fetch yesterday's close from daily_prices for all symbols
            symbols = [row[0] for row in result]
            placeholders = ", ".join(f"'{s}'" for s in symbols)

            yesterday_prices = {}
            try:
                cached_result = execute_sql(
                    f"""
                    SELECT symbol, close
                    FROM daily_prices
                    WHERE symbol IN ({placeholders})
                    AND date = :yesterday
                    """,
                    params={"yesterday": str(yesterday)},
                    fetch_results=True,
                )
                if cached_result:
                    yesterday_prices = {row[0]: float(row[1]) for row in cached_result}
            except Exception as cache_err:
                logger.warning(f"Cache lookup error: {cache_err}")

            # Process positions with yesterday's close
            positions = []
            missing_symbols = []

            for row in result:
                symbol, qty, equity, current_price = row
                qty = float(qty or 0)
                equity = float(equity or 0)
                current_price = float(current_price or 0)

                # Get yesterday's close - try cache first, then yfinance
                prev_close = yesterday_prices.get(symbol)

                if prev_close is None and current_price > 0:
                    missing_symbols.append(symbol)
                    # Will batch fetch from yfinance below
                    prev_close = None

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

            # Batch fetch missing symbols from yfinance (limit to 10 to avoid rate limits)
            if missing_symbols:
                try:
                    for sym in missing_symbols[:10]:
                        ticker = yf.Ticker(sym)
                        hist = ticker.history(period="2d", interval="1d")
                        if len(hist) >= 2:
                            prev_close = float(hist["Close"].iloc[-2])
                            # Update the position with correct data
                            for p in positions:
                                if p["symbol"] == sym and prev_close > 0:
                                    p["prev_close"] = prev_close
                                    p["daily_pct"] = (
                                        (p["current_price"] - prev_close) / prev_close
                                    ) * 100
                                    p["daily_dollar"] = (
                                        p["current_price"] - prev_close
                                    ) * p["qty"]
                except Exception as yf_err:
                    logger.warning(f"yfinance fallback error: {yf_err}")

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

    # Background task for automatic refresh (every 24 hours)
    @tasks.loop(hours=24)
    async def auto_refresh_snaptrade():
        """Automatically refresh SnapTrade data every 24 hours."""
        global _last_refresh_time

        logger.info("🔄 Starting automatic SnapTrade data refresh...")

        try:
            from src.snaptrade_collector import SnapTradeCollector

            collector = SnapTradeCollector()
            results = collector.collect_all_data(write_parquet=False)

            _last_refresh_time = datetime.now(timezone.utc)

            if results.get("success"):
                logger.info(f"✅ Auto-refresh complete: {results}")
            else:
                logger.warning(f"⚠️ Auto-refresh had errors: {results.get('errors')}")

        except Exception as e:
            logger.error(f"❌ Auto-refresh failed: {e}")

    @auto_refresh_snaptrade.before_loop
    async def before_auto_refresh():
        """Wait for bot to be ready before starting auto-refresh."""
        await bot.wait_until_ready()
        logger.info("🕐 Auto-refresh task scheduled (every 24 hours)")

    @bot.command(name="auto_on", aliases=["start_auto_refresh"])
    async def start_auto_refresh(ctx):
        """Start automatic 24-hour data sync (admin)."""
        global _auto_refresh_running

        if auto_refresh_snaptrade.is_running():
            await ctx.send(
                embed=EmbedFactory.warning(
                    title="Auto-Refresh Already Running",
                    description="The background sync task is already active.",
                )
            )
            return

        auto_refresh_snaptrade.start()
        _auto_refresh_running = True

        embed = build_embed(
            category=EmbedCategory.SUCCESS,
            title="Auto-Refresh Started",
            description="SnapTrade data will sync automatically every **24 hours**.",
            footer_hint="Use !auto_off to stop",
        )
        await ctx.send(embed=embed)

    @bot.command(name="auto_off", aliases=["stop_auto_refresh"])
    async def stop_auto_refresh(ctx):
        """Stop automatic data sync (admin)."""
        global _auto_refresh_running

        if not auto_refresh_snaptrade.is_running():
            await ctx.send(
                embed=EmbedFactory.warning(
                    title="Auto-Refresh Not Running",
                    description="No background sync task is currently active.",
                )
            )
            return

        auto_refresh_snaptrade.cancel()
        _auto_refresh_running = False

        embed = build_embed(
            category=EmbedCategory.ADMIN,
            title="Auto-Refresh Stopped",
            description="Automatic background sync has been disabled.",
            footer_hint="Use !auto_on to restart",
        )
        await ctx.send(embed=embed)
