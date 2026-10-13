/**
 * Sorting in (B6) against a stand-in of the server: the e-invoice in the inbox (the note, the mark in the list, where
 * the due date came from), "Als Regel merken" after choosing a kind or a vault, the box and the XML in the document's
 * download menu, the rules card (as sentences, on and off, order, a new rule, the operator's for the whole server),
 * the kinds card, the switch for personal vaults on the AI card, and the history line of the proposals.
 */
import { Route, Routes } from 'react-router-dom'

import type { DocumentEvent, Me } from '../api/client'
import i18n, { changeLanguage } from '../i18n'
import { eventWhat } from '../lib/events'
import { forgetPictures } from '../lib/pictures'
import { INBOX, Page, Server, inboxOf, plain } from '../test/harness'
import { idle, until } from '../test/wait'
import { DocumentPage } from './DocumentPage'
import { InboxPage } from './InboxPage'
import { AiCard } from './settings/AiCard'
import { KindsCard, RulesCard } from './settings/SortingCards'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const invoiceKind = { id: 1, key: 'invoice', name: 'Rechnung', hue: 28, position: 0 }
const health = { id: 2, key: 'health', name: 'Gesundheit', hue: 340, position: 1 }
const vaults = [
  { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 1, size: 1, members: [] },
  { id: 9, name: 'Ferienwohnung', icon: 'sun', personal_of: null, my_right: 'manage', documents: 1, size: 1, members: [] },
]
const heating = {
  id: 11, vault_id: 9, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title: 'Rechnung 2026-0473', sender: { id: 5, name: 'Elektro Brandt GmbH' },
  kind: invoiceKind, date: '2026-10-06', amount: 22491, currency: 'EUR', tags: [], dates: [{ kind: 'due', date: '2026-10-20' }], pages: 1, source: 'mail',
  status: 'inbox', added_at: '2026-10-08T07:42:00Z', trashed_at: null, trash_ends_at: null, change_seq: 1, current_version: 1, my_right: 'manage',
  via_share: false, can_share: true, notes: 0, process_error: '', duplicate: null, einvoice: 'ZUGFeRD (EN 16931)',
  suggest: { title: 'einvoice', sender: 'einvoice', kind: 'einvoice', date: 'einvoice', amount: 'einvoice', dates: 'einvoice', vault: 'rule' },
}
const invoice = {
  version: 1, xml_only: false, format: 'ZUGFeRD (EN 16931)', number: '2026-0473', issued: '2026-10-06', due: '2026-10-20', seller: 'Elektro Brandt GmbH',
  seller_vat: 'DE987654321', buyer: 'Ferienwohnung Lindenhof', buyer_ref: 'LINDENHOF-12', iban: 'DE02120300000000202051', currency: 'EUR', net: 18900,
  tax: 3591, gross: 22491, payable: 22491, credit_note: false,
  lines: [{ text: 'Wartung Gasbrennwerttherme', quantity: '1', unit: 'C62', price: 12900, total: 12900 }, { text: 'Anfahrt', quantity: '1', unit: 'C62', price: 3500, total: 3500 }],
}

beforeEach(async () => {
  forgetPictures()
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    [INBOX]: inboxOf([heating]),
    'GET /api/v1/vaults': vaults,
    'GET /api/v1/kinds?vault_id=9': [invoiceKind, health],
    'GET /api/v1/kinds': [invoiceKind, health],
    'GET /api/v1/senders': [],
    'GET /api/v1/documents/11': { ...heating, status: 'filed' },
    'GET /api/v1/documents/11/einvoice': invoice,
    'GET /api/v1/documents/11/versions/1/text': { version: 1, state: 'done', pages: ['Rechnung'], ocr_pages: 0, languages: '', long_document_pages: 300 },
    'POST /api/v1/documents/11/rule': { id: 3 },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

function inbox(at = '/eingang/11') {
  return page.show(
    <Routes>
      <Route path="eingang/:id" element={<InboxPage />} />
    </Routes>,
    at,
  )
}

describe('the e-invoice and the rules in the inbox', () => {
  it('says that the fields come from the e-invoice, and marks it in the list', async () => {
    await inbox()
    await until(() => page.box.querySelector('[data-testid="einvoice-notice"]'))
    const notice = plain(page.box.querySelector('[data-testid="einvoice-notice"]')!.textContent)
    expect(notice).toContain('E-Rechnung erkannt')
    expect(notice).toContain('ZUGFeRD (EN 16931). Absender, Datum, Betrag und Rechnungsnummer stammen aus den Daten der Rechnung')
    expect(notice).toContain('Rechnungsnummer 2026-0473, zahlbar bis 20.10.2026.')
    expect(page.box.querySelector('ul[aria-label="Eingang"] [aria-label="E-Rechnung"]')).toBeTruthy()
    // Every field says where it came from, the due date too.
    expect(page.text.match(/E-Rechnung/g)!.length).toBeGreaterThanOrEqual(6)
  })

  it('offers a rule when a kind is chosen, and makes it with the sender of the field', async () => {
    await inbox()
    await page.click(page.box.querySelector<HTMLButtonElement>('[role="radio"][aria-checked="false"]'))
    const offer = await until(() => page.box.querySelector('[data-testid="remember"]'))
    expect(plain(offer.textContent)).toContain('Immer so? Absender „Elektro Brandt GmbH“ ist immer Gesundheit.')
    await page.click(page.button('Als Regel merken'))
    expect(server.changes()).toEqual(['POST /api/v1/documents/11/rule'])
    expect(server.called('POST', '/api/v1/documents/11/rule')!.body).toEqual({ kind_id: 2 })
    expect(page.text).toContain('Regel angelegt. Sie gilt ab dem nächsten Dokument.')
  })

  it('saves a sender typed in the field before the rule names it, and "Nur diesmal" makes none', async () => {
    await inbox()
    await page.type(page.box.querySelector<HTMLInputElement>('input[aria-label="Absender"]'), 'Brandt Haustechnik')
    await page.choose(page.select('Tresor'), '7')
    expect(plain(page.box.querySelector('[data-testid="remember"]')!.textContent)).toContain('Absender „Brandt Haustechnik“ kommt immer nach Jule (persönlich)')
    await page.click(page.button('Als Regel merken'))
    expect(server.changes()).toEqual(['PATCH /api/v1/documents/11', 'POST /api/v1/documents/11/rule'])
    expect(server.called('PATCH', '/api/v1/documents/11')!.body).toEqual({ sender: 'Brandt Haustechnik' })
    expect(server.called('POST', '/api/v1/documents/11/rule')!.body).toEqual({ vault_id: 7 })
    page.close()
    server.install()
    await inbox()
    await page.choose(page.select('Tresor'), '7')
    await page.click(page.button('Nur diesmal'))
    expect(page.box.querySelector('[data-testid="remember"]')).toBeNull()
    expect(server.changes()).toEqual([])
  })

  it('offers no rule to somebody who does not manage the vault', async () => {
    server.answers[INBOX] = inboxOf([{ ...heating, my_right: 'edit' }])
    await inbox()
    await page.click(page.box.querySelector<HTMLButtonElement>('[role="radio"][aria-checked="false"]'))
    expect(page.box.querySelector('[data-testid="remember"]')).toBeNull()
  })
})

describe('the e-invoice on the document page', () => {
  it('shows the box and offers the XML', async () => {
    server.answers['GET /api/v1/documents/11/versions'] = [{ n: 1, current: true, pages: 1, size: 1, sha256: 'x', created_at: '2026-10-08T07:42:00Z', created_by: null, note: '', kind: 'pdf', has_archive: true, has_pages: true, path: '' }]
    server.answers['GET /api/v1/documents/11/events'] = []
    server.answers['GET /api/v1/documents/11/notes'] = []
    server.answers['GET /api/v1/documents/11/shares'] = []
    server.answers['GET /api/v1/documents/11/links'] = []
    server.answers['GET /api/v1/people'] = []
    await page.show(
      <Routes>
        <Route path="dokument/:id" element={<DocumentPage slots={{}} />} />
      </Routes>,
      '/dokument/11',
    )
    const box = await until(() => page.box.querySelector('[data-testid="einvoice-box"]'))
    const text = plain(box.textContent)
    for (const part of ['E-Rechnung · ZUGFeRD (EN 16931)', 'Rechnungsnummer2026-0473', 'Leitweg-IDLINDENHOF-12', 'Zahlbar bis20.10.2026', 'DE02 1203 0000 0000 2020 51', '1 × Wartung Gasbrennwerttherme', 'gesamt224,91']) {
      expect(text.replace(/\u00a0/g, ' ')).toContain(part)
    }
    expect(text).not.toContain('Kam als reine XML-Datei')
    await page.click(page.button('Herunterladen'))
    const item = [...page.box.querySelectorAll<HTMLAnchorElement>('a[role="menuitem"]')].find((a) => a.textContent?.includes('E-Rechnung als XML'))
    expect(item?.getAttribute('href')).toBe('/api/v1/documents/11/versions/1/einvoice')
  })
})

describe('the rules card', () => {
  const rules = [
    { id: 1, vault_id: null, position: 1, on: true, hits: 48, last_hit_at: null, when: [{ field: 'sender', op: 'is', values: ['Stadtwerke Lindenau'] }], then: [{ field: 'kind', value: 1 }, { field: 'tag', value: 'strom' }, { field: 'vault', value: 9 }], created_at: '2026-10-01T00:00:00Z' },
    { id: 2, vault_id: 7, position: 1, on: true, hits: 133, last_hit_at: null, when: [{ field: 'text', op: 'contains', values: ['Ferienwohnung', 'Lindenhof 12a'] }], then: [{ field: 'vault', value: 9 }], created_at: '2026-10-01T00:00:00Z' },
    { id: 3, vault_id: 7, position: 2, on: false, hits: 0, last_hit_at: null, when: [{ field: 'amount', op: 'over', value: 100000 }], then: [{ field: 'title', value: 'Groß {jahr}' }], created_at: '2026-10-01T00:00:00Z' },
  ]
  beforeEach(() => {
    server.answers['GET /api/v1/settings/rules'] = [rules[0]]
    server.answers['GET /api/v1/rules'] = [rules[1], rules[2]]
    server.answers['PATCH /api/v1/settings/rules/1'] = rules[0]
    server.answers['PATCH /api/v1/rules/2'] = rules[1]
    server.answers['POST /api/v1/settings/rules'] = rules[0]
    server.answers['POST /api/v1/rules'] = rules[1]
  })

  it('reads every rule as a sentence, with its hits and where it applies', async () => {
    await page.show(<RulesCard server />)
    await until(() => page.box.querySelectorAll('[data-testid="rule"]').length === 3)
    const lines = [...page.box.querySelectorAll('[data-testid="rule"]')].map((li) => plain(li.textContent).replace(/\s+/g, ' '))
    expect(lines[0]).toContain('Wenn Absender ist „Stadtwerke Lindenau“ Art Rechnung, Tag strom, Tresor Ferienwohnung')
    expect(lines[0]).toContain('48 Mal gegriffen · alle Tresore')
    expect(lines[1]).toContain('Text enthält „Ferienwohnung“ oder „Lindenhof 12a“ Tresor Ferienwohnung')
    expect(lines[1]).toContain('in Jule')
    expect(lines[2]).toContain('Betrag über 1.000,00 € Titel „Groß {jahr}“')
  })

  it('switches, moves and deletes each rule where it belongs', async () => {
    server.answers['DELETE /api/v1/rules/3'] = 204
    server.answers['PATCH /api/v1/rules/3'] = rules[2]
    await page.show(<RulesCard server />)
    await until(() => page.box.querySelectorAll('[data-testid="rule"]').length === 3)
    const [server0, , third] = [...page.box.querySelectorAll<HTMLElement>('[data-testid="rule"]')]
    await page.click(server0.querySelector<HTMLButtonElement>('[role="switch"]'))
    expect(server.called('PATCH', '/api/v1/settings/rules/1')!.body).toEqual({ on: false })
    await page.click(page.button('Regel nach oben', third))
    expect(server.called('PATCH', '/api/v1/rules/3')!.body).toEqual({ position: 1 })
    await page.click(page.button('Regel löschen', third))
    expect(server.changes()).not.toContain('DELETE /api/v1/rules/3')
    await page.inDialog('Abbrechen')
    expect(server.changes()).not.toContain('DELETE /api/v1/rules/3')
    await page.click(page.button('Regel löschen', third))
    await page.inDialog('Regel löschen')
    expect(server.changes()).toContain('DELETE /api/v1/rules/3')
  })

  it('makes a rule for the whole server or for a vault', async () => {
    await page.show(<RulesCard server />)
    await until(() => page.button('Regel'))
    await page.click(page.button('Regel'))
    await page.type(page.box.querySelector<HTMLInputElement>('input[aria-label="Absender"]'), 'Stadtwerke Lindenau')
    await page.choose(page.select('dann'), 'tag')
    await page.type(page.box.querySelector<HTMLInputElement>('input[aria-label="Tag"]'), 'strom')
    await page.click(page.button('Regel anlegen'))
    expect(server.called('POST', '/api/v1/settings/rules')!.body).toEqual({ when: [{ field: 'sender', op: 'is', values: ['Stadtwerke Lindenau'] }], then: [{ field: 'tag', value: 'strom' }] })
    await page.click(page.button('Regel'))
    await page.choose(page.select('Gilt für'), '9')
    await page.choose(page.select('Wenn'), 'amount')
    await page.type(page.box.querySelector<HTMLInputElement>('input[aria-label="Betrag"]'), '250,00')
    await page.choose(page.select('Tresor'), '7')
    await page.click(page.button('Regel anlegen'))
    expect(server.called('POST', '/api/v1/rules')!.body).toEqual({ vault_id: 9, when: [{ field: 'amount', op: 'over', value: 25000 }], then: [{ field: 'vault', value: 7 }] })
  })

  it('stays away for somebody who manages no vault and has no rules', async () => {
    server.answers['GET /api/v1/rules'] = []
    server.answers['GET /api/v1/vaults'] = [{ ...vaults[1], my_right: 'edit' }]
    await page.show(<RulesCard />)
    await idle()
    expect(page.text).not.toContain('Regeln')
  })
})

describe('the kinds card and the AI card', () => {
  it('sends whoever looks for the kinds to the order page, where they are kept', async () => {
    await page.show(<KindsCard />)
    const link = [...page.box.querySelectorAll('a')].find((a) => a.textContent?.includes('Arten unter Ordnung öffnen'))!
    expect(link.getAttribute('href')).toBe('/ordnung?tab=kinds')
    expect(page.box.querySelector('input')).toBeNull()
  })

  it('leaves personal vaults out of the AI until the operator lets them in', async () => {
    server.answers['GET /api/v1/settings/ai'] = { provider: 'local', url: 'http://ollama:11434/v1/', model: 'llama3.1:8b', key_set: false, skip_personal: true }
    server.answers['PUT /api/v1/settings/ai'] = { provider: 'local', url: 'http://ollama:11434/v1/', model: 'llama3.1:8b', key_set: false, skip_personal: false }
    await page.show(<AiCard />)
    const toggle = await until(() => page.box.querySelector<HTMLButtonElement>('[role="switch"][aria-label="Persönliche Tresore auslassen"]'))
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    await page.click(toggle)
    expect(server.called('PUT', '/api/v1/settings/ai')!.body).toEqual({ skip_personal: false })
    expect(page.box.querySelector('[role="switch"][aria-label="Persönliche Tresore auslassen"]')!.getAttribute('aria-checked')).toBe('false')
  })

  it('sets the daily limit of AI requests and shows today\'s count', async () => {
    const local = { provider: 'local', url: 'http://ollama:11434/v1/', model: 'llama3.1:8b', key_set: false, skip_personal: true }
    server.answers['GET /api/v1/settings/ai'] = { ...local, daily_limit: 200, used_today: 37 }
    server.answers['PUT /api/v1/settings/ai'] = { ...local, daily_limit: 50, used_today: 37 }
    await page.show(<AiCard />)
    const counter = await until(() => page.box.querySelector('[data-testid="ai-used-today"]'))
    expect(counter.textContent).toContain('37')
    const field = page.box.querySelector<HTMLInputElement>('input[type="number"]')!
    expect(field.value).toBe('200')
    await page.type(field, 'viele')
    await page.click(page.button('Grenze speichern'))
    expect(server.called('PUT', '/api/v1/settings/ai')).toBeUndefined()
    expect(page.text).toContain('Bitte eine ganze Zahl von 0 bis 100000 eingeben.')
    await page.type(page.box.querySelector<HTMLInputElement>('input[type="number"]'), '50')
    await page.click(page.button('Grenze speichern'))
    expect(server.called('PUT', '/api/v1/settings/ai')!.body).toEqual({ daily_limit: 50 })
    expect(page.box.querySelector<HTMLInputElement>('input[type="number"]')!.value).toBe('50')
  })

  it('keeps the operator\'s own instructions for the AI, saved on their own', async () => {
    const local = { provider: 'local', url: 'http://ollama:11434/v1/', model: 'llama3.1:8b', key_set: false, skip_personal: true }
    server.answers['GET /api/v1/settings/ai'] = { ...local, instructions: 'Titel immer auf Deutsch.' }
    server.answers['PUT /api/v1/settings/ai'] = { ...local, instructions: 'Bei Rechnungen die Nummer.' }
    await page.show(<AiCard />)
    const area = await until(() => page.box.querySelector<HTMLTextAreaElement>('textarea'))
    expect(area.value).toBe('Titel immer auf Deutsch.')
    expect(area.maxLength).toBe(2000)
    expect(page.button('Anweisungen speichern')!.disabled).toBe(true)
    await page.type(area, 'Bei Rechnungen die Nummer.')
    await page.click(page.button('Anweisungen speichern'))
    expect(server.called('PUT', '/api/v1/settings/ai')!.body).toEqual({ instructions: 'Bei Rechnungen die Nummer.' })
    expect(page.box.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('Bei Rechnungen die Nummer.')
    expect(page.text).toContain('Anweisungen gespeichert.')
  })
})

describe('kinds of a vault', () => {
  const mine = { id: 5, key: '', name: 'Mietvertrag', hue: 120, position: 0, vault_id: 9 }
  const radios = () => [...page.box.querySelectorAll<HTMLButtonElement>('[role="radio"]')]
  const checked = () => radios().filter((r) => r.getAttribute('aria-checked') === 'true').map((r) => plain(r.textContent))

  it('makes a kind at the end of the choice, for the vault of the document, and chooses it at once', async () => {
    server.answers['POST /api/v1/kinds'] = { id: 6, key: '', name: 'Garantie', hue: 94, position: 0, vault_id: 9 }
    await inbox()
    await page.click(page.button('Neue Art'))
    await page.type(page.box.querySelector<HTMLInputElement>('input[placeholder="zum Beispiel Mietvertrag"]'), 'Garantie')
    await page.click(page.button('Anlegen'))
    expect(server.called('POST', '/api/v1/kinds')!.body).toEqual({ name: 'Garantie', hue: 94, vault_id: 9 })
    expect(checked()).toEqual(['Garantie'])
    expect(page.button('Anlegen')).toBeUndefined()
  })

  it('offers the kinds that sound like the typed one, and takes the very same name instead of making it', async () => {
    await inbox()
    await page.click(page.button('Neue Art'))
    const field = () => page.box.querySelector<HTMLInputElement>('input[placeholder="zum Beispiel Mietvertrag"]')
    await page.type(field(), 'Rechnnung')
    expect(page.text).toContain('Meintest du:')
    await page.click(page.button('Rechnung wählen'))
    expect(checked()).toEqual(['Rechnung'])
    expect(server.changes()).toEqual([])
    await page.click(page.button('Neue Art'))
    await page.type(field(), 'GESUNDHEIT')
    expect(page.text).toContain('„Gesundheit“ gibt es schon. Sie wird ausgewählt.')
    await page.click(page.button('Diese nehmen'))
    expect(checked()).toEqual(['Gesundheit'])
    expect(server.changes()).toEqual([])
  })

  it('says what went wrong when the server refuses, and makes nothing twice', async () => {
    server.fails['POST /api/v1/kinds'] = { status: 422, code: 'invalid_name' }
    await inbox()
    await page.click(page.button('Neue Art'))
    await page.type(page.box.querySelector<HTMLInputElement>('input[placeholder="zum Beispiel Mietvertrag"]'), 'Garantie')
    await page.click(page.button('Anlegen'))
    expect(page.box.querySelector('form [role="alert"]')).toBeTruthy()
    expect(checked()).toEqual(['Rechnung'])
  })

  it('has no field for somebody who may only read', async () => {
    server.answers[INBOX] = inboxOf([{ ...heating, my_right: 'read' }])
    await inbox()
    expect(page.button('Neue Art')).toBeUndefined()
  })

  it('files a kind of the vault before the move, which takes it along by name', async () => {
    server.answers['GET /api/v1/kinds?vault_id=9'] = [invoiceKind, health, mine]
    server.answers['POST /api/v1/documents/11/move'] = heating
    server.answers['PATCH /api/v1/documents/11'] = heating
    await inbox()
    await page.click(radios().find((r) => plain(r.textContent) === 'Mietvertrag'))
    await page.choose(page.select('Tresor'), '7')
    await page.click(page.button('Ablegen'))
    expect(server.changes()).toEqual(['PATCH /api/v1/documents/11', 'POST /api/v1/documents/11/move', 'PATCH /api/v1/documents/11'])
    const patches = server.calls.filter((c) => c.method === 'PATCH').map((c) => c.body)
    expect(patches).toEqual([{ kind_id: 5 }, { status: 'filed' }])
  })
})

describe('the history', () => {
  it('says which fields nexpaper proposed, and a move by a rule', () => {
    const context = { people: new Map(), vaults: new Map([[7, 'Jule'], [9, 'Ferienwohnung']]), sourceText: (s: string) => s }
    const proposed = { id: 1, at: '', action: 'proposed', by: null, by_link: '', detail: { fields: ['sender', 'vault', 'amount'], from: {} } } as unknown as DocumentEvent
    expect(eventWhat(proposed, i18n.t, context)).toBe('hat den Absender und den Betrag vorgeschlagen')
    const moved = { id: 2, at: '', action: 'moved', by: null, by_link: '', detail: { from: 7, to: 9, by: 'rule' } } as unknown as DocumentEvent
    expect(eventWhat(moved, i18n.t, context)).toBe('hat es nach einer Regel von Jule nach Ferienwohnung verschoben')
  })
})
