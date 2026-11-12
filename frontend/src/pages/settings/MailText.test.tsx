/**
 * The text of a mail as a document: the switch on the mailbox card (off from the start, one sentence for whom it is,
 * saved at once), the count of such documents in the last run and after "Fetch now", in German and English, and the
 * line in a document's history.
 */
import type { DocumentEvent, IntakeSettings } from '../../api/client'
import i18n, { changeLanguage } from '../../i18n'
import { eventWhat } from '../../lib/events'
import { Page, Server } from '../../test/harness'
import { IntakeCards } from './IntakeCards'

const server = new Server()
const page = new Page()

function settings(mail: Partial<IntakeSettings['mail']> = {}): IntakeSettings {
  return {
    folder: { on: false, path: '', used: '/data/eingang', problem: '', operator: 'Jule', people: [] },
    mail: {
      on: true, host: 'imap.example.com', port: 993, security: 'tls', user: 'paper@example.com', password_set: true, address: 'paper@example.com',
      folder: 'INBOX', after: 'read', private: false, drop_unknown: false, auth_server: '', last: { at: null, ok: true, code: '', mails: 0, files: 0, unknown: 0 },
      text: false,
      ...mail,
    },
  }
}

function toggle(label: string): HTMLButtonElement {
  const found = document.querySelector<HTMLButtonElement>(`button[role="switch"][aria-label="${label}"]`)
  expect(found, label).toBeTruthy()
  return found!
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/settings/intake': settings() }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('Mails without an attachment as a document', () => {
  it('shows the switch off, says for whom it is, and saves it at once', async () => {
    server.answers['PUT /api/v1/settings/intake'] = settings({ text: true })
    await page.show(<IntakeCards />)
    const toggled = toggle('Mails ohne Anhang als Dokument nehmen')
    expect(toggled.getAttribute('aria-checked')).toBe('false')
    expect(page.text).toContain(
      'Eine Mail ganz ohne Anhang wird zu einem PDF mit ihrem Text, etwa eine weitergeleitete Bestellbestätigung. Nur wenn sie von einer bestätigten Adresse einer Person kommt und der Mailserver die Echtheit bestätigt hat (dmarc=pass), dann in deren Eingang. Nie für unbekannte Absender, nie allein über die Adresse mit +name, höchstens 50 am Tag je Person.',
    )
    expect(document.querySelector('[data-testid="mail-text-judge"]')).toBeNull()
    await page.click(toggled)
    expect(server.calls.filter((c) => c.method === 'PUT').map((c) => c.body)).toEqual([{ mail_text: true }])
    expect(toggle('Mails ohne Anhang als Dokument nehmen').getAttribute('aria-checked')).toBe('true')
  })

  it('names the server whose verdict counts, and says when there is none', async () => {
    server.answers['GET /api/v1/settings/intake'] = settings({ text: true })
    await page.show(<IntakeCards />)
    expect(document.querySelector('[data-testid="mail-text-judge"]')!.textContent).toBe(
      'Es zählt das Urteil von example.com. Schreibt dieser Server kein dmarc=pass in die Mail, wird kein Text genommen.',
    )
    page.close()
    server.answers['GET /api/v1/settings/intake'] = settings({ text: true, auth_server: 'mx.example.net' })
    await page.show(<IntakeCards />)
    expect(document.querySelector('[data-testid="mail-text-judge"]')!.textContent).toContain('Urteil von mx.example.net.')
    page.close()
    server.answers['GET /api/v1/settings/intake'] = settings({ text: true, address: '', auth_server: '' })
    await page.show(<IntakeCards />)
    expect(document.querySelector('[data-testid="mail-text-judge"]')!.textContent).toBe(
      'Ohne Adresse des Postfachs oder vertrauten Server gibt es kein Urteil über die Echtheit, also wird kein Text genommen.',
    )
  })

  it('turns it off again', async () => {
    server.answers['GET /api/v1/settings/intake'] = settings({ text: true })
    server.answers['PUT /api/v1/settings/intake'] = settings({ text: false })
    await page.show(<IntakeCards />)
    await page.click(toggle('Mails ohne Anhang als Dokument nehmen'))
    expect(server.called('PUT', '/api/v1/settings/intake')!.body).toEqual({ mail_text: false })
  })

  it('counts the documents made of a mail text in the last run and after fetching', async () => {
    server.answers['GET /api/v1/settings/intake'] = settings({ last: { at: new Date().toISOString(), ok: true, code: '', mails: 3, files: 3, unknown: 0, texts: 2 } })
    server.answers['POST /api/v1/settings/intake/mail/fetch'] = { mails: 1, files: 1, unknown: 0, passed: 0, more: false, texts: 1 }
    await page.show(<IntakeCards />)
    expect(document.querySelector('[data-testid="mail-last"]')!.textContent).toBe('Zuletzt abgeholt gerade eben: Mails 3, Dokumente 3. Davon 2 aus dem Text von Mails.')
    await page.click(page.button('Jetzt abholen'))
    expect(page.text).toContain('Abgeholt. Mails: 1, Dokumente: 1. Davon 1 aus dem Text einer Mail.')
  })

  it('says nothing of mail texts when there were none', async () => {
    server.answers['GET /api/v1/settings/intake'] = settings({ last: { at: new Date().toISOString(), ok: true, code: '', mails: 1, files: 1, unknown: 0, texts: 0 } })
    await page.show(<IntakeCards />)
    expect(document.querySelector('[data-testid="mail-last"]')!.textContent).toBe('Zuletzt abgeholt gerade eben: Mails 1, Dokumente 1.')
  })

  it('speaks English as well', async () => {
    await changeLanguage('en', false)
    await page.show(<IntakeCards />)
    expect(toggle('Take mails without an attachment as a document')).toBeTruthy()
    expect(page.text).toContain('Never for unknown senders, never through the address with +name alone, at most 50 a day per person.')
  })
})

describe('the history of a document made of a mail text', () => {
  const context = { people: new Map(), vaults: new Map(), sourceText: (s: string) => (s === 'mail' ? 'Aus dem Postfach' : s) }
  const made = { id: 1, at: '', action: 'created', by: null, by_link: '', detail: { source: 'mail', mail_text: true } } as unknown as DocumentEvent
  const plain = { id: 2, at: '', action: 'created', by: null, by_link: '', detail: { source: 'mail' } } as unknown as DocumentEvent

  it('says it came from the text of a mail', () => {
    expect(eventWhat(made, i18n.t, context)).toBe('hat es angelegt: aus dem Text einer Mail')
    expect(eventWhat(plain, i18n.t, context)).toBe('hat es angelegt: aus dem Postfach')
  })

  it('in English too', async () => {
    await changeLanguage('en', false)
    expect(eventWhat(made, i18n.t, context)).toBe('created it: from the text of a mail')
  })
})
