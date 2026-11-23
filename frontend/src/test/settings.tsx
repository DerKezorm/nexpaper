/**
 * The settings as the app routes them (`App.tsx`), for tests: the areas under `/settings/<slug>` and the pages of
 * before (`/konto?tab=…`, `/einstellungen?tab=…`, `/ueber`), which lead to their area. A test can still open an
 * address of before and lands where the app lands.
 */
import { Route, Routes } from 'react-router-dom'

import { FormerAddress, SettingsPage } from '../pages/SettingsPage'

export function SettingsRoutes() {
  return (
    <Routes>
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="/settings/:tab" element={<SettingsPage />} />
      <Route path="/konto" element={<FormerAddress page="konto" />} />
      <Route path="/einstellungen" element={<FormerAddress page="einstellungen" />} />
      <Route path="/ueber" element={<FormerAddress page="ueber" />} />
    </Routes>
  )
}
