/**
 * Unit tests for arbEngine.ts
 * Run with: npx vitest run src/lib/arbEngine.test.ts
 */
import { describe, it, expect } from 'vitest';
import {
  computeArb,
  computeHedge,
  americanToDecimal,
  decimalToAmerican,
  applyBoostToDecimal,
  convertRhOdds,
  type ArbInputs,
  type HedgeInputs,
} from './arbEngine';
import testCases from './arb_cases.json';

// Helper to convert snake_case JSON to camelCase ArbInputs
function toArbInputs(jsonInputs: Record<string, unknown>): ArbInputs {
  return {
    odds1: jsonInputs.odds1 as number,
    odds2: jsonInputs.odds2 as number,
    totalStake: (jsonInputs.total_stake as number) ?? 0,
    biasToBet1: (jsonInputs.bias_to_bet1 as number) ?? 50,
    isBoosted1: (jsonInputs.is_boosted1 as boolean) ?? false,
    isBoosted2: (jsonInputs.is_boosted2 as boolean) ?? false,
    boostPct1: (jsonInputs.boost_pct1 as number) ?? 0,
    boostPct2: (jsonInputs.boost_pct2 as number) ?? 0,
    maxStake1: jsonInputs.max_stake1 as number | undefined,
    maxStake2: jsonInputs.max_stake2 as number | undefined,
    mode: (jsonInputs.mode as 'arb' | 'noLoss') ?? undefined,
  };
}

describe('Odds Conversion', () => {
  describe('americanToDecimal', () => {
    it('converts positive odds correctly', () => {
      expect(americanToDecimal(100)).toBeCloseTo(2.0, 4);
      expect(americanToDecimal(150)).toBeCloseTo(2.5, 4);
      expect(americanToDecimal(200)).toBeCloseTo(3.0, 4);
      expect(americanToDecimal(500)).toBeCloseTo(6.0, 4);
    });

    it('converts negative odds correctly', () => {
      expect(americanToDecimal(-100)).toBeCloseTo(2.0, 4);
      expect(americanToDecimal(-110)).toBeCloseTo(1.909, 2);
      expect(americanToDecimal(-200)).toBeCloseTo(1.5, 4);
      expect(americanToDecimal(-500)).toBeCloseTo(1.2, 4);
    });

    it('returns null for invalid odds', () => {
      expect(americanToDecimal(0)).toBeNull();
      expect(americanToDecimal(50)).toBeNull();  // dead zone
      expect(americanToDecimal(-50)).toBeNull(); // dead zone
      expect(americanToDecimal(NaN)).toBeNull();
    });
  });

  describe('decimalToAmerican', () => {
    it('converts high decimal to positive american', () => {
      expect(decimalToAmerican(2.0)).toBe(100);
      expect(decimalToAmerican(2.5)).toBe(150);
      expect(decimalToAmerican(3.0)).toBe(200);
    });

    it('converts low decimal to negative american', () => {
      expect(decimalToAmerican(1.5)).toBeCloseTo(-200, 0);
      expect(decimalToAmerican(1.2)).toBeCloseTo(-500, 0);
    });

    it('returns null for invalid decimal odds', () => {
      expect(decimalToAmerican(0)).toBeNull();
      expect(decimalToAmerican(1.0)).toBeNull();  // implies 100% probability
      expect(decimalToAmerican(-1)).toBeNull();
      expect(decimalToAmerican(NaN)).toBeNull();
    });
  });

  describe('Round-trip conversions', () => {
    // These odds should round-trip exactly (or very close)
    const roundTripOdds = [-500, -250, -200, -110, -101, 100, 105, 150, 250, 500];
    
    roundTripOdds.forEach((american) => {
      it(`round-trips ${american} correctly`, () => {
        const decimal = americanToDecimal(american);
        expect(decimal).not.toBeNull();
        const backToAmerican = decimalToAmerican(decimal!);
        // Use toBeCloseTo to handle floating point precision
        expect(backToAmerican).toBeCloseTo(american, 0);
      });
    });

    // Special case: -100 and +100 both convert to decimal 2.0, which becomes +100
    it('converts -100 to decimal 2.0 (same as +100)', () => {
      expect(americanToDecimal(-100)).toBeCloseTo(2.0, 4);
      expect(americanToDecimal(100)).toBeCloseTo(2.0, 4);
      // Both return +100 since decimal 2.0 is positive american by convention
      expect(decimalToAmerican(2.0)).toBe(100);
    });
  });
});

// ============================================================================
// GOLDEN TEST CASE: Profit Boost Calculator Reference
// ============================================================================
// This test validates our engine matches the reference Profit Boost Calculator
// Inputs: Stake=$10, Odds1=+280 with 50% boost, Odds2=-280, Hedge=100%
// Expected: Both outcomes yield equal profit of $3.68
// ============================================================================
describe('Golden Test: Profit Boost Calculator', () => {
  describe('applyBoostToDecimal', () => {
    it('applies 50% boost to +280 correctly (3.80 → 5.20)', () => {
      const dec = americanToDecimal(280);
      expect(dec).toBeCloseTo(3.80, 4);
      
      const boosted = applyBoostToDecimal(dec!, 50);
      expect(boosted).toBeCloseTo(5.20, 4);
    });
    
    it('converts boosted decimal 5.20 to +420 American', () => {
      const american = decimalToAmerican(5.20);
      expect(american).toBeCloseTo(420, 0);
    });
  });
  
  describe('computeHedge with 100% hedge (optimal)', () => {
    const goldenInputs: HedgeInputs = {
      odds1: 280,
      stake1: 10,
      odds2: -280,
      hedgePercent: 100,
      isBoosted1: true,
      boostPct1: 50,
      isBoosted2: false,
      boostPct2: 0
    };
    
    it('calculates effective boosted odds as +420', () => {
      const result = computeHedge(goldenInputs);
      expect(result).not.toBeNull();
      expect(result!.effective_american1).toBe('+420');
      expect(result!.odds1_decimal).toBeCloseTo(5.2, 2);
    });
    
    it('calculates optimal hedge stake as $38.32', () => {
      const result = computeHedge(goldenInputs);
      expect(result).not.toBeNull();
      // stake2_optimal = stake1 * dec1 / dec2 = 10 * 5.2 / 1.357 = 38.32
      expect(result!.optimal_stake2).toBeCloseTo(38.32, 2);
      // At 100% hedge, actual stake2 should equal optimal
      expect(result!.stake2).toBeCloseTo(38.32, 2);
    });
    
    it('calculates total stake as $48.32', () => {
      const result = computeHedge(goldenInputs);
      expect(result).not.toBeNull();
      expect(result!.total_stake).toBeCloseTo(48.32, 2);
    });
    
    it('calculates profit if Bet1 wins: $42 - $38.32 = $3.68', () => {
      const result = computeHedge(goldenInputs);
      expect(result).not.toBeNull();
      // profit1_alone = stake1 * (dec1 - 1) = 10 * 4.2 = $42
      expect(result!.profit_bet1_wins).toBeCloseTo(42.00, 2);
      // net_if_1_wins = profit1_alone - stake2 = 42 - 38.32 = 3.68
      expect(result!.total_if_1_wins).toBeCloseTo(3.68, 2);
    });
    
    it('calculates profit if Bet2 wins: $13.68 - $10 = $3.68', () => {
      const result = computeHedge(goldenInputs);
      expect(result).not.toBeNull();
      // profit2_alone = stake2 * (dec2 - 1) = 38.32 * 0.357 = 13.68
      expect(result!.profit_bet2_wins).toBeCloseTo(13.68, 2);
      // net_if_2_wins = profit2_alone - stake1 = 13.68 - 10 = 3.68
      expect(result!.total_if_2_wins).toBeCloseTo(3.68, 2);
    });
    
    it('calculates guaranteed and best profit as $3.68 (equal)', () => {
      const result = computeHedge(goldenInputs);
      expect(result).not.toBeNull();
      expect(result!.guaranteed_profit).toBeCloseTo(3.68, 2);
      expect(result!.best_profit).toBeCloseTo(3.68, 2);
    });
    
    it('calculates arb % as +7.62% (positive = profitable)', () => {
      const result = computeHedge(goldenInputs);
      expect(result).not.toBeNull();
      // arb_pct = guaranteed / total_stake * 100 = 3.68 / 48.32 * 100 = 7.62
      expect(result!.arb_pct).toBeCloseTo(7.62, 1);
      expect(result!.arb_pct).toBeGreaterThan(0); // Must be positive
      expect(result!.has_arb).toBe(true);
    });
  });
  
  describe('hedge slider behavior', () => {
    const baseInputs: HedgeInputs = {
      odds1: 280,
      stake1: 10,
      odds2: -280,
      hedgePercent: 100,
      isBoosted1: true,
      boostPct1: 50,
      isBoosted2: false,
      boostPct2: 0
    };
    
    it('0% hedge means no hedge (stake2 = 0)', () => {
      const result = computeHedge({ ...baseInputs, hedgePercent: 0 });
      expect(result).not.toBeNull();
      expect(result!.stake2).toBe(0);
      expect(result!.total_if_1_wins).toBeCloseTo(42, 2); // Full profit if bet1 wins
      expect(result!.total_if_2_wins).toBeCloseTo(-10, 2); // Lose stake1 if bet2 wins
    });
    
    it('50% hedge means half optimal stake', () => {
      const result = computeHedge({ ...baseInputs, hedgePercent: 50 });
      expect(result).not.toBeNull();
      expect(result!.stake2).toBeCloseTo(19.16, 2); // 38.32 * 0.5
    });
    
    it('200% hedge means double optimal stake (over-hedge)', () => {
      const result = computeHedge({ ...baseInputs, hedgePercent: 200 });
      expect(result).not.toBeNull();
      expect(result!.stake2).toBeCloseTo(76.63, 1); // 38.32 * 2 (relaxed precision)
    });
  });
});

describe('Robinhood Converter', () => {
  it('converts simple RH price correctly', () => {
    const result = convertRhOdds(0.40, 0.02);
    expect(result).not.toBeNull();
    expect(result!.effective_price).toBeCloseTo(0.42, 4);
    expect(result!.decimal).toBeCloseTo(2.38, 2);
    expect(result!.implied_prob).toBeCloseTo(0.42, 4);
    expect(result!.american).toBe(138);
  });

  it('converts low RH price to high positive american', () => {
    const result = convertRhOdds(0.10, 0.02);
    expect(result).not.toBeNull();
    expect(result!.effective_price).toBeCloseTo(0.12, 4);
    expect(result!.american).toBeGreaterThan(500);
  });

  it('converts high RH price to negative american', () => {
    const result = convertRhOdds(0.80, 0.02);
    expect(result).not.toBeNull();
    expect(result!.american).toBeLessThan(-200);
  });

  it('returns null when price + fee >= 1', () => {
    expect(convertRhOdds(0.99, 0.01)).toBeNull();
    expect(convertRhOdds(0.98, 0.03)).toBeNull();
  });

  it('returns null for invalid prices', () => {
    expect(convertRhOdds(0, 0.02)).toBeNull();
    expect(convertRhOdds(1, 0.02)).toBeNull();
    expect(convertRhOdds(-0.5, 0.02)).toBeNull();
  });
});

describe('computeArb - Basic Cases', () => {
  it('detects no arb with standard vig (-110/-110)', () => {
    const result = computeArb({
      odds1: -110,
      odds2: -110,
      totalStake: 100,
      biasToBet1: 50,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.has_arb).toBe(false);
    expect(result!.can_no_loss).toBe(false);
    expect(result!.edge_pct).toBeLessThan(0);
  });

  it('detects true arb with +105/+105', () => {
    const result = computeArb({
      odds1: 105,
      odds2: 105,
      totalStake: 100,
      biasToBet1: 50,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.has_arb).toBe(true);
    expect(result!.can_no_loss).toBe(true);
    expect(result!.edge_pct).toBeGreaterThan(0);
    expect(result!.guaranteed_profit).toBeGreaterThan(0);
  });

  it('calculates symmetric arb correctly (-110/+120)', () => {
    const result = computeArb({
      odds1: -110,
      odds2: 120,
      totalStake: 100,
      biasToBet1: 50,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.has_arb).toBe(true);
    expect(result!.edge_pct).toBeCloseTo(2.16, 1);
    expect(result!.stake1).toBeCloseTo(53.49, 0);
    expect(result!.stake2).toBeCloseTo(46.51, 0);
  });
});

describe('computeArb - Extreme Bias', () => {
  it('allocates 0% to bet1 when bias=0', () => {
    const result = computeArb({
      odds1: -110,
      odds2: 120,
      totalStake: 100,
      biasToBet1: 0,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.stake1).toBe(0);
    expect(result!.stake2).toBe(100);
  });

  it('allocates 100% to bet1 when bias=100', () => {
    const result = computeArb({
      odds1: -110,
      odds2: 120,
      totalStake: 100,
      biasToBet1: 100,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.stake1).toBe(100);
    expect(result!.stake2).toBe(0);
  });

  it('clamps bias > 100 to 100', () => {
    const result = computeArb({
      odds1: -110,
      odds2: 120,
      totalStake: 100,
      biasToBet1: 150,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.stake1).toBe(100);
  });

  it('clamps bias < 0 to 0', () => {
    const result = computeArb({
      odds1: -110,
      odds2: 120,
      totalStake: 100,
      biasToBet1: -50,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.stake1).toBe(0);
  });
});

describe('computeArb - Boosts', () => {
  it('creates arb from -110/-110 with 25% boost', () => {
    const result = computeArb({
      odds1: -110,
      odds2: -110,
      totalStake: 100,
      biasToBet1: 50,
      isBoosted1: true,
      boostPct1: 25,
      isBoosted2: false,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.has_arb).toBe(true);
    // Effective decimal = 1 + (1.909-1) * 1.25 = 2.136, effective american ~+114
    expect(result!.effective_american1).toMatch(/^\+?11[3-5]$/);
  });

  it('boost not enough does not create arb', () => {
    const result = computeArb({
      odds1: -200,
      odds2: -200,
      totalStake: 100,
      biasToBet1: 50,
      isBoosted1: true,
      boostPct1: 10,
      isBoosted2: false,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.has_arb).toBe(false);
  });

  it('handles boost on both sides', () => {
    const result = computeArb({
      odds1: -110,
      odds2: -110,
      totalStake: 100,
      biasToBet1: 50,
      isBoosted1: true,
      boostPct1: 20,
      isBoosted2: true,
      boostPct2: 20,
    });
    expect(result).not.toBeNull();
    expect(result!.has_arb).toBe(true);
  });

  it('clamps boost > 500% to 500%', () => {
    const result = computeArb({
      odds1: -110,
      odds2: -110,
      totalStake: 100,
      biasToBet1: 50,
      isBoosted1: true,
      boostPct1: 1000, // should be clamped to 500
      isBoosted2: false,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    // With 500% boost on -110: decimal 1.909 * 6 = ~5.45 ish (max effective)
    // The formula is: 1 + (1.909 - 1) * (1 + 5) = 1 + 0.909 * 6 = 6.45
    expect(result!.odds1_decimal).toBeLessThanOrEqual(7);
  });
});

describe('computeArb - Stake Caps', () => {
  it('respects max_stake1 cap', () => {
    const result = computeArb({
      odds1: 105,
      odds2: 105,
      totalStake: 100,
      biasToBet1: 50,
      maxStake1: 20,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.stake1).toBeLessThanOrEqual(20);
  });

  it('respects max_stake2 cap', () => {
    const result = computeArb({
      odds1: 105,
      odds2: 105,
      totalStake: 100,
      biasToBet1: 50,
      maxStake2: 30,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.stake2).toBeLessThanOrEqual(30);
  });

  it('respects both caps simultaneously', () => {
    const result = computeArb({
      odds1: 105,
      odds2: 105,
      totalStake: 100,
      biasToBet1: 50,
      maxStake1: 10,
      maxStake2: 15,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.stake1).toBeLessThanOrEqual(10);
    expect(result!.stake2).toBeLessThanOrEqual(15);
    expect(result!.total_stake).toBe(result!.stake1 + result!.stake2);
  });
});

describe('computeArb - No-Loss Mode', () => {
  it('guarantees no loss when arb exists (bias 0)', () => {
    const result = computeArb({
      odds1: 105,
      odds2: 105,
      totalStake: 100,
      biasToBet1: 0,
      mode: 'noLoss',
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.can_no_loss).toBe(true);
    expect(result!.profit1).toBeGreaterThanOrEqual(-0.01);
    expect(result!.profit2).toBeGreaterThanOrEqual(-0.01);
  });

  it('guarantees no loss when arb exists (bias 50)', () => {
    const result = computeArb({
      odds1: 105,
      odds2: 105,
      totalStake: 100,
      biasToBet1: 50,
      mode: 'noLoss',
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.profit1).toBeGreaterThanOrEqual(-0.01);
    expect(result!.profit2).toBeGreaterThanOrEqual(-0.01);
  });

  it('guarantees no loss when arb exists (bias 100)', () => {
    const result = computeArb({
      odds1: 105,
      odds2: 105,
      totalStake: 100,
      biasToBet1: 100,
      mode: 'noLoss',
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.profit1).toBeGreaterThanOrEqual(-0.01);
    expect(result!.profit2).toBeGreaterThanOrEqual(-0.01);
  });

  it('cannot guarantee no loss when no arb exists', () => {
    const result = computeArb({
      odds1: -110,
      odds2: -110,
      totalStake: 100,
      biasToBet1: 50,
      mode: 'noLoss',
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.has_arb).toBe(false);
    expect(result!.can_no_loss).toBe(false);
  });

  it('respects caps in no-loss mode', () => {
    const result = computeArb({
      odds1: 150,
      odds2: 150,
      totalStake: 100,
      biasToBet1: 50,
      mode: 'noLoss',
      maxStake1: 45,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    });
    expect(result).not.toBeNull();
    expect(result!.stake1).toBeLessThanOrEqual(45);
    expect(result!.profit1).toBeGreaterThanOrEqual(-0.01);
    expect(result!.profit2).toBeGreaterThanOrEqual(-0.01);
  });
});

describe('computeArb - Invalid Inputs', () => {
  it('returns null for zero total stake', () => {
    expect(computeArb({
      odds1: -110,
      odds2: 120,
      totalStake: 0,
      biasToBet1: 50,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    })).toBeNull();
  });

  it('returns null for negative total stake', () => {
    expect(computeArb({
      odds1: -110,
      odds2: 120,
      totalStake: -50,
      biasToBet1: 50,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    })).toBeNull();
  });

  it('returns null for invalid odds1', () => {
    expect(computeArb({
      odds1: 0,
      odds2: 120,
      totalStake: 100,
      biasToBet1: 50,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    })).toBeNull();
  });

  it('returns null for invalid odds2', () => {
    expect(computeArb({
      odds1: -110,
      odds2: 50, // dead zone
      totalStake: 100,
      biasToBet1: 50,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    })).toBeNull();
  });

  it('returns null for NaN inputs', () => {
    expect(computeArb({
      odds1: NaN,
      odds2: 120,
      totalStake: 100,
      biasToBet1: 50,
      isBoosted1: false,
      isBoosted2: false,
      boostPct1: 0,
      boostPct2: 0,
    })).toBeNull();
  });
});

describe('Test Cases from JSON', () => {
  // Filter to only test cases with expected results (not sections or RH tests)
  const arbTestCases = testCases.filter(
    (tc): tc is typeof tc & { inputs: Record<string, unknown>; expected: Record<string, unknown> } =>
      'inputs' in tc && 'expected' in tc && !('inputs_rh' in tc)
  );

  arbTestCases.forEach((tc) => {
    it(tc.name, () => {
      const inputs = toArbInputs(tc.inputs);
      
      if (tc.expected.result === null) {
        expect(computeArb(inputs)).toBeNull();
        return;
      }

      const result = computeArb(inputs);
      expect(result).not.toBeNull();

      // Check expected fields
      for (const [key, expectedValue] of Object.entries(tc.expected)) {
        if (key === 'result') continue;
        
        const actualValue = (result as unknown as Record<string, unknown>)[key];
        
        if (typeof expectedValue === 'number') {
          expect(actualValue).toBeCloseTo(expectedValue, 1);
        } else {
          expect(actualValue).toBe(expectedValue);
        }
      }

      // Check assertions if present
      if ('assertions' in tc && tc.assertions) {
        const assertions = tc.assertions as Record<string, number>;
        if (assertions.profit1_gte !== undefined) {
          expect(result!.profit1).toBeGreaterThanOrEqual(assertions.profit1_gte);
        }
        if (assertions.profit2_gte !== undefined) {
          expect(result!.profit2).toBeGreaterThanOrEqual(assertions.profit2_gte);
        }
        if (assertions.stake1_lte !== undefined) {
          expect(result!.stake1).toBeLessThanOrEqual(assertions.stake1_lte);
        }
      }
    });
  });
});
