/**
 * Inputs, against a stand-in of the server: Settings, Inputs with its words (the folder with a line per
 * person, the mailbox with its fields and "Afterwards"), "Save and try" that saves and then tries, the server's refusals
 * in the words of the card, the password never shown; My account, Upload with the addresses forwarded from, adding one
 * (a mail with a link), removing one, the own mailbox address and subfolder; the page of the link in that mail.
 */
import { Route, Routes } from 'react-router-dom'

import type { IntakeSettings, MyIntake } from '../../api/client'
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { SenderConfirmPage } from '../AuthPages'
import { IntakeCards, MyIntakeCards } from './IntakeCards'

const auth = { status: 'signedOut' as string, me: null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../../state/auth', () => ({ useAuth: () => auth, safeNext: (next: string | null) => next ?? '/' }))

const server = new Server()
const page = new Page()

function settings(change: { folder?: Partial<IntakeSettings['folder']>; mail?: Partial<IntakeSettings['mail']> } = {}): IntakeSettings {
  return {
    folder: {
      on: true, path: '/data/eingang', used: '/data/eingang', problem: '', operator: 'Jule',
      people: [{ name: 'jule', display_name: 'Jule', path: '/data/eingang/jule/' }, { name: 'tom', display_name: 'Tom', path: '/data/eingang/tom/' }],
      ...change.folder,
    },
    mail: {
      on: true, host: 'imap.example.com', port: 993, security: 'tls', user: 'paper@example.com', password_set: true, address: 'paper@example.com',
      folder: 'INBOX', after: 'move', private: false, drop_unknown: false, auth_server: '', last: { at: null, ok: true, code: '', mails: 0, files: 0, unknown: 0 },
      ...change.mail,
    },
  }
}

const mine: MyIntake = {
  mail_on: true, mail_address: 'paper@example.com', plus_address: 'paper+jule@example.com', account_address: 'jule@example.com',
  senders: [{ id: 3, address: 'jule.berger@example.org', confirmed: true, until: null }, { id: 4, address: 'neu@example.org', confirmed: false, until: '2026-10-10T08:00:00Z' }],
  folder_on: true, folder: '/data/eingang/jule/', can_confirm: true,
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/settings/intake': settings(), 'GET /api/v1/me/intake': mine }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

function field(label: string): HTMLInputElement {
  const input = [...document.querySelectorAll<HTMLLabelElement>('label')].find((l) => l.textContent?.startsWith(label))?.querySelector('input')
  expect(input, label).toBeTruthy()
  return input!
}

function toggle(label: string): HTMLButtonElement {
  const found = document.querySelector<HTMLButtonElement>(`button[role="switch"][aria-label="${label}"]`)
  expect(found, label).toBeTruthy()
  return found!
}

describe('Settings, Inputs', () => {
  it('shows both cards with their words', async () => {
    await page.show(<IntakeCards />)
    for (const words of [
      'Eingangsordner', 'Für den Scanner im Netz oder alles, was per Freigabe hereinkommt.', 'Eingangsordner beobachten', 'Ordner im Container',
      'Im Compose-Beispiel als Volume eingebunden. Per SMB freigeben macht der Server, nicht nexpaper.',
      '/data/eingang/jule/ → Eingang von Jule', '/data/eingang/tom/ → Eingang von Tom', '/data/eingang/ → Eingang der Betreiberin',
      'Abgeholt wird erst, wenn eine Datei 10 Sekunden lang nicht mehr wächst; danach wird sie aus dem Ordner genommen.',
      'E-Mail-Postfach', 'erkannt an der Absenderadresse oder an paper+name@.', 'Postfach abholen', 'Alle 5 Minuten, per IMAP.',
      'Adresse des Postfachs', 'Benutzer', 'Danach', 'Als gelesen markieren', 'In „nexpaper“ verschieben', 'Löschen', 'Port 993, TLS.',
      'Genommen werden PDF, Bilder und E-Rechnungen als XML. Mails von unbekannten Absendern landen im Eingang der Betreiberin, markiert als „unbekannt“; nichts wird automatisch abgelegt.',
      'Speichern und ausprobieren',
    ]) {
      expect(page.text, words).toContain(words)
    }
    expect(field('Server').value).toBe('imap.example.com')
    expect(field('Passwort').value).toBe('')
    expect(field('Passwort').placeholder).toBe('gespeichert, leer lassen zum Behalten')
    expect(document.querySelector('[role="radio"][aria-checked="true"]')!.textContent).toBe('In „nexpaper“ verschieben')
  })

  it('switches the folder and the mailbox at once, and changes "Afterwards" with one press', async () => {
    server.answers['PUT /api/v1/settings/intake'] = settings({ folder: { on: false }, mail: { after: 'delete' } })
    await page.show(<IntakeCards />)
    await page.click(toggle('Eingangsordner beobachten'))
    expect(server.called('PUT', '/api/v1/settings/intake')!.body).toEqual({ folder_on: false })
    await page.click(page.button('Löschen'))
    expect(server.calls.filter((c) => c.method === 'PUT').map((c) => c.body)).toEqual([{ folder_on: false }, { mail_after: 'delete' }])
  })

  it('saves the mailbox, then tries it, and says what it found', async () => {
    server.answers['PUT /api/v1/settings/intake'] = settings({ mail: { host: 'imap.example.org' } })
    server.answers['POST /api/v1/settings/intake/mail/test'] = { mails: 2, after: 'move' }
    await page.show(<IntakeCards />)
    await page.type(field('Server'), 'imap.example.org')
    await page.type(field('Passwort'), 'geheim-im-test')
    await page.click(page.button('Speichern und ausprobieren'))
    expect(server.changes()).toEqual(['PUT /api/v1/settings/intake', 'POST /api/v1/settings/intake/mail/test'])
    expect(server.called('PUT', '/api/v1/settings/intake')!.body).toEqual({
      mail_host: 'imap.example.org', mail_port: 993, mail_security: 'tls', mail_address: 'paper@example.com', mail_user: 'paper@example.com', mail_password: 'geheim-im-test',
      mail_auth_server: '',
    })
    expect(page.text).toContain('Verbunden. 2 neue Mails gefunden.')
    expect(field('Passwort').value).toBe('')
  })

  it('leaves the password out when nothing was typed', async () => {
    server.answers['PUT /api/v1/settings/intake'] = settings()
    server.answers['POST /api/v1/settings/intake/mail/test'] = { mails: 1, after: 'move' }
    await page.show(<IntakeCards />)
    await page.click(page.button('Speichern und ausprobieren'))
    expect(server.called('PUT', '/api/v1/settings/intake')!.body).not.toHaveProperty('mail_password')
    expect(page.text).toContain('Verbunden. 1 neue Mail gefunden.')
  })

  it.each([
    ['mail_login_failed', 'Der Mailserver kennt Benutzer oder Passwort nicht.'],
    ['mail_address_private', 'Der Mailserver liegt im eigenen Netz. Erlaube erst Server im eigenen Netz.'],
    ['mail_tls_failed', 'Die sichere Verbindung zum Mailserver hat nicht geklappt.'],
    ['mail_address_refused', 'Diese Adresse erreicht nexpaper nie.'],
  ])('says %s in the words of the card', async (code, words) => {
    server.answers['PUT /api/v1/settings/intake'] = settings()
    server.fails['POST /api/v1/settings/intake/mail/test'] = { status: 502, code }
    await page.show(<IntakeCards />)
    await page.click(page.button('Speichern und ausprobieren'))
    expect(document.querySelector('[role="alert"]')!.textContent).toBe(words)
  })

  it('says why a folder cannot be the intake folder', async () => {
    server.fails['PUT /api/v1/settings/intake'] = { status: 422, code: 'folder_forbidden' }
    await page.show(<IntakeCards />)
    await page.type(field('Ordner im Container'), '/data')
    await page.click(page.button('Speichern'))
    expect(server.called('PUT', '/api/v1/settings/intake')!.body).toEqual({ folder_path: '/data' })
    expect(page.text).toContain('Aus diesem Ordner darf nexpaper keine Dateien nehmen.')
  })

  it('fetches now and tells how the last run went', async () => {
    server.answers['GET /api/v1/settings/intake'] = settings({ mail: { last: { at: new Date(Date.now() - 2 * 3600_000).toISOString(), ok: false, code: 'mail_timeout', mails: 0, files: 0, unknown: 0 } } })
    server.answers['POST /api/v1/settings/intake/mail/fetch'] = { mails: 1, files: 2, unknown: 0, passed: 0, more: false }
    await page.show(<IntakeCards />)
    expect(document.querySelector('[data-testid="mail-last"]')!.textContent).toBe('Zuletzt vor 2 Stunden nicht geklappt: Der Mailserver hat zu lange gebraucht.')
    await page.click(page.button('Jetzt abholen'))
    expect(page.text).toContain('Abgeholt. Mails: 1, Dokumente: 2.')
  })

  it('says what "afterwards" does instead when the server cannot delete single mails', async () => {
    server.answers['PUT /api/v1/settings/intake'] = settings({ mail: { after: 'delete' } })
    server.answers['POST /api/v1/settings/intake/mail/test'] = { mails: 0, after: 'read' }
    await page.show(<IntakeCards />)
    await page.click(page.button('Speichern und ausprobieren'))
    expect(page.text).toContain('Verbunden. 0 neue Mails gefunden. Der Server kann einzelne Mails nicht löschen oder verschieben; nexpaper markiert sie stattdessen als gelesen.')
  })

  it('leaves unknown senders in the mailbox on a switch, and says when a mail stays because it was not taken whole', async () => {
    server.answers['PUT /api/v1/settings/intake'] = settings({ mail: { drop_unknown: true } })
    await page.show(<IntakeCards />)
    expect(page.text).toContain('Mails mit Anhängen über den Grenzen bleiben im Postfach und werden markiert.')
    expect(page.text).toContain('Sie bleiben dann im Postfach und kommen nicht in den Eingang der Betreiberin.')
    await page.click(toggle('Mails von unbekannten Absendern verwerfen'))
    expect(server.called('PUT', '/api/v1/settings/intake')!.body).toEqual({ mail_drop_unknown: true })
  })

  it('tells of mails skipped, flagged and left for tomorrow in the last run', async () => {
    server.answers['GET /api/v1/settings/intake'] = settings({ mail: { last: { at: new Date().toISOString(), ok: true, code: '', mails: 1, files: 1, unknown: 0, skipped: 2, flagged: 1, deferred: 0 } } })
    await page.show(<IntakeCards />)
    expect(document.querySelector('[data-testid="mail-last"]')!.textContent).toBe(
      'Zuletzt abgeholt gerade eben: Mails 1, Dokumente 1. 2 Mails übersprungen, zu aufwendig. 1 Mail im Postfach markiert.',
    )
  })

  it('names the trusted server for the verdict on senders, and says where nexpaper may only read in a subfolder', async () => {
    server.answers['GET /api/v1/settings/intake'] = settings({
      folder: { people: [{ name: 'jule', display_name: 'Jule', path: '/data/eingang/jule/', problem: 'folder_readonly' }] },
    })
    server.answers['PUT /api/v1/settings/intake'] = settings()
    server.answers['POST /api/v1/settings/intake/mail/test'] = { mails: 0, after: 'move' }
    await page.show(<IntakeCards />)
    expect(page.text).toContain('/data/eingang/jule/ → Eingang von Julenur lesbar, nexpaper nimmt hier nichts')
    expect(page.text).toContain('Bei gehosteten Postfächern den Namen des Anbieters eintragen, etwa mx.google.com.')
    await page.type(field('Vertrauter Server für Absenderprüfung'), 'mx.google.com')
    await page.click(page.button('Speichern und ausprobieren'))
    expect(server.called('PUT', '/api/v1/settings/intake')!.body).toMatchObject({ mail_auth_server: 'mx.google.com' })
  })

  it('says when nexpaper may only read in the folder', async () => {
    server.answers['GET /api/v1/settings/intake'] = settings({ folder: { problem: 'folder_readonly' } })
    await page.show(<IntakeCards />)
    expect(page.text).toContain('nexpaper darf in diesem Ordner nichts verschieben oder löschen. Solange nimmt es nichts daraus.')
  })

  it('hides the fields while the mailbox is off', async () => {
    server.answers['GET /api/v1/settings/intake'] = settings({ mail: { on: false }, folder: { on: false } })
    await page.show(<IntakeCards />)
    expect(page.text).not.toContain('Adresse des Postfachs')
    expect(page.text).not.toContain('Ordner im Container')
    expect(toggle('Postfach abholen').getAttribute('aria-checked')).toBe('false')
  })
})

describe('My account, Upload', () => {
  it('lists the addresses forwarded from, the own mailbox address and the subfolder', async () => {
    await page.show(<MyIntakeCards />)
    for (const words of [
      'Per Mail', 'Rechnungen an paper@example.com weiterleiten. nexpaper erkennt dich an deiner Absenderadresse und legt die Anhänge in deinen Eingang.',
      'jule@example.com', 'Adresse deines Kontos', 'jule.berger@example.org', 'neu@example.org', 'wartet auf Bestätigung', 'Weitere Absenderadresse',
      'Bekommt eine Mail mit Bestätigungslink, damit niemand fremde Adressen einträgt.',
      'Von irgendeiner anderen Adresse geht es mit deiner eigenen Postfach-Adresse:', 'paper+jule@example.com',
      'Dein Unterordner für den Scanner im Netz.', '/data/eingang/jule/',
    ]) {
      expect(page.text, words).toContain(words)
    }
  })

  it('adds an address (the server mails the link) and removes one', async () => {
    server.answers['POST /api/v1/me/mail-senders'] = { id: 5, address: 'b@example.org', confirmed: false, until: '2026-10-10T08:00:00Z' }
    server.answers['DELETE /api/v1/me/mail-senders/3'] = 204
    await page.show(<MyIntakeCards />)
    await page.type(field('Weitere Absenderadresse'), 'b@example.org')
    await page.click(page.button('Hinzufügen'))
    expect(server.called('POST', '/api/v1/me/mail-senders')!.body).toEqual({ address: 'b@example.org' })
    expect(page.text).toContain('Mail mit Bestätigungslink an b@example.org geschickt.')
    await page.click(page.button('Entfernen: jule.berger@example.org'))
    // Nothing is sent before the person said yes (and Abbrechen sends nothing either).
    expect(server.changes()).toEqual(['POST /api/v1/me/mail-senders'])
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual(['POST /api/v1/me/mail-senders'])
    await page.click(page.button('Entfernen: jule.berger@example.org'))
    await page.inDialog('Adresse entfernen')
    expect(server.changes()).toEqual(['POST /api/v1/me/mail-senders', 'DELETE /api/v1/me/mail-senders/3'])
  })

  it('says when an address counts already', async () => {
    server.fails['POST /api/v1/me/mail-senders'] = { status: 409, code: 'sender_exists' }
    await page.show(<MyIntakeCards />)
    await page.type(field('Weitere Absenderadresse'), 'jule.berger@example.org')
    await page.click(page.button('Hinzufügen'))
    expect(page.text).toContain('Diese Adresse zählt schon.')
  })

  it('shows nothing of a mailbox or a folder that is off, and no field without a mail server', async () => {
    server.answers['GET /api/v1/me/intake'] = { ...mine, folder_on: false, folder: '', can_confirm: false }
    await page.show(<MyIntakeCards />)
    expect(page.text).not.toContain('/data/eingang/jule/')
    expect(page.text).toContain('Ohne Mailserver lässt sich keine Adresse bestätigen.')
    expect(document.querySelector('input')).toBeNull()
    page.close()
    server.answers['GET /api/v1/me/intake'] = { ...mine, mail_on: false, mail_address: '', plus_address: '' }
    await page.show(<MyIntakeCards />)
    expect(page.text).not.toContain('Per Mail')
    expect(page.text).toContain('/data/eingang/jule/')
  })
})

describe('the page of the link to a sender address', () => {
  const token = 'c'.repeat(30)

  it('says whom it is for and confirms only on a press', async () => {
    server.answers[`GET /api/v1/mail-senders/confirm/${token}`] = { name: 'jule', address: 'jule.berger@example.org' }
    server.answers[`POST /api/v1/mail-senders/confirm/${token}`] = { name: 'jule', address: 'jule.berger@example.org' }
    await page.show(
      <Routes>
        <Route path="absender/:token" element={<SenderConfirmPage />} />
      </Routes>,
      `/absender/${token}`,
    )
    expect(document.querySelector('h1')!.textContent).toBe('Absenderadresse bestätigen')
    expect(page.text).toContain('Danach kommen Anhänge, die jule von jule.berger@example.org an nexpaper weiterleitet, in den eigenen Eingang.')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Bestätigen'))
    expect(server.changes()).toEqual([`POST /api/v1/mail-senders/confirm/${token}`])
    expect(document.querySelector('h1')!.textContent).toBe('Bestätigt')
    expect(page.text).toContain('Mails von jule.berger@example.org kommen jetzt in den Eingang von jule.')
  })

  it('says so when the link does not hold', async () => {
    server.fails[`GET /api/v1/mail-senders/confirm/${token}`] = { status: 404, code: 'sender_link_invalid' }
    await page.show(
      <Routes>
        <Route path="absender/:token" element={<SenderConfirmPage />} />
      </Routes>,
      `/absender/${token}`,
    )
    expect(document.querySelector('h1')!.textContent).toBe('Dieser Link gilt nicht mehr')
  })
})

