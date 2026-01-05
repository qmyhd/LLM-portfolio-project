import React from 'react';
import { HedgeResult } from '../lib/arbEngine';

interface Props {
  result: HedgeResult | null;
}

export const ResultsPanel: React.FC<Props> = ({ result }) => {
  if (!result) {
    return (
      <div className="panel results-panel">
        <div style={{
          textAlign: 'center', 
          opacity: 0.5, 
          padding: '60px 20px',
          color: 'var(--text-muted)'
        }}>
          <div style={{fontSize: '2rem', marginBottom: '8px'}}>📊</div>
          <h3 style={{margin: 0, fontWeight: 500}}>Enter odds to see results</h3>
        </div>
      </div>
    );
  }

  const fmtMoney = (n: number) => {
    const sign = n >= 0 ? '' : '-';
    return `${sign}$${Math.abs(n).toFixed(2)}`;
  };

  const profitColor = (n: number) => 
    n >= 0 ? 'var(--accent-success)' : 'var(--accent-danger)';

  // Arb % is now ROI-based: positive = profitable (green)
  const arbColor = (n: number) => 
    n > 0 ? 'var(--accent-success)' : n < 0 ? 'var(--accent-danger)' : 'var(--text-muted)';

  return (
    <div className="panel results-panel">
      {/* Summary Section - At Top */}
      <div className="summary-section">
        <div className="summary-item">
          <label>Guaranteed</label>
          <div className="summary-value" style={{color: profitColor(result.guaranteed_profit)}}>
            {fmtMoney(result.guaranteed_profit)}
          </div>
        </div>
        <div className="summary-item">
          <label>Best Case</label>
          <div className="summary-value" style={{color: profitColor(result.best_profit)}}>
            {fmtMoney(result.best_profit)}
          </div>
        </div>
        <div className="summary-item">
          <label>Total Stake</label>
          <div className="summary-value" style={{color: 'var(--text-primary)'}}>
            {fmtMoney(result.total_stake)}
          </div>
        </div>
        <div className="summary-item">
          <label>Arb %</label>
          <div className="summary-value" style={{color: arbColor(result.arb_pct)}}>
            {result.arb_pct.toFixed(2)}%
          </div>
        </div>
      </div>

      {/* First Bet Wins Section */}
      <div className="outcome-section">
        <h3>First Bet Wins</h3>
        <div className="outcome-grid">
          <div className="outcome-item">
            <label>First Bet Profit</label>
            <div className="outcome-value" style={{color: profitColor(result.profit_bet1_wins)}}>
              {fmtMoney(result.profit_bet1_wins)}
            </div>
          </div>
          <div className="outcome-item">
            <label>Second Bet Loss</label>
            <div className="outcome-value" style={{color: profitColor(result.loss_bet2_if_1_wins)}}>
              {fmtMoney(result.loss_bet2_if_1_wins)}
            </div>
          </div>
          <div className="outcome-item total">
            <label>Total Profit</label>
            <div className="outcome-value" style={{color: profitColor(result.total_if_1_wins)}}>
              {fmtMoney(result.total_if_1_wins)}
            </div>
          </div>
        </div>
      </div>

      {/* Second Bet Wins Section */}
      <div className="outcome-section">
        <h3>Second Bet Wins</h3>
        <div className="outcome-grid">
          <div className="outcome-item">
            <label>First Bet Loss</label>
            <div className="outcome-value" style={{color: profitColor(result.loss_bet1_if_2_wins)}}>
              {fmtMoney(result.loss_bet1_if_2_wins)}
            </div>
          </div>
          <div className="outcome-item">
            <label>Second Bet Profit</label>
            <div className="outcome-value" style={{color: profitColor(result.profit_bet2_wins)}}>
              {fmtMoney(result.profit_bet2_wins)}
            </div>
          </div>
          <div className="outcome-item total">
            <label>Total Profit</label>
            <div className="outcome-value" style={{color: profitColor(result.total_if_2_wins)}}>
              {fmtMoney(result.total_if_2_wins)}
            </div>
          </div>
        </div>
      </div>

      {/* Optimal Hedge Info */}
      <div className="info-section">
        <div className="info-item">
          <span className="info-label">Break-even Stake (Bet 2):</span>
          <span className="info-value">${result.breakeven_stake2.toFixed(2)}</span>
        </div>
        <div className="info-item">
          <span className="info-label">Optimal Stake for Equal Profit:</span>
          <span className="info-value">${result.optimal_stake2.toFixed(2)}</span>
        </div>
      </div>
    </div>
  );
};
