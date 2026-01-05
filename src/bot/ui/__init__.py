"""
Bot UI Components - Design System

Centralized UI components for consistent Discord bot responses.
Implements a standardized visual language across all commands.
"""

from .embed_factory import (
    EmbedFactory,
    EmbedCategory,
    build_embed,
    format_money,
    format_pnl,
    format_percent,
    status_emoji,
    action_emoji,
    render_table,
)
from .portfolio_view import PortfolioView
from .help_view import HelpView, HelpSelect
from .pagination import PaginatedView

__all__ = [
    # Embed Factory
    "EmbedFactory",
    "EmbedCategory",
    "build_embed",
    "format_money",
    "format_pnl",
    "format_percent",
    "status_emoji",
    "action_emoji",
    "render_table",
    # Views
    "PortfolioView",
    "HelpView",
    "HelpSelect",
    "PaginatedView",
]
