/**
 * The small helpers of K1 against a stand-in of the server: the dialog "Überweisen" (where each part comes from, the code
 * asked for with a body after a pause, nothing for a purpose the standard does not take, "Als bezahlt merken"), the note
 * on a sender at the document and under Ordnung (deleting a sender kept for its note asks first), the pin at the
 * document, in the table and on top of the archive's overview, the card of the quick upload, and the follow-up with its
 * sentence at the document and on the deadlines page.
 */
import { act } from 'react'
import { Route, Routes } from 'react-router-dom'

import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { forgetPictures } from '../lib/pictures'
import { forgetSaved } from '../lib/saved'
import { Page, Server, plain } from '../test/harness'
import { idle, until } from '../test/wait'
import { ArchivePage } from './ArchivePage'
import { DeadlinesPage } from './DeadlinesPage'
import { DocumentPage } from './DocumentPage'
import { OrderPage } from './OrderPage'
import { QuickPage } from './QuickPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'member', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const IBAN = 'DE12120300000000004711'
const OTHER = 'DE85120300000000004712'
const kind = { id: 1, key: 'invoice', name: 'Rechnung', hue: 28, position: 0 }
function doc(extra: Record<string, unknown> = {}) {
  return {
    id: 7, vault_id: 9, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title: 'Stromrechnung Oktober', sender: { id: 5, name: 'Stadtwerke Lindenau' },
    kind, date: '2026-10-01', amount: 8640, currency: 'EUR', tags: [], dates: [{ kind: 'due', date: '2026-10-20' }], pages: 1, source: 'upload',
    status: 'filed', added_at: '2026-10-01T08:00:00Z', trashed_at: null, trash_ends_at: null, change_seq: 3, current_version: 1, my_right: 'edit',
    via_share: false, can_share: false, notes: 0, process_error: '', duplicate: null, suggest: {}, pinned: false, sender_memo: '', ...extra,
  }
}
const info = (extra: Record<string, unknown> = {}) => ({
  ready: true, missing: [], recipient: 'Stadtwerke Lindenau', recipient_origin: 'sender', ibans: [{ iban: IBAN, origin: 'text' }], amount: 8640,
  amount_origin: 'document', currency: 'EUR', purpose: 'R-2026-17', purpose_origin: 'text', purpose_max: 140, ...extra,
})
const vaults = [
  { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 1, size: 1, members: [] },
  { id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'edit', documents: 1, size: 1, members: [] },
]
const CODE = 'POST /api/v1/documents/7/transfer/code'
const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'

function showDocument() {
  return page.show(
    <Routes>
      <Route path="dokument/:id" element={<DocumentPage slots={{}} />} />
    </Routes>,
    '/dokument/7',
  )
}
const codeCalls = () => server.calls.filter((c) => `${c.method} ${c.url}` === CODE)
async function type(field: HTMLInputElement | HTMLTextAreaElement, value: string) {
  await page.type(field, value)
}

beforeEach(async () => {
  forgetPictures()
  forgetSaved()
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/documents/7': doc(),
    'GET /api/v1/documents/7/transfer': info(),
    [CODE]: SVG,
    'GET /api/v1/vaults': vaults,
    'GET /api/v1/kinds?vault_id=9': [kind],
    'GET /api/v1/senders': [],
    'GET /api/v1/documents/7/versions': [],
    'POST /api/v1/documents/7/dates/due/done': doc({ dates: [{ kind: 'due', date: '2026-10-20', done: { at: '2026-10-05T10:00:00Z', by: null } }] }),
    'PUT /api/v1/documents/7/pin': { pinned: true, count: 1, max: 20 },
    'DELETE /api/v1/documents/7/pin': 204,
    'PUT /api/v1/senders/5/memo': { id: 5, name: 'Stadtwerke Lindenau', vault_id: 9, memo: 'Kunde 4711\nTelefon 0000' },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

// --- Überweisen ---------------------------------------------------------------------------------------------------

describe('the transfer code', () => {
  it('opens only when the document gives a transfer, and says where each part comes from', async () => {
    server.answers['GET /api/v1/documents/7/transfer'] = info({ ready: false, missing: ['iban'], ibans: [] })
    await showDocument()
    expect(page.box.querySelector('[data-testid="transfer-button"]')).toBeNull()
    page.close()
    server.answers['GET /api/v1/documents/7/transfer'] = info()
    await showDocument()
    await page.click(page.box.querySelector<HTMLButtonElement>('[data-testid="transfer-button"]'))
    const dialog = page.dialog!
    expect(plain(dialog.textContent)).toContain('Stadtwerke Lindenau')
    expect(plain(dialog.textContent)).toContain('DE12 1203 0000 0000 0047 11')
    expect([...dialog.querySelectorAll('[data-testid="origin-text"]')].map((x) => plain(x.textContent))).toEqual([
      'aus dem Text gelesen, bitte mit dem Dokument vergleichen', 'aus dem Text gelesen, bitte mit dem Dokument vergleichen'])
    expect(plain(dialog.textContent)).toContain('In der Banking-App'.length ? 'Banking-App' : '')
    // The code is asked for after a pause, with the IBAN and the purpose in the body, never in the address.
    await until(() => codeCalls().length > 0, 'the code')
    expect(codeCalls()[0].body).toEqual({ iban: IBAN, amount: 8640, purpose: 'R-2026-17' })
    expect(codeCalls()[0].url).not.toContain(IBAN)
    await until(() => dialog.querySelector('img[data-testid="transfer-code"]'))
  })

  it('names the e-invoice as the origin, and lets the person choose between two IBANs', async () => {
    server.answers['GET /api/v1/documents/7/transfer'] = info({ recipient_origin: 'einvoice', ibans: [{ iban: IBAN, origin: 'einvoice' }, { iban: OTHER, origin: 'text' }], amount_origin: 'einvoice', purpose_origin: 'einvoice' })
    await showDocument()
    await page.click(page.box.querySelector<HTMLButtonElement>('[data-testid="transfer-button"]'))
    const dialog = page.dialog!
    expect(dialog.querySelectorAll('[data-testid="origin-einvoice"]').length).toBeGreaterThanOrEqual(3)
    const radios = [...dialog.querySelectorAll<HTMLInputElement>('input[type="radio"]')]
    expect(radios).toHaveLength(2)
    await until(() => codeCalls().length === 1)
    await act(async () => radios[1].click())
    await until(() => codeCalls().length === 2)
    expect(codeCalls()[1].body).toEqual({ iban: OTHER, amount: 8640, purpose: 'R-2026-17' })
    expect(dialog.querySelector('[data-testid="origin-text"]')).toBeTruthy()
  })

  it('draws the code anew after the typing pauses, and never for a purpose the standard does not take', async () => {
    await showDocument()
    await page.click(page.box.querySelector<HTMLButtonElement>('[data-testid="transfer-button"]'))
    await until(() => codeCalls().length === 1)
    const purpose = page.dialog!.querySelector<HTMLInputElement>('input[aria-label="Verwendungszweck"]')!
    await type(purpose, 'R-2026-17 <script>')
    await new Promise((resolve) => setTimeout(resolve, 600))
    await idle()
    expect(codeCalls()).toHaveLength(1)
    expect(plain(page.dialog!.textContent)).toContain("Im Verwendungszweck gehen Buchstaben")
    await type(purpose, 'Rechnung R-2026-17 Müller')
    await until(() => codeCalls().length === 2)
    expect(codeCalls()[1].body).toEqual({ iban: IBAN, amount: 8640, purpose: 'Rechnung R-2026-17 Müller' })
    expect(plain(page.dialog!.textContent)).toContain('von dir geändert')
  })

  it('marks the due date paid, only for somebody who may change the document', async () => {
    await showDocument()
    await page.click(page.box.querySelector<HTMLButtonElement>('[data-testid="transfer-button"]'))
    await page.inDialog('Als bezahlt merken')
    expect(server.called('POST', '/api/v1/documents/7/dates/due/done')).toBeTruthy()
    expect(plain(page.dialog!.textContent)).toContain('Als bezahlt gemerkt')
    page.close()
    server.answers['GET /api/v1/documents/7'] = doc({ my_right: 'read' })
    await showDocument()
    await page.click(page.box.querySelector<HTMLButtonElement>('[data-testid="transfer-button"]'))
    expect(page.button('Als bezahlt merken', page.dialog!)).toBeUndefined()
  })

  it('says a server refusal in words', async () => {
    server.fails[CODE] = { status: 422, code: 'unknown_iban' }
    await showDocument()
    await page.click(page.box.querySelector<HTMLButtonElement>('[data-testid="transfer-button"]'))
    await until(() => page.dialog!.querySelector('[role="alert"]'))
    expect(plain(page.dialog!.textContent)).toContain('Diese IBAN steht nicht im Dokument.')
  })
})

// --- Merkzettel --------------------------------------------------------------------------------------------------

describe('the note on a sender', () => {
  it('stands under the sender and an editor changes it with the pencil', async () => {
    server.answers['GET /api/v1/documents/7'] = doc({ sender_memo: 'Kunde 4711' })
    await showDocument()
    expect(plain(page.box.querySelector('[data-testid="sender-memo"]')!.textContent)).toContain('Kunde 4711')
    await page.click(page.button('Merkzettel zu Stadtwerke Lindenau bearbeiten'))
    const area = page.dialog!.querySelector('textarea')!
    await type(area, 'Kunde 4711\nTelefon 0000')
    await page.inDialog('Speichern')
    expect(server.called('PUT', '/api/v1/senders/5/memo')?.body).toEqual({ memo: 'Kunde 4711\nTelefon 0000' })
    expect(plain(page.box.querySelector('[data-testid="sender-memo"]')!.textContent)).toContain('Telefon 0000')
  })

  it('offers to write one, and shows nothing through a share or to somebody who may only read it empty', async () => {
    await showDocument()
    expect(page.button('Merkzettel anlegen')).toBeTruthy()
    page.close()
    server.answers['GET /api/v1/documents/7'] = doc({ via_share: true, sender_memo: null })
    await showDocument()
    expect(page.box.querySelector('[data-testid="sender-memo"]')).toBeNull()
    page.close()
    server.answers['GET /api/v1/vaults'] = [vaults[0], { ...vaults[1], my_right: 'read' }]
    server.answers['GET /api/v1/documents/7'] = doc({ my_right: 'read', sender_memo: 'Kunde 4711' })
    await showDocument()
    expect(plain(page.box.querySelector('[data-testid="sender-memo"]')!.textContent)).toContain('Kunde 4711')
    expect(page.button('Merkzettel zu Stadtwerke Lindenau bearbeiten')).toBeUndefined()
  })
})

describe('the note under Ordnung', () => {
  const senders = 'GET /api/v1/order/senders?order=name&limit=100'
  beforeEach(() => {
    server.answers[senders] = {
      items: [
        { id: 5, name: 'Stadtwerke Lindenau', vault_id: 9, right: 'edit', documents: 0, in_trash: 0, can_change: false, memo: 'Kunde 4711', can_edit_memo: true },
        { id: 6, name: 'Hansa', vault_id: 9, right: 'edit', documents: 2, in_trash: 0, can_change: false, memo: '', can_edit_memo: true },
      ],
      total: 2,
    }
    server.answers['DELETE /api/v1/senders/5'] = 204
  })

  it('shows the note, why a sender without documents stays, and deletes it only after a yes', async () => {
    await page.show(<OrderPage />, '/ordnung')
    const text = page.text
    expect(text).toContain('Kunde 4711')
    expect(text).toContain('Bleibt wegen des Merkzettels stehen, auch ohne Dokument.')
    expect(page.button('Merkzettel anlegen')).toBeTruthy()
    await page.click(page.button('Löschen: Stadtwerke Lindenau'))
    expect(plain(page.dialog!.textContent)).toContain('Der Merkzettel geht mit.')
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Löschen: Stadtwerke Lindenau'))
    await page.inDialog('Absender löschen')
    expect(server.changes()).toEqual(['DELETE /api/v1/senders/5'])
    // A sender with documents is not the editor's to delete.
    expect(page.button('Löschen: Hansa')).toBeUndefined()
  })
})

// --- Anheften ----------------------------------------------------------------------------------------------------

describe('pinning', () => {
  it('pins and unpins at the document, for oneself', async () => {
    await showDocument()
    const button = () => page.box.querySelector<HTMLButtonElement>('[data-testid="pin-button"]')!
    expect(button().getAttribute('aria-pressed')).toBe('false')
    await page.click(button())
    expect(server.changes()).toEqual(['PUT /api/v1/documents/7/pin'])
    expect(button().getAttribute('aria-pressed')).toBe('true')
    expect(plain(button().textContent).trim()).toBe('Angeheftet')
    await page.click(button())
    expect(server.changes()).toEqual(['PUT /api/v1/documents/7/pin', 'DELETE /api/v1/documents/7/pin'])
  })

  it('says kindly that twenty is the most', async () => {
    server.fails['PUT /api/v1/documents/7/pin'] = { status: 409, code: 'too_many_pins', values: { max: 20 } }
    await showDocument()
    await page.click(page.box.querySelector<HTMLButtonElement>('[data-testid="pin-button"]'))
    expect(page.text).toContain('Du hast schon 20 Dokumente angeheftet. Löse erst eines, dann passt dieses dazu.')
  })

  it('stands on top of the archive overview with the pin in the row, only with something pinned', async () => {
    const WHOLE = 'GET /api/v1/search/overview?status=filed'
    const NEWEST = 'GET /api/v1/search?q=&status=filed&limit=6'
    const overview = { total: 1, senders: [], kinds: [], years: [], tags: [] }
    server.answers = {
      ...server.answers,
      'GET /api/v1/kinds': [kind],
      'GET /api/v1/people': [],
      'GET /api/v1/tags': [],
      'GET /api/v1/saved-searches': [],
      'GET /api/v1/documents?status=filed&via_share=true&limit=1': { items: [], next: null },
      [WHOLE]: overview,
      [NEWEST]: { items: [{ document: doc({ id: 8, title: 'Brief' }), title_marks: [], sender_marks: [], excerpt: null }], total: 1, next: null, understood: {} },
      'GET /api/v1/pins': { items: [], max: 20 },
    }
    await page.show(<ArchivePage slots={{}} />, '/')
    expect(page.box.querySelector('[data-testid="pinned-section"]')).toBeNull()
    page.close()
    server.answers['GET /api/v1/pins'] = { items: [doc({ pinned: true })], max: 20 }
    await page.show(<ArchivePage slots={{}} />, '/')
    const pinned = page.box.querySelector('[data-testid="pinned-section"]')!
    expect(plain(pinned.textContent)).toContain('Angeheftet')
    expect(plain(pinned.textContent)).toContain('Stromrechnung Oktober')
    expect(pinned.querySelector('[data-testid="pinned"]')?.getAttribute('aria-label')).toBe('angeheftet')
  })

  it('shows the first six on the phone, each a tap away', async () => {
    const eight = Array.from({ length: 8 }, (_, n) => doc({ id: 20 + n, title: `Angeheftet ${n}` }))
    server.answers['GET /api/v1/quick'] = { recent: [], inbox: 0, vaults: [], target_vault_id: null }
    server.answers['GET /api/v1/pins?limit=6'] = { items: eight, max: 20 }
    const { Uploader } = await import('../lib/uploader')
    const { UploadProvider } = await import('../state/uploads')
    await page.show(
      <UploadProvider uploader={new Uploader()}>
        <QuickPage />
      </UploadProvider>,
      '/schnell',
    )
    const card = page.box.querySelector('[data-testid="quick-pinned"]')!
    const links = [...card.querySelectorAll('a')]
    expect(links).toHaveLength(6)
    expect(links[0].getAttribute('href')).toBe('/dokument/20')
  })
})

// --- Wiedervorlage -----------------------------------------------------------------------------------------------

describe('the follow-up', () => {
  it('is set at the document with its sentence, only what changed is sent', async () => {
    server.answers['GET /api/v1/documents/7'] = doc({ dates: [] })
    server.answers['PATCH /api/v1/documents/7'] = doc({ dates: [{ kind: 'follow_up', date: '2026-11-01', note: '' }] })
    await showDocument()
    await page.click(page.button('Termin hinzufügen') ?? [...page.box.querySelectorAll('button')].find((b) => plain(b.textContent).includes('Termin')))
    await page.click([...page.box.querySelectorAll('button')].find((b) => plain(b.textContent) === 'Wiedervorlage'))
    const first = server.calls.filter((c) => c.method === 'PATCH')
    expect(first).toHaveLength(1)
    expect((first[0].body as { set_dates: { kind: string; note: string }[] }).set_dates[0]).toMatchObject({ kind: 'follow_up', note: '' })
    const sentence = await until(() => page.box.querySelector<HTMLInputElement>('input[aria-label="Was dann?"]'))
    await type(sentence, 'nachfragen,   ob erstattet')
    await act(async () => sentence.dispatchEvent(new FocusEvent('focusout', { bubbles: true })))
    await idle()
    const patches = server.calls.filter((c) => c.method === 'PATCH')
    expect(patches.at(-1)!.body).toEqual({ set_dates: [{ kind: 'follow_up', note: 'nachfragen, ob erstattet' }] })
    expect(page.text).toContain('nie in der Erinnerung')
  })

  it('stands on the deadlines page with its sentence and its own filter', async () => {
    const item = {
      document_id: 7, title: 'Physiotherapie', status: 'filed', vault_id: 9, via_share: false, sender: null, amount: null, currency: 'EUR', kind: 'follow_up', what: 'follow_up',
      date: '2026-10-12', days: 2, end: '2026-10-12', notice: null, renew_months: null, renews_to: null, missed: null, done: null, snoozed_until: null, note: 'nachfragen, ob erstattet',
    }
    const list = { today: '2026-10-10', soon_days: 14, overdue: { total: 0, items: [] }, soon: { total: 1, items: [item] }, later: { total: 0, items: [] }, done: { total: 0, items: [] }, counts: { 9: 1 }, shared: 0 }
    server.answers['GET /api/v1/deadlines?done=true'] = list
    server.answers['GET /api/v1/deadlines?done=true&what=follow_up'] = list
    server.answers['GET /api/v1/me/reminders'] = { muted: [], muted_shared: false }
    server.answers['GET /api/v1/keeping?limit=200'] = { items: [], total: 0 }
    await page.show(<DeadlinesPage />, '/fristen')
    expect(plain(page.box.querySelector('[data-testid="follow-up-sentence"]')!.textContent)).toBe('nachfragen, ob erstattet')
    expect(page.text).toContain('Wiedervorlage am')
    await page.click([...page.box.querySelectorAll('button')].find((b) => plain(b.textContent) === 'Wiedervorlage'))
    expect(server.called('GET', '/api/v1/deadlines?done=true&what=follow_up')).toBeTruthy()
  })
})
