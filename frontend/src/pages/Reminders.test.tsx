/**
 * My account › Notifications (before "Erinnerungen", whose address leads there) against a stand-in of the server: after
 * the kit's "Auf welchem Weg" nexpaper's cards with the choices from the start, a change goes out at once with only what changed, mail greyed out with its reason, the weekly overview
 * alone, the test message; and the mark of a muted vault and the way to these choices on the deadlines page.
 */
import { act } from 'react'

import type { Deadline, Me, Reminders } from '../api/client'
import { changeLanguage } from '../i18n'
import { Page, Server, plain } from '../test/harness'
import { idle, until } from '../test/wait'
import { SettingsRoutes } from '../test/settings'
import { DeadlinesPage } from './DeadlinesPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'member', sign_in: 'password', email: 'jule@example.com', language: 'de', email_confirmed: true,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const BASE: Reminders = {
  deadlines: true, trashed: 0,
  rhythm: 'single', push: true, mail: false, lead: { due: 3, cancel: 14, warranty: 30 }, same_day: true, muted: [], muted_shared: false,
  options: { due: [1, 3, 7, 14], cancel: [7, 14, 30, 60], warranty: [7, 14, 30, 60] }, hour: 8, time_zone: 'Europe/Berlin', push_devices: 2,
  mail_address: 'jule@example.com', mail_problem: null,
  vaults: [
    { id: 1, name: 'jule', icon: 'user', personal: true, personal_of_other: false, muted: false, others: 0 },
    { id: 2, name: 'Haushalt', icon: 'home', personal: false, personal_of_other: false, muted: false, others: 1 },
  ],
  read_only: [{ id: 3, name: 'Tom', icon: 'user', personal: false, personal_of_other: true }],
  shared: 0,
  may_go: 0,
}

function deadline(id: number, title: string, fields: Partial<Deadline>): Deadline {
  return {
    document_id: id, title, status: 'filed', vault_id: 2, via_share: false, sender: 'Stadt Lindenau', amount: 21200, currency: 'EUR', kind: 'due',
    what: 'pay', date: '2026-10-08', days: 0, end: '2026-10-08', notice: null, renew_months: null, renews_to: null, missed: null, done: null,
    snoozed_until: null, ...fields,
  }
}
const KURTAXE = deadline(5, 'Kurtaxe Abrechnung', { date: '2026-10-05', end: '2026-10-05', days: -3 })
const MOBILE = deadline(4, 'Handyvertrag Telekom', {
  vault_id: 1, kind: 'contract_end', what: 'cancel', date: '2026-10-22', days: 14, end: '2027-01-22', notice: { n: 3, unit: 'months' }, renew_months: 12, renews_to: '2028-01-22',
})
const LIST = {
  today: '2026-10-08', soon_days: 14, overdue: { total: 1, items: [KURTAXE] }, soon: { total: 1, items: [MOBILE] }, later: { total: 0, items: [] },
  done: null, counts: { '1': 1, '2': 1 }, shared: 0,
}

function answer(r: Partial<Reminders> = {}): void {
  server.answers['GET /api/v1/me/reminders'] = { ...BASE, ...r }
  server.answers['PUT /api/v1/me/reminders'] = { ...BASE, ...r }
}

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.me = me
  auth.setMe.mockClear()
  server.answers = {
    'GET /api/v1/deadlines?limit=50': LIST,
    'GET /api/v1/deadlines?done=true': { ...LIST, done: { total: 0, items: [] } },
    'GET /api/v1/vaults': [
      { id: 1, name: 'jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 3, size: 0, members: [] },
      { id: 2, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'edit', documents: 9, size: 0, members: [] },
    ],
    'POST /api/v1/me/reminders/test': { push: { sent: 2, gone: 0, failed: 0 }, mail: false, by_push: true, by_mail: false },
  }
  answer()
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

/** The kit's box to tick (`CheckboxRow`, never a sliding switch) named by exactly its label. */
const toggle = (label: string) => {
  const named = [...page.box.querySelectorAll('label')].find((item) => item.textContent === label)
  const box = named ? (document.getElementById(named.htmlFor) as HTMLInputElement | null) : null
  if (box) expect([box.type, box.getAttribute('role')]).toEqual(['checkbox', null])
  return box
}
const cards = () => [...page.box.querySelectorAll('section[data-card] h2')].map((h) => plain(h.textContent))
/** The words of a field's label (the kit joins them by `for`). */
const labelOf = (field: HTMLElement) => [...page.box.querySelectorAll('label')].find((item) => item.htmlFor === field.id)?.textContent
/** The choices of "Wie früh": each a field of the kit with its label and value. */
const leads = () =>
  [...page.box.querySelectorAll<HTMLSelectElement>('[data-card="deadlines-early"] select')].map((select) => [labelOf(select), select.value])
const NOTIFICATIONS = '/settings/notifications'

describe('my account, reminders', () => {
  it('has the four cards with the choices from the start', async () => {
    await page.show(<SettingsRoutes />, '/konto?tab=erinnerungen')
    // The address of before leads to "Benachrichtigungen" (E1); the first card is the kit's "Auf welchem Weg", then nexpaper's.
    expect(page.box.querySelector('[aria-current="page"][data-testid^="settings-nav-"]')!.textContent).toContain('Benachrichtigungen')
    expect(page.box.querySelector('[data-testid="settings-area-notifications"]')).toBeTruthy()
    expect(cards()).toEqual(['Auf welchem Weg', 'Fristen verwenden', 'Wie du erinnert wirst', 'Wie früh', 'Welche Tresore', 'So sieht es aus'])
    expect([...page.box.querySelectorAll('section[data-card]')].map((card) => card.getAttribute('data-card'))).toEqual(['notify-ways', 'deadlines-use', 'deadlines-how', 'deadlines-early', 'deadlines-vaults', 'deadlines-preview'])
    expect(page.text).toContain('Je Frist eine Nachricht, so früh wie unten eingestellt.')
    expect(toggle('Push aufs Handy und in den Browser')!.checked).toBe(true)
    expect(page.text).toContain('Auf 2 Geräten eingeschaltet. Tippen öffnet das Dokument.')
    expect(toggle('Mail an jule@example.com')!.checked).toBe(false)
    expect(page.text).toContain('Um 8 Uhr morgens in deiner Zeitzone (Europe/Berlin).')
    expect(leads()).toEqual([['Rechnung fällig', '3'], ['Letzter Kündigungstag', '14'], ['Garantie läuft ab', '30']])
    expect(toggle('Mein Tresor')!.checked).toBe(true)
    expect(page.text).toContain('Auch die anderen mit Bearbeiten-Recht werden erinnert.')
    expect(page.text).toContain('Nur lesen, darum keine Erinnerungen:')
    expect(page.text).toContain('Tom (persönlich)')
    // The examples, with the person's deadlines: a contract on the lock screen, the week by mail, never an amount.
    expect(page.text).toContain('Kündigen bis Do, 22.10.: Handyvertrag Telekom')
    expect(page.text).toContain('Noch 14 Tage. Danach verlängert sich der Vertrag bis 22.01.2028.')
    expect(page.text).toContain('Diese Woche: 0 Fristen, 1 überfällig')
    expect(page.text).toContain('Guten Morgen Jule, das steht diese Woche an:')
    expect(page.text).toContain('Mo, 05.10. · Zahlen: Kurtaxe Abrechnung')
    expect(page.text).not.toContain('212')
    // Nothing may go: no block, as in the real mail.
    expect(page.text).not.toContain('Darf weg')
    expect(page.text).not.toContain('Aufbewahrungszeit')
  })

  it('shows the documents that may go in the preview of the weekly overview, the number the server gives', async () => {
    answer({ may_go: 5 })
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(page.text).toContain('Darf weg')
    expect(page.text).toContain('Bei 5 Dokumenten ist die Aufbewahrungszeit um.')
    page.close()
    answer({ may_go: 1 })
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(page.text).toContain('Bei einem Dokument ist die Aufbewahrungszeit um.')
  })

  it('says in the preview what nexpaper put in the trash by itself in the last week', async () => {
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(page.text).not.toContain('hat nexpaper in den Papierkorb gelegt')
    page.close()
    answer({ trashed: 3 })
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(page.text).toContain('3 Dokumente hat nexpaper in den Papierkorb gelegt, ihre Aufbewahrungszeit war um. Dort lassen sie sich 30 Tage zurückholen.')
    page.close()
    answer({ trashed: 1 })
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(page.text).toContain('Ein Dokument hat nexpaper in den Papierkorb gelegt')
  })

  it('sends only what changed, at once', async () => {
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    await page.click(toggle('Haushalt'))
    expect(server.called('PUT', '/api/v1/me/reminders')!.body).toEqual({ muted: [2] })
    const due = [...page.box.querySelectorAll<HTMLSelectElement>('[data-card="deadlines-early"] select')].find((select) => labelOf(select) === 'Rechnung fällig')!
    await act(async () => {
      due.value = '7'
      due.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await idle()
    expect(server.calls.filter((c) => c.method === 'PUT').map((c) => c.body)).toEqual([{ muted: [2] }, { lead: { due: 7 } }])
    await page.click(toggle('Am Tag selbst noch einmal'))
    expect(server.calls.filter((c) => c.method === 'PUT').at(-1)!.body).toEqual({ same_day: false })
  })

  it('says why mail cannot go and offers no weekly overview then', async () => {
    answer({ mail_problem: 'no_server', mail_address: '' })
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    const mail = toggle('Mail')!
    expect(mail.disabled).toBe(true)
    expect(page.text).toContain('Der Betreiber hat keinen Mailserver eingerichtet, darum geht das nicht.')
    const weekly = [...page.box.querySelectorAll<HTMLButtonElement>('[data-card="deadlines-how"] [role="radio"]')].find((b) => b.textContent === 'Einmal die Woche')!
    expect(weekly.disabled).toBe(true)
    await page.click(mail)
    expect(server.changes()).toEqual([])
  })

  it('with the weekly overview alone shows where it goes and no single ways', async () => {
    answer({ rhythm: 'weekly' })
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(page.text).toContain('Die Wochenübersicht geht per Mail an jule@example.com.')
    expect(page.text).toContain('Montags um 8 Uhr eine Mail mit allem, was in dieser Woche ansteht.')
    expect(toggle('Push aufs Handy und in den Browser')).toBeNull()
    expect(cards()).toEqual(['Auf welchem Weg', 'Fristen verwenden', 'Wie du erinnert wirst', 'Welche Tresore', 'So sieht es aus'])
  })

  it('warns when no single reminder can reach the person', async () => {
    answer({ push: false })
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(page.text).toContain('So bekommst du keine einzelnen Erinnerungen. Die Seite Fristen zeigt trotzdem alles.')
  })

  it('sends a test message', async () => {
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    const test = page.button('Testnachricht schicken')!
    expect([test.dataset.kind, test.dataset.icon]).toEqual(['secondary', 'Send'])
    await page.click(test)
    expect(server.changes()).toEqual(['POST /api/v1/me/reminders/test'])
  })

  it('shows a refused change with its reason and the choices as they stand', async () => {
    server.fails['PUT /api/v1/me/reminders'] = { status: 409, code: 'mail_unavailable' }
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    await page.click(toggle('Mail an jule@example.com'))
    expect(page.text).toContain('Erinnerungen per Mail brauchen einen Mailserver und eine bestätigte Adresse.')
    expect(toggle('Mail an jule@example.com')!.checked).toBe(false)
  })

  it('comes in English too', async () => {
    await changeLanguage('en', false)
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(cards()).toEqual(['Which way', 'Use deadlines', 'How you are reminded', 'How early', 'Which vaults', 'What it looks like'])
    expect(page.text).toContain('Cancel by Thu, Oct 22: Handyvertrag Telekom')
    page.close()
    answer({ may_go: 2 })
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(page.text).toContain('The keeping time of 2 documents is over.')
  })
})

describe('deadlines on or off for the person', () => {
  const off = { ...me, profile: { ...me.profile, deadlines: false } } as Me

  it('is on from the start, with a switch at the top that asks before it switches off', async () => {
    server.answers['PUT /api/v1/me/preferences'] = { ...me.profile, deadlines: false }
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(toggle('Fristen verwenden')!.checked).toBe(true)
    expect(page.text).toContain('Gilt nur für dich. Die anderen im Haushalt behalten ihre Einstellungen.')
    await page.click(toggle('Fristen verwenden'))
    await until(() => page.dialog)
    expect(plain(page.dialog!.textContent)).toContain('Fristen ausschalten?')
    expect(plain(page.dialog!.textContent)).toContain('Die Termine an den Dokumenten bleiben.')
    // Nothing was sent, and Abbrechen sends nothing either.
    expect(server.changes()).toEqual([])
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    expect(auth.setMe).not.toHaveBeenCalled()
    await page.click(toggle('Fristen verwenden'))
    await until(() => page.dialog)
    await page.inDialog('Ausschalten')
    await until(() => server.called('PUT', '/api/v1/me/preferences'))
    expect(server.called('PUT', '/api/v1/me/preferences')!.body).toEqual({ deadlines: false })
    expect(server.changes()).toEqual(['PUT /api/v1/me/preferences'])
    expect(auth.setMe).toHaveBeenCalledWith(expect.objectContaining({ profile: expect.objectContaining({ deadlines: false }) }))
  })

  it('says that deadlines are off, with the way to switch them on again, and nothing else', async () => {
    auth.me = off
    server.answers['PUT /api/v1/me/preferences'] = { ...me.profile, deadlines: true }
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(cards()).toEqual(['Auf welchem Weg', 'Fristen sind aus'])
    expect(page.text).toContain('Im Menü steht kein Punkt Fristen, du bekommst keine Erinnerungen und keine Wochenübersicht.')
    expect(page.text).toContain('Die Termine an den Dokumenten bleiben, und die anderen Personen sind nicht betroffen.')
    expect(toggle('Fristen verwenden')).toBeNull()
    expect(page.button('Testnachricht schicken')).toBeUndefined()
    // Switching on needs no question; it goes back to the choices.
    const on = page.button('Fristen einschalten')!
    expect([on.dataset.kind, on.dataset.icon]).toEqual(['primary', 'Check'])
    await page.click(on)
    expect(server.called('PUT', '/api/v1/me/preferences')!.body).toEqual({ deadlines: true })
    expect(auth.setMe).toHaveBeenCalledWith(expect.objectContaining({ profile: expect.objectContaining({ deadlines: true }) }))
    auth.me = me
  })

  it('shows a refusal of the server and stays as it is', async () => {
    server.fails['PUT /api/v1/me/preferences'] = { status: 422, code: 'bad_preference' }
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    await page.click(toggle('Fristen verwenden'))
    await until(() => page.dialog)
    await page.inDialog('Ausschalten')
    expect(auth.setMe).not.toHaveBeenCalled()
    expect(plain(page.dialog!.textContent)).toContain('Diesen Wert bietet nexpaper nicht an.')
  })

  it('reads the same in English', async () => {
    await changeLanguage('en', false)
    auth.me = off
    await page.show(<SettingsRoutes />, NOTIFICATIONS)
    expect(cards()).toEqual(['Which way', 'Deadlines are off'])
    expect(page.button('Switch deadlines on')).toBeTruthy()
    auth.me = me
  })
})

describe('the deadlines page', () => {
  it('marks a muted vault and leads to the choices', async () => {
    answer({ muted: [2] })
    await page.show(<DeadlinesPage />, '/fristen')
    const rows = [...page.box.querySelectorAll('[data-testid="deadline"]')]
    expect(rows.map((row) => plain(row.textContent).includes('stumm'))).toEqual([true, false])
    const link = [...page.box.querySelectorAll('a')].find((a) => a.textContent === 'Mein Konto › Benachrichtigungen')!
    expect(link.getAttribute('href')).toBe('/settings/notifications')
  })
})
