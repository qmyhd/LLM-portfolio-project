"""
Portfolio Interactive View

Provides paginated, filterable portfolio display with:
- Page navigation
- Filter buttons (All, Winners, Losers)
- P/L display toggle ($ vs %)
- Refresh button
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import discord

from .embed_factory import (
    EmbedCategory,
    EmbedFactory,
    EmbedField,
    format_money,
    format_pnl,
    format_percent,
    pnl_emoji,
    render_table,
)


class PortfolioView(discord.ui.View):
    """Interactive portfolio view with pagination and filters."""

    def __init__(
        self,
        positions: List[Dict[str, Any]],
        page_size: int = 10,
        timeout: float = 120.0,
        title: str = "📊 Portfolio Positions",
        initial_filter: str = "all",
    ):
        """Initialize portfolio view.

        Args:
            positions: List of position dicts with keys:
                symbol, quantity, price, equity, pnl, pnl_pct, cost
            page_size: Positions per page
            timeout: View timeout in seconds
            title: Embed title
            initial_filter: Initial filter mode ("all", "winners", "losers")
        """
        super().__init__(timeout=timeout)
        self.all_positions = positions
        self.positions = positions.copy()
        self.page_size = page_size
        self.title = title
        self.current_page = 0
        self.filter_mode = initial_filter  # all | winners | losers
        self.display_mode = "dollar"  # dollar | percent

        # Apply initial filter if not "all"
        if initial_filter != "all":
            self._apply_filter()

        self._update_button_states()

    @property
    def total_pages(self) -> int:
        """Total number of pages based on filtered positions."""
        if not self.positions:
            return 1
        return max(1, (len(self.positions) + self.page_size - 1) // self.page_size)

    @property
    def current_slice(self) -> List[Dict[str, Any]]:
        """Get positions for current page."""
        start = self.current_page * self.page_size
        end = start + self.page_size
        return self.positions[start:end]

    def _apply_filter(self):
        """Apply current filter to positions and sort appropriately."""
        if self.filter_mode == "winners":
            self.positions = [p for p in self.all_positions if p.get("pnl", 0) > 0]
            # Sort winners by P/L% descending (best performers first)
            self.positions.sort(key=lambda x: x.get("pnl_pct", 0), reverse=True)
        elif self.filter_mode == "losers":
            self.positions = [p for p in self.all_positions if p.get("pnl", 0) < 0]
            # Sort losers by P/L% ascending (worst performers first)
            self.positions.sort(key=lambda x: x.get("pnl_pct", 0))
        else:
            self.positions = self.all_positions.copy()
            # Default sort by equity (largest positions first)

        # Reset to first page when filter changes
        self.current_page = 0

    def _update_button_states(self):
        """Update button enabled/disabled states."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                # Navigation buttons
                if child.custom_id == "prev":
                    child.disabled = self.current_page == 0
                elif child.custom_id == "next":
                    child.disabled = self.current_page >= self.total_pages - 1
                # Filter buttons - highlight active
                elif child.custom_id == "filter_all":
                    child.style = (
                        discord.ButtonStyle.primary
                        if self.filter_mode == "all"
                        else discord.ButtonStyle.secondary
                    )
                elif child.custom_id == "filter_winners":
                    child.style = (
                        discord.ButtonStyle.success
                        if self.filter_mode == "winners"
                        else discord.ButtonStyle.secondary
                    )
                elif child.custom_id == "filter_losers":
                    child.style = (
                        discord.ButtonStyle.danger
                        if self.filter_mode == "losers"
                        else discord.ButtonStyle.secondary
                    )
                # Display mode toggle
                elif child.custom_id == "toggle_mode":
                    child.label = (
                        "Show %" if self.display_mode == "dollar" else "Show $"
                    )

    def _calculate_totals(self) -> Dict[str, float]:
        """Calculate totals from filtered positions."""
        total_equity = sum(p.get("equity", 0) for p in self.positions)
        total_pnl = sum(p.get("pnl", 0) for p in self.positions)
        total_cost = sum(p.get("cost", 0) for p in self.positions)
        total_pnl_pct = (
            ((total_equity - total_cost) / total_cost * 100) if total_cost > 0 else 0
        )

        return {
            "equity": total_equity,
            "pnl": total_pnl,
            "cost": total_cost,
            "pnl_pct": total_pnl_pct,
            "count": len(self.positions),
        }

    def _find_extremes(self) -> tuple:
        """Find best and worst positions by P/L."""
        if not self.all_positions:
            return None, None

        sorted_by_pnl = sorted(self.all_positions, key=lambda x: x.get("pnl", 0))
        worst = sorted_by_pnl[0] if sorted_by_pnl else None
        best = sorted_by_pnl[-1] if sorted_by_pnl else None

        return best, worst

    def build_embed(self) -> discord.Embed:
        """Build the portfolio embed for current state."""
        totals = self._calculate_totals()
        best, worst = self._find_extremes()

        # Determine color based on P/L
        color = 0x2ECC71 if totals["pnl"] >= 0 else 0xE74C3C

        # Build summary section with both $ and % P/L
        summary_lines = [
            f"**💰 Total Value:** {format_money(totals['equity'])}",
            f"**{pnl_emoji(totals['pnl'])} Total P/L:** {format_pnl(totals['pnl'], show_emoji=False)} ({format_percent(totals['pnl_pct'])})",
        ]

        # Add best/worst inline with both $ and %
        if best and worst and best != worst:
            best_pnl_str = f"{format_percent(best.get('pnl_pct', 0))}"
            worst_pnl_str = f"{format_percent(worst.get('pnl_pct', 0))}"
            summary_lines.append(
                f"**🏆 Best:** {best['symbol']} {best_pnl_str} • "
                f"**📉 Worst:** {worst['symbol']} {worst_pnl_str}"
            )

        summary = "\n".join(summary_lines)

        # Build positions table
        positions_slice = self.current_slice

        if positions_slice:
            # Table headers - always show both $ and % P/L
            headers = ["Symbol", "Qty", "Price", "Value", "P/L ($)", "P/L (%)"]
            rows = []

            for p in positions_slice:
                symbol = p.get("symbol", "N/A")[:8]
                qty = f"{p.get('quantity', 0):.1f}"
                price = f"${p.get('price', 0):.2f}"
                value = f"${p.get('equity', 0):,.0f}"

                # Always show both P/L formats
                pnl_dollar = p.get("pnl", 0)
                pnl_percent = p.get("pnl_pct", 0)
                pnl_d_str = f"${pnl_dollar:+,.0f}" if pnl_dollar != 0 else "$0"
                pnl_p_str = f"{pnl_percent:+.1f}%" if pnl_percent != 0 else "0.0%"

                rows.append([symbol, qty, price, value, pnl_d_str, pnl_p_str])

            # Add summary row separator and totals
            rows.append(["─" * 6, "─" * 4, "─" * 6, "─" * 7, "─" * 7, "─" * 6])
            total_pnl = totals["pnl"]
            total_pnl_pct = totals["pnl_pct"]
            rows.append(
                [
                    "TOTAL",
                    f"{len(self.positions)}",
                    "",
                    f"${totals['equity']:,.0f}",
                    f"${total_pnl:+,.0f}",
                    f"{total_pnl_pct:+.1f}%",
                ]
            )

            table = render_table(
                headers=headers,
                rows=rows,
                alignments=["l", "r", "r", "r", "r", "r"],
                max_rows=self.page_size + 2,  # +2 for separator and summary row
            )
        else:
            table = "```\nNo positions match filter\n```"

        # Create embed
        embed = discord.Embed(
            title=self.title,
            description=f"{summary}\n\n{table}",
            color=color,
        )

        # Add filter indicator
        filter_text = {
            "all": "All Positions",
            "winners": "📈 Winners Only",
            "losers": "📉 Losers Only",
        }

        embed.set_footer(
            text=f"Page {self.current_page + 1}/{self.total_pages} • "
            f"{filter_text[self.filter_mode]} • "
            f"{len(self.positions)} positions • "
            f"Use buttons below to navigate"
        )

        return embed

    async def update_message(self, interaction: discord.Interaction):
        """Update message with new state."""
        self._update_button_states()
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    # Navigation buttons (Row 0)
    @discord.ui.button(
        label="◀️ Prev",
        style=discord.ButtonStyle.secondary,
        custom_id="prev",
        row=0,
    )
    async def prev_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to previous page."""
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_message(interaction)

    @discord.ui.button(
        label="Next ▶️",
        style=discord.ButtonStyle.secondary,
        custom_id="next",
        row=0,
    )
    async def next_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Go to next page."""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
        await self.update_message(interaction)

    @discord.ui.button(
        label="Show %",
        style=discord.ButtonStyle.secondary,
        custom_id="toggle_mode",
        row=0,
    )
    async def toggle_display(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Toggle between $ and % display."""
        self.display_mode = "percent" if self.display_mode == "dollar" else "dollar"
        await self.update_message(interaction)

    # Filter buttons (Row 1)
    @discord.ui.button(
        label="All",
        style=discord.ButtonStyle.primary,
        custom_id="filter_all",
        row=1,
    )
    async def filter_all(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Show all positions."""
        self.filter_mode = "all"
        self._apply_filter()
        await self.update_message(interaction)

    @discord.ui.button(
        label="📈 Winners",
        style=discord.ButtonStyle.secondary,
        custom_id="filter_winners",
        row=1,
    )
    async def filter_winners(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Show only winning positions."""
        self.filter_mode = "winners"
        self._apply_filter()
        await self.update_message(interaction)

    @discord.ui.button(
        label="📉 Losers",
        style=discord.ButtonStyle.secondary,
        custom_id="filter_losers",
        row=1,
    )
    async def filter_losers(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Show only losing positions."""
        self.filter_mode = "losers"
        self._apply_filter()
        await self.update_message(interaction)

    @discord.ui.button(
        label="🔁 Refresh",
        style=discord.ButtonStyle.primary,
        custom_id="refresh",
        row=1,
    )
    async def refresh_data(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Refresh portfolio data from database."""
        # Show loading state
        button.disabled = True
        button.label = "⏳ Refreshing..."
        await interaction.response.edit_message(view=self)

        try:
            # Fetch fresh data
            from src.db import execute_sql

            result = execute_sql(
                """
                SELECT symbol, quantity, price, equity, average_buy_price, open_pnl
                FROM positions
                WHERE quantity > 0
                ORDER BY equity DESC
                LIMIT 100
                """,
                fetch_results=True,
            )

            if result:
                new_positions = []
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

                    new_positions.append(
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

                self.all_positions = new_positions
                self._apply_filter()

        except Exception:
            pass  # Keep existing data on error

        # Reset button
        button.disabled = False
        button.label = "🔁 Refresh"
        self._update_button_states()

        await interaction.edit_original_response(
            embed=self.build_embed(),
            view=self,
        )

    async def on_timeout(self):
        """Disable all buttons on timeout."""
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True
