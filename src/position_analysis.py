"""
Enhanced position tracking analysis for chart.py integration.
Provides deeper insights into position management over time.
"""

from datetime import datetime
from typing import Dict, List



def analyze_position_history(symbol: str, start_date: datetime, end_date: datetime) -> Dict:
    """
    Analyze complete position history for a symbol including:
    - Position size evolution over time
    - Cost basis tracking
    - Unrealized vs realized P/L
    - Trade frequency and patterns
    
    Args:
        symbol: Stock ticker symbol
        start_date: Analysis start date
        end_date: Analysis end date
        
    Returns:
        Dictionary containing comprehensive position analysis
    """
    
    # Get trade data using chart.py function
    from src.bot.commands.chart import query_trade_data
    trade_data = query_trade_data(symbol, start_date, end_date)
    if trade_data.empty:
        return {"error": "No trade data found"}
    
    # Get current position from positions table
    get_current_position_size(symbol)
    
    # Calculate position evolution
    position_timeline = []
    cost_basis_timeline = []
    pnl_timeline = []
    
    running_shares = 0
    total_cost = 0
    total_realized_pnl = 0
    
    for _, trade in trade_data.iterrows():
        action = trade['action'].lower()
        shares = float(trade['total_quantity'])
        price = float(trade['execution_price'])
        trade_value = shares * price
        
        if action == 'buy':
            running_shares += shares
            total_cost += trade_value
            avg_cost_basis = total_cost / running_shares if running_shares > 0 else 0
            
        elif action == 'sell':
            # Calculate realized P/L (simplified - could use FIFO for precision)
            if running_shares > 0:
                avg_cost_basis = total_cost / running_shares
                realized_pnl = (price - avg_cost_basis) * shares
                total_realized_pnl += realized_pnl
                
                # Update position
                running_shares -= shares
                if running_shares > 0:
                    # Proportionally reduce cost basis
                    total_cost = total_cost * (running_shares / (running_shares + shares))
                else:
                    total_cost = 0
        
        # Record timeline point
        position_timeline.append({
            'date': trade['execution_date'],
            'position_size': running_shares,
            'action': action,
            'trade_price': price,
            'trade_shares': shares
        })
        
        cost_basis_timeline.append({
            'date': trade['execution_date'],
            'avg_cost_basis': total_cost / running_shares if running_shares > 0 else 0,
            'total_cost': total_cost
        })
        
        pnl_timeline.append({
            'date': trade['execution_date'],
            'realized_pnl': total_realized_pnl,
            'trade_pnl': realized_pnl if action == 'sell' else 0
        })
    
    # Calculate current unrealized P/L if position exists
    current_price = get_current_price(symbol)
    current_cost_basis = total_cost / running_shares if running_shares > 0 else 0
    unrealized_pnl = (current_price - current_cost_basis) * running_shares if running_shares > 0 else 0
    
    # Trading pattern analysis
    buy_trades = trade_data[trade_data['action'].str.lower() == 'buy']
    sell_trades = trade_data[trade_data['action'].str.lower() == 'sell']
    
    analysis = {
        'symbol': symbol,
        'analysis_period': {
            'start': start_date.isoformat(),
            'end': end_date.isoformat()
        },
        'position_summary': {
            'current_shares': running_shares,
            'current_cost_basis': current_cost_basis,
            'current_market_value': running_shares * current_price,
            'total_invested': sum(buy_trades['execution_price'] * buy_trades['total_quantity']),
            'total_divested': sum(sell_trades['execution_price'] * sell_trades['total_quantity']),
            'realized_pnl': total_realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'total_pnl': total_realized_pnl + unrealized_pnl
        },
        'trading_activity': {
            'total_trades': len(trade_data),
            'buy_trades': len(buy_trades),
            'sell_trades': len(sell_trades),
            'avg_buy_price': buy_trades['execution_price'].mean() if not buy_trades.empty else 0,
            'avg_sell_price': sell_trades['execution_price'].mean() if not sell_trades.empty else 0,
            'largest_buy': buy_trades['total_quantity'].max() if not buy_trades.empty else 0,
            'largest_sell': sell_trades['total_quantity'].max() if not sell_trades.empty else 0
        },
        'timeline_data': {
            'position_evolution': position_timeline,
            'cost_basis_evolution': cost_basis_timeline,
            'pnl_evolution': pnl_timeline
        }
    }
    
    return analysis


def get_current_position_size(symbol: str) -> float:
    """Get current position size for a symbol from positions table."""
    try:
        from src.database import execute_sql
        
        result = execute_sql("""
            SELECT quantity FROM positions 
            WHERE symbol = ? AND sync_timestamp = (SELECT MAX(sync_timestamp) FROM positions WHERE symbol = ?)
        """, (symbol, symbol), fetch_results=True)
        
        if result:
            try:
                return float(result[0][0])  # type: ignore
            except (IndexError, TypeError):
                return 0.0
        return 0.0
    except Exception as e:
        print(f"Error getting current position: {e}")
        return 0.0


def get_current_price(symbol: str) -> float:
    """Get current price for a symbol from realtime_prices table."""
    try:
        from src.database import execute_sql
        
        result = execute_sql("""
            SELECT price FROM realtime_prices 
            WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1
        """, (symbol,), fetch_results=True)
        
        if result:
            try:
                return float(result[0][0])  # type: ignore
            except (IndexError, TypeError):
                return 0.0
        return 0.0
    except Exception as e:
        print(f"Error getting current price: {e}")
        return 0.0


def create_enhanced_chart_annotations(position_analysis: Dict) -> List[Dict]:
    """
    Create enhanced annotations for charts based on position analysis.
    
    Args:
        position_analysis: Output from analyze_position_history
        
    Returns:
        List of annotation objects for chart overlay
    """
    annotations = []
    
    # Add position size annotations at key points
    timeline = position_analysis.get('timeline_data', {}).get('position_evolution', [])
    
    for i, point in enumerate(timeline):
        # Add annotation for significant position changes
        if i == 0 or abs(point['position_size'] - timeline[i-1]['position_size']) > 50:  # Threshold for "significant"
            annotations.append({
                'date': point['date'],
                'text': f"Position: {point['position_size']:.0f} shares",
                'type': 'position_size',
                'value': point['position_size']
            })
    
    # Add cost basis annotations
    cost_timeline = position_analysis.get('timeline_data', {}).get('cost_basis_evolution', [])
    if cost_timeline:
        final_cost_basis = cost_timeline[-1]['avg_cost_basis']
        if final_cost_basis > 0:
            annotations.append({
                'date': cost_timeline[-1]['date'],
                'text': f"Avg Cost: ${final_cost_basis:.2f}",
                'type': 'cost_basis',
                'value': final_cost_basis
            })
    
    # Add P/L milestones
    summary = position_analysis.get('position_summary', {})
    if summary.get('total_pnl', 0) != 0:
        annotations.append({
            'date': timeline[-1]['date'] if timeline else None,
            'text': f"Total P/L: ${summary['total_pnl']:.2f}",
            'type': 'total_pnl',
            'value': summary['total_pnl']
        })
    
    return annotations


def generate_position_report(symbol: str, start_date: datetime, end_date: datetime) -> str:
    """
    Generate a comprehensive text report of position management.
    
    Args:
        symbol: Stock ticker symbol
        start_date: Analysis start date
        end_date: Analysis end date
        
    Returns:
        Formatted text report
    """
    analysis = analyze_position_history(symbol, start_date, end_date)
    
    if 'error' in analysis:
        return f"❌ {analysis['error']}"
    
    summary = analysis['position_summary']
    activity = analysis['trading_activity']
    
    report = f"""
📊 **Position Analysis Report: ${symbol}**

**Position Summary:**
• Current Shares: {summary['current_shares']:.0f}
• Avg Cost Basis: ${summary['current_cost_basis']:.2f}
• Market Value: ${summary['current_market_value']:.2f}
• Total Invested: ${summary['total_invested']:.2f}
• Realized P/L: ${summary['realized_pnl']:.2f}
• Unrealized P/L: ${summary['unrealized_pnl']:.2f}
• **Total P/L: ${summary['total_pnl']:.2f}**

**Trading Activity:**
• Total Trades: {activity['total_trades']}
• Buy Trades: {activity['buy_trades']} (Avg: ${activity['avg_buy_price']:.2f})
• Sell Trades: {activity['sell_trades']} (Avg: ${activity['avg_sell_price']:.2f})
• Largest Buy: {activity['largest_buy']:.0f} shares
• Largest Sell: {activity['largest_sell']:.0f} shares

**Performance Metrics:**
• Win Rate: {(summary['realized_pnl'] > 0) * 100:.0f}% (realized)
• ROI: {(summary['total_pnl'] / summary['total_invested'] * 100) if summary['total_invested'] > 0 else 0:.1f}%
"""
    
    return report.strip()
