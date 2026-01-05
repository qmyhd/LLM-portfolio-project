import React from 'react';
import { ArbInputs, computeArb } from '../lib/arbEngine';

interface Props {
  inputs: ArbInputs;
  onBiasChange: (bias: number) => void;
}

export const WhatIfPanel: React.FC<Props> = ({ inputs, onBiasChange }) => {
  
  const scenarios = [30, 40, 50, 60, 70];
  
  return (
    <div className="panel whatif-panel">
      <h2>🧪 Sensitivity</h2>
      
      <div className="section">
        <div className="metric-label" style={{marginBottom: 'var(--space-sm)'}}>Quick Adjust</div>
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 'var(--space-xs)', marginBottom: 'var(--space-lg)'}}>
          <button className={`btn ${inputs.biasToBet1 === 50 ? 'btn-primary' : ''}`} onClick={() => onBiasChange(50)}>50/50</button>
          <button className={`btn ${inputs.biasToBet1 === 60 ? 'btn-primary' : ''}`} onClick={() => onBiasChange(60)}>60/40</button>
          <button className={`btn ${inputs.biasToBet1 === 70 ? 'btn-primary' : ''}`} onClick={() => onBiasChange(70)}>70/30</button>
        </div>
        
        <div style={{marginBottom: 'var(--space-lg)'}}>
          <div style={{display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-xs)', alignItems: 'baseline'}}>
            <span className="metric-label">Custom Bias</span>
            <span style={{fontFamily: "'JetBrains Mono', monospace", fontSize: 'var(--font-sm)', color: 'var(--accent-primary)'}}>{inputs.biasToBet1}%</span>
          </div>
          <input 
            type="range" 
            min="0" 
            max="100" 
            value={inputs.biasToBet1} 
            onChange={(e) => onBiasChange(parseInt(e.target.value))}
            style={{width: '100%'}}
          />
        </div>
      </div>

      <div className="section">
        <div className="metric-label" style={{marginBottom: 'var(--space-sm)'}}>ROI Matrix</div>
        <table className="outcome-table" style={{fontSize: 'var(--font-xs)'}}>
          <thead>
            <tr>
              <th>Bias</th>
              <th>ROI 1</th>
              <th>ROI 2</th>
            </tr>
          </thead>
          <tbody>
            {scenarios.map(bias => {
              const res = computeArb({ ...inputs, biasToBet1: bias });
              if (!res) return null;
              const isActive = bias === inputs.biasToBet1;
              return (
                <tr key={bias} style={{background: isActive ? 'rgba(79, 143, 247, 0.08)' : 'transparent'}}>
                  <td style={{color: isActive ? 'var(--accent-primary)' : 'var(--text-secondary)', fontWeight: isActive ? 600 : 400}}>{bias}%</td>
                  <td className={res.roi1 >= 0 ? 'text-green' : 'text-red'}>{res.roi1.toFixed(1)}%</td>
                  <td className={res.roi2 >= 0 ? 'text-green' : 'text-red'}>{res.roi2.toFixed(1)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
