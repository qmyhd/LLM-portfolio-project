import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'
import { runDevTests } from './lib/arbEngine.devtest.ts'

// Run tests in console
if (import.meta.env.DEV) {
  runDevTests();
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
