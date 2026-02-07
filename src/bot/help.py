"""
Custom Help Command for Portfolio Bot

Provides a clean, grouped help output with interactive category selection.
Commands are organized by feature category with concise descriptions.
"""

import discord
from discord.ext import commands

from src.bot.ui.help_view import HelpView
from src.bot.ui import EmbedFactory, EmbedCategory


class PortfolioHelpCommand(commands.HelpCommand):
    """Custom help command with grouped categories and interactive navigation."""

    # Command categories with descriptions
    CATEGORIES = {
        "📈 Portfolio & SnapTrade": {
            "description": "View and sync your brokerage data",
            "commands": {
                "fetch": "Sync data from brokerage (positions/orders/balances)",
                "portfolio": "Show current positions with P/L (interactive)",
                "piechart": "Pie chart with ticker symbols and logos inside each slice",
                "orders": "Show executed orders (DRIP filtered, `!orders AAPL` to see all)",
                "movers": "Top/bottom performers by daily and total P/L",
                "status": "Data freshness and row counts",
            },
        },
        "💬 Discord Analytics": {
            "description": "Process and analyze Discord messages",
            "commands": {
                "history": "Fetch message history to database",
                "process": "Clean and process recent messages",
                "backfill": "Import full channel history (one-time)",
            },
        },
        "🐦 Twitter & News": {
            "description": "Twitter data and sentiment analysis",
            "commands": {
                "twitter": "Twitter data for a stock symbol",
                "tweets": "Recent tweets mentioning stocks",
                "twitter_stats": "Twitter activity statistics",
                "twitter_backfill": "Backfill Twitter data from Discord links",
            },
        },
        "📊 Charts & Analysis": {
            "description": "Stock charts and technical analysis",
            "commands": {
                "chart": "Generate stock chart with position overlay",
                "piechart": "Portfolio allocation pie chart with in-slice labels",
            },
        },
        "🔧 Admin": {
            "description": "Administrative commands",
            "commands": {
                "fetch": "Manual on-demand brokerage data sync",
                "status": "Show data freshness and database stats",
            },
        },
    }

    # Hidden/internal commands (not shown in help)
    HIDDEN_COMMANDS = {"EOD", "peekraw"}

    def get_command_signature(self, command):
        """Get a clean command signature."""
        return f"!{command.qualified_name}"

    async def send_bot_help(self, mapping):
        """Send the interactive help message with category dropdown."""
        view = HelpView(self.CATEGORIES)
        await self.get_destination().send(
            embed=view.build_initial_embed(),
            view=view,
        )

    async def send_command_help(self, command):
        """Send help for a specific command."""
        # Check if command is hidden
        if (
            command.name.upper() in self.HIDDEN_COMMANDS
            or command.name in self.HIDDEN_COMMANDS
        ):
            await self.get_destination().send(
                embed=EmbedFactory.warning(
                    title="Command Not Found",
                    description=f"Command `{command.name}` not found or is hidden.",
                )
            )
            return

        embed = EmbedFactory.create(
            title=f"📖 !{command.qualified_name}",
            description=command.help or "No description available.",
            category=EmbedCategory.INFO,
        )

        # Add usage
        if command.signature:
            embed.add_field(
                name="Usage",
                value=f"`!{command.qualified_name} {command.signature}`",
                inline=False,
            )
        else:
            embed.add_field(
                name="Usage",
                value=f"`!{command.qualified_name}`",
                inline=False,
            )

        # Add aliases if any
        if command.aliases:
            embed.add_field(
                name="Aliases",
                value=", ".join(f"`!{a}`" for a in command.aliases),
                inline=False,
            )

        embed.set_footer(text="💡 Use !help to see all categories")

        await self.get_destination().send(embed=embed)

    async def send_error_message(self, error):
        """Send error message for unknown commands."""
        await self.get_destination().send(
            embed=EmbedFactory.error(title="Help Error", description=str(error))
        )

    async def send_cog_help(self, cog):
        """Send help for a cog (category)."""
        # We don't use cogs, so redirect to main help
        await self.send_bot_help(None)

    async def send_group_help(self, group):
        """Send help for a command group."""
        # We don't use groups, so redirect to command help
        await self.send_command_help(group)


def setup_help(bot: commands.Bot):
    """Replace the default help command with our custom one."""
    bot.help_command = PortfolioHelpCommand()
