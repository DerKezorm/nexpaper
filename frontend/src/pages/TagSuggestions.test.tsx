/**
 * The tags offered while a tag is typed come from the vault of the document (the vault it ends up in), on the document
 * page, in the inbox, and for several documents at once; a name that only other vaults have is never offered.
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
function doc(id: number, vault: number, status: string, extra: Record<string, unknown> = {}) {
  return {
    id, vault_id: vault, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title: `Rechnung ${id}`, sender: null, kind: invoice, date: '2026-10-06',
    amount: 22491, currency: 'EUR', tags: ['haus'], dates: [], pages: 1, source: 'upload', status, added_at: `2026-10-08T07:${40 + (id % 10)}:00Z`, trashed_at: null,
    trash_ends_at: null, change_seq: id, current_version: 1, my_right: 'manage', via_share: false, can_share: true, notes: 0, process_error: '', duplicate: null,
    suggest: {}, ...extra,
  }
}
const vaults = [
  { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 1, size: 1, members: [] },
  { id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'manage', documents: 1, size: 1, members: [] },
]
// The vault 9 has Strom and Haus; "Geheim" belongs to the vault 7 only.
const tagsOfHaushalt = [
  { name: 'Strom', items: [{ id: 1, vault_id: 9 }] },
  { name: 'haus', items: [{ id: 2, vault_id: 9 }] },
]
const tagsOfJule = [{ name: 'Geheim', items: [{ id: 3, vault_id: 7 }] }]

const options = () => [...page.box.querySelectorAll('[role="option"]')].map((o) => plain(o.textContent))
const patches = () => server.calls.filter((c) => c.method === 'PATCH').map((c) => c.body)
const tagField = (label = 'Tag hinzufügen') => page.box.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!
const asked = () => server.calls.filter((c) => c.url.startsWith('/api/v1/tags')).map((c) => c.url)

beforeEach(async () => {
  forgetPictures()
  await changeLanguage('de', false)
  server.answers = {
    'GET /api/v1/documents/7': doc(7, 9, 'filed'),
    'GET /api/v1/vaults': vaults,
    'GET /api/v1/kinds?vault_id=9': [invoice],
    'GET /api/v1/kinds?vault_id=7': [invoice],
    'GET /api/v1/kinds': [invoice],
    'GET /api/v1/senders': [],
    'GET /api/v1/tags?vault_id=9': tagsOfHaushalt,
    'GET /api/v1/tags?vault_id=7': tagsOfJule,
    'GET /api/v1/documents/7/versions': [],
    'GET /api/v1/documents/7/events': [],
    'PATCH /api/v1/documents/7': doc(7, 9, 'filed', { tags: ['haus', 'Strom'] }),
    [INBOX]: inboxOf([doc(11, 9, 'inbox'), doc(12, 9, 'inbox')]),
    'GET /api/v1/documents/11/origin': { source: 'upload', unknown: false, sender: '', subject: '', folder: '', file: '', at: null },
    'PATCH /api/v1/documents/11': doc(11, 9, 'filed'),
    'POST /api/v1/documents/11/move': doc(11, 7, 'inbox'),
    'POST /api/v1/inbox/file': { filed: [11, 12], failed: [] },
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
const showInbox = (at = '/eingang/11') =>
  page.show(
    <Routes>
      <Route path="eingang/:id" element={<InboxPage />} />
      <Route path="eingang" element={<InboxPage />} />
    </Routes>,
    at,
  )

describe('the tags on the document page', () => {
  it('come from the vault of the document, and a look-alike is named', async () => {
    await showDocument()
    await until(() => asked().length > 0)
    expect(asked()).toEqual(['/api/v1/tags?vault_id=9'])
    await act(async () => tagField().focus())
    await page.type(tagField(), 'Stromvertrag')
    expect(options()).toEqual(['Meintest du Strom?', '„Stromvertrag“ neu anlegen'])
    await page.click(page.box.querySelectorAll<HTMLElement>('[role="option"]')[0])
    await until(() => patches().length === 1)
    expect(patches()).toEqual([{ tags: ['haus', 'Strom'] }])
  })

  it('never offers a name that only another vault has', async () => {
    // Even if the server's answer held it: only what the vault of the document has counts.
    server.answers['GET /api/v1/tags?vault_id=9'] = [...tagsOfHaushalt, ...tagsOfJule]
    await showDocument()
    await until(() => asked().length > 0)
    await act(async () => tagField().focus())
    await page.type(tagField(), 'Geheim')
    expect(options()).toEqual(['„Geheim“ neu anlegen'])
  })

  it('asks for no tags of somebody who may not change the document', async () => {
    server.answers['GET /api/v1/documents/7'] = doc(7, 9, 'filed', { my_right: 'read' })
    await showDocument()
    await until(() => page.text.includes('Rechnung 7'))
    expect(asked()).toEqual([])
    expect(page.box.querySelector('input[aria-label="Tag hinzufügen"]')).toBeNull()
  })
})

describe('the tags in the inbox', () => {
  it('come from the vault the document ends up in, also after it is changed', async () => {
    await showInbox()
    await until(() => asked().includes('/api/v1/tags?vault_id=9'))
    await act(async () => tagField().focus())
    await page.type(tagField(), 'stro')
    expect(options()).toEqual(['Strom', '„stro“ neu anlegen'])
    await page.type(tagField(), '')
    await page.choose(page.select('Tresor'), '7')
    await until(() => asked().includes('/api/v1/tags?vault_id=7'))
    await act(async () => tagField().focus())
    await page.type(tagField(), 'stro')
    expect(options()).toEqual(['„stro“ neu anlegen'])
    await page.type(tagField(), 'gehe')
    expect(options()).toEqual(['Geheim', '„gehe“ neu anlegen'])
  })

  it('files with the tag that was chosen', async () => {
    await showInbox()
    await until(() => asked().length > 0)
    await act(async () => tagField().focus())
    await page.type(tagField(), 'Stromvertrag')
    await page.click(page.box.querySelectorAll<HTMLElement>('[role="option"]')[0])
    await page.click(page.button('Ablegen'))
    await until(() => patches().length === 1)
    expect(patches()[0]).toMatchObject({ tags: ['haus', 'Strom'], status: 'filed' })
  })
})

describe('the tag for several documents at once', () => {
  const bar = () => page.box.querySelector('[role="region"]')!

  it('is chosen among the tags of the vault they are in, and files with it', async () => {
    await showInbox('/eingang')
    await page.click(page.button('Auswählen'))
    await page.click(page.box.querySelector<HTMLElement>('input[aria-label="Rechnung 11 auswählen"]'))
    await page.click(page.box.querySelector<HTMLElement>('input[aria-label="Rechnung 12 auswählen"]'))
    await until(() => asked().includes('/api/v1/tags?vault_id=9'))
    const field = bar().querySelector<HTMLInputElement>('input[aria-label="Tag dazu"]')!
    await act(async () => field.focus())
    await page.type(field, 'Stromvertrag')
    expect(options()).toEqual(['Meintest du Strom?', '„Stromvertrag“ neu anlegen'])
    await page.click(page.box.querySelectorAll<HTMLElement>('[role="option"]')[0])
    expect(plain(bar().textContent)).toContain('Strom')
    await page.click(page.button('2 ablegen'))
    expect(server.called('POST', '/api/v1/inbox/file')!.body).toEqual({ ids: [11, 12], add_tags: ['Strom'] })
  })

  it('follows the vault they are sent to', async () => {
    await showInbox('/eingang')
    await page.click(page.button('Auswählen'))
    await page.click(page.box.querySelector<HTMLElement>('input[aria-label="Rechnung 11 auswählen"]'))
    await page.choose(bar().querySelector<HTMLSelectElement>('select[aria-label="Tresor"]'), '7')
    await until(() => asked().includes('/api/v1/tags?vault_id=7'))
    const field = bar().querySelector<HTMLInputElement>('input[aria-label="Tag dazu"]')!
    await act(async () => field.focus())
    await page.type(field, 'gehe')
    expect(options()).toEqual(['Geheim', '„gehe“ neu anlegen'])
  })
})
