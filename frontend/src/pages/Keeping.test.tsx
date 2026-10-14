/**
 * Keeping documents in the interface (F3): the column "Aufbewahren" of the kinds in Order with the question about the
 * documents already there, the line "Aufbewahren bis" with where it came from, and the question before the trash while
 * the time still runs. Against a stand-in of the server: nothing is sent before the person said so.
 */
import { useState } from 'react'

import type { DocumentInfo, Me } from '../api/client'
import { trashQuestion } from '../components/KeepTrash'
import { Dates, type DateEntry, type KeepContext } from '../components/DocumentFields'
import i18n, { changeLanguage } from '../i18n'
import { Page, Server, plain } from '../test/harness'
import { until } from '../test/wait'
import { OrderPage } from './OrderPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const kind = (id: number, name: string, vault_id: number | null, documents: number, extra: Record<string, unknown> = {}) => ({
  id, name, vault_id, right: vault_id === null ? null : 'manage', documents, in_trash: 0, can_change: true, key: '', hue: 28, position: 0, keep_years: null, keep_new_only: false, ...extra,
})
const KINDS = [
  kind(30, 'Rechnung', null, 453, { key: 'invoice' }),
  kind(31, 'Steuer', null, 21, { key: 'tax', keep_years: 10 }),
  kind(32, 'Mietvertrag', 9, 2, { keep_years: 3, keep_new_only: true }),
  kind(33, 'Beleg', 10, 4, { right: 'read', can_change: false, keep_years: 6 }),
]

beforeEach(async () => {
  await changeLanguage('de', false)
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(2026, 9, 8, 12, 0))
  auth.me = me
  server.answers = {
    'GET /api/v1/vaults': [
      { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 3, size: 1, members: [] },
      { id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'manage', documents: 9, size: 1, members: [] },
      { id: 10, name: 'Ferienwohnung', icon: 'sun', personal_of: null, my_right: 'read', documents: 2, size: 1, members: [] },
    ],
    'GET /api/v1/order/kinds?order=name&limit=500': { items: KINDS, total: KINDS.length },
    'POST /api/v1/kinds/30/keeping/preview': { documents: 453, by_hand: 1, expired: 220 },
    'PUT /api/v1/kinds/30/keeping': { kind: { ...KINDS[0], keep_years: 2 }, changed: 452, queued: false },
    'PUT /api/v1/kinds/31/keeping': { kind: { ...KINDS[1], keep_years: null }, changed: 21, queued: false },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const rows = () => [...page.box.querySelectorAll('ul[aria-label] > li')].map((li) => plain(li.textContent))

describe('the column "Aufbewahren" of the kinds', () => {
  it('shows the time of every kind, a choice where the person may set it and the time as text elsewhere', async () => {
    await page.show(<OrderPage />, '/ordnung?tab=kinds')
    await until(() => rows().length === 4)
    expect(page.select('Rechnung, aufbewahren')!.value).toBe('0')
    expect([...page.select('Rechnung, aufbewahren')!.options].map((o) => o.textContent)).toEqual(['nicht festgelegt', '1 Jahr', '2 Jahre', '3 Jahre', '5 Jahre', '6 Jahre', '8 Jahre', '10 Jahre', '30 Jahre'])
    expect(page.select('Steuer, aufbewahren')!.value).toBe('10')
    expect(rows()[2]).toContain('Aufbewahren gilt für neu abgelegte')
    expect(page.select('Beleg, aufbewahren')).toBeNull()
    expect(rows()[3]).toContain('Aufbewahren6 Jahre')
    // The box with the usual times, without guarantee.
    expect(page.text).toContain('Aufbewahren zählt ab dem Ende des Jahres im Dokumentdatum')
    expect(page.text).toContain('Beispiele aus Deutschland, Stand 2026, ohne Gewähr')
  })

  it('asks before setting a time: only for new ones, or for all there, with the numbers of the server', async () => {
    await page.show(<OrderPage />, '/ordnung?tab=kinds')
    await until(() => rows().length === 4)
    await page.choose(page.select('Rechnung, aufbewahren'), '2')
    await until(() => page.dialog)
    expect(server.changes()).toEqual(['POST /api/v1/kinds/30/keeping/preview'])
    expect(server.called('POST', '/api/v1/kinds/30/keeping/preview')!.body).toEqual({ years: 2 })
    const text = plain(page.dialog!.textContent)
    expect(text).toContain('Rechnung: 2 Jahre aufbewahren')
    expect(text).toContain('Ende des Jahres im Dokumentdatum plus 2 Jahre, also für eines vom 08.10.2026 der 31.12.2028.')
    expect(text).toContain('Auch für die 453 vorhandenen?')
    expect(text).toContain('1 mit einem von Hand gesetzten Datum behalten es.')
    expect(text).toContain('Bei 220 wäre die Zeit schon um. Sie erscheinen unter Fristen, „Darf weg“, gelöscht wird nichts von selbst.')
    // Abbrechen sets nothing.
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual(['POST /api/v1/kinds/30/keeping/preview'])
    await page.choose(page.select('Rechnung, aufbewahren'), '2')
    await until(() => page.dialog)
    await page.inDialog('Für alle 453')
    expect(server.called('PUT', '/api/v1/kinds/30/keeping')!.body).toEqual({ years: 2, existing: true })
    await page.choose(page.select('Rechnung, aufbewahren'), '2')
    await until(() => page.dialog)
    await page.inDialog('Nur für neue')
    expect(server.calls.filter((c) => c.method === 'PUT').map((c) => c.body)).toEqual([{ years: 2, existing: true }, { years: 2, existing: false }])
  })

  it('takes a time away without asking: nothing is deleted, dates set by hand stay', async () => {
    await page.show(<OrderPage />, '/ordnung?tab=kinds')
    await until(() => rows().length === 4)
    await page.choose(page.select('Steuer, aufbewahren'), '0')
    expect(page.dialog).toBeNull()
    expect(server.called('PUT', '/api/v1/kinds/31/keeping')!.body).toEqual({ years: null, existing: true })
  })

  it('sets the time without a question when there is no document of the kind', async () => {
    server.answers['POST /api/v1/kinds/30/keeping/preview'] = { documents: 0, by_hand: 0, expired: 0 }
    await page.show(<OrderPage />, '/ordnung?tab=kinds')
    await until(() => rows().length === 4)
    await page.choose(page.select('Rechnung, aufbewahren'), '8')
    await until(() => server.called('PUT', '/api/v1/kinds/30/keeping'))
    expect(server.called('PUT', '/api/v1/kinds/30/keeping')!.body).toEqual({ years: 8, existing: true })
  })
})

function Terms({ start, keep, sent }: { start: DateEntry[]; keep: KeepContext; sent: (dates: DateEntry[]) => void }) {
  const [dates, setDates] = useState(start)
  return (
    <Dates
      dates={dates}
      start="2026-09-17"
      keep={keep}
      onChange={(next) => {
        sent(next)
        setDates(next)
      }}
    />
  )
}

describe('the line "Aufbewahren bis"', () => {
  const steuer: KeepContext = { kindName: 'Steuer', years: 10, base: 2026, fresh: true }

  it('says it came from the kind, and a date typed there is set by hand', async () => {
    const sent = vi.fn()
    await page.show(<Terms start={[{ kind: 'keep_until', date: '2036-12-31', manual: false }]} keep={steuer} sent={sent} />)
    expect(page.text).toContain('Aus der Art Steuer: 10 Jahre nach Ende 2026.')
    expect(page.text).not.toContain('darf weg')
    // No cross: a time of the kind is not taken away here.
    expect(page.button('Aufbewahren bis entfernen')).toBeUndefined()
    const field = page.box.querySelector<HTMLInputElement>('input[aria-label="Aufbewahren bis"]')
    expect(field!.value).toBe('2036-12-31')
    await page.type(field, '2040-06-30')
    expect(sent).toHaveBeenLastCalledWith([{ kind: 'keep_until', date: '2040-06-30', manual: true }])
    expect(page.text).toContain('Von Hand gesetzt. Wieder aus der Art rechnen (Steuer, 10 Jahre)')
    // Back to the kind: the term is left out, the server works it out again.
    await page.click(page.button('Wieder aus der Art rechnen (Steuer, 10 Jahre)'))
    expect(sent).toHaveBeenLastCalledWith([])
    expect(page.text).toContain('Aus der Art Steuer: 10 Jahre nach Ende 2026.')
  })

  it('works the date out itself while a kind or a date is changed and not saved, and says when the time is over', async () => {
    await page.show(<Terms start={[]} keep={{ kindName: 'Rechnung', years: 2, base: 2020, fresh: false }} sent={vi.fn()} />)
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Aufbewahren bis"]')!.value).toBe('2022-12-31')
    expect(page.text).toContain('Aus der Art Rechnung: 2 Jahre nach Ende 2020. Die Zeit ist um, es darf weg.')
    // The choice of terms does not offer a second "Aufbewahren bis".
    await page.click(page.button('Termin'))
    expect([...page.box.querySelectorAll('button')].map((b) => plain(b.textContent))).not.toContain('Aufbewahren bis')
  })

  it('works it out anew from the draft when the kind was changed and not saved yet, and shows none for a kind without', async () => {
    const stored: DateEntry[] = [{ kind: 'keep_until', date: '2036-12-31', manual: false }]
    await page.show(<Terms start={stored} keep={{ kindName: 'Rechnung', years: 8, base: 2026, fresh: false }} sent={vi.fn()} />)
    expect(page.box.querySelector<HTMLInputElement>('input[aria-label="Aufbewahren bis"]')!.value).toBe('2034-12-31')
    expect(page.text).toContain('Aus der Art Rechnung: 8 Jahre nach Ende 2026.')
    page.close()
    await page.show(<Terms start={stored} keep={{ kindName: 'Bank', years: null, base: 2026, fresh: false }} sent={vi.fn()} />)
    expect(page.box.querySelector('input[aria-label="Aufbewahren bis"]')).toBeNull()
  })

  it('without a time of the kind, a date set by hand is just a term', async () => {
    const sent = vi.fn()
    await page.show(<Terms start={[{ kind: 'keep_until', date: '2030-01-01', manual: true }]} keep={{ kindName: 'Bank', years: null, base: 2026, fresh: true }} sent={sent} />)
    expect(page.text).not.toContain('Wieder aus der Art rechnen')
    expect(page.text).not.toContain('Aus der Art')
    await page.click(page.button('Aufbewahren bis entfernen'))
    expect(sent).toHaveBeenLastCalledWith([])
  })
})

describe('the question before the trash', () => {
  const doc = (dates: DocumentInfo['dates']) => ({ title: 'Einkommensteuerbescheid 2025', date: '2026-09-17', added_at: '2026-09-18T10:00:00Z', dates, kind: { id: 4, key: 'tax', name: 'Steuer', hue: 0, position: 3 } }) as DocumentInfo

  it('names a keeping time that still runs, and where it came from', () => {
    const t = i18n.t.bind(i18n)
    const fromKind = trashQuestion(doc([{ kind: 'keep_until', date: '2036-12-31', manual: false }]), t, 'de', '2026-10-08')
    expect(fromKind.confirm).toBe('Trotzdem in den Papierkorb')
    const byHand = trashQuestion(doc([{ kind: 'keep_until', date: '2026-10-08', manual: true }]), t, 'de', '2026-10-08')
    expect(byHand.confirm).toBe('Trotzdem in den Papierkorb')
    // Over (yesterday), or none: the question as always.
    expect(trashQuestion(doc([{ kind: 'keep_until', date: '2026-10-07', manual: true }]), t, 'de', '2026-10-08').confirm).toBe('In den Papierkorb')
    expect(trashQuestion(doc([]), t, 'de', '2026-10-08').confirm).toBe('In den Papierkorb')
  })

  it('reads the same in English', async () => {
    await changeLanguage('en', false)
    const t = i18n.t.bind(i18n)
    expect(trashQuestion(doc([{ kind: 'keep_until', date: '2036-12-31', manual: false }]), t, 'en', '2026-10-08').confirm).toBe('Move to the trash anyway')
  })
})
