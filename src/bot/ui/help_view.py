"""
Interactive Help View

Provides dropdown-based help navigation by category.
"""

from typing import Dict, List, Optional

import discord
from discord.ext import commands

from .embed_factory import EmbedCategory, EmbedFactory, EmbedField


class HelpSelect(discord.ui.Select):
    """Dropdown for selecting help category."""

    def __init__(self, categories: Dict[str, Dict]):
        """Initialize help select.

        Args:
            categories: Dict of category_name -> {description, commands}
        """
        self.categories = categories

        options = [
            discord.SelectOption(
                label=name.replace("📈 ", "")
                .replace("💬 ", "")
                .replace("🐦 ", "")
                .replace("📊 ", "")
                .replace("🔧 ", ""),
                description=data.get("description", "")[:50],
                emoji=name[0] if name[0] in "📈💬🐦📊🔧" else "📋",
                value=name,
            )
            for name, data in categories.items()
        ]

        super().__init__(
            placeholder="Choose a command category...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        """Handle category selection."""
        selected = self.values[0]
        category_data = self.categories.get(selected, {})

        # Build command list
        commands_dict = category_data.get("commands", {})
        commands_text = []

        for cmd_name, desc in commands_dict.items():
            commands_text.append(f"`!{cmd_name}` — {desc}")

        description = (
            "\n".join(commands_text)
            if commands_text
            else "No commands in this category"
        )

        # Determine color based on category
        if "Portfolio" in selected or "SnapTrade" in selected:
            color = 0x2ECC71  # Green
        elif "Discord" in selected:
            color = 0x3498DB  # Blue
        elif "Twitter" in selected:
            color = 0x1DA1F2  # Twitter blue
        elif "Admin" in selected:
            color = 0xE67E22  # Orange
        else:
            color = 0x9B59B6  # Purple

        embed = discord.Embed(
            title=f"📖 Help · {selected}",
            description=f"*{category_data.get('description', '')}*\n\n{description}",
            color=color,
        )
        embed.set_footer(text="💡 Type !help <command> for detailed usage")

        await interaction.response.edit_message(embed=embed, view=self.view)


class HelpView(discord.ui.View):
    """Interactive help view with category dropdown."""

    def __init__(self, categories: Dict[str, Dict], timeout: float = 120.0):
        """Initialize help view.

        Args:
            categories: Dict of category_name -> {description, commands}
            timeout: View timeout in seconds
        """
        super().__init__(timeout=timeout)
        self.categories = categories

        # Add the select dropdown
        self.add_item(HelpSelect(categories))

    def build_initial_embed(self) -> discord.Embed:
        """Build the initial help embed with overview."""
        embed = discord.Embed(
            title="📚 Portfolio Bot Commands",
            description="Select a category below to view commands, or type `!help <command>` for details.",
            color=0x9B59B6,  # Purple
        )

        # Add category overview
        for category_name, data in self.categories.items():
            cmd_count = len(data.get("commands", {}))
            embed.add_field(
                name=category_name,
                value=f"{data.get('description', '')} ({cmd_count} commands)",
                inline=False,
            )

        embed.set_footer(text="💡 Use the dropdown below to explore commands")

        return embed

    async def on_timeout(self):
        """Disable dropdown on timeout."""
        for child in self.children:
            if isinstance(child, discord.ui.Select):
                child.disabled = True


class StatsView(discord.ui.View):
    """Interactive stats view with drill-down buttons."""

    def __init__(
        self,
        stats_data: Dict,
        channel_name: Optional[str] = None,
        timeout: float = 120.0,
    ):
        """Initialize stats view.

        Args:
            stats_data: Statistics dictionary
            channel_name: Optional channel name for context
            timeout: View timeout in seconds
        """
        super().__init__(timeout=timeout)
        self.stats_data = stats_data
        self.channel_name = channel_name
        self.view_mode = "summary"  # summary | tickers | users | raw

    def build_summary_embed(self) -> discord.Embed:
        """Build summary statistics embed."""
        embed = discord.Embed(
            title=f"📉 Channel Statistics{f' · #{self.channel_name}' if self.channel_name else ''}",
            color=0x3498DB,
        )

        stats = self.stats_data

        # Summary fields
        embed.add_field(
            name="📊 Messages",
            value=f"**{stats.get('total_messages', 0):,}** total\n"
            f"{stats.get('processed', 0):,} processed",
            inline=True,
        )

        embed.add_field(
            name="🏷️ Tickers",
            value=f"**{stats.get('unique_tickers', 0)}** unique\n"
            f"{stats.get('total_mentions', 0):,} mentions",
            inline=True,
        )

        embed.add_field(
            name="👥 Users",
            value=f"**{stats.get('unique_users', 0)}** active",
            inline=True,
        )

        # Top tickers preview
        top_tickers = stats.get("top_tickers", [])
        if top_tickers:
            ticker_text = " • ".join(
                f"**${t['symbol']}** ({t['count']})" for t in top_tickers[:5]
            )
            embed.add_field(
                name="🔥 Top Tickers",
                value=ticker_text,
                inline=False,
            )

        embed.set_footer(text="Use buttons below for detailed views")

        return embed

    def build_tickers_embed(self) -> discord.Embed:
        """Build detailed tickers view."""
        embed = discord.Embed(
            title="🏷️ Ticker Mentions",
            color=0x3498DB,
        )

        top_tickers = self.stats_data.get("top_tickers", [])

        if top_tickers:
            lines = []
            for i, t in enumerate(top_tickers[:20], 1):
                lines.append(f"{i}. **${t['symbol']}** — {t['count']} mentions")
            embed.description = "\n".join(lines)
        else:
            embed.description = "No ticker data available"

        return embed

    def build_embed(self) -> discord.Embed:
        """Build embed based on current view mode."""
        if self.view_mode == "tickers":
            return self.build_tickers_embed()
        return self.build_summary_embed()

    async def update_message(self, interaction: discord.Interaction):
        """Update message with current view."""
        await interaction.response.edit_message(
            embed=self.build_embed(),
            view=self,
        )

    @discord.ui.button(
        label="📊 Summary",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def show_summary(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Show summary view."""
        self.view_mode = "summary"
        await self.update_message(interaction)

    @discord.ui.button(
        label="🏷️ Top Tickers",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def show_tickers(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Show tickers view."""
        self.view_mode = "tickers"
        await self.update_message(interaction)

    async def on_timeout(self):
        """Disable buttons on timeout."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
