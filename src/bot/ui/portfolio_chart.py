"""
Portfolio Pie Chart Generator

Generates a pie chart visualization of portfolio holdings for Discord display.
Uses Discord dark theme colors for consistent styling.

Features:
- Top 10 positions with company logos and tickers inside slices
- "Others" aggregation for remaining positions
- Logo + ticker placement inside each slice using patheffects for readability
- Discord-friendly dark theme styling
"""

import io
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.patheffects as path_effects
from matplotlib.offsetbox import OffsetImage, AnnotationBbox

logger = logging.getLogger(__name__)

# ── Discord Dark Style Constants ──────────────────────────────────────────
FIG_BG = "#1e1f22"  # outer window – Discord dark grey‑black
PANEL_BG = "#202225"  # chart panel (slightly lighter)
TXT = "#e0e0e0"  # off‑white labels
TXT_DARK = "#b5bac1"  # muted text for secondary info

# Color palette for pie slices (Discord-friendly, high contrast)
PIE_COLORS = [
    "#5865F2",  # Discord blurple
    "#3ba55d",  # Discord green
    "#faa61a",  # Discord gold
    "#ed4245",  # Discord red
    "#9b59b6",  # Purple
    "#e91e63",  # Pink
    "#00bcd4",  # Cyan
    "#ff9800",  # Orange
    "#8bc34a",  # Light green
    "#607d8b",  # Blue grey
    "#795548",  # Brown
    "#673ab7",  # Deep purple
    "#03a9f4",  # Light blue
    "#ff5722",  # Deep orange
    "#009688",  # Teal
    "#cddc39",  # Lime
    "#9e9e9e",  # Grey
    "#4caf50",  # Green (for Others)
]


def _fetch_logo_images(
    symbols: List[str], size: Tuple[int, int] = (32, 32)
) -> Dict[str, any]:
    """
    Fetch logo images for symbols using PIL.

    Uses the centralized logo_helper with TTL caching and multi-provider fallback.

    Args:
        symbols: List of ticker symbols
        size: Image size (width, height)

    Returns:
        Dict mapping symbol to PIL Image (or None if not found)
    """
    try:
        from PIL import Image
        from .logo_helper import get_logo_image, prefetch_logos
    except ImportError:
        logger.debug("PIL not available for logo fetching")
        return {}

    # Prefetch to warm cache
    prefetch_logos(symbols[:10])

    logos = {}
    for symbol in symbols[:10]:  # Limit to top 10
        try:
            buffer = get_logo_image(symbol, size=size)
            if buffer:
                img = Image.open(buffer)
                logos[symbol] = img
            else:
                logos[symbol] = None
        except Exception as e:
            logger.debug(f"Failed to fetch logo for {symbol}: {e}")
            logos[symbol] = None

    found = sum(1 for v in logos.values() if v is not None)
    logger.info(f"Fetched {found}/{len(logos)} logo images")
    return logos


def generate_portfolio_pie_chart(
    positions: List[Dict],
    top_n: int = 10,
    title: str = "Portfolio Top Holdings by Value",
    save_path: Optional[Path] = None,
    return_buffer: bool = True,
    include_logos: bool = True,
) -> Tuple[Optional[io.BytesIO], str]:
    """
    Generate a pie chart of top portfolio holdings by value with in-slice labels.

    Features:
    - Top N positions (default 10) shown as individual slices
    - Remaining positions aggregated into "Others" slice
    - Ticker symbols and logos placed INSIDE each slice
    - Wide slices: logo + ticker side-by-side
    - Narrow slices: ticker only or smaller logo
    - Discord dark theme styling

    Args:
        positions: List of position dicts with 'symbol' and 'equity' keys
        top_n: Number of top positions to show (default 10)
        title: Chart title
        save_path: Optional path to save PNG file
        return_buffer: If True, return BytesIO buffer for Discord upload
        include_logos: If True, fetch and display company logos inside slices

    Returns:
        Tuple of (BytesIO buffer or None, chart_filename)
    """
    if not positions:
        return None, ""

    # Sort by equity value (descending) and take top N
    sorted_positions = sorted(positions, key=lambda x: x.get("equity", 0), reverse=True)

    # Separate top N and Others
    top_positions = sorted_positions[:top_n]
    other_positions = sorted_positions[top_n:]

    # Calculate total portfolio value
    total_value = sum(p.get("equity", 0) for p in positions)
    if total_value <= 0:
        return None, ""

    # Prepare data for pie chart
    labels = []
    values = []
    colors = []

    for i, pos in enumerate(top_positions):
        symbol = pos.get("symbol", "N/A")
        equity = pos.get("equity", 0)
        if equity > 0:
            labels.append(symbol)
            values.append(equity)
            colors.append(PIE_COLORS[i % len(PIE_COLORS)])

    # Add "Others" slice if there are more positions
    if other_positions:
        others_total = sum(p.get("equity", 0) for p in other_positions)
        if others_total > 0:
            labels.append(f"Others ({len(other_positions)})")
            values.append(others_total)
            colors.append(PIE_COLORS[-1])  # Use grey for Others

    if not values:
        return None, ""

    # Calculate percentages for display and slice sizing
    percentages = [v / total_value * 100 for v in values]

    # Fetch logos for top positions (if enabled)
    logo_images = {}
    if include_logos:
        top_symbols = [
            pos.get("symbol") for pos in top_positions[:10] if pos.get("symbol")
        ]
        logo_images = _fetch_logo_images(top_symbols, size=(28, 28))

    # Create figure with Discord dark theme - SINGLE subplot (no legend panel)
    fig, ax = plt.subplots(figsize=(10, 10), facecolor=FIG_BG)
    ax.set_facecolor(PANEL_BG)

    # Create pie chart WITHOUT autopct (we'll add custom labels inside slices)
    wedges, _ = ax.pie(
        values,
        labels=None,  # No external labels
        colors=colors,
        startangle=90,
        wedgeprops=dict(width=0.55, edgecolor=FIG_BG, linewidth=2),  # Donut style
    )

    # Add title
    ax.set_title(title, color=TXT, fontsize=16, fontweight="bold", pad=20)

    # Add total value in center of donut
    ax.text(
        0,
        0,
        f"Total\n${total_value:,.0f}",
        ha="center",
        va="center",
        fontsize=16,
        fontweight="bold",
        color=TXT,
    )

    # Text styling with outline for readability on colored backgrounds
    text_outline = [
        path_effects.Stroke(linewidth=3, foreground=FIG_BG),
        path_effects.Normal(),
    ]

    # Add ticker + logo inside each slice
    for i, (wedge, label, pct) in enumerate(zip(wedges, labels, percentages)):
        # Calculate center position of the wedge
        theta_mid = (wedge.theta1 + wedge.theta2) / 2
        theta_rad = math.radians(theta_mid)

        # Position at ~70% of the way from center (inside the donut ring)
        r_text = 0.72

        # Determine layout based on slice size
        is_others = label.startswith("Others")
        symbol = label if not is_others else "Others"

        if pct >= 5:
            # Large slice: logo + ticker side-by-side
            logo_size = 24
            logo_offset = 0.06  # Offset logo slightly toward center
            text_offset = 0.06  # Offset text slightly toward edge
        elif pct >= 3:
            # Medium slice: smaller logo + ticker
            logo_size = 18
            logo_offset = 0.04
            text_offset = 0.04
        else:
            # Small slice: ticker only (no logo)
            logo_size = 0
            logo_offset = 0
            text_offset = 0

        # Calculate positions perpendicular to radius for side-by-side layout
        # Perpendicular direction (90 degrees rotated)
        perp_theta = theta_rad + math.pi / 2

        # Center of the slice
        x_center = r_text * math.cos(theta_rad)
        y_center = r_text * math.sin(theta_rad)

        # Add ticker text
        if pct >= 1.5:  # Only show text for slices >= 1.5%
            # For large slices, offset text from logo; for small, center it
            if logo_size > 0 and not is_others:
                x_text = x_center + text_offset * math.cos(perp_theta)
                y_text = y_center + text_offset * math.sin(perp_theta)
            else:
                x_text = x_center
                y_text = y_center

            # Determine font size based on slice
            fontsize = 10 if pct >= 5 else (9 if pct >= 3 else 8)

            # Add ticker text with percentage
            display_text = f"{symbol}\n{pct:.1f}%" if pct >= 3 else symbol

            ax.text(
                x_text,
                y_text,
                display_text,
                ha="center",
                va="center",
                fontsize=fontsize,
                fontweight="bold",
                color="white",
                path_effects=text_outline,
            )

        # Add logo for non-Others slices with sufficient size
        if logo_size > 0 and not is_others and label in logo_images:
            logo_img = logo_images.get(label)
            if logo_img is not None:
                try:
                    img_array = np.array(logo_img)

                    # Position logo offset from text
                    x_logo = x_center - logo_offset * math.cos(perp_theta)
                    y_logo = y_center - logo_offset * math.sin(perp_theta)

                    # Scale zoom based on logo_size
                    zoom = logo_size / 28.0 * 0.9

                    imagebox = OffsetImage(img_array, zoom=zoom)
                    imagebox.image.axes = ax

                    ab = AnnotationBbox(
                        imagebox,
                        (x_logo, y_logo),
                        xycoords="data",
                        frameon=True,
                        bboxprops=dict(
                            boxstyle="circle,pad=0.08",
                            facecolor="white",
                            edgecolor="white",
                            alpha=0.95,
                        ),
                        pad=0,
                    )
                    ax.add_artist(ab)
                    logger.debug(
                        f"Added logo for {label} at ({x_logo:.2f}, {y_logo:.2f})"
                    )

                except Exception as logo_err:
                    logger.debug(f"Failed to add logo for {label}: {logo_err}")

    plt.tight_layout()

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chart_filename = f"portfolio_pie_{timestamp}.png"

    # Save to file if path provided
    if save_path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(
            save_path,
            facecolor=FIG_BG,
            edgecolor="none",
            dpi=150,
            bbox_inches="tight",
            pad_inches=0.2,
        )

    # Return BytesIO buffer for Discord
    buffer = None
    if return_buffer:
        buffer = io.BytesIO()
        plt.savefig(
            buffer,
            format="png",
            facecolor=FIG_BG,
            edgecolor="none",
            dpi=150,
            bbox_inches="tight",
            pad_inches=0.2,
        )
        buffer.seek(0)

    plt.close(fig)

    return buffer, chart_filename


def generate_portfolio_summary_stats(positions: List[Dict]) -> Dict:
    """
    Generate summary statistics for portfolio.

    Args:
        positions: List of position dicts

    Returns:
        Dict with summary stats
    """
    if not positions:
        return {}

    total_equity = sum(p.get("equity", 0) for p in positions)
    total_pnl = sum(p.get("pnl", 0) for p in positions)
    total_cost = sum(p.get("cost", 0) for p in positions)

    winners = [p for p in positions if p.get("pnl", 0) > 0]
    losers = [p for p in positions if p.get("pnl", 0) < 0]

    # Calculate overall P/L %
    overall_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    return {
        "total_equity": total_equity,
        "total_pnl": total_pnl,
        "total_cost": total_cost,
        "overall_pnl_pct": overall_pnl_pct,
        "num_positions": len(positions),
        "num_winners": len(winners),
        "num_losers": len(losers),
        "winner_pct": len(winners) / len(positions) * 100 if positions else 0,
    }
