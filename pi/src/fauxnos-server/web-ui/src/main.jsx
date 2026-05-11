import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import ComponentSheet from './components/ComponentSheet'
import './index.css'

// Route at the entry rather than inside App so the live App component stays
// a pure single-purpose tree — no Rules-of-Hooks gymnastics around an
// early conditional return. `?vibe=1` is the design-language preview;
// removing this branch after sign-off is a one-line delete.
const isVibePreview =
  typeof window !== 'undefined' &&
  new URLSearchParams(window.location.search).has('vibe')

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {isVibePreview ? <ComponentSheet /> : <App />}
  </StrictMode>
)
