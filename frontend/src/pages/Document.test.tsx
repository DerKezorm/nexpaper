/**
 * One document against a stand-in of the server: the fields saved one by one for somebody who may change them, nothing
 * to change for a reader (only notes, which everybody who sees a document may write), the downloads, the trash, moving,
 * the text page by page, notes (own ones changed, a manager deletes any), versions with their downloads, the history in
 * words, and the places of block B5 that stay hidden until its parts are plugged in.
 */
import { act } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'

import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { forgetPictures } from '../lib/pictures'
import { Page, Server, plain } from '../test/harness'
import { idle, until } from '../test/wait'
import { slots } from '../slots'
import { DocumentPage } from './DocumentPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const tax = { id: 4, key: 'tax', name: 'Steuer', hue: 0, position: 3 }
const base = {
  id: 7, vault_id: 9, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title: 'Einkommensteuerbescheid 2025', sender: { id: 5, name: 'Finanzamt Lindenau' },
  kind: tax, date: '2026-09-17', amount: 128417, currency: 'EUR', tags: ['steuer-2025'], dates: [{ kind: 'keep_until', date: '2036-12-31' }], pages: 6,
  source: 'upload', status: 'filed', added_at: '2026-09-18T18:15:00Z', trashed_at: null, trash_ends_at: null, change_seq: 3, current_version: 1,
  my_right: 'manage', via_share: false, can_share: true, notes: 1, process_error: '', duplicate: null, suggest: {},
}
const vaults = [
  { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 1, size: 1, members: [] },
  { id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'manage', documents: 1, size: 1, members: [] },
]

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>
}
function show(slots = {}) {
  return page.show(
    <>
      <Routes>
        <Route path="dokument/:id" element={<DocumentPage slots={slots} />} />
        <Route path="/" element={<p>archive</p>} />
      </Routes>
      <Where />
    </>,
    '/dokument/7',
  )
}
const where = () => plain(page.box.querySelector('[data-testid="where"]')!.textContent)
const input = (label: string) => page.box.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)

beforeEach(async () => {
  forgetPictures()
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/documents/7': base,
    'GET /api/v1/vaults': vaults,
    'GET /api/v1/kinds?vault_id=9': [tax, { id: 1, key: 'invoice', name: 'Rechnung', hue: 28, position: 0 }],
    'GET /api/v1/senders': [{ name: 'Finanzamt Lindenau', items: [{ id: 5, vault_id: 9 }] }],
    'GET /api/v1/documents/7/versions': [
      { n: 2, current: true, pages: 6, size: 120000, sha256: 'x', created_at: '2026-09-19T08:00:00Z', created_by: { id: 1, name: 'jule', display_name: 'Jule' }, note: 'Seiten gedreht', kind: 'pdf', has_archive: true, has_pages: true, path: 'Haushalt/2026/Finanzamt Lindenau/2026-09-17 Einkommensteuerbescheid 2025.pdf' },
      { n: 1, current: false, pages: 6, size: 100000, sha256: 'y', created_at: '2026-09-18T18:15:00Z', created_by: { id: 1, name: 'jule', display_name: 'Jule' }, note: '', kind: 'pdf', has_archive: true, has_pages: true },
    ],
    'GET /api/v1/documents/7/shares': [],
    'GET /api/v1/documents/7/links': [{ id: 3, document_id: 7, recipient: 'Steuerbüro Kessler', until: '2026-10-31T10:00:00Z', allow_download: true, opened_count: 2, last_opened_at: null, created_at: '2026-09-19T09:00:00Z', created_by: null, revoked_at: null, status: 'active', can_copy: true }],
    'GET /api/v1/people': [{ id: 1, name: 'jule', display_name: 'Jule' }, { id: 3, name: 'lea', display_name: 'Lea' }],
    'GET /api/v1/documents/7/events': [
      { id: 3, at: '2026-09-19T09:47:00Z', action: 'link_opened', by: null, by_link: 'Steuerbüro Kessler', detail: null },
      { id: 2, at: '2026-09-18T18:16:00Z', action: 'changed', by: { id: 1, name: 'jule', display_name: 'Jule' }, by_link: '', detail: { fields: ['status'], status: 'filed' } },
      { id: 1, at: '2026-09-18T18:15:00Z', action: 'created', by: { id: 1, name: 'jule', display_name: 'Jule' }, by_link: '', detail: { source: 'upload' } },
    ],
    'GET /api/v1/documents/7/notes': [
      { id: 1, author: { id: 1, name: 'jule', display_name: 'Jule' }, text: 'Am 3.4. überwiesen', created_at: '2026-09-20T10:00:00Z', updated_at: null, mine: true },
      { id: 2, author: { id: 2, name: 'tom', display_name: 'Tom' }, text: 'Kopie ans Steuerbüro', created_at: '2026-09-21T10:00:00Z', updated_at: null, mine: true },
    ],
    'GET /api/v1/documents/7/versions/1/text': { version: 1, state: 'done', pages: ['Finanzamt Lindenau\nBescheid', '', 'Seite drei'], ocr_pages: 2, languages: 'deu+eng', long_document_pages: 300 },
    'PATCH /api/v1/documents/7': base,
    'POST /api/v1/documents/7/move': { ...base, vault_id: 7 },
    'DELETE /api/v1/documents/7': { ...base, status: 'trash' },
    'POST /api/v1/documents/7/notes': { id: 9, author: { id: 1, name: 'jule', display_name: 'Jule' }, text: 'neu', created_at: '2026-10-01T00:00:00Z', updated_at: null, mine: true },
    'DELETE /api/v1/documents/7/notes/2': 204,
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('a document for somebody who may change it', () => {
  it('saves each field as it is changed, the amount in cents', async () => {
    await show()
    const title = input('Titel')!
    await page.type(title, 'Steuerbescheid 2025')
    title.dispatchEvent(new FocusEvent('focusout', { bubbles: true }))
    await until(() => server.called('PATCH', '/api/v1/documents/7'))
    expect(server.calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ title: 'Steuerbescheid 2025' }])
    const amount = input('Betrag')!
    expect(amount.value).toBe('1.284,17')
    await page.type(amount, '1.300,50')
    amount.dispatchEvent(new FocusEvent('focusout', { bubbles: true }))
    await until(() => server.calls.filter((c) => c.method === 'PATCH').length === 2)
    await page.choose(page.select('Art'), '1')
    await page.click(page.button('steuer-2025 entfernen'))
    expect(server.calls.filter((c) => c.method === 'PATCH').map((c) => c.body).slice(1)).toEqual([{ amount: 130050 }, { kind_id: 1 }, { tags: [] }])
  })

  it('saves the title with Enter, exactly once', async () => {
    await show()
    const title = input('Titel')!
    title.focus()
    await page.type(title, 'Steuerbescheid 2025')
    await act(async () => title.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    await until(() => server.called('PATCH', '/api/v1/documents/7'))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(server.calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ title: 'Steuerbescheid 2025' }])
  })

  it('puts the old title back with Escape and sends nothing', async () => {
    await show()
    const title = input('Titel')!
    title.focus()
    await page.type(title, 'Etwas anderes')
    await act(async () => title.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(input('Titel')!.value).toBe('Einkommensteuerbescheid 2025')
    expect(server.calls.filter((c) => c.method === 'PATCH')).toEqual([])
  })

  it('refuses an empty title without asking the server, puts the old one back and says why', async () => {
    await show()
    const title = input('Titel')!
    title.focus()
    await page.type(title, '   ')
    await act(async () => title.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(server.calls.filter((c) => c.method === 'PATCH')).toEqual([])
    expect(input('Titel')!.value).toBe('Einkommensteuerbescheid 2025')
    expect(page.text).toContain('Ein Titel hat 1 bis 200 Zeichen')
  })

  it('searches the senders with a magnifying glass alone, named and hinted, not with the word', async () => {
    await show()
    const button = page.button('Absender suchen')!
    expect(plain(button.textContent)).toBe('')
    expect(button.getAttribute('title')).toBe('Absender suchen')
  })

  it('makes a kind of the vault from the choice of kinds, and sets it', async () => {
    server.answers['POST /api/v1/kinds'] = { id: 4, key: '', name: 'Garantie', hue: 94, position: 0, vault_id: 9 }
    await show()
    await page.choose(page.select('Art'), '__new')
    expect(server.changes()).toEqual([])
    await page.type(page.box.querySelector<HTMLInputElement>('input[placeholder="zum Beispiel Mietvertrag"]'), 'Garantie')
    await page.click(page.button('Anlegen'))
    expect(server.called('POST', '/api/v1/kinds')!.body).toEqual({ name: 'Garantie', hue: 94, vault_id: 9 })
    expect(server.calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([{ kind_id: 4 }])
    expect(page.button('Anlegen')).toBeUndefined()
  })

  it('refuses an amount that is none, without asking the server', async () => {
    await show()
    const amount = input('Betrag')!
    await page.type(amount, 'viel')
    amount.dispatchEvent(new FocusEvent('focusout', { bubbles: true }))
    await until(() => page.text.includes('Schreib einen Betrag wie 86,40 oder 1.234,56.'))
    expect(server.changes()).toEqual([])
  })

  it('moves it to another vault', async () => {
    await show()
    await page.choose(page.select('Tresor'), '7')
    expect(server.called('POST', '/api/v1/documents/7/move')!.body).toEqual({ vault_id: 7 })
  })

  it('offers the searchable PDF and the original, and puts it in the trash from the menu', async () => {
    await show()
    await page.click(page.button('Herunterladen'))
    expect([...page.box.querySelectorAll('[role="menu"] a')].map((a) => a.getAttribute('href'))).toEqual(['/api/v1/documents/7/versions/1/archive', '/api/v1/documents/7/versions/1/file'])
    await page.click(page.button('Mehr'))
    const items = [...page.box.querySelectorAll('[role="menu"] [role="menuitem"]')].map((item) => plain(item.querySelector('.font-semibold')!.textContent))
    // Without the parts of block B5 there is no new version and no joining.
    expect(items).toEqual(['Text kopieren', 'Verschieben', 'In den Papierkorb'])
    await page.click([...page.box.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((b) => plain(b.textContent)?.includes('In den Papierkorb')))
    // It is asked first, with what happens: 30 days, and it can be brought back. Abbrechen sends nothing.
    expect(server.changes()).toEqual([])
    expect(plain(page.dialog!.textContent)).toContain('liegt 30 Tage im Papierkorb und lässt sich in dieser Zeit zurückholen')
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Mehr'))
    await page.click([...page.box.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find((b) => plain(b.textContent)?.includes('In den Papierkorb')))
    await page.inDialog('In den Papierkorb')
    expect(server.changes()).toEqual(['DELETE /api/v1/documents/7'])
    expect(where()).toBe('/')
  })

  it('shows the places of block B5 once their parts are plugged in', async () => {
    const PageEditor = () => <p>page editor</p>
    const NewVersion = () => <p>new version</p>
    const MergeDialog = () => <p>merge</p>
    const VersionActions = ({ version }: { version: { n: number } }) => <span>bring back {version.n}</span>
    await show({ PageEditor, NewVersion, MergeDialog, VersionActions })
    await page.click(page.button('Seiten bearbeiten'))
    expect(page.text).toContain('page editor')
    await page.click(page.button('Mehr'))
    expect(page.text).toContain('Neue Version hochladen')
    expect(page.text).toContain('Mit anderem zusammenfügen')
    await page.click(page.box.querySelector<HTMLButtonElement>('[role="tab"]:nth-child(4)'))
    expect(page.text).toContain('bring back 1')
  })

  it('has the page tools of block B5 in their places: the editor, the menu, the versions with their state', async () => {
    const jule = { id: 1, name: 'jule', display_name: 'Jule' }
    const row = (n: number, over: Record<string, unknown>) => ({ n, current: false, pages: 6, size: 1000, sha256: 'x', created_at: '2026-09-19T08:00:00Z', created_by: jule, note: '', kind: 'pdf', has_archive: false, has_pages: true, origin: '', from_n: null, state: 'ready', error: '', ...over })
    server.answers['GET /api/v1/documents/7/versions'] = [
      row(4, { origin: 'uploaded', state: 'processing', pages: 0 }),
      row(3, { origin: 'restored', from_n: 1, current: true }),
      row(2, { origin: 'pages', pages: 5 }),
      row(1, { note: 'upload' }),
    ]
    server.answers['POST /api/v1/documents/7/versions/2/restore'] = { ...base, current_version: 5 }
    await show(slots)
    await page.click(page.button('Seiten bearbeiten'))
    expect(page.text).toContain('Seite antippen, dann drehen, verschieben oder löschen.')
    await page.click(page.button('Abbrechen'))
    await page.click(page.button('Mehr'))
    expect(page.text).toContain('Neue Version hochladen')
    expect(page.text).toContain('Mit anderem zusammenfügen')
    await page.click(page.button('Mehr'))
    await page.click(page.box.querySelector<HTMLButtonElement>('[role="tab"]:nth-child(4)'))
    const lines = () => [...page.box.querySelectorAll('[role="tabpanel"] p.font-semibold')].map((p) => plain(p.textContent))
    expect(lines()).toEqual(['Neue Fassung hochgeladenwird gelesen', 'Fassung 1 zurückgeholtaktuell', 'Seiten bearbeitet', 'Hochgeladen im Browser'])
    expect(page.button('Fassung 4 zurückholen')).toBeUndefined()
    await page.click(page.button('Fassung 2 zurückholen'))
    expect(server.called('POST', '/api/v1/documents/7/versions/2/restore')!.body).toEqual({ base_version: 1 })
  })

  it('has no page tools without them', async () => {
    await show()
    expect(page.button('Seiten bearbeiten')).toBeUndefined()
  })

  it('shows who it was shared with by link', async () => {
    await show()
    await until(() => page.box.querySelector('[data-testid="shared-box"]'))
    expect(plain(page.box.querySelector('[data-testid="shared-box"]')!.textContent)).toContain('Link für Steuerbüro Kessler, bis 31.10.2026, 2× geöffnet')
  })
})

describe('where the file lies', () => {
  it('says it below the details, from the folder for documents on', async () => {
    await show()
    await until(() => page.box.querySelector('[data-testid="stored-at"]'))
    expect(plain(page.box.querySelector('[data-testid="stored-at"]')!.textContent)).toBe(' · Ablage: Haushalt/2026/Finanzamt Lindenau/2026-09-17 Einkommensteuerbescheid 2025.pdf')
  })

  it('says the placeholders of the disk in the language of the page, the real path stays in the title', async () => {
    const real = 'Jule/undated/no sender/undated Document.png'
    server.answers['GET /api/v1/documents/7/versions'] = [{ n: 1, current: true, pages: 1, size: 1000, sha256: 'x', created_at: '2026-09-18T18:15:00Z', created_by: null, note: '', kind: 'image', has_archive: false, has_pages: true, path: real }]
    await show()
    await until(() => page.box.querySelector('[data-testid="stored-at"]'))
    const line = page.box.querySelector('[data-testid="stored-at"]')!
    expect(plain(line.textContent)).toBe(' · Ablage: Jule/ohne Datum/ohne Absender/ohne Datum Dokument.png')
    expect(plain(line.getAttribute('title'))).toBe(real)
  })

  it('shows no place for a document that still waits in the inbox: its files move when it is filed', async () => {
    server.answers['GET /api/v1/documents/7'] = { ...base, status: 'inbox' }
    await show()
    await idle()
    expect(page.box.querySelector('[data-testid="stored-at"]')).toBeNull()
  })

  it('keeps a title that turns its text around apart from the page', async () => {
    const turned = `strom ${String.fromCharCode(0x202e)}txt.exe${String.fromCharCode(0x202c)} Rechnung`
    server.answers['GET /api/v1/documents/7'] = { ...base, title: turned, my_right: 'read', can_share: false }
    await show()
    expect(page.box.querySelector('h1 bdi')!.textContent).toBe(turned)
  })
})

describe('a document for a reader', () => {
  beforeEach(() => {
    server.answers['GET /api/v1/documents/7'] = { ...base, my_right: 'read', can_share: false }
  })

  it('does not ask whom it is shared with and shows no list of it', async () => {
    server.answers['GET /api/v1/documents/7/shares'] = [{ user: { id: 3, name: 'lea', display_name: 'Lea' }, right: 'read', created_at: '2026-09-19T09:00:00Z' }]
    await show()
    await idle()
    expect(server.called('GET', '/api/v1/documents/7/shares')).toBeUndefined()
    expect(server.called('GET', '/api/v1/documents/7/links')).toBeUndefined()
    expect(page.box.querySelector('[data-testid="shared-box"]')).toBeNull()
  })

  it('has nothing to change, only notes', async () => {
    await show()
    expect(plain(page.box.querySelector('h1')!.textContent)).toBe('Einkommensteuerbescheid 2025')
    expect(plain(page.box.querySelector('[data-testid="read-only"]')!.textContent)!.trim()).toBe('nur lesen')
    for (const label of ['Titel', 'Absender', 'Betrag', 'Datum']) expect(input(label), label).toBeNull()
    expect(page.select('Tresor')).toBeNull()
    expect(page.button('Teilen')).toBeUndefined()
    await page.click(page.button('Mehr'))
    expect([...page.box.querySelectorAll('[role="menuitem"]')].map((item) => plain(item.querySelector('.font-semibold')!.textContent))).toEqual(['Text kopieren'])
    await page.click(page.box.querySelector<HTMLButtonElement>('[role="tab"]:nth-child(3)'))
    expect(input('Notiz schreiben')).toBeTruthy()
  })
})

describe('the tabs', () => {
  it('show the text page by page, with the languages it was recognised in', async () => {
    await show()
    await page.click(page.box.querySelector<HTMLButtonElement>('[role="tab"]:nth-child(2)'))
    expect(page.text).toContain('Erkannt auf Deutsch, Englisch.')
    expect(page.text).toContain('Seite 1Finanzamt Lindenau')
    expect(page.text).toContain('Auf dieser Seite steht kein Text.')
  })

  it('show the notes, change only the own and let a manager delete any', async () => {
    await show()
    await page.click(page.box.querySelector<HTMLButtonElement>('[role="tab"]:nth-child(3)'))
    expect(page.text).toContain('Am 3.4. überwiesen')
    expect(page.box.querySelectorAll('button[aria-label="Notiz ändern"]')).toHaveLength(1)
    expect(page.box.querySelectorAll('button[aria-label="Notiz löschen"]')).toHaveLength(2)
    await page.type(input('Notiz schreiben'), 'Neue Notiz')
    await page.click(page.button('Notiz speichern'))
    expect(server.called('POST', '/api/v1/documents/7/notes')!.body).toEqual({ text: 'Neue Notiz' })
    await page.click(page.box.querySelectorAll<HTMLButtonElement>('button[aria-label="Notiz löschen"]')[1])
    expect(server.called('DELETE', '/api/v1/documents/7/notes/2')).toBeUndefined()
    await page.inDialog('Notiz löschen')
    expect(server.called('DELETE', '/api/v1/documents/7/notes/2')).toBeTruthy()
  })

  it('list the versions, each with its own download', async () => {
    await show()
    await page.click(page.box.querySelector<HTMLButtonElement>('[role="tab"]:nth-child(4)'))
    expect(page.text).toContain('Seiten gedreht')
    expect(page.text).toContain('aktuell')
    expect([...page.box.querySelectorAll('a[download]')].map((a) => a.getAttribute('href'))).toEqual(['/api/v1/documents/7/versions/2/file', '/api/v1/documents/7/versions/1/file'])
  })

  it('tell the history in words', async () => {
    await show()
    await page.click(page.box.querySelector<HTMLButtonElement>('[role="tab"]:nth-child(5)'))
    const lines = [...page.box.querySelectorAll('[data-testid="history"] li > p:nth-of-type(1)')].map((p) => plain(p.textContent))
    expect(lines).toEqual(['Jemand über den Link für „Steuerbüro Kessler“ hat es geöffnet', 'Jule hat es abgelegt', 'Jule hat es angelegt: hochgeladen im Browser'])
  })
})

describe('a document that is not there', () => {
  it('says so, like one the person may not see', async () => {
    server.fails['GET /api/v1/documents/7'] = { status: 404, code: 'not_found' }
    await show()
    expect(page.text).toContain('Dieses Dokument gibt es nicht oder nicht mehr.')
  })
})

describe('the check of the files on the page of a document', () => {
  it('says nothing while the files are in order', async () => {
    server.answers['GET /api/v1/documents/7'] = { ...base, files_state: '' }
    await show()
    expect(page.box.querySelector('[data-testid="file-notice"]')).toBeNull()
  })

  it('warns of a missing file and says what to do, in German and in English', async () => {
    server.answers['GET /api/v1/documents/7'] = { ...base, files_state: 'missing' }
    await show()
    const notice = page.box.querySelector('[data-testid="file-notice"]')
    expect(notice?.getAttribute('role')).toBe('alert')
    expect(plain(notice?.textContent)).toContain('Eine Datei dieses Dokuments fehlt auf dem Server.')
    expect(plain(notice?.textContent)).toContain('aus der Sicherung deines Servers zurück')
  })

  it('warns of a changed file in English', async () => {
    await changeLanguage('en', false)
    server.answers['GET /api/v1/documents/7'] = { ...base, files_state: 'changed' }
    await show()
    expect(plain(page.box.querySelector('[data-testid="file-notice"]')?.textContent)).toContain('A file of this document is not the same any more.')
  })

  it('tells the lines of the check in the history, by nexpaper itself', async () => {
    server.answers['GET /api/v1/documents/7/events'] = [
      { id: 3, at: '2026-10-10T03:12:00Z', action: 'files_whole', by: null, by_link: '', detail: null },
      { id: 2, at: '2026-10-09T03:12:00Z', action: 'files_changed', by: null, by_link: '', detail: null },
      { id: 1, at: '2026-10-08T03:12:00Z', action: 'files_missing', by: null, by_link: '', detail: null },
    ]
    await show()
    await page.click(page.box.querySelector<HTMLButtonElement>('[role="tab"]:nth-child(5)'))
    const lines = [...page.box.querySelectorAll('[data-testid="history"] li > p:nth-of-type(1)')].map((p) => plain(p.textContent))
    expect(lines).toEqual([
      'nexpaper fand beim Prüfen der Dateien alles wieder in Ordnung',
      'nexpaper fand beim Prüfen der Dateien eine veränderte Datei',
      'nexpaper fand beim Prüfen der Dateien eine fehlende Datei',
    ])
  })
})
