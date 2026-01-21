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
    format_percent_colored,
    status_emoji,
    action_emoji,
    render_table,
)
from .portfolio_view import PortfolioView
from .help_view import HelpView, HelpSelect
from .pagination import PaginatedView
from .logo_helper import (
    get_logo_url,
    get_logo_image,
    prefetch_logos,
    clear_logo_cache,
    get_cache_stats,
)

__all__ = [
    # Embed Factory
    "EmbedFactory",
    "EmbedCategory",
    "build_embed",
    "format_money",
    "format_pnl",
    "format_percent",
    "format_percent_colored",
    "status_emoji",
    "action_emoji",
    "render_table",
    # Views
    "PortfolioView",
    "HelpView",
    "HelpSelect",
    "PaginatedView",
    # Logo Helper
    "get_logo_url",
    "get_logo_image",
    "prefetch_logos",
    "clear_logo_cache",
    "get_cache_stats",
]
