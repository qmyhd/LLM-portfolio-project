import { useState } from 'react';
import { InputsPanel } from './components/InputsPanel';
import { ResultsPanel } from './components/ResultsPanel';
import { HedgeInputs, computeHedge } from './lib/arbEngine';
import './index.css';

// Default inputs matching the golden test case (Profit Boost Calculator reference)
const DEFAULT_INPUTS: HedgeInputs = {
  odds1: 280,
  stake1: 10,
  odds2: -280,
  hedgePercent: 100,
  isBoosted1: true,
  isBoosted2: false,
  boostPct1: 50,
  boostPct2: 0
};

function App() {
  const [inputs, setInputs] = useState<HedgeInputs>(DEFAULT_INPUTS);

  const result = computeHedge(inputs);

  return (
    <div className="app-container">
      <header className="animate-fade-in">
        <div className="header-content">
          <h1>Hedge Calculator</h1>
        </div>
        <div className="header-actions">
          <button 
            className="btn" 
            onClick={() => setInputs(DEFAULT_INPUTS)}
          >
            ↺ Reset
          </button>
        </div>
      </header>
      
      <main className="hedge-layout animate-fade-in" style={{animationDelay: '0.1s'}}>
        <InputsPanel inputs={inputs} onChange={setInputs} />
        <ResultsPanel result={result} />
      </main>
    </div>
  );
}

export default App;
