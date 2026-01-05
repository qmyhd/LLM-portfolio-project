"""
Embed Factory - Centralized Embed Builder

Provides consistent styling across all bot embeds with:
- Category-based color coding
- Standardized layouts
- Money/percent formatting
- Status emoji conventions
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Union

import discord


class EmbedCategory(Enum):
    """Embed categories with associated colors and emojis."""

    # Portfolio / SnapTrade - Green
    PORTFOLIO = ("portfolio", 0x2ECC71, "📊")  # Green
    POSITIONS = ("positions", 0x2ECC71, "📈")
    ORDERS = ("orders", 0x27AE60, "📜")
    BALANCES = ("balances", 0x1ABC9C, "💰")
    MOVERS = ("movers", 0x2ECC71, "🔥")

    # Discord Analytics - Blue
    DISCORD = ("discord", 0x3498DB, "💬")  # Blue
    STATS = ("stats", 0x2980B9, "📉")
    HISTORY = ("history", 0x3498DB, "📚")

    # Twitter - Cyan
    TWITTER = ("twitter", 0x1DA1F2, "🐦")  # Twitter Blue
    SENTIMENT = ("sentiment", 0x17A2B8, "📰")

    # Charts & Analysis - Purple
    CHART = ("chart", 0x9B59B6, "📈")
    ANALYSIS = ("analysis", 0x8E44AD, "🔬")

    # Admin / System - Orange/Red
    ADMIN = ("admin", 0xE67E22, "⚙️")  # Orange
    WARNING = ("warning", 0xF39C12, "⚠️")  # Yellow/Orange
    ERROR = ("error", 0xE74C3C, "❌")  # Red
    SUCCESS = ("success", 0x2ECC71, "✅")  # Green
    INFO = ("info", 0x3498DB, "ℹ️")  # Blue

    # Help
    HELP = ("help", 0x9B59B6, "📖")  # Purple

    @property
    def color(self) -> int:
        return self.value[1]

    @property
    def emoji(self) -> str:
        return self.value[2]

    @classmethod
    def from_string(cls, name: str) -> "EmbedCategory":
        """Get category from string name."""
        name_lower = name.lower()
        for cat in cls:
            if cat.value[0] == name_lower:
                return cat
        return cls.INFO  # Default


# Status emojis
STATUS_EMOJIS = {
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "pending": "⏳",
    "loading": "🔄",
    "refresh": "🔁",
    "time": "⏱️",
    "updated": "🔁",
    "info": "ℹ️",
}

# Action emojis for orders
ACTION_EMOJIS = {
    "buy": "🟢",
    "sell": "🔴",
    "sell_short": "🟡",
    "cover": "🟣",
    "dividend": "💵",
    "split": "✂️",
}

# P/L directional emojis
PNL_EMOJIS = {
    "up": "📈",
    "down": "📉",
    "flat": "➡️",
}


def status_emoji(status: str) -> str:
    """Get status emoji by name."""
    return STATUS_EMOJIS.get(status.lower(), "•")


def action_emoji(action: str) -> str:
    """Get action emoji for order types."""
    return ACTION_EMOJIS.get(action.lower(), "•")


def pnl_emoji(value: float) -> str:
    """Get P/L directional emoji."""
    if value > 0:
        return PNL_EMOJIS["up"]
    elif value < 0:
        return PNL_EMOJIS["down"]
    return PNL_EMOJIS["flat"]


def format_money(value: float, include_sign: bool = False) -> str:
    """Format money with $ symbol, 2 decimals, thousands separators.

    Examples:
        format_money(1234.567) -> "$1,234.57"
        format_money(-500.5, include_sign=True) -> "-$500.50"
        format_money(1000, include_sign=True) -> "+$1,000.00"
    """
    if value is None:
        return "$0.00"

    if include_sign:
        if value >= 0:
            return f"+${value:,.2f}"
        else:
            return f"-${abs(value):,.2f}"
    else:
        if value >= 0:
            return f"${value:,.2f}"
        else:
            return f"-${abs(value):,.2f}"


def format_pnl(value: float, show_emoji: bool = True) -> str:
    """Format P/L value with emoji and sign.

    Examples:
        format_pnl(1500.50) -> "📈 +$1,500.50"
        format_pnl(-200.00) -> "📉 -$200.00"
    """
    if value is None:
        return "➡️ $0.00"

    emoji = pnl_emoji(value) if show_emoji else ""
    money = format_money(value, include_sign=True)

    return f"{emoji} {money}".strip()


def format_percent(value: float, include_sign: bool = True) -> str:
    """Format percentage with sign.

    Examples:
        format_percent(15.5) -> "+15.50%"
        format_percent(-3.2) -> "-3.20%"
    """
    if value is None:
        return "0.00%"

    if include_sign:
        return f"{value:+.2f}%"
    return f"{value:.2f}%"


def render_table(
    headers: List[str],
    rows: List[List[str]],
    alignments: Optional[List[str]] = None,
    max_rows: int = 15,
) -> str:
    """Render a monospace table for Discord code blocks.

    Args:
        headers: Column headers
        rows: List of row data (each row is a list of strings)
        alignments: List of 'l', 'r', 'c' for each column
        max_rows: Maximum rows to display

    Returns:
        Formatted table string wrapped in code block
    """
    if not rows:
        return "```\nNo data available\n```"

    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows[:max_rows]:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    # Default alignments (right for numbers, left for text)
    if not alignments:
        alignments = ["l"] * len(headers)

    def format_cell(text: str, width: int, align: str) -> str:
        text = str(text)
        if align == "r":
            return text.rjust(width)
        elif align == "c":
            return text.center(width)
        return text.ljust(width)

    # Build table
    lines = ["```"]

    # Header
    header_line = " ".join(
        format_cell(h, col_widths[i], alignments[i]) for i, h in enumerate(headers)
    )
    lines.append(header_line)
    lines.append("─" * len(header_line))

    # Data rows
    displayed_rows = rows[:max_rows]
    for row in displayed_rows:
        row_line = " ".join(
            format_cell(str(cell), col_widths[i], alignments[i])
            for i, cell in enumerate(row)
            if i < len(col_widths)
        )
        lines.append(row_line)

    # Truncation indicator
    if len(rows) > max_rows:
        lines.append(f"... +{len(rows) - max_rows} more rows")

    lines.append("```")
    return "\n".join(lines)


@dataclass
class EmbedField:
    """Embed field data."""

    name: str
    value: str
    inline: bool = True


class EmbedFactory:
    """Factory for creating consistent Discord embeds."""

    @staticmethod
    def create(
        category: Union[EmbedCategory, str],
        title: str,
        description: Optional[str] = None,
        fields: Optional[List[EmbedField]] = None,
        footer_hint: Optional[str] = None,
        timestamp: bool = True,
        thumbnail_url: Optional[str] = None,
        image_url: Optional[str] = None,
        author_name: Optional[str] = None,
        author_icon_url: Optional[str] = None,
    ) -> discord.Embed:
        """Create a styled embed with consistent formatting.

        Args:
            category: EmbedCategory or string name for color/styling
            title: Embed title (emoji will be prepended from category)
            description: Main description text
            fields: List of EmbedField objects
            footer_hint: Helpful hints for footer
            timestamp: Whether to include timestamp
            thumbnail_url: Small image URL
            image_url: Large image URL
            author_name: Author name for top of embed
            author_icon_url: Author icon URL

        Returns:
            Styled discord.Embed
        """
        # Resolve category
        if isinstance(category, str):
            cat = EmbedCategory.from_string(category)
        else:
            cat = category

        # Build title with emoji
        full_title = f"{cat.emoji} {title}"

        # Create embed
        embed = discord.Embed(
            title=full_title,
            description=description,
            color=cat.color,
        )

        # Add fields
        if fields:
            for field in fields:
                embed.add_field(
                    name=field.name,
                    value=field.value,
                    inline=field.inline,
                )

        # Add footer with hints and timestamp
        footer_parts = []
        if footer_hint:
            footer_parts.append(f"💡 {footer_hint}")

        if footer_parts:
            embed.set_footer(text=" • ".join(footer_parts))

        if timestamp:
            embed.timestamp = datetime.utcnow()

        # Optional elements
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        if image_url:
            embed.set_image(url=image_url)
        if author_name:
            embed.set_author(name=author_name, icon_url=author_icon_url)

        return embed

    @staticmethod
    def success(
        title: str,
        description: Optional[str] = None,
        fields: Optional[List[EmbedField]] = None,
        footer_hint: Optional[str] = None,
    ) -> discord.Embed:
        """Create a success embed."""
        return EmbedFactory.create(
            category=EmbedCategory.SUCCESS,
            title=title,
            description=description,
            fields=fields,
            footer_hint=footer_hint,
        )

    @staticmethod
    def error(
        title: str,
        description: Optional[str] = None,
        error_details: Optional[str] = None,
    ) -> discord.Embed:
        """Create an error embed."""
        desc = description or ""
        if error_details:
            desc += f"\n```{error_details[:500]}```"

        return EmbedFactory.create(
            category=EmbedCategory.ERROR,
            title=title,
            description=desc,
            footer_hint="Try again or check logs for details",
        )

    @staticmethod
    def warning(
        title: str,
        description: Optional[str] = None,
    ) -> discord.Embed:
        """Create a warning embed."""
        return EmbedFactory.create(
            category=EmbedCategory.WARNING,
            title=title,
            description=description,
        )

    @staticmethod
    def loading(
        title: str = "Processing",
        description: Optional[str] = None,
    ) -> discord.Embed:
        """Create a loading/in-progress embed."""
        return EmbedFactory.create(
            category=EmbedCategory.INFO,
            title=f"🔄 {title}",
            description=description or "Please wait...",
            timestamp=False,
        )

    @staticmethod
    def portfolio_summary(
        total_value: float,
        total_pnl: float,
        total_pnl_pct: float,
        position_count: int,
        best_position: Optional[Dict[str, Any]] = None,
        worst_position: Optional[Dict[str, Any]] = None,
    ) -> discord.Embed:
        """Create a portfolio summary embed."""
        # Determine color based on P/L
        if total_pnl >= 0:
            cat = EmbedCategory.SUCCESS
        else:
            cat = EmbedCategory.ERROR

        # Build summary description
        desc_lines = [
            f"**Total Value:** {format_money(total_value)}",
            f"**Total P/L:** {format_pnl(total_pnl)} ({format_percent(total_pnl_pct)})",
            f"**Positions:** {position_count}",
        ]

        embed = EmbedFactory.create(
            category=cat,
            title="Portfolio Summary",
            description="\n".join(desc_lines),
        )

        # Add best/worst positions
        if best_position:
            embed.add_field(
                name="🏆 Top Performer",
                value=f"**{best_position['symbol']}** {format_pnl(best_position.get('pnl', 0))}",
                inline=True,
            )

        if worst_position:
            embed.add_field(
                name="📉 Worst Performer",
                value=f"**{worst_position['symbol']}** {format_pnl(worst_position.get('pnl', 0))}",
                inline=True,
            )

        return embed


# Convenience function for simple embed creation
def build_embed(
    category: Union[EmbedCategory, str],
    title: str,
    description: Optional[str] = None,
    fields: Optional[List[tuple]] = None,
    footer_hint: Optional[str] = None,
    **kwargs,
) -> discord.Embed:
    """Convenience function to build embeds quickly.

    Args:
        category: Category name or EmbedCategory
        title: Embed title
        description: Main text
        fields: List of (name, value, inline) tuples
        footer_hint: Footer hint text
        **kwargs: Additional EmbedFactory.create arguments

    Returns:
        discord.Embed
    """
    embed_fields = None
    if fields:
        embed_fields = [
            EmbedField(name=f[0], value=f[1], inline=f[2] if len(f) > 2 else True)
            for f in fields
        ]

    return EmbedFactory.create(
        category=category,
        title=title,
        description=description,
        fields=embed_fields,
        footer_hint=footer_hint,
        **kwargs,
    )
