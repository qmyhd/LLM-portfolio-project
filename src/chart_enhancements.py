"""
Enhanced chart.py integration for position tracking visualization.
Adds cost basis lines, position evolution, and enhanced analytics to existing charts.
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Optional

import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
import yfinance as yf

from src.bot.commands.chart import FIFOPositionTracker, query_trade_data

# Set up paths
BASE_DIR = Path(__file__).resolve().parent.parent  # Project root
CHARTS_DIR = BASE_DIR / "charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

# Add these functions to integrate with existing chart.py

def create_enhanced_chart_with_position_analysis(symbol: str, period: str = "6mo", 
                                              chart_type: str = "candle", 
                                              theme: str = "robinhood_black") -> Tuple[Optional[str], str]:
    """
    Enhanced version of create_chart that includes position analysis overlay.
    
    Args:
        symbol: Stock ticker symbol
        period: Time period for chart data
        chart_type: Type of chart (candle, ohlc, line)
        theme: Chart theme (robinhood_black, claude_style, discord_dark)
        
    Returns:
        Tuple of (chart_path, analysis_report) where chart_path can be None on error
    """
    from src.position_analysis import (
        analyze_position_history,
        create_enhanced_chart_annotations,
    )
    
    # Get basic chart data
    data = yf.download(symbol, period=period, interval="1d")
    if data is None or data.empty:
        return None, "❌ Unable to fetch stock data"
    
    # Calculate date range for position analysis
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)  # 6 months of trade analysis
    
    # Get position analysis
    position_analysis = analyze_position_history(symbol, start_date, end_date)
    
    # Create enhanced annotations
    create_enhanced_chart_annotations(position_analysis)
    
    # Get existing trade data and process with FIFO
    trade_data = query_trade_data(symbol, start_date, end_date)
    
    if not trade_data.empty:
        # Process trades with FIFO for accurate P/L
        fifo_tracker = FIFOPositionTracker()
        buy_markers = []
        sell_markers = []
        
        # Add cost basis evolution line data
        cost_basis_data = []
        
        for _, trade in trade_data.iterrows():
            trade_date = pd.to_datetime(trade['execution_date']).date()
            action = trade['action'].lower()
            shares = float(trade['total_quantity'])
            price = float(trade['execution_price'])
            
            if action == 'buy':
                fifo_tracker.add_buy(shares, price, trade_date)
                buy_markers.append({
                    'date': trade_date,
                    'price': price,
                    'shares': shares,
                    'value': shares * price
                })
                
                # Calculate current cost basis after this buy
                total_shares = sum([buy[0] for buy in fifo_tracker.buy_queue])
                total_cost = sum([buy[0] * buy[1] for buy in fifo_tracker.buy_queue])
                avg_cost_basis = total_cost / total_shares if total_shares > 0 else 0
                
                cost_basis_data.append({
                    'date': trade_date,
                    'cost_basis': avg_cost_basis,
                    'position_size': total_shares
                })
                
            elif action == 'sell':
                realized_pnl = fifo_tracker.process_sell(shares, price, trade_date)
                sell_markers.append({
                    'date': trade_date,
                    'price': price,
                    'shares': shares,
                    'value': shares * price,
                    'pnl': realized_pnl
                })
                
                # Update cost basis after sell
                total_shares = sum([buy[0] for buy in fifo_tracker.buy_queue])
                if total_shares > 0:
                    total_cost = sum([buy[0] * buy[1] for buy in fifo_tracker.buy_queue])
                    avg_cost_basis = total_cost / total_shares
                    cost_basis_data.append({
                        'date': trade_date,
                        'cost_basis': avg_cost_basis,
                        'position_size': total_shares
                    })
    
    # Create the chart with enhanced features
    chart_path = create_enhanced_visual_chart(data, symbol, buy_markers, sell_markers, 
                                            cost_basis_data, theme, chart_type)
    
    # Generate comprehensive analysis report
    if 'error' not in position_analysis:
        from src.position_analysis import generate_position_report
        analysis_report = generate_position_report(symbol, start_date, end_date)
        
        # Add chart-specific insights
        analysis_report += "\n\n📈 **Chart Analysis:**\n"
        analysis_report += f"• Chart Period: {period} ({chart_type} style)\n"
        analysis_report += f"• Trade Markers: {len(buy_markers)} buys, {len(sell_markers)} sells\n"
        
        if cost_basis_data and not data.empty:
            final_cost_basis = cost_basis_data[-1]['cost_basis']
            current_price = float(data['Close'].iloc[-1])  # Ensure numeric type
            cost_basis_vs_current = ((current_price - final_cost_basis) / final_cost_basis) * 100
            analysis_report += f"• Cost Basis vs Current: ${final_cost_basis:.2f} vs ${current_price:.2f} ({cost_basis_vs_current:+.1f}%)\n"
    else:
        analysis_report = position_analysis['error']
    
    return chart_path, analysis_report


def create_enhanced_visual_chart(data: pd.DataFrame, symbol: str, buy_markers: List, 
                               sell_markers: List, cost_basis_data: List, 
                               theme: str, chart_type: str) -> str:
    """
    Create visually enhanced chart with cost basis line and position indicators.
    
    Args:
        data: Price data from yfinance
        symbol: Stock ticker
        buy_markers: List of buy trade markers
        sell_markers: List of sell trade markers 
        cost_basis_data: List of cost basis evolution points
        theme: Chart theme
        chart_type: Chart type
        
    Returns:
        Path to saved chart file
    """
    
    # Set up theme-specific styling
    if theme == "robinhood_black":
        style = mpf.make_mpf_style(
            base_mpf_style='nightclouds',
            gridstyle='-',
            gridcolor='#2d2d2d',
            facecolor='#000000',
            edgecolor='#2d2d2d'
        )
        bg_color = '#000000'
        cost_basis_color = '#ff6b6b'  # Soft red for cost basis line
        
    elif theme == "claude_style":
        style = mpf.make_mpf_style(
            base_mpf_style='charles',
            gridstyle=':',
            gridcolor='#e0e0e0'
        )
        bg_color = '#ffffff'
        cost_basis_color = '#e17055'
        
    else:  # discord_dark
        style = mpf.make_mpf_style(
            base_mpf_style='nightclouds',
            gridstyle='-',
            gridcolor='#4f545c',
            facecolor='#36393f',
            edgecolor='#72767d'
        )
        bg_color = '#36393f'
        cost_basis_color = '#f04747'
    
    # Prepare markers for mplfinance
    buy_points = []
    sell_points = []
    
    # Convert markers to mplfinance format
    data_index = data.index
    
    for buy in buy_markers:
        marker_date = pd.to_datetime(buy['date'])
        if marker_date in data_index:
            # Position buy marker slightly below the low
            low_price = data.loc[marker_date, 'Low']
            marker_price = pd.to_numeric(low_price) * 0.995  # 0.5% below low  # type: ignore
            buy_points.append(marker_price)
        else:
            buy_points.append(np.nan)
    
    for sell in sell_markers:
        marker_date = pd.to_datetime(sell['date'])
        if marker_date in data_index:
            # Position sell marker slightly above the high
            high_price = data.loc[marker_date, 'High']
            marker_price = pd.to_numeric(high_price) * 1.005  # 0.5% above high  # type: ignore
            sell_points.append(marker_price)
        else:
            sell_points.append(np.nan)
    
    # Create cost basis line if we have data
    addplot_list = []
    
    if cost_basis_data:
        # Create cost basis DataFrame aligned with price data
        cost_basis_series = pd.Series(index=data.index, dtype=float)
        
        # Forward-fill cost basis values
        current_cost_basis = None
        for cb_point in cost_basis_data:
            cb_date = pd.to_datetime(cb_point['date'])
            if cb_date in data.index:
                current_cost_basis = cb_point['cost_basis']
            
            # Fill from this date forward until next update
            if current_cost_basis is not None:
                mask = data.index >= cb_date
                cost_basis_series[mask] = current_cost_basis
        
        # Add cost basis line to chart
        addplot_list.append(
            mpf.make_addplot(cost_basis_series, 
                           color=cost_basis_color, 
                           width=2, 
                           linestyle='--',
                           alpha=0.8)
        )
    
    # Add buy/sell markers if they exist
    if buy_points:
        buy_series = pd.Series(buy_points, index=data.index[:len(buy_points)])
        addplot_list.append(
            mpf.make_addplot(buy_series, 
                           type='scatter', 
                           markersize=100, 
                           marker='^',
                           color='#00ff00',
                           alpha=0.8)
        )
    
    if sell_points:
        sell_series = pd.Series(sell_points, index=data.index[:len(sell_points)])
        addplot_list.append(
            mpf.make_addplot(sell_series,
                           type='scatter',
                           markersize=100,
                           marker='v',
                           color='#ff4444',
                           alpha=0.8)
        )
    
    # Enhanced title with position info
    if cost_basis_data:
        final_position = cost_basis_data[-1]['position_size']
        final_cost_basis = cost_basis_data[-1]['cost_basis']
        current_price = data['Close'].iloc[-1]
        unrealized_pnl = (current_price - final_cost_basis) * final_position
        
        title = f"{symbol} - Position: {final_position:.0f} shares | Cost Basis: ${final_cost_basis:.2f} | Unrealized P/L: ${unrealized_pnl:+.2f}"
    else:
        title = f"{symbol} - Enhanced Position Tracking"
    
    # Create the chart
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{symbol}_{theme}_{chart_type}_enhanced_{timestamp}.png"
    chart_path = CHARTS_DIR / filename
    
    # Configure chart type
    plot_type = chart_type if chart_type in ['candle', 'ohlc', 'line'] else 'candle'
    
    # Generate the chart
    fig, axes = mpf.plot(
        data,
        type=plot_type,
        style=style,
        title=title,
        addplot=addplot_list if addplot_list else None,
        volume=True,
        savefig=dict(fname=str(chart_path), facecolor=bg_color, dpi=300),
        returnfig=True,
        figsize=(12, 8)
    )
    
    # Add custom legend for cost basis line
    if cost_basis_data:
        axes[0].text(0.02, 0.98, 'Cost Basis Line', 
                    transform=axes[0].transAxes,
                    fontsize=10, 
                    color=cost_basis_color,
                    ha='left', va='top',
                    bbox=dict(boxstyle='round,pad=0.3', 
                             facecolor=bg_color, 
                             edgecolor=cost_basis_color,
                             alpha=0.8))
    
    plt.close(fig)  # Free memory
    
    return str(chart_path)


def add_position_size_indicator(symbol: str) -> Optional[str]:
    """
    Create a position size evolution chart for a given symbol.
    
    Args:
        symbol: Stock ticker symbol
        
    Returns:
        Path to position size chart or None if error
    """
    from src.position_analysis import analyze_position_history
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)  # 1 year
    
    analysis = analyze_position_history(symbol, start_date, end_date)
    
    if 'error' in analysis:
        return None
    
    timeline = analysis.get('timeline_data', {}).get('position_evolution', [])
    
    if not timeline:
        return None
    
    # Create position size chart
    dates = [pd.to_datetime(point['date']) for point in timeline]
    position_sizes = [point['position_size'] for point in timeline]
    
    plt.figure(figsize=(10, 6))
    plt.plot(dates, position_sizes, marker='o', linewidth=2, markersize=6)
    plt.fill_between(dates, position_sizes, alpha=0.3)
    plt.title(f'{symbol} Position Size Evolution')
    plt.xlabel('Date')
    plt.ylabel('Shares Held')
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # Save chart
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{symbol}_position_evolution_{timestamp}.png"
    chart_path = CHARTS_DIR / filename
    plt.savefig(chart_path, dpi=300, facecolor='white')
    plt.close()
    
    return str(chart_path)
