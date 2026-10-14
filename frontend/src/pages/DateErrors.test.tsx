/**
 * A date that cannot be right is caught at its field: a year of two digits is read as 20xx when the field is left, and
 * a date the server refuses marks the field it came in, with the year it probably meant and a button to take it, on the
 * document page and in the inbox.
 */
import { act } from 'react'
import { Route, Routes } from 'react-router-dom'

import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { forgetPictures } from '../lib/pictures'
import { INBOX, Page, Server, inboxOf, plain } from '../test/harness'
import { until } from '../test/wait'
import { DocumentPage } from './DocumentPage'
import { InboxPage } from './InboxPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const invoice = { id: 1, key: 'invoice', name: 'Rechnung', hue: 28, position: 0 }
function doc(id: number, status: string) {
  return {
    id, vault_id: 9, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title: 'Rechnung Heizungswartung', sender: { id: 5, name: 'Elektro Brandt GmbH' },
    kind: invoice, date: '2026-10-06', amount: 22491, currency: 'EUR', tags: ['handwerker'], dates: [{ kind: 'due', date: '2026-10-20' }, { kind: 'contract_end', date: '2027-02-28' }],
    pages: 1, source: 'upload', status, added_at: '2026-10-08T07:42:00Z', trashed_at: null, trash_ends_at: null, change_seq: id, current_version: 1,
    my_right: 'manage', via_share: false, can_share: true, notes: 0, process_error: '', duplicate: null, suggest: {},
  }
}
const filed = doc(7, 'filed')
const waiting = doc(11, 'inbox')
const vaults = [{ id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'manage', documents: 1, size: 1, members: [] }]

const input = (label: string) => page.box.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!
const patches = () => server.calls.filter((c) => c.method === 'PATCH').map((c) => c.body)
const leave = (field: HTMLElement) => act(async () => void field.dispatchEvent(new FocusEvent('focusout', { bubbles: true })))
const alerts = () => [...page.box.querySelectorAll('[role="alert"]')].map((a) => plain(a.textContent))

beforeEach(async () => {
  forgetPictures()
  await changeLanguage('de', false)
  server.answers = {
    'GET /api/v1/documents/7': filed,
    'GET /api/v1/vaults': vaults,
    'GET /api/v1/kinds?vault_id=9': [invoice],
    'GET /api/v1/senders': [],
    'GET /api/v1/documents/7/versions': [],
    'GET /api/v1/documents/7/events': [],
    'PATCH /api/v1/documents/7': filed,
    [INBOX]: inboxOf([waiting]),
    'GET /api/v1/kinds': [invoice],
    'GET /api/v1/documents/11/origin': { source: 'upload', unknown: false, sender: '', subject: '', folder: '', file: '', at: null },
    'PATCH /api/v1/documents/11': { ...waiting, status: 'filed' },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

const showDocument = () =>
  page.show(
    <Routes>
      <Route path="dokument/:id" element={<DocumentPage slots={{}} />} />
    </Routes>,
    '/dokument/7',
  )
const showInbox = () =>
  page.show(
    <Routes>
      <Route path="eingang/:id" element={<InboxPage />} />
      <Route path="eingang" element={<InboxPage />} />
    </Routes>,
    '/eingang/11',
  )

describe('a date on the document page', () => {
  it('waits while a year is typed and reads 0027 as 2027 when the field is left', async () => {
    await showDocument()
    const date = input('Datum')
    await page.type(date, '0002-02-28')
    await page.type(date, '0027-02-28')
    expect(patches()).toEqual([])
    await leave(date)
    await until(() => patches().length === 1)
    expect(patches()).toEqual([{ date: '2027-02-28' }])
    expect(date.value).toBe('2027-02-28')
  })

  it('saves a whole year at once and a cleared date as none', async () => {
    await showDocument()
    await page.type(input('Datum'), '2026-11-02')
    await until(() => patches().length === 1)
    await page.type(input('Datum'), '')
    await until(() => patches().length === 2)
    expect(patches()).toEqual([{ date: '2026-11-02' }, { date: null }])
  })

  it('marks the date the server refuses and says which years are allowed', async () => {
    server.fails['PATCH /api/v1/documents/7'] = { status: 422, code: 'invalid_date', values: { field: 'date' } }
    await showDocument()
    // A year of 100 and over is no typo of 20xx: nothing to guess, only the years that are allowed.
    await page.type(input('Datum'), '0202-02-28')
    await leave(input('Datum'))
    await until(() => alerts().length > 0)
    expect(input('Datum').getAttribute('aria-invalid')).toBe('true')
    expect(alerts()).toEqual(['Dieses Datum geht nicht. Erlaubt sind die Jahre 1900 bis 2200.'])
    expect(page.button('Übernehmen')).toBeUndefined()
    // Taking back a wrong date by typing a right one clears the mark.
    server.fails = {}
    await page.type(input('Datum'), '2026-11-02')
    await until(() => patches().length === 2)
    expect(patches()[1]).toEqual({ date: '2026-11-02' })
    expect(alerts()).toEqual([])
  })

  it('marks the term that was refused and no other', async () => {
    server.fails['PATCH /api/v1/documents/7'] = { status: 422, code: 'invalid_date', values: { field: 'set_dates[0]' } }
    await showDocument()
    // Only the term that changed is sent (a page that is behind sends back nothing it did not see change).
    await page.type(input('Vertrag bis'), '1850-01-01')
    await until(() => alerts().length > 0)
    expect(patches()).toEqual([{ set_dates: [{ kind: 'contract_end', date: '1850-01-01' }] }])
    expect(input('Vertrag bis').getAttribute('aria-invalid')).toBe('true')
    expect(input('Fällig am').getAttribute('aria-invalid')).toBe('false')
    expect(alerts()).toEqual(['Dieses Datum geht nicht. Erlaubt sind die Jahre 1900 bis 2200.'])
  })

  it('reads a year of two digits in a term too', async () => {
    await showDocument()
    await page.type(input('Fällig am'), '0027-03-01')
    await leave(input('Fällig am'))
    await until(() => patches().length === 1)
    expect(patches()).toEqual([{ set_dates: [{ kind: 'due', date: '2027-03-01' }] }])
  })

  it('still says a refusal that names no field below, as before', async () => {
    server.fails['PATCH /api/v1/documents/7'] = { status: 422, code: 'invalid_date', values: {} }
    await showDocument()
    await page.type(input('Datum'), '1850-01-01')
    await until(() => alerts().length > 0)
    expect(alerts()).toEqual(['Dieses Datum geht nicht.'])
    expect(input('Datum').getAttribute('aria-invalid')).toBe('false')
  })
})

describe('a date in the inbox', () => {
  it('reads 0027 as 2027 when the field is left, so filing sends the year meant', async () => {
    await showInbox()
    await until(() => !!page.button('Ablegen'))
    await page.type(input('Datum'), '0027-02-28')
    await leave(input('Datum'))
    expect(input('Datum').value).toBe('2027-02-28')
    await page.click(page.button('Ablegen'))
    await until(() => patches().length === 1)
    expect(patches()[0]).toMatchObject({ date: '2027-02-28', status: 'filed' })
  })

  it('marks the field when the date goes as it stands (Ctrl+Enter from inside the field) and the server refuses', async () => {
    server.fails['PATCH /api/v1/documents/11'] = { status: 422, code: 'invalid_date', values: { field: 'date' } }
    await showInbox()
    await until(() => !!page.button('Ablegen'))
    await page.type(input('Datum'), '0027-02-28')
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true })))
    await until(() => alerts().length > 0)
    expect(patches()[0]).toMatchObject({ date: '0027-02-28' })
    expect(input('Datum').getAttribute('aria-invalid')).toBe('true')
    expect(alerts()).toEqual(['Das Jahr 0027 ist wohl ein Tippfehler. Gemeint ist 2027?Übernehmen'])
    server.fails = {}
    await page.click(page.button('Übernehmen'))
    expect(input('Datum').value).toBe('2027-02-28')
    expect(alerts()).toEqual([])
    await page.click(page.button('Ablegen'))
    await until(() => patches().length === 2)
    expect(patches()[1]).toMatchObject({ date: '2027-02-28', status: 'filed' })
  })

  it('marks the term (set_dates[n]) that was refused', async () => {
    server.fails['PATCH /api/v1/documents/11'] = { status: 422, code: 'invalid_date', values: { field: 'set_dates[0]' } }
    await showInbox()
    await until(() => !!page.button('Ablegen'))
    await page.type(input('Vertrag bis'), '0027-02-28')
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true })))
    await until(() => alerts().length > 0)
    expect(input('Vertrag bis').getAttribute('aria-invalid')).toBe('true')
    expect(input('Datum').getAttribute('aria-invalid')).toBe('false')
    expect(alerts()).toEqual(['Das Jahr 0027 ist wohl ein Tippfehler. Gemeint ist 2027?Übernehmen'])
    await page.click(page.button('Übernehmen'))
    expect(input('Vertrag bis').value).toBe('2027-02-28')
  })
})
