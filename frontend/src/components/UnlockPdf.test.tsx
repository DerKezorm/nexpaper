/**
 * Protected PDFs (P1) against test data: the field at the card (the password goes once, the field is emptied after
 * every try, a wrong one says so), the box "merken" (off from the start, a name needed), the list under My account (no
 * password anywhere, renaming, deleting only after the question, an entry that is lost), and the lines of the history.
 */
import type { TFunction } from 'i18next'

import type { DocumentEvent } from '../api/client'
import i18n, { changeLanguage } from '../i18n'
import { eventWhat } from '../lib/events'
import { PdfPasswordsCard } from '../pages/settings/PdfPasswordsCard'
import { Page, Server } from '../test/harness'
import { UnlockPdf } from './UnlockPdf'

const server = new Server()
const page = new Page()
/** Made now: no password stands in the code. */
const secret = () => `Pw-${Math.random().toString(36).slice(2)}`

const entries = [
  { id: 1, name: 'Gehaltsabrechnung', created_at: '2026-11-01T08:00:00Z', last_matched_at: '2026-11-10T08:00:00Z', readable: true },
  { id: 2, name: 'Versicherung', created_at: '2026-11-02T08:00:00Z', last_matched_at: null, readable: false },
]

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = {
    'POST /api/v1/documents/5/unlock': { document: { id: 5, status: 'processing' }, kept: '' },
    'GET /api/v1/pdf-passwords': entries,
    'PATCH /api/v1/pdf-passwords/1': { ...entries[0], name: 'Lohn' },
    'DELETE /api/v1/pdf-passwords/1': 204,
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

const field = () => document.querySelector<HTMLInputElement>('input[type="password"]')
const remember = () => document.querySelector<HTMLInputElement>('input[type="checkbox"]')

describe('the field at the card', () => {
  it('sends the password once, with nothing kept from the start, and empties the field', async () => {
    const opened = vi.fn()
    await page.show(<UnlockPdf documentId={5} onOpened={opened} />)
    expect(page.text).toContain('Passwort')
    expect(page.text).toContain('Das Original bleibt, wie es kam.')
    expect(remember()!.checked).toBe(false)
    const password = secret()
    await page.type(field(), password)
    await page.click(page.button('Öffnen'))
    expect(server.calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', url: '/api/v1/documents/5/unlock', body: { password } }])
    expect(opened).toHaveBeenCalledTimes(1)
    expect(field()!.value).toBe('')
  })

  it('says when the password is wrong, and keeps nothing of it', async () => {
    server.fails = { 'POST /api/v1/documents/5/unlock': { status: 422, code: 'wrong_pdf_password' } }
    const opened = vi.fn()
    await page.show(<UnlockPdf documentId={5} onOpened={opened} />)
    const password = secret()
    await page.type(field(), password)
    await page.click(page.button('Öffnen'))
    expect(page.text).toContain('Dieses Passwort öffnet das PDF nicht.')
    expect(opened).not.toHaveBeenCalled()
    expect(field()!.value).toBe('')
    expect(page.text).not.toContain(password)
  })

  it('asks for a name before a password is kept, then sends both', async () => {
    await page.show(<UnlockPdf documentId={5} onOpened={() => undefined} />)
    const password = secret()
    await page.type(field(), password)
    await page.check(remember())
    await page.click(page.button('Öffnen'))
    expect(server.changes()).toEqual([])
    expect(page.text).toContain('Gib dem Passwort einen Namen')
    await page.type(document.querySelector<HTMLInputElement>('input[placeholder="zum Beispiel Gehaltsabrechnung"]'), ' Gehalt ')
    await page.click(page.button('Öffnen'))
    expect(server.called('POST', '/api/v1/documents/5/unlock')!.body).toEqual({ password, remember: true, name: 'Gehalt' })
  })

  it('says when the brake holds', async () => {
    server.fails = { 'POST /api/v1/documents/5/unlock': { status: 429, code: 'pdf_password_too_often' } }
    await page.show(<UnlockPdf documentId={5} onOpened={() => undefined} />)
    await page.type(field(), secret())
    await page.click(page.button('Öffnen'))
    expect(page.text).toContain('Zu viele Versuche für dieses PDF.')
  })
})

describe('the list under My account', () => {
  it('shows names and dates, never a password, and says when one is lost', async () => {
    await page.show(<PdfPasswordsCard />)
    expect(page.text).toContain('Gemerkte PDF-Passwörter')
    const rows = [...document.querySelectorAll('[data-testid="pdf-password"]')]
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('Gehaltsabrechnung')
    expect(rows[0].textContent).toContain('gemerkt am 1.11.2026')
    expect(rows[0].textContent).toContain('zuletzt gepasst am 10.11.2026')
    expect(rows[1].textContent).toContain('hat noch nicht gepasst')
    expect(document.querySelectorAll('[data-testid="pdf-password-lost"]')).toHaveLength(1)
    expect(document.querySelectorAll('input[type="password"]')).toHaveLength(0)
  })

  it('deletes only after the question', async () => {
    await page.show(<PdfPasswordsCard />)
    await page.click(page.button('Gehaltsabrechnung löschen'))
    expect(page.dialog?.textContent).toContain('lässt sich nicht zurückholen')
    expect(server.changes()).toEqual([])
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Gehaltsabrechnung löschen'))
    await page.inDialog('Löschen')
    expect(server.changes()).toEqual(['DELETE /api/v1/pdf-passwords/1'])
  })

  it('renames an entry', async () => {
    await page.show(<PdfPasswordsCard />)
    await page.click(page.button('Gehaltsabrechnung umbenennen'))
    await page.type(document.querySelector<HTMLInputElement>('input[aria-label="Name für das gemerkte Passwort"]'), 'Lohn')
    await page.click(page.button('Namen speichern'))
    expect(server.called('PATCH', '/api/v1/pdf-passwords/1')!.body).toEqual({ name: 'Lohn' })
  })

  it('says how to get one when there is none', async () => {
    server.answers['GET /api/v1/pdf-passwords'] = []
    await page.show(<PdfPasswordsCard />)
    expect(document.querySelector('[data-testid="pdf-passwords-empty"]')?.textContent).toContain('Noch keine.')
  })
})

describe('the history', () => {
  const event = (by: string): DocumentEvent => ({ id: 1, action: 'pdf_opened', at: '2026-11-12T08:00:00Z', by: null, by_link: null, detail: { by } }) as unknown as DocumentEvent
  const context = { people: new Map(), vaults: new Map(), sourceText: (s: string) => s }

  it('says a person opened it, or that a remembered password did, never which', () => {
    const t = i18n.t.bind(i18n) as TFunction
    expect(eventWhat(event('typed'), t, context)).toBe('hat das PDF mit dem Passwort geöffnet')
    expect(eventWhat(event('kept'), t, context)).toBe('hat das PDF mit einem gemerkten Passwort geöffnet')
  })
})
