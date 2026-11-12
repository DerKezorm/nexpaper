/**
 * A document whose original is a protected PDF (P1), on the document page: the mark beside the fields, the sentence at
 * "Herunterladen: Original", and, while the PDF waits for its password, the field where the reading error stands (only
 * for somebody who may change the document).
 */
import { Route, Routes } from 'react-router-dom'

import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { forgetPictures } from '../lib/pictures'
import { Page, Server } from '../test/harness'
import { DocumentPage } from './DocumentPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'member', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const base = {
  id: 7, vault_id: 9, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title: 'Gehaltsabrechnung Oktober', sender: null, kind: null, date: null,
  amount: null, currency: 'EUR', tags: [], dates: [], pages: 2, source: 'upload', status: 'inbox', added_at: '2026-11-12T08:00:00Z', trashed_at: null,
  trash_ends_at: null, change_seq: 3, current_version: 1, my_right: 'edit', via_share: false, can_share: true, notes: 0, process_error: '', duplicate: null,
  suggest: {}, original_protected: 'password',
}

function show() {
  return page.show(
    <Routes>
      <Route path="dokument/:id" element={<DocumentPage slots={{}} />} />
    </Routes>,
    '/dokument/7',
  )
}

beforeEach(async () => {
  forgetPictures()
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/documents/7': base, 'GET /api/v1/vaults': [], 'GET /api/v1/documents/7/versions': [] }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

it('marks a protected original and says so at downloading the original', async () => {
  await show()
  expect(document.querySelector('[data-testid="original-protected"]')?.textContent).toContain('Original mit Passwort')
  await page.click(page.button('Herunterladen'))
  expect(page.text).toContain('mit Passwort geschützt, so wie es kam')
  expect(document.querySelector('[data-testid="protected-pdf"]')).toBeNull()
})

it('marks an original that is only locked against printing in its own words', async () => {
  server.answers['GET /api/v1/documents/7'] = { ...base, original_protected: 'restricted' }
  await show()
  expect(document.querySelector('[data-testid="original-protected"]')?.textContent).toContain('Original gesperrt')
})

it('shows no mark for any other document', async () => {
  server.answers['GET /api/v1/documents/7'] = { ...base, original_protected: '' }
  await show()
  expect(document.querySelector('[data-testid="original-protected"]')).toBeNull()
})

it('offers the password field where the reading error stands, to who may change it only', async () => {
  server.answers['GET /api/v1/documents/7'] = { ...base, pages: 0, process_error: 'encrypted', original_protected: '' }
  await show()
  const box = document.querySelector('[data-testid="protected-pdf"]')
  expect(box?.textContent).toContain('Das PDF ist mit einem Passwort geschützt')
  expect(box?.querySelector('[data-testid="unlock-pdf"]')).not.toBeNull()
  page.close()
  server.answers['GET /api/v1/documents/7'] = { ...base, pages: 0, process_error: 'encrypted', original_protected: '', my_right: 'read' }
  await show()
  const read = document.querySelector('[data-testid="protected-pdf"]')
  expect(read?.textContent).toContain('Wer das Dokument bearbeiten darf')
  expect(read?.querySelector('[data-testid="unlock-pdf"]')).toBeNull()
})
