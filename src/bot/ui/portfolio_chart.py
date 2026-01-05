"""
Portfolio Pie Chart Generator

Generates a pie chart visualization of portfolio holdings for Discord display.
Uses Discord dark theme colors for consistent styling.
"""

import io
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

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


def generate_portfolio_pie_chart(
    positions: List[Dict],
    top_n: int = 17,
    title: str = "Portfolio Top Holdings by Value",
    save_path: Optional[Path] = None,
    return_buffer: bool = True,
) -> Tuple[Optional[io.BytesIO], str]:
    """
    Generate a pie chart of top portfolio holdings by value.

    Args:
        positions: List of position dicts with 'symbol' and 'equity' keys
        top_n: Number of top positions to show (default 17)
        title: Chart title
        save_path: Optional path to save PNG file
        return_buffer: If True, return BytesIO buffer for Discord upload

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

    # Calculate percentages for display
    percentages = [v / total_value * 100 for v in values]

    # Create figure with Discord dark theme
    fig, (ax_pie, ax_legend) = plt.subplots(
        1, 2, figsize=(14, 8), gridspec_kw={"width_ratios": [2, 1]}, facecolor=FIG_BG
    )
    ax_pie.set_facecolor(PANEL_BG)
    ax_legend.set_facecolor(PANEL_BG)

    # Custom autopct function that only shows % for large slices
    def make_autopct(values):
        def autopct(pct):
            if pct >= 3:  # Only show percentage if >= 3%
                return f"{pct:.1f}%"
            return ""

        return autopct

    # Create pie chart
    wedges, texts, autotexts = ax_pie.pie(
        values,
        labels=None,  # We'll add custom legend instead
        autopct=make_autopct(values),
        colors=colors,
        startangle=90,
        pctdistance=0.75,
        wedgeprops=dict(width=0.6, edgecolor=FIG_BG, linewidth=2),  # Donut style
        textprops=dict(color=TXT, fontsize=10, fontweight="bold"),
    )

    # Style the percentage labels
    for autotext in autotexts:
        autotext.set_color(TXT)
        autotext.set_fontweight("bold")
        autotext.set_fontsize(9)

    # Add title to pie chart
    ax_pie.set_title(title, color=TXT, fontsize=14, fontweight="bold", pad=20)

    # Add total value in center of donut
    ax_pie.text(
        0,
        0,
        f"Total\n${total_value:,.0f}",
        ha="center",
        va="center",
        fontsize=14,
        fontweight="bold",
        color=TXT,
    )

    # Create legend with values in the right panel
    legend_entries = []
    for i, (label, value, pct) in enumerate(zip(labels, values, percentages)):
        legend_entries.append(f"{label}: ${value:,.0f} ({pct:.1f}%)")

    # Create legend patches
    legend_patches = [
        mpatches.Patch(color=colors[i], label=legend_entries[i])
        for i in range(len(legend_entries))
    ]

    # Add legend to right panel
    ax_legend.axis("off")
    ax_legend.legend(
        handles=legend_patches,
        loc="center left",
        fontsize=9,
        frameon=False,
        labelcolor=TXT,
        title="Holdings",
        title_fontsize=11,
    )

    # Make legend title white
    legend = ax_legend.get_legend()
    if legend:
        legend.get_title().set_color(TXT)

    plt.tight_layout()

    # Generate filename
    timestamp = plt.datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
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
