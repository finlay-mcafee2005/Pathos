import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { installAuthFetch } from './utils/session'
import L from 'leaflet'

// maps keep the small required OpenStreetMap credit, without the extra "Leaflet" label
L.Control.Attribution.prototype.options.prefix = false

installAuthFetch()

// apply the saved light/dark theme right away (the intro shows before any page mounts)
try { document.documentElement.setAttribute('data-theme', localStorage.getItem('theme') || 'light') } catch { /* ignore */ }

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
