import '@fontsource-variable/figtree'
import '@fontsource-variable/fraunces'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
import './i18n'
import './index.css'
import { openShare, sweepShared } from './lib/shared'
import { followSystem } from './lib/theme'
import { AuthProvider } from './state/auth'

followSystem()

// The service worker from the start, not only for Web Push: Android's share menu sends files to it (`public/sw.js`).
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => void navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => undefined))
}
// Files shared from another app and never uploaded do not stay in the browser: only the share this page shows stays.
void sweepShared(openShare(window.location))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
