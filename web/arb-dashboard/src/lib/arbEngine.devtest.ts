import { computeArb, ArbInputs } from './arbEngine';
import cases from './arb_cases.json';

export function runDevTests() {
  try {
    console.log("Running Arb Engine Dev Tests...");
    console.table(cases.map(c => ({ name: c.name })));

    let passed = 0;
    let failed = 0;

    cases.forEach((c: any) => {
      // Skip section markers (non-test entries)
      if (!c.inputs || !c.expected) {
        return;
      }

      const inputs: ArbInputs = {
        odds1: c.inputs.odds1,
        odds2: c.inputs.odds2,
        totalStake: c.inputs.total_stake ?? 100,
        biasToBet1: c.inputs.bias_to_bet1 ?? 50,
        isBoosted1: c.inputs.is_boosted1 || false,
        isBoosted2: c.inputs.is_boosted2 || false,
        boostPct1: c.inputs.boost_pct1 || 0,
        boostPct2: c.inputs.boost_pct2 || 0,
        maxStake1: c.inputs.max_stake1,
        maxStake2: c.inputs.max_stake2,
        mode: c.inputs.mode
      };

      // Handle expected null result
      if (c.expected.result === null) {
        const result = computeArb(inputs);
        if (result === null) {
          console.log(`%cPASS: ${c.name} (expected null)`, 'color: green');
          passed++;
        } else {
          console.error(`FAIL: ${c.name} - Expected null, got result`);
          failed++;
        }
        return;
      }

      const result = computeArb(inputs);

      if (!result) {
        console.error(`FAIL: ${c.name} - Result is null`);
        failed++;
        return;
      }

      const errors: string[] = [];
      const expected = c.expected;

      for (const key in expected) {
        if (key === 'result') continue; // Skip 'result' key
        // @ts-ignore
        const actual = result[key];
        // @ts-ignore
        const exp = expected[key];

        if (typeof exp === 'number' && typeof actual === 'number') {
          if (Math.abs(actual - exp) > 0.1) {
            errors.push(`${key}: exp ${exp}, got ${actual.toFixed(2)}`);
          }
        } else if (actual !== exp) {
          errors.push(`${key}: exp ${exp}, got ${actual}`);
        }
      }

      if (errors.length === 0) {
        console.log(`%cPASS: ${c.name}`, 'color: green');
        passed++;
      } else {
        console.error(`FAIL: ${c.name}`, errors);
        failed++;
      }
    });

    console.log(`Tests Complete. Passed: ${passed}, Failed: ${failed}`);
  } catch (error) {
    console.error("Dev tests failed:", error);
  }
}
