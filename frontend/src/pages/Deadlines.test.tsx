/**
 * The deadlines page against a stand-in of the server (the mock's `FristenPage`, its today the 8th of October 2026):
 * the sections, the words of each deadline, done and undo, later only for oneself, the filters; and the terms of a
 * contract in the fields of a document.
 */
import { act } from 'react'

import type { Deadline, DocumentInfo, Me } from '../api/client'
import { Dates, type DateEntry } from '../components/DocumentFields'
import { changeLanguage } from '../i18n'
import { Page, Server, plain } from '../test/harness'
import { DeadlinesPage } from './DeadlinesPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'member', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

function deadline(id: number, title: string, fields: Partial<Deadline>): Deadline {
  return {
    document_id: id, title, status: 'filed', vault_id: 2, via_share: false, sender: 'Stadt Lindenau', amount: null, currency: 'EUR', kind: 'due',
    what: 'pay', date: '2026-10-08', days: 0, end: '2026-10-08', notice: null, renew_months: null, renews_to: null, missed: null, done: null,
    snoozed_until: null, ...fields,
  }
}

const KURTAXE = deadline(5, 'Kurtaxe Abrechnung 3. Quartal', { date: '2026-10-05', end: '2026-10-05', days: -3, amount: 21200 })
const PROPHYLAXE = deadline(1, 'Rechnung Prophylaxe', { sender: 'Zahnarztpraxis Dr. Sommer', amount: 9640, status: 'inbox' })
const FITNESS = deadline(2, 'Mitgliedschaft Fitnessstudio', {
  vault_id: 1, kind: 'contract_end', what: 'cancel', date: '2026-10-18', days: 10, end: '2026-11-15', notice: { n: 4, unit: 'weeks' }, renew_months: 12, renews_to: '2027-11-15',
})
const MOBILE = deadline(4, 'Mobilfunkvertrag', {
  vault_id: 1, kind: 'contract_end', what: 'ends', date: '2026-12-31', days: 84, end: '2026-12-31', notice: { n: 3, unit: 'months' }, renew_months: 12, renews_to: '2027-12-31', missed: '2026-09-30',
})
const WATER = deadline(6, 'Abschlag Wasser Oktober', {
  date: '2026-10-01', end: '2026-10-01', days: -7, amount: 4800, done: { at: '2026-09-29T08:00:00Z', by: { id: 3, name: 'tom', display_name: 'Tom' } },
})

function gone(id: number, title: string, vault_id: number, keep: string): DocumentInfo {
  return {
    id, vault_id, title, date: '2013-12-31', added_at: '2026-10-02T10:00:00Z', status: 'filed', sender: { id: id + 100, name: `Absender ${id}` }, kind: null,
    dates: [{ kind: 'keep_until', date: keep, manual: true }],
  } as unknown as DocumentInfo
}
const WEG = [gone(21, 'Gehaltsabrechnungen 2013', 1, '2023-12-31'), gone(22, 'Kontoauszug Dezember', 2, '2024-12-31')]

const LIST = {
  today: '2026-10-08', soon_days: 14,
  overdue: { total: 1, items: [KURTAXE] },
  soon: { total: 2, items: [PROPHYLAXE, FITNESS] },
  later: { total: 1, items: [MOBILE] },
  done: { total: 1, items: [WATER] },
  counts: { '1': 2, '2': 2 }, shared: 0,
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = {
    'GET /api/v1/deadlines?done=true': LIST,
    'GET /api/v1/deadlines?done=true&what=pay': { ...LIST, soon: { total: 1, items: [PROPHYLAXE] }, later: { total: 0, items: [] } },
    'GET /api/v1/vaults': [
      { id: 1, name: 'jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 3, size: 0, members: [] },
      { id: 2, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'edit', documents: 9, size: 0, members: [] },
    ],
    'GET /api/v1/keeping?limit=500': { items: WEG, total: 2 },
    'GET /api/v1/keeping?vault_id=2&limit=500': { items: [WEG[1]], total: 1 },
    'POST /api/v1/documents/trash': { trashed: [21], failed: [] },
    'POST /api/v1/documents/5/dates/due/done': {},
    'DELETE /api/v1/documents/6/dates/due/done': {},
    'PUT /api/v1/documents/5/dates/due/snooze': { until: '2026-10-11' },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

const rows = () => [...page.box.querySelectorAll('[data-testid="deadline"]')]
const headings = () => [...page.box.querySelectorAll('section h2')].map((h) => plain(h.textContent))

describe('the deadlines page', () => {
  it('has the sections of the mock and says each deadline as it does', async () => {
    await page.show(<DeadlinesPage />, '/fristen')
    expect(page.box.querySelector('h1')!.textContent).toBe('Fristen')
    expect(headings()).toEqual(['Überfällig1', 'Nächste 14 Tage2', 'Später1', 'Darf weg 2'])
    const [kurtaxe, prophylaxe, fitness, mobile] = rows().map((row) => plain(row.textContent))
    expect(kurtaxe).toContain('Zahlen bis Mo, 05.10.2026')
    expect(kurtaxe).toContain('seit 3 Tagen')
    expect(kurtaxe).toContain('212,00')
    expect(prophylaxe).toContain('heute')
    expect(prophylaxe).toContain('im Eingang')
    expect(fitness).toContain('Kündigen bis So, 18.10.2026')
    expect(fitness).toContain('Vertrag bis 15.11.2026, 4 Wochen Kündigungsfrist. Ohne Kündigung verlängert er sich bis 15.11.2027.')
    expect(mobile).toContain('Vertrag endet Do, 31.12.2026')
    expect(mobile).toContain('in 3 Monaten')
    expect(mobile).toContain('Der letzte Kündigungstag war der 30.09.2026. Ohne Kündigung läuft der Vertrag bis 31.12.2027 weiter, nexpaper trägt das am 01.01.2027 selbst ein.')
    // The overdue one is drawn as such; the inbox one leads to the inbox.
    expect(rows()[0].className).toContain('bg-warn-soft')
    expect(rows()[1].querySelector('a')!.getAttribute('href')).toBe('/eingang/1')
    expect(rows()[2].querySelector('a')!.getAttribute('href')).toBe('/dokument/2')
    // The vault chips: the vaults that have deadlines, the own one as "Mein Tresor".
    expect(page.text).toContain('Alle Tresore')
    expect(page.text).toContain('Mein Tresor')
    expect(page.text).toContain('Erledigte zeigen (1)')
  })

  it('marks a deadline done and says so; done ones show on request with who and undo', async () => {
    await page.show(<DeadlinesPage />, '/fristen')
    await page.click(page.button('Bezahlt', rows()[0]))
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/dates/due/done'])
    expect(page.text).not.toContain('Erledigt0')
    await page.check(page.box.querySelector<HTMLInputElement>('input[type="checkbox"]'))
    expect(headings()).toContain('Erledigt1')
    const water = rows().at(-1)!
    expect(plain(water.textContent)).toContain('Bezahlt')
    expect(plain(water.textContent)).toContain('Tom, 29.09.2026')
    await page.click(page.button('Rückgängig', water))
    expect(server.changes()).toContain('DELETE /api/v1/documents/6/dates/due/done')
  })

  it('puts a deadline off for oneself only, by 1, 3 or 7 days', async () => {
    await page.show(<DeadlinesPage />, '/fristen')
    await page.click(page.button('Später', rows()[0]))
    const menu = page.box.querySelector('[role="menu"]')!
    expect(plain(menu.textContent)).toContain('Nur für dich. Die anderen im Tresor werden weiter erinnert.')
    expect([...menu.querySelectorAll('button')].map((b) => plain(b.textContent))).toEqual(['Morgen09.10.', 'In 3 Tagen11.10.', 'In einer Woche15.10.'])
    await page.click(page.button('In 3 Tagen11.10.', menu))
    expect(server.called('PUT', '/api/v1/documents/5/dates/due/snooze')!.body).toEqual({ days: 3 })
  })

  it('shows a later that lasts, with a way to end it', async () => {
    server.answers['GET /api/v1/deadlines?done=true'] = { ...LIST, overdue: { total: 1, items: [{ ...KURTAXE, snoozed_until: '2026-10-11' }] } }
    server.answers['DELETE /api/v1/documents/5/dates/due/snooze'] = 204
    await page.show(<DeadlinesPage />, '/fristen')
    expect(plain(rows()[0].textContent)).toContain('Erinnert dich wieder am So, 11.10.')
    await page.click(page.button('Jetzt wieder', rows()[0]))
    expect(server.changes()).toEqual(['DELETE /api/v1/documents/5/dates/due/snooze'])
  })

  it('filters by what is to be done', async () => {
    await page.show(<DeadlinesPage />, '/fristen')
    await page.click(page.button('Zahlen'))
    expect(server.called('GET', '/api/v1/deadlines?done=true&what=pay')).toBeTruthy()
    expect(rows().map((row) => plain(row.querySelector('a')!.textContent))).toEqual(['Kurtaxe Abrechnung 3. Quartal', 'Rechnung Prophylaxeim Eingang'])
  })

  it('says when nothing is open', async () => {
    server.answers['GET /api/v1/deadlines?done=true'] = { ...LIST, overdue: { total: 0, items: [] }, soon: { total: 0, items: [] }, later: { total: 0, items: [] }, done: { total: 0, items: [] } }
    await page.show(<DeadlinesPage />, '/fristen')
    expect(page.text).toContain('Nichts offen')
    expect(page.text).toContain('Fristen entstehen aus den Terminen der Dokumente: fällig am, Vertrag bis, Garantie bis.')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    await page.show(<DeadlinesPage />, '/fristen')
    expect(page.box.querySelector('h1')!.textContent).toBe('Deadlines')
    expect(plain(rows()[0].textContent)).toContain('Pay by Mon, 10/05/2026')
    expect(plain(rows()[0].textContent)).toContain('3 days ago')
  })
})

describe('may go ("Darf weg") on the deadlines page', () => {
  const sections = () => [...page.box.querySelectorAll('section')].map((s) => plain(s.querySelector('h2')!.textContent))

  it('is a filter with its number, and below the other sections at "Alle"', async () => {
    await page.show(<DeadlinesPage />, '/fristen')
    expect(plain(page.button('Darf weg 2')!.textContent)).toBe('Darf weg 2')
    // The deadlines first, then what may go; the number of the deadlines (menu, sections) does not include it.
    expect(sections()).toEqual(['Überfällig1', 'Nächste 14 Tage2', 'Später1', 'Darf weg 2'])
    expect(rows().length).toBe(4)
  })

  it('shows only what may go under its filter, with nothing to tick for the done ones', async () => {
    await page.show(<DeadlinesPage />, '/fristen')
    await page.click(page.button('Darf weg 2'))
    expect(sections()).toEqual(['Darf weg 2'])
    expect(rows().length).toBe(0)
    expect(page.box.querySelector('label.invisible')).toBeTruthy()
    expect(page.text).toContain('Gehaltsabrechnungen 2013')
    expect(page.text).toContain('Kontoauszug Dezember')
  })

  it('follows the vault chosen on the page, and a share alone has none', async () => {
    await page.show(<DeadlinesPage />, '/fristen')
    await page.click(page.button('Darf weg 2'))
    await page.click(page.button('Haushalt'))
    expect(server.called('GET', '/api/v1/keeping?vault_id=2&limit=500')).toBeTruthy()
    expect(page.text).toContain('Kontoauszug Dezember')
    expect(page.text).not.toContain('Gehaltsabrechnungen 2013')
    // The number on the chip is still the whole of it.
    expect(plain(page.button('Darf weg 2')!.textContent)).toBe('Darf weg 2')
  })

  it('has nothing for what is seen through a share alone, and the chip keeps the whole number', async () => {
    server.answers['GET /api/v1/deadlines?done=true'] = { ...LIST, shared: 1 }
    server.answers['GET /api/v1/deadlines?done=true&shared=true'] = { ...LIST, shared: 1 }
    await page.show(<DeadlinesPage />, '/fristen')
    await page.click(page.button('Darf weg 2'))
    await page.click(page.button('Einzeln geteilt'))
    expect(page.text).not.toContain('Gehaltsabrechnungen 2013')
    expect(page.text).toContain('Nichts, dessen Aufbewahrungszeit um ist.')
    expect(plain(page.button('Darf weg 2')!.textContent)).toBe('Darf weg 2')
    expect(server.calls.some((c) => c.url.startsWith('/api/v1/keeping?vault_id'))).toBe(false)
  })

  it('is not there when nothing may go, and nothing is asked of the trash by the page itself', async () => {
    server.answers['GET /api/v1/keeping?limit=500'] = { items: [], total: 0 }
    await page.show(<DeadlinesPage />, '/fristen')
    expect(page.button('Darf weg')).toBeUndefined()
    expect(sections()).toEqual(['Überfällig1', 'Nächste 14 Tage2', 'Später1'])
    expect(server.changes()).toEqual([])
  })

  it('stays below the empty card when no deadline is open', async () => {
    server.answers['GET /api/v1/deadlines?done=true'] = { ...LIST, overdue: { total: 0, items: [] }, soon: { total: 0, items: [] }, later: { total: 0, items: [] }, done: { total: 0, items: [] } }
    await page.show(<DeadlinesPage />, '/fristen')
    expect(page.text).toContain('Nichts offen')
    expect(sections()).toEqual(['Darf weg 2'])
  })

  it('puts the picked ones in the trash only after the question', async () => {
    await page.show(<DeadlinesPage />, '/fristen')
    await page.click(page.button('Darf weg 2'))
    await page.check(page.box.querySelector<HTMLInputElement>('input[aria-label="Gehaltsabrechnungen 2013 auswählen"]'))
    await page.click(page.button('In den Papierkorb (1)'))
    expect(server.changes()).toEqual([])
    expect(plain(page.dialog!.textContent)).toContain('1 Dokument in den Papierkorb?')
    await page.inDialog('In den Papierkorb')
    expect(server.called('POST', '/api/v1/documents/trash')!.body).toEqual({ ids: [21] })
  })
})

describe('the terms of a contract in the fields', () => {
  function show(dates: DateEntry[], extra: Partial<Parameters<typeof Dates>[0]> = {}) {
    const onChange = vi.fn()
    return page.show(<Dates dates={dates} onChange={onChange} start="2026-10-08" {...extra} />).then(() => onChange)
  }

  it('works the last day to cancel out and gives the new terms to the page', async () => {
    const onChange = await show([{ kind: 'contract_end', date: '2026-12-31', notice: { n: 3, unit: 'months' }, renew_months: 12 }])
    expect(plain(page.box.querySelector('[data-testid="last-to-cancel"]')!.textContent)).toBe('Letzter Kündigungstag: Mi, 30.09.2026. Schon vorbei, der Vertrag läuft bis 31.12.2027 weiter.')
    expect(page.text).toContain('Wann die Kündigung ankommen muss, steht im Vertrag.')
    await page.choose(page.select('Kündigungsfrist, Einheit'), 'weeks')
    expect(onChange).toHaveBeenLastCalledWith([{ kind: 'contract_end', date: '2026-12-31', notice: { n: 3, unit: 'weeks' }, renew_months: 12 }])
    await page.choose(page.select('Verlängerung'), '0')
    expect(onChange).toHaveBeenLastCalledWith([{ kind: 'contract_end', date: '2026-12-31', notice: { n: 3, unit: 'months' }, renew_months: null }])
    await page.click(page.button('Keine Kündigungsfrist'))
    expect(onChange).toHaveBeenLastCalledWith([{ kind: 'contract_end', date: '2026-12-31', notice: null, renew_months: 12 }])
  })

  it('takes the number of the period when the field is left, not at every key', async () => {
    const onChange = await show([{ kind: 'contract_end', date: '2027-05-31', notice: { n: 3, unit: 'months' }, renew_months: 12 }])
    const number = page.box.querySelector<HTMLInputElement>('input[aria-label="Kündigungsfrist, Zahl"]')!
    await page.type(number, '6')
    expect(onChange).not.toHaveBeenCalled()
    await act(async () => number.dispatchEvent(new FocusEvent('focusout', { bubbles: true })))
    expect(onChange).toHaveBeenLastCalledWith([{ kind: 'contract_end', date: '2027-05-31', notice: { n: 6, unit: 'months' }, renew_months: 12 }])
  })

  it('starts a new contract with three months and twelve', async () => {
    const onChange = await show([])
    await page.click(page.button('Termin'))
    await page.click(page.button('Vertrag bis'))
    expect(onChange).toHaveBeenLastCalledWith([{ kind: 'contract_end', date: '2026-10-08', notice: { n: 3, unit: 'months' }, renew_months: 12 }])
  })

  it('marks a deadline done, or takes that back, on the document page only', async () => {
    const onDone = vi.fn()
    await show([{ kind: 'due', date: '2026-10-20' }, { kind: 'keep_until', date: '2036-12-31' }], { onDone, done: {} })
    expect(page.button('Als bezahlt markieren')).toBeTruthy()
    // Keeping is no deadline: nothing to mark there.
    expect(page.box.querySelectorAll('button').length).toBe(4)
    await page.click(page.button('Als bezahlt markieren'))
    expect(onDone).toHaveBeenCalledWith('due', true)
    page.close()
    await show([{ kind: 'due', date: '2026-10-20' }], { onDone, done: { due: { at: '2026-10-08T09:00:00Z', by: { id: 1, name: 'jule', display_name: 'Jule' } } } })
    expect(page.text).toContain('BezahltJule, 08.10.2026')
    await page.click(page.button('Rückgängig'))
    expect(onDone).toHaveBeenLastCalledWith('due', false)
  })

  it('shows no done line where the page does not ask for it (the inbox)', async () => {
    await show([{ kind: 'due', date: '2026-10-20' }])
    expect(page.button('Als bezahlt markieren')).toBeUndefined()
  })
})
