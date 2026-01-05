/**
 * Arbitrage Engine v4
 * 
 * Primary use case: Boosted bet hedging
 * - User has a boosted bet with max stake (Bet 1)
 * - User wants to hedge with the opposite side (Bet 2)
 * - Slider controls hedge level (0% = no hedge, 100% = optimal/equal profit, 200% = over-hedge)
 * 
 * Key formulas:
 * - Boosted decimal: dec_boosted = 1 + (dec_raw - 1) * (1 + boostPct/100)
 * - Optimal hedge stake: stake2_optimal = stake1 * dec1 / dec2
 * - Net if Bet1 wins: profit1_alone - stake2 = stake1*(dec1-1) - stake2
 * - Net if Bet2 wins: profit2_alone - stake1 = stake2*(dec2-1) - stake1
 * - Arb %: guaranteed_profit / total_stake * 100 (positive = profitable)
 */

// ============================================================================
// Types
// ============================================================================

export interface HedgeInputs {
  odds1: number;           // Boosted bet odds (American)
  stake1: number;          // Fixed stake on boosted bet (max stake)
  odds2: number;           // Hedge bet odds (American)
  hedgePercent: number;    // 0-200 (0=no hedge, 100=break-even on Bet1 win, 200=over-hedge)
  
  // Optional profit boosts
  isBoosted1: boolean;
  boostPct1: number;
  isBoosted2: boolean;
  boostPct2: number;
  
  // Stake rounding
  roundTo1?: number;
  roundTo2?: number;
}

export interface HedgeResult {
  odds1_american: number;
  odds2_american: number;
  stake1: number;
  stake2: number;
  
  odds1_decimal: number;
  odds2_decimal: number;
  effective_american1: string;
  effective_american2: string;
  
  implied_prob1: number;
  implied_prob2: number;
  
  arb_pct: number;
  has_arb: boolean;
  
  // Scenario: Bet 1 Wins
  profit_bet1_wins: number;
  loss_bet2_if_1_wins: number;
  total_if_1_wins: number;
  
  // Scenario: Bet 2 Wins
  loss_bet1_if_2_wins: number;
  profit_bet2_wins: number;
  total_if_2_wins: number;
  
  guaranteed_profit: number;
  best_profit: number;
  total_stake: number;
  
  optimal_stake2: number;
  breakeven_stake2: number;
}

// ============================================================================
// Odds Conversion
// ============================================================================

export function americanToDecimal(american: number): number | null {
  if (!Number.isFinite(american) || american === 0) return null;
  if (american > -100 && american < 100) return null;
  return american > 0 ? 1 + (american / 100) : 1 + (100 / Math.abs(american));
}

export function decimalToAmerican(decimal: number): number | null {
  if (!Number.isFinite(decimal) || decimal <= 1) return null;
  return decimal >= 2 ? (decimal - 1) * 100 : -100 / (decimal - 1);
}

export function decimalToImpliedProb(decimal: number): number | null {
  if (!Number.isFinite(decimal) || decimal <= 0) return null;
  return 1 / decimal;
}

export function formatAmerican(val: number): string {
  const rounded = Math.round(val);
  return rounded > 0 ? `+${rounded}` : `${rounded}`;
}

function roundToStep(value: number, step: number | undefined): number {
  if (!step || step <= 0) return value;
  return Math.round(value / step) * step;
}

/**
 * Apply profit boost to decimal odds.
 * The boost applies to the PROFIT portion (dec - 1), not the full decimal.
 * Example: +280 (dec=3.80) with 50% boost → 1 + 2.80*1.5 = 5.2 → +420
 */
export function applyBoostToDecimal(decimal: number, boostPct: number): number {
  if (!Number.isFinite(decimal) || decimal <= 1) return decimal;
  if (!Number.isFinite(boostPct) || boostPct <= 0) return decimal;
  return 1 + (decimal - 1) * (1 + boostPct / 100);
}

// ============================================================================
// Main Hedge Calculation
// ============================================================================

export function computeHedge(inputs: HedgeInputs): HedgeResult | null {
  const {
    odds1, odds2, stake1, hedgePercent,
    isBoosted1, boostPct1, isBoosted2, boostPct2,
    roundTo1, roundTo2
  } = inputs;
  
  if (!Number.isFinite(stake1) || stake1 <= 0) return null;
  
  // Clamp hedge percent to valid range
  const clampedHedge = Math.max(0, Math.min(200, hedgePercent || 0));
  
  // Convert American odds to decimal
  const dec1Raw = americanToDecimal(odds1);
  const dec2Raw = americanToDecimal(odds2);
  if (dec1Raw === null || dec2Raw === null) return null;
  
  // Apply boosts if enabled
  let dec1 = dec1Raw;
  let dec2 = dec2Raw;
  
  if (isBoosted1 && boostPct1 > 0) {
    dec1 = applyBoostToDecimal(dec1Raw, boostPct1);
  }
  if (isBoosted2 && boostPct2 > 0) {
    dec2 = applyBoostToDecimal(dec2Raw, boostPct2);
  }
  
  // Implied probabilities (for reference)
  const prob1 = decimalToImpliedProb(dec1);
  const prob2 = decimalToImpliedProb(dec2);
  if (prob1 === null || prob2 === null) return null;
  
  // Round stake1 if specified
  const actualStake1 = roundToStep(stake1, roundTo1);
  
  // ============================================================================
  // KEY FORMULA: Optimal hedge stake for equal profit on both outcomes
  // stake2_optimal = stake1 * dec1 / dec2
  // 
  // Derivation: For equal profit on both outcomes:
  //   net_if_1_wins = net_if_2_wins
  //   stake1*(dec1-1) - stake2 = stake2*(dec2-1) - stake1
  //   stake1*dec1 - stake1 - stake2 = stake2*dec2 - stake2 - stake1
  //   stake1*dec1 = stake2*dec2
  //   stake2 = stake1 * dec1 / dec2
  // ============================================================================
  const optimal_stake2 = actualStake1 * dec1 / dec2;
  
  // Breakeven stake: makes net_if_1_wins = 0
  // stake1*(dec1-1) - stake2 = 0 → stake2 = stake1*(dec1-1)
  const breakeven_stake2 = actualStake1 * (dec1 - 1);
  
  // Actual hedge stake based on slider (100% = optimal)
  // At 100%: stake2 = optimal_stake2 (equal profit both outcomes)
  // At 0%: stake2 = 0 (no hedge)
  // At 200%: stake2 = 2 * optimal_stake2 (over-hedge)
  let stake2_raw = (clampedHedge / 100) * optimal_stake2;
  const actualStake2 = roundToStep(stake2_raw, roundTo2);
  
  // Total stake
  const totalStake = actualStake1 + actualStake2;
  
  // ============================================================================
  // P&L Calculations (NET PROFIT, not payout)
  // ============================================================================
  
  // Profit from bet1 alone (if it wins)
  const profit1_alone = actualStake1 * (dec1 - 1);
  // Profit from bet2 alone (if it wins)  
  const profit2_alone = actualStake2 * (dec2 - 1);
  
  // Net profit if Bet 1 wins (we get profit1, lose stake2)
  const net_if_1_wins = profit1_alone - actualStake2;
  
  // Net profit if Bet 2 wins (we get profit2, lose stake1)
  const net_if_2_wins = profit2_alone - actualStake1;
  
  // Guaranteed and best case
  const guaranteed_profit = Math.min(net_if_1_wins, net_if_2_wins);
  const best_profit = Math.max(net_if_1_wins, net_if_2_wins);
  
  // ============================================================================
  // Arb % as ROI (positive = profitable)
  // ============================================================================
  const arbPct = totalStake > 0 ? (guaranteed_profit / totalStake) * 100 : 0;
  const hasArb = guaranteed_profit > 0;
  
  // Effective odds for display
  const effOdds1Val = decimalToAmerican(dec1);
  const effOdds2Val = decimalToAmerican(dec2);
  
  return {
    odds1_american: odds1,
    odds2_american: odds2,
    stake1: actualStake1,
    stake2: actualStake2,
    odds1_decimal: dec1,
    odds2_decimal: dec2,
    effective_american1: effOdds1Val !== null ? formatAmerican(effOdds1Val) : "N/A",
    effective_american2: effOdds2Val !== null ? formatAmerican(effOdds2Val) : "N/A",
    implied_prob1: prob1,
    implied_prob2: prob2,
    arb_pct: arbPct,
    has_arb: hasArb,
    
    // Scenario: Bet 1 Wins
    profit_bet1_wins: profit1_alone,
    loss_bet2_if_1_wins: -actualStake2,
    total_if_1_wins: net_if_1_wins,
    
    // Scenario: Bet 2 Wins
    loss_bet1_if_2_wins: -actualStake1,
    profit_bet2_wins: profit2_alone,
    total_if_2_wins: net_if_2_wins,
    
    guaranteed_profit,
    best_profit,
    total_stake: totalStake,
    optimal_stake2,
    breakeven_stake2,
  };
}

// ============================================================================
// Robinhood Event Contract Converter
// ============================================================================

export interface RHOutput {
  effective_price: number;
  implied_prob: number;
  decimal: number;
  american: number;
}

export function convertRhOdds(price: number, fee: number): RHOutput | null {
  if (!Number.isFinite(price) || price <= 0 || price >= 1) return null;
  if (!Number.isFinite(fee) || fee < 0) return null;
  
  const effectivePrice = price + fee;
  if (effectivePrice >= 1) return null;
  
  const decimal = 1 / effectivePrice;
  const american = decimalToAmerican(decimal);
  if (american === null) return null;
  
  return {
    effective_price: effectivePrice,
    implied_prob: effectivePrice,
    decimal: decimal,
    american: Math.round(american),
  };
}

// Legacy exports for backwards compatibility
export type ArbMode = 'arb' | 'noLoss';
export interface ArbInputs {
  odds1: number;
  odds2: number;
  totalStake: number;
  biasToBet1: number;
  isBoosted1: boolean;
  isBoosted2: boolean;
  boostPct1: number;
  boostPct2: number;
  maxStake1?: number;
  maxStake2?: number;
  mode?: ArbMode;
}
export interface ArbResult {
  odds1_american: number;
  odds2_american: number;
  total_stake: number;
  boosts1: number;
  boosts2: number;
  mode: ArbMode;
  odds1_decimal: number;
  odds2_decimal: number;
  implied_prob1: number;
  implied_prob2: number;
  effective_american1: string;
  effective_american2: string;
  stake1: number;
  stake2: number;
  payout1: number;
  payout2: number;
  profit1: number;
  profit2: number;
  roi1: number;
  roi2: number;
  profit_if_1: number;
  profit_if_2: number;
  roi_if_1: number;
  roi_if_2: number;
  has_arb: boolean;
  arb_pct: number;
  edge_pct: number;
  guaranteed_profit: number;
  worst_profit: number;
  best_profit: number;
  can_no_loss: boolean;
  s1_min: number | null;
  s1_max: number | null;
  effective_odds1: string;
  effective_odds2: string;
}
export function computeArb(inputs: ArbInputs): ArbResult | null {
  const hedgeResult = computeHedge({
    odds1: inputs.odds1,
    stake1: inputs.totalStake * (inputs.biasToBet1 / 100) || inputs.totalStake / 2,
    odds2: inputs.odds2,
    hedgePercent: 100,
    isBoosted1: inputs.isBoosted1,
    boostPct1: inputs.boostPct1,
    isBoosted2: inputs.isBoosted2,
    boostPct2: inputs.boostPct2,
  });
  if (!hedgeResult) return null;
  
  return {
    odds1_american: hedgeResult.odds1_american,
    odds2_american: hedgeResult.odds2_american,
    total_stake: hedgeResult.total_stake,
    boosts1: inputs.isBoosted1 ? inputs.boostPct1 : 0,
    boosts2: inputs.isBoosted2 ? inputs.boostPct2 : 0,
    mode: inputs.mode || 'arb',
    odds1_decimal: hedgeResult.odds1_decimal,
    odds2_decimal: hedgeResult.odds2_decimal,
    implied_prob1: hedgeResult.implied_prob1,
    implied_prob2: hedgeResult.implied_prob2,
    effective_american1: hedgeResult.effective_american1,
    effective_american2: hedgeResult.effective_american2,
    stake1: hedgeResult.stake1,
    stake2: hedgeResult.stake2,
    payout1: hedgeResult.stake1 * hedgeResult.odds1_decimal,
    payout2: hedgeResult.stake2 * hedgeResult.odds2_decimal,
    profit1: hedgeResult.total_if_1_wins,
    profit2: hedgeResult.total_if_2_wins,
    roi1: hedgeResult.total_stake > 0 ? (hedgeResult.total_if_1_wins / hedgeResult.total_stake) * 100 : 0,
    roi2: hedgeResult.total_stake > 0 ? (hedgeResult.total_if_2_wins / hedgeResult.total_stake) * 100 : 0,
    profit_if_1: hedgeResult.total_if_1_wins,
    profit_if_2: hedgeResult.total_if_2_wins,
    roi_if_1: hedgeResult.total_stake > 0 ? (hedgeResult.total_if_1_wins / hedgeResult.total_stake) * 100 : 0,
    roi_if_2: hedgeResult.total_stake > 0 ? (hedgeResult.total_if_2_wins / hedgeResult.total_stake) * 100 : 0,
    has_arb: hedgeResult.has_arb,
    arb_pct: hedgeResult.arb_pct,
    edge_pct: -hedgeResult.arb_pct,
    guaranteed_profit: hedgeResult.guaranteed_profit,
    worst_profit: hedgeResult.guaranteed_profit,
    best_profit: hedgeResult.best_profit,
    can_no_loss: hedgeResult.guaranteed_profit >= 0,
    s1_min: null,
    s1_max: null,
    effective_odds1: hedgeResult.effective_american1,
    effective_odds2: hedgeResult.effective_american2,
  };
}
