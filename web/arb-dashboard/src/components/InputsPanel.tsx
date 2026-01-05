import React, { useState, useEffect, useCallback } from 'react';
import { HedgeInputs, convertRhOdds, americanToDecimal, applyBoostToDecimal } from '../lib/arbEngine';

interface Props {
  inputs: HedgeInputs;
  onChange: (newInputs: HedgeInputs) => void;
}

/**
 * Compute the displayed stake2 value based on current inputs.
 * This mirrors the arbEngine logic for optimal_stake2.
 */
function computeDisplayedStake2(inputs: HedgeInputs): string {
  const { odds1, odds2, stake1, hedgePercent, isBoosted1, boostPct1, isBoosted2, boostPct2 } = inputs;
  
  if (!stake1 || stake1 <= 0) return '$0.00';
  
  // Convert to decimal
  const dec1Raw = americanToDecimal(odds1);
  const dec2Raw = americanToDecimal(odds2);
  if (dec1Raw === null || dec2Raw === null) return '$0.00';
  
  // Apply boosts
  let dec1 = dec1Raw;
  let dec2 = dec2Raw;
  if (isBoosted1 && boostPct1 > 0) {
    dec1 = applyBoostToDecimal(dec1Raw, boostPct1);
  }
  if (isBoosted2 && boostPct2 > 0) {
    dec2 = applyBoostToDecimal(dec2Raw, boostPct2);
  }
  
  // Optimal stake2 for equal profit
  const optimal_stake2 = stake1 * dec1 / dec2;
  
  // Apply hedge percent (100% = optimal)
  const stake2 = (hedgePercent / 100) * optimal_stake2;
  
  return `$${stake2.toFixed(2)}`;
}

/**
 * Compute the ROI-based arb percentage (positive = profitable).
 * arb_pct = guaranteed_profit / total_stake * 100
 */
function computeArbPct(inputs: HedgeInputs): string {
  const { odds1, odds2, stake1, hedgePercent, isBoosted1, boostPct1, isBoosted2, boostPct2 } = inputs;
  
  if (!stake1 || stake1 <= 0 || !odds1 || !odds2) return '0.0';
  
  // Convert to decimal
  const dec1Raw = americanToDecimal(odds1);
  const dec2Raw = americanToDecimal(odds2);
  if (dec1Raw === null || dec2Raw === null) return '0.0';
  
  // Apply boosts
  let dec1 = dec1Raw;
  let dec2 = dec2Raw;
  if (isBoosted1 && boostPct1 > 0) {
    dec1 = applyBoostToDecimal(dec1Raw, boostPct1);
  }
  if (isBoosted2 && boostPct2 > 0) {
    dec2 = applyBoostToDecimal(dec2Raw, boostPct2);
  }
  
  // Optimal stake2 for equal profit
  const optimal_stake2 = stake1 * dec1 / dec2;
  const stake2 = (hedgePercent / 100) * optimal_stake2;
  
  // P&L calculations
  const profit1_alone = stake1 * (dec1 - 1);
  const profit2_alone = stake2 * (dec2 - 1);
  const net_if_1_wins = profit1_alone - stake2;
  const net_if_2_wins = profit2_alone - stake1;
  
  const guaranteed = Math.min(net_if_1_wins, net_if_2_wins);
  const totalStake = stake1 + stake2;
  
  const arbPct = totalStake > 0 ? (guaranteed / totalStake) * 100 : 0;
  return arbPct.toFixed(1);
}

export const InputsPanel: React.FC<Props> = ({ inputs, onChange }) => {
  const handleChange = (field: keyof HedgeInputs, value: any) => {
    onChange({ ...inputs, [field]: value });
  };

  const validateNumeric = (value: string, allowDecimal: boolean = false): number | null => {
    if (value === '' || value === '-') return 0;
    const pattern = allowDecimal ? /^-?\d*\.?\d*$/ : /^-?\d+$/;
    if (!pattern.test(value)) return null;
    const num = allowDecimal ? parseFloat(value) : parseInt(value);
    return isNaN(num) ? null : num;
  };

  // Event Contract Converter State
  const [ecPrice, setEcPrice] = useState<string>("0.41");
  const [ecFee, setEcFee] = useState<string>("0.01");
  const [computedOdds, setComputedOdds] = useState<{ american: number; decimal: number } | null>(null);
  const [showConverter, setShowConverter] = useState(false);

  const computeOdds = useCallback(() => {
    const p = parseFloat(ecPrice);
    const f = parseFloat(ecFee);
    if (!isNaN(p) && !isNaN(f) && p > 0 && p <= 1) {
      const res = convertRhOdds(p, f);
      setComputedOdds(res);
    } else {
      setComputedOdds(null);
    }
  }, [ecPrice, ecFee]);

  useEffect(() => {
    computeOdds();
  }, [computeOdds]);

  return (
    <div className="panel inputs-panel">
      <h2>Betting Odds</h2>
      
      {/* First Bet Row */}
      <div className="odds-row">
        <div className="odds-field">
          <label>First Bet Odds</label>
          <input 
            type="text" 
            inputMode="numeric"
            value={inputs.odds1} 
            onChange={(e) => {
              const val = validateNumeric(e.target.value, false);
              if (val !== null) handleChange('odds1', val);
            }} 
          />
        </div>
        <div className="odds-field">
          <label>First Bet Stake</label>
          <input 
            type="text"
            inputMode="decimal"
            value={inputs.stake1} 
            onChange={(e) => {
              const val = validateNumeric(e.target.value, true);
              if (val !== null) handleChange('stake1', val);
            }} 
          />
        </div>
        <div className="odds-field">
          <label>Stake Rounding</label>
          <input 
            type="text"
            inputMode="decimal"
            placeholder=""
            value={inputs.roundTo1 || ''} 
            onChange={(e) => {
              if (e.target.value === '') {
                handleChange('roundTo1', undefined);
              } else {
                const val = validateNumeric(e.target.value, true);
                if (val !== null) handleChange('roundTo1', val);
              }
            }} 
          />
        </div>
        <div className="odds-field arb-display">
          <label>Arb %</label>
          <div className="arb-value">{computeArbPct(inputs)}</div>
        </div>
      </div>

      {/* Second Bet Row */}
      <div className="odds-row">
        <div className="odds-field">
          <label>Second Bet Odds</label>
          <input 
            type="text"
            inputMode="numeric"
            value={inputs.odds2} 
            onChange={(e) => {
              const val = validateNumeric(e.target.value, false);
              if (val !== null) handleChange('odds2', val);
            }} 
          />
        </div>
        <div className="odds-field">
          <label>Second Bet Stake</label>
          <div className="calculated-value">
            {computeDisplayedStake2(inputs)}
          </div>
        </div>
        <div className="odds-field">
          <label>Stake Rounding</label>
          <input 
            type="text"
            inputMode="decimal"
            placeholder=""
            value={inputs.roundTo2 || ''} 
            onChange={(e) => {
              if (e.target.value === '') {
                handleChange('roundTo2', undefined);
              } else {
                const val = validateNumeric(e.target.value, true);
                if (val !== null) handleChange('roundTo2', val);
              }
            }} 
          />
        </div>
      </div>

      {/* Boost Options */}
      <div className="boost-row">
        <label style={{display: 'flex', alignItems: 'center', gap: '8px'}}>
          <input 
            type="checkbox" 
            checked={inputs.isBoosted1} 
            onChange={(e) => handleChange('isBoosted1', e.target.checked)} 
          /> 
          Bet 1 Boost %
        </label>
        <input 
          type="text"
          inputMode="decimal"
          value={inputs.boostPct1} 
          disabled={!inputs.isBoosted1}
          style={{opacity: inputs.isBoosted1 ? 1 : 0.5, width: '60px'}}
          onChange={(e) => {
            const val = validateNumeric(e.target.value, true);
            if (val !== null) handleChange('boostPct1', val);
          }} 
        />
        <label style={{display: 'flex', alignItems: 'center', gap: '8px', marginLeft: '20px'}}>
          <input 
            type="checkbox" 
            checked={inputs.isBoosted2} 
            onChange={(e) => handleChange('isBoosted2', e.target.checked)} 
          /> 
          Bet 2 Boost %
        </label>
        <input 
          type="text"
          inputMode="decimal"
          value={inputs.boostPct2} 
          disabled={!inputs.isBoosted2}
          style={{opacity: inputs.isBoosted2 ? 1 : 0.5, width: '60px'}}
          onChange={(e) => {
            const val = validateNumeric(e.target.value, true);
            if (val !== null) handleChange('boostPct2', val);
          }} 
        />
      </div>

      {/* Hedge Slider */}
      <div className="hedge-section">
        <div className="hedge-header">
          <span>Hedge Level</span>
          <span className="hedge-value">{inputs.hedgePercent}%</span>
        </div>
        <div className="hedge-slider-container">
          <span className="slider-label">No Hedge</span>
          <input 
            type="range" 
            min="0" 
            max="200" 
            value={inputs.hedgePercent} 
            onChange={(e) => handleChange('hedgePercent', parseInt(e.target.value))}
          />
          <span className="slider-label">Over-hedge</span>
        </div>
        <div className="hedge-presets">
          <button className={`btn ${inputs.hedgePercent === 0 ? 'btn-primary' : ''}`} onClick={() => handleChange('hedgePercent', 0)}>0%</button>
          <button className={`btn ${inputs.hedgePercent === 50 ? 'btn-primary' : ''}`} onClick={() => handleChange('hedgePercent', 50)}>50%</button>
          <button className={`btn ${inputs.hedgePercent === 100 ? 'btn-primary' : ''}`} onClick={() => handleChange('hedgePercent', 100)}>100%</button>
          <button className={`btn ${inputs.hedgePercent === 150 ? 'btn-primary' : ''}`} onClick={() => handleChange('hedgePercent', 150)}>150%</button>
        </div>
      </div>

      {/* Event Contract Converter (Collapsible) */}
      <div className="converter-section">
        <button className="converter-toggle" onClick={() => setShowConverter(!showConverter)}>
          {showConverter ? '▼' : '▶'} Event Contract Converter
        </button>
        {showConverter && (
          <div className="converter-content">
            <div className="control-row">
              <label>Contract Price</label>
              <input 
                type="text"
                inputMode="decimal"
                value={ecPrice} 
                onChange={(e) => {
                  if (/^\d*\.?\d*$/.test(e.target.value)) setEcPrice(e.target.value);
                }}
                placeholder="0.41"
                style={{width: '80px'}}
              />
            </div>
            <div className="control-row">
              <label>Fee</label>
              <input 
                type="text"
                inputMode="decimal"
                value={ecFee} 
                onChange={(e) => {
                  if (/^\d*\.?\d*$/.test(e.target.value)) setEcFee(e.target.value);
                }}
                placeholder="0.01"
                style={{width: '80px'}}
              />
            </div>
            {computedOdds && (
              <div className="odds-result">
                <span className="odds-value">{computedOdds.american >= 0 ? '+' : ''}{computedOdds.american}</span>
                <span className="odds-decimal">Decimal: {computedOdds.decimal.toFixed(3)}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
