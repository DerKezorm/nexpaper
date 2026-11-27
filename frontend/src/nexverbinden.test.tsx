// Vorlage nexverbinden 0.2.0
// @vitest-environment jsdom
/**
 * The parts of the module in the app: the card of a partner app in each state, the cards of all partners, the consent
 * page, the page the browser comes back to, and the operator's card, built from the ui kit, the module's words in
 * German, English and French. What each part shows and what it sends. Copied once by bauplaene/verbinden/tools/sync.py
 * to `frontend/src/nexverbinden.test.tsx`; then the app's file. Fill in the places marked APP. Needs react-dom.
 */
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { NexuiLanguage } from './vendor/nexui'
import {
  ConnectionCard,
  ConnectionsArea,
  ConnectionsOperatorCard,
  ConsentPage,
  OPERATOR_PAGE,
  PARTNER_OPERATOR_PAGE,
  RETURN_GRACE_MS,
  ReturnPage,
  VERBINDEN_TEXTS,
  carryProblem,
  areaActions,
  type ConnectionsAdmin,
  type ConsentInfo,
  type PartnerView,
  type VerbindenRequest,
} from './vendor/nexverbinden'

// APP: this app's name and a partner of it in the catalog, with what each may do at the other (purpose ids; an app that
// only grants leaves USES empty, one that only uses leaves GRANTS empty).
const APP = 'nexpaper'
const PARTNER = 'nextime'
const USES: Record<string, string> = {}
const GRANTS: Record<string, string> = { 'deadlines.read': 'read' }

// Derived from the pair above (since 0.1.2): the cases fit a guest (it uses something at the partner) as well as a
// host that only grants (nexfolk, nextasks).
const FIRST_USE = Object.keys(USES)[0]
const FIRST_GRANT = Object.keys(GRANTS)[0]
const IS_GUEST = FIRST_USE !== undefined
const word = (grantedBy: string, id: string) => (VERBINDEN_TEXTS.de.purposes as Record<string, Record<string, string>>)[grantedBy]?.[id] ?? id
// Since 0.2.0: a second partner for the operator's card, never the one above.
const SECOND = ['nexpaper', 'nexmail'].find((name) => name !== PARTNER && name !== APP) ?? 'nexdiary'
const OWN_PURPOSE = Object.keys((VERBINDEN_TEXTS.de.purposes as Record<string, Record<string, string>>)[APP] ?? {})[0] ?? 'own.purpose'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Call = { path: string; method: string; body: unknown }

let root: Root
let box: HTMLDivElement
let calls: Call[]
let answers: Record<string, unknown>
let refuse: Record<string, unknown>
let went: string[]

function view(more: Partial<PartnerView> = {}): PartnerView {
  return {
    partner: PARTNER,
    state: 'connected',
    address: 'https://partner.example.com',
    address_from_operator: false,
    set_up: true,
    host: 'partner.example.com',
    uses: Object.keys(USES),
    grants: Object.keys(GRANTS),
    uses_levels: USES,
    grants_levels: GRANTS,
    account: 'kim',
    since: '2026-11-20T10:00:00+00:00',
    ok_at: '2026-11-26T14:00:00+00:00',
    used_at: null,
    stale_since: null,
    problem: null,
    areas_used: [{ id: 11, name: 'Zuhause' }],
    areas_granted: null,
    legacy: null,
    version: '0.9.0',
    areas_choice: [],
    ...more,
  }
}

const request: VerbindenRequest = async <T,>(path: string, init?: { method?: string; body?: unknown }) => {
  const method = init?.method ?? 'GET'
  calls.push({ path, method, body: init?.body })
  const key = `${method} ${path.split('?')[0]}`
  if (key in refuse) throw { detail: refuse[key] }
  if (!(key in answers)) throw new Error(`no answer for ${key}`)
  return answers[key] as T
}

async function show(node: ReactNode, language = 'de') {
  await act(async () => {
    root.render(<NexuiLanguage language={language}>{node}</NexuiLanguage>)
  })
}

const byTest = (id: string) => box.querySelector(`[data-testid="${id}"]`) as HTMLElement | null

async function click(id: string) {
  const found = byTest(id)
  expect(found, id).not.toBeNull()
  await act(async () => {
    found!.click()
  })
}

async function typeInto(id: string, value: string) {
  const input = byTest(id) as HTMLInputElement
  expect(input, id).not.toBeNull()
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => {
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const pause = (ms: number) => act(async () => {
  await new Promise((done) => setTimeout(done, ms))
})

async function confirmDialog() {
  const dialog = byTest('connection-disconnect-dialog') ?? (document.body.querySelector('[data-testid="connection-disconnect-dialog"]') as HTMLElement | null)
  expect(dialog).not.toBeNull()
  const buttons = Array.from(dialog!.querySelectorAll('button')).filter((button) => button.getAttribute('data-kind') === 'danger')
  await act(async () => {
    buttons.at(-1)?.click()
  })
}

beforeEach(() => {
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  calls = []
  answers = {}
  refuse = {}
  went = []
  window.sessionStorage.clear()
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
})

describe('the card of a partner app', () => {
  it('not connected: set up by the operator, one click off to the partner, no address to type (V42)', async () => {
    answers[`POST /api/connect/partners/${PARTNER}/start`] = { go: 'https://partner.example.com/connect/app?state=s' }
    await show(<ConnectionCard app={APP} view={view({ state: 'none', account: null, host: '', address_from_operator: true })} request={request} navigate={(url) => went.push(url)} manual={<p>form</p>} defaultOpen />)
    expect(byTest('connection-state')?.textContent).toBe('Nicht verbunden')
    expect(byTest('connection-address')).toBeNull()
    expect(box.querySelector('input[type="url"]')).toBeNull()
    // V46: a new connection by hand only for the operator.
    expect(byTest('connection-manual')).toBeNull()
    await click('connection-connect')
    expect(calls.at(-1)).toEqual({ path: `/api/connect/partners/${PARTNER}/start`, method: 'POST', body: { areas: null } })
    expect(went).toEqual(['https://partner.example.com/connect/app?state=s'])
  })

  it('not set up on this server: says so; the operator gets the way there and the form by hand (V42, V46)', async () => {
    const notSetUp = view({ state: 'none', account: null, host: '', address: '', set_up: false })
    await show(<ConnectionCard app={APP} view={notSetUp} request={request} manual={<p>form</p>} defaultOpen />)
    expect(byTest('connection-not-set-up')?.textContent).toContain(`${PARTNER} ist auf diesem Server nicht eingerichtet`)
    expect(byTest('connection-not-set-up')?.textContent).toContain('Der Betreiber trägt die Adresse')
    expect(byTest('connection-connect')).toBeNull()
    expect(byTest('connection-set-up')).toBeNull()
    expect(byTest('connection-manual')).toBeNull()
    await show(<ConnectionCard key="op" app={APP} view={notSetUp} request={request} manual={<p>form</p>} operator defaultOpen />)
    expect(byTest('connection-not-set-up')?.textContent).toContain(`Trag die Adresse von ${PARTNER}`)
    expect(byTest('connection-set-up')?.getAttribute('href')).toBe(OPERATOR_PAGE)
    // E67 (0.1.18): the card stands under Server › Verbindungen; the anchor stays.
    expect(OPERATOR_PAGE).toBe('/settings/server-connections#nex-apps')
    expect(byTest('connection-manual')).not.toBeNull()
  })

  it('a refusal the operator can lift names the place, and links there for him, here or in the partner (B2)', async () => {
    refuse[`POST /api/connect/partners/${PARTNER}/start`] = { code: 'local_off' }
    await show(<ConnectionCard app={APP} view={view({ state: 'none', account: null })} request={request} defaultOpen />)
    await click('connection-connect')
    expect(byTest('connection-problem')?.textContent).toContain('Server › Verbindungen › Andere nex-Apps')
    expect(byTest('connection-problem')?.textContent).not.toContain('Allgemein')
    expect(byTest('connection-problem')?.textContent).not.toContain('nicht erreichbar')
    expect(byTest('connection-set-up')).toBeNull()
    await show(<ConnectionCard key="op" app={APP} view={view({ state: 'none', account: null })} request={request} operator defaultOpen />)
    await click('connection-connect')
    expect(byTest('connection-set-up')?.getAttribute('href')).toBe(OPERATOR_PAGE)
    // The other side does not ask this app in the own network (sent back from its consent page, B6).
    await show(<ConnectionCard key="there" app={APP} view={view({ state: 'none', account: null })} request={request} operator carried="partner_local_off" />)
    expect(byTest('connection-problem')?.textContent).toBe(
      VERBINDEN_TEXTS.de.errors.partner_local_off.replaceAll('{partner}', PARTNER).replaceAll('{app}', APP),
    )
    // 0.1.18: into the partner by the address of before, which a partner of any version understands.
    expect(byTest('connection-set-up')?.getAttribute('href')).toBe(`https://partner.example.com${PARTNER_OPERATOR_PAGE}`)
    expect(PARTNER_OPERATOR_PAGE).toBe('/settings/general#nex-apps')
    expect(byTest('connection-set-up')?.textContent).toBe(`In ${PARTNER} einrichten`)
  })

  it('says what goes out when one app asks about a person (V53, 0.1.13)', async () => {
    await show(<ConnectionCard app={APP} view={view({ state: 'none', account: null, sends_person: true })} request={request} defaultOpen />)
    expect(byTest('connection-sends-person')?.textContent).toBe(
      VERBINDEN_TEXTS.de.card.sendsPerson.replaceAll('{app}', APP).replaceAll('{partner}', PARTNER),
    )
    expect(byTest('connection-receives-person')).toBeNull()
    await show(<ConnectionCard key="other" app={APP} view={view({ receives_person: true })} request={request} defaultOpen />)
    expect(byTest('connection-receives-person')?.textContent).toContain(`Dafür schickt ${PARTNER} Name, Mailadressen und Telefonnummern`)
    expect(byTest('connection-sends-person')).toBeNull()
  })

  it('a connection whose partner sits in the own network without the switch says why (B2)', async () => {
    await show(<ConnectionCard app={APP} view={view({ state: 'unreachable', problem: 'local_off', stale_since: '2026-11-26T14:05:00+00:00' })} request={request} operator defaultOpen />)
    expect(byTest('connection-local-off')?.textContent).toContain(`${APP} fragt keine Adressen im eigenen Netz`)
    expect(byTest('connection-unreachable')).toBeNull()
    expect(byTest('connection-set-up')?.getAttribute('href')).toBe(OPERATOR_PAGE)
  })

  it('where the partner reads areas here, the card asks for them before the click (all at first)', async () => {
    answers[`POST /api/connect/partners/${PARTNER}/start`] = { go: 'https://partner.example.com/connect/app?state=s' }
    const choice = [{ id: 1, name: 'Arbeit' }, { id: 2, name: 'Familie' }]
    await show(<ConnectionCard app={APP} view={view({ state: 'none', account: null, areas_choice: choice })} request={request} navigate={(url) => went.push(url)} defaultOpen />)
    expect(byTest('connection-areas')).not.toBeNull()
    expect((byTest('connection-all-areas') as HTMLInputElement).checked).toBe(true)
    expect(byTest('connection-area-1')).toBeNull()
    await click('connection-all-areas')
    expect((byTest('connection-connect') as HTMLButtonElement).disabled).toBe(true)
    await click('connection-area-2')
    await click('connection-connect')
    expect(calls.at(-1)).toMatchObject({ method: 'POST', body: { areas: [2] } })
    await show(<ConnectionCard key="plain" app={APP} view={view({ state: 'none', account: null })} request={request} navigate={(url) => went.push(url)} defaultOpen />)
    expect(byTest('connection-areas')).toBeNull()
    await click('connection-connect')
    expect(calls.at(-1)).toMatchObject({ body: { areas: null } })
  })

  it('asks for the areas by what the partner does there, from its purposes (V-11, V37, 0.1.4)', async () => {
    const choice = [{ id: 1, name: 'Arbeit' }]
    const ask = async (key: string, grants: Record<string, string>, areaWord?: string) => {
      await show(<ConnectionCard key={key} app={APP} view={view({ state: 'none', account: null, areas_choice: choice, grants: Object.keys(grants), grants_levels: grants })} request={request} areaWord={areaWord} defaultOpen />)
      return byTest('connection-areas-question')?.textContent
    }
    // Purposes the module does not know say it by their level.
    expect(await ask('reads', { 'some.read': 'read' })).toBe(`Wo darf ${PARTNER} lesen?`)
    expect(await ask('writes', { 'some.read': 'read', 'some.write': 'write' }, 'Adressbücher')).toBe(`Wo darf ${PARTNER} lesen und ändern?`)
    expect(byTest('connection-all-areas')?.parentElement?.textContent).toContain('Alle Adressbücher, auch spätere')
    // The app's own purposes in the catalog say what they do with the module's words.
    const ids = Object.keys((VERBINDEN_TEXTS.de.areaActions as Record<string, Record<string, unknown>>)[APP] ?? {})
    if (ids.length > 0) {
      const levels = Object.fromEntries(ids.map((id) => [id, 'read']))
      expect(await ask('own', levels)).toBe(`Wo darf ${PARTNER} ${areaActions(VERBINDEN_TEXTS.de, APP, ids, levels)}?`)
      expect(byTest('connection-areas-question')?.textContent).not.toContain(VERBINDEN_TEXTS.de.card.actionRead + '?')
    }
  })

  it('says each purpose of the catalog with its own words, the same thing once, in every language', () => {
    const { de, en, fr } = VERBINDEN_TEXTS
    // nexmail at nexfolk: reading and changing contacts is one thing.
    const contacts = ['contacts.read', 'contacts.write']
    expect(areaActions(de, 'nexfolk', contacts, {})).toBe('Kontakte lesen, anlegen und ändern')
    expect(areaActions(en, 'nexfolk', contacts, {})).toBe('read, create and change contacts')
    expect(areaActions(fr, 'nexfolk', contacts, {})).toBe('lire, créer et modifier les contacts')
    // nextime at nextasks: tasks read and ticked off.
    const tasks = ['tasks.read', 'tasks.complete']
    expect(areaActions(de, 'nextasks', tasks, {})).toBe('Aufgaben lesen und abhaken')
    expect(areaActions(en, 'nextasks', tasks, {})).toBe('read and tick off tasks')
    expect(areaActions(fr, 'nextasks', tasks, {})).toBe('lire et cocher les tâches')
    // nexmail at nextime: two things.
    const events = ['calendars.read', 'events.write', 'invitations.answer']
    expect(areaActions(de, 'nextime', events, {})).toBe('Termine lesen, anlegen und ändern und Einladungen beantworten')
    expect(areaActions(en, 'nextime', events, {})).toBe('read, create and change events and answer invitations')
    expect(areaActions(fr, 'nextime', events, {})).toBe('lire, créer et modifier les rendez-vous et répondre aux invitations')
    expect(areaActions(de, 'nextasks', ['tasks.read', 'tasks.complete', 'members.read'], {})).toBe('Aufgaben lesen und abhaken und Mitglieder sehen')
    expect(areaActions(de, 'nexpaper', ['documents.add'], { 'documents.add': 'write' })).toBe('Dokumente ablegen')
    expect(areaActions(de, 'nexlore', ['notes.add'], {})).toBe('Notizen ablegen')
    expect(areaActions(de, 'nextasks', ['tasks.read', 'tasks.read'], {})).toBe('Aufgaben lesen')
    expect(areaActions(de, 'nextasks', ['tasks.read', 'some.write'], { 'some.write': 'write' })).toBe('Aufgaben lesen und lesen und ändern')
  })

  it('a partner too old says so and opens the form by hand', async () => {
    refuse[`POST /api/connect/partners/${PARTNER}/start`] = { code: 'partner_too_old' }
    await show(<ConnectionCard app={APP} view={view({ state: 'none', account: null })} request={request} manual={<p data-testid="own-form">form</p>} operator defaultOpen />)
    await click('connection-connect')
    expect(byTest('connection-state')?.textContent).toBe('Zu alt')
    expect(byTest('connection-problem')?.textContent).toContain('von Hand')
    expect(byTest('own-form')).toBeNull()
    await click('connection-manual')
    expect(byTest('own-form')).not.toBeNull()
  })

  it('connected: what flows each way, the facts, renew and disconnect', async () => {
    const changed: PartnerView[] = []
    answers[`DELETE /api/connect/partners/${PARTNER}`] = view({ state: 'none' })
    await show(<ConnectionCard app={APP} view={view()} request={request} onChange={(found) => changed.push(found)} defaultOpen><p data-testid="own-part">lists</p></ConnectionCard>)
    expect(byTest('connection-state')?.textContent).toBe(IS_GUEST ? 'Verbunden' : `Nutzt ${APP}`)
    expect(byTest('connection-summary')?.textContent).toContain('partner.example.com')
    if (FIRST_USE) expect(byTest('connection-app-may')?.textContent).toContain(word(PARTNER, FIRST_USE))
    if (FIRST_GRANT) expect(byTest('connection-partner-may')?.textContent).toContain(word(APP, FIRST_GRANT))
    expect(byTest('connection-account')?.textContent).toContain('kim')
    expect(byTest('own-part')).not.toBeNull()
    expect(byTest('connection-renew') !== null).toBe(IS_GUEST)
    await click('connection-disconnect')
    await confirmDialog()
    expect(calls.at(-1)).toMatchObject({ path: `/api/connect/partners/${PARTNER}`, method: 'DELETE' })
    expect(changed.at(-1)?.state).toBe('none')
  })

  it('a partner that only uses this app: "Nutzt", what it may here, and "Zugriff beenden"', async () => {
    await show(<ConnectionCard app={APP} view={view({ uses: [], uses_levels: {}, grants: [OWN_PURPOSE], grants_levels: { [OWN_PURPOSE]: 'read' } })} request={request} defaultOpen />)
    expect(byTest('connection-state')?.textContent).toBe(`Nutzt ${APP}`)
    expect(byTest('connection-partner-may')?.textContent).toContain(word(APP, OWN_PURPOSE))
    expect(byTest('connection-disconnect')?.textContent).toBe('Zugriff beenden')
    expect(byTest('connection-renew')).toBeNull()
  })

  it("the app's own parts stand open in every state, by hand or not connected at all (V23)", async () => {
    const legacy = { shown: 'ntk_AbCd', expires_at: null }
    for (const state of ['none', 'legacy', 'connected', 'unreachable', 'refused', 'resting', 'off'] as const) {
      await show(<ConnectionCard key={state} app={APP} view={view({ state, legacy: state === 'legacy' ? legacy : null })} request={request} defaultOpen><p data-testid="own-part">lists</p></ConnectionCard>)
      expect(byTest('own-part'), state).not.toBeNull()
    }
  })

  it('not reachable: the last state with its time, and checking again', async () => {
    answers[`POST /api/connect/partners/${PARTNER}/check`] = view()
    await show(<ConnectionCard app={APP} view={view({ state: 'unreachable', stale_since: '2026-11-26T14:05:00+00:00' })} request={request} when={(iso) => iso.slice(11, 16)} defaultOpen />)
    expect(byTest('connection-state')?.textContent).toBe('Nicht erreichbar')
    expect(byTest('connection-summary')?.textContent).toContain('14:05')
    expect(byTest('connection-unreachable')?.textContent).toContain('14:00')
    await click('connection-check')
    expect(calls.at(-1)).toMatchObject({ path: `/api/connect/partners/${PARTNER}/check`, method: 'POST' })
  })

  it('refused, resting, switched off: each says what happened and what helps', async () => {
    await show(<ConnectionCard app={APP} view={view({ state: 'refused' })} request={request} defaultOpen />)
    expect(byTest('connection-refused')).not.toBeNull()
    expect(byTest('connection-disconnect')?.textContent).toBe('Entfernen')
    expect(byTest('connection-connect')?.textContent).toBe('Neu verbinden')
    await show(<ConnectionCard app={APP} view={view({ state: 'resting' })} request={request} defaultOpen />)
    expect(byTest('connection-resting')).not.toBeNull()
    await show(<ConnectionCard app={APP} view={view({ state: 'off' })} request={request} defaultOpen />)
    expect(byTest('connection-off')).not.toBeNull()
  })

  it('an older connection by API key: shown as it is, and "läuft ab" with its day', async () => {
    const legacy = { shown: 'ntk_AbCd', expires_at: '2026-12-03T10:00:00+00:00' }
    await show(<ConnectionCard app={APP} view={view({ state: 'expiring', account: null, legacy })} request={request} manual={<p>form</p>} defaultOpen />)
    expect(byTest('connection-state')?.textContent).toBe('Läuft ab')
    expect(byTest('connection-expiring')).not.toBeNull()
    expect(byTest('connection-facts')?.textContent).toContain('ntk_AbCd')
    expect(byTest('connection-connect')?.textContent).toBe('Neu verbinden')
    // E65 (0.1.5): a day with two digits, in English as well.
    expect(byTest('connection-until')?.textContent).toContain('03.12.2026')
    await show(<ConnectionCard key="en" app={APP} view={view({ state: 'expiring', account: null, legacy })} request={request} manual={<p>form</p>} language="en" defaultOpen />, 'en')
    expect(byTest('connection-until')?.textContent).toContain('03/12/2026')
  })

  it('writes a moment in the one form of every app (E65) and the area word small in an English sentence (M-19)', async () => {
    await show(<ConnectionCard app={APP} view={view()} request={request} language="en" defaultOpen />, 'en')
    expect(byTest('connection-ok-at')?.textContent).toMatch(/(\d\d\/\d\d\/\d{4}|today|yesterday), \d\d:\d\d$/)
    const choice = [{ id: 1, name: 'Work' }]
    await show(<ConnectionCard key="areas" app={APP} view={view({ state: 'none', account: null, areas_choice: choice, grants: ['some.read'], grants_levels: { 'some.read': 'read' } })} request={request} areaWord="Address books" language="en" defaultOpen />, 'en')
    expect(byTest('connection-all-areas')?.parentElement?.textContent).toContain('All address books, including later ones')
  })

  it('at 420 px keeps the partner\'s name whole and puts state and address under it as one (V-15)', async () => {
    await show(
      <div style={{ width: '420px' }}>
        <ConnectionCard app={APP} view={view({ state: 'unreachable', stale_since: '2026-11-26T14:05:00+00:00', host: 'a-very-long-host-name.example.com' })} request={request} />
      </div>,
    )
    const main = box.querySelector<HTMLElement>('[data-part="collapsible-main"]')!
    expect(main.className.split(' ')).toContain('flex-wrap')
    const title = main.querySelector<HTMLElement>('[data-part="collapsible-title"]')!
    expect(title.textContent).toContain(PARTNER)
    expect(title.className.split(' ')).toEqual(expect.arrayContaining(['min-w-[min(100%,10rem)]', 'basis-40']))
    const summary = main.querySelector<HTMLElement>('[data-testid="connection-summary"]')!
    expect(summary.className.split(' ')).toEqual(expect.arrayContaining(['min-w-0', 'max-w-full']))
    expect(byTest('connection-state')!.parentElement!.className.split(' ')).toContain('shrink-0')
    expect(Array.from(summary.querySelectorAll('span')).some((part) => part.className.includes('truncate'))).toBe(true)
  })

  it('says what each app may do under its own sentence, without arrows (B10, 0.2.0)', async () => {
    for (const state of ['none', 'connected'] as const) {
      await show(<ConnectionCard key={state} app={APP} view={view({ state })} request={request} defaultOpen />)
      if (FIRST_USE) expect(byTest('connection-app-may')?.textContent).toContain(`${APP} darf bei ${PARTNER}`)
      else expect(byTest('connection-app-may')).toBeNull()
      if (FIRST_GRANT) expect(byTest('connection-partner-may')?.textContent).toContain(`${PARTNER} darf bei ${APP}`)
      else expect(byTest('connection-partner-may')).toBeNull()
      expect(box.querySelector('.lucide-arrow-left, .lucide-arrow-right'), state).toBeNull()
    }
    await show(<ConnectionCard key="nothing" app={APP} view={view({ state: 'none', uses: [], grants: [] })} request={request} defaultOpen />)
    expect(byTest('connection-would-flow')?.textContent).toContain(VERBINDEN_TEXTS.de.card.onlyCheck)
  })

  it('the button waits only until this page is back in front or the time is up (B13, 0.2.0)', async () => {
    answers[`POST /api/connect/partners/${PARTNER}/start`] = { go: 'https://partner.example.com/connect/app?state=s' }
    await show(<ConnectionCard app={APP} view={view({ state: 'none', account: null })} request={request} navigate={(url) => went.push(url)} defaultOpen />)
    await click('connection-connect')
    expect(went).toHaveLength(1)
    expect((byTest('connection-connect') as HTMLButtonElement).disabled).toBe(true)
    // Right after leaving a return does not count yet.
    await act(async () => {
      window.dispatchEvent(new Event('focus'))
    })
    expect((byTest('connection-connect') as HTMLButtonElement).disabled).toBe(true)
    await pause(RETURN_GRACE_MS + 50)
    await act(async () => {
      window.dispatchEvent(new Event('focus'))
    })
    expect((byTest('connection-connect') as HTMLButtonElement).disabled).toBe(false)
    expect(byTest('connection-stopped')?.textContent).toBe(VERBINDEN_TEXTS.de.card.aborted.replaceAll('{partner}', PARTNER))
    // Nothing comes back at all: free again after the time.
    await show(<ConnectionCard key="slow" app={APP} view={view({ state: 'none', account: null })} request={request} navigate={(url) => went.push(url)} waitSeconds={0.1} defaultOpen />)
    await click('connection-connect')
    expect((byTest('connection-connect') as HTMLButtonElement).disabled).toBe(true)
    await pause(200)
    expect((byTest('connection-connect') as HTMLButtonElement).disabled).toBe(false)
    expect(byTest('connection-stopped')?.textContent).toBe(VERBINDEN_TEXTS.de.card.timedOut.replaceAll('{partner}', PARTNER))
    await click('connection-connect')
    expect(byTest('connection-stopped')).toBeNull()
  })

  it('an older connection by API key ends with "Trennen" where the app can forget it (B9, 0.2.0)', async () => {
    answers[`DELETE /api/connect/partners/${PARTNER}`] = view({ state: 'none', legacy: null })
    const legacy = { shown: 'ntk_AbCd', expires_at: null, can_end: true }
    await show(<ConnectionCard app={APP} view={view({ state: 'legacy', account: null, legacy })} request={request} defaultOpen />)
    expect(byTest('connection-disconnect')?.textContent).toBe('Trennen')
    await click('connection-disconnect')
    const dialog = byTest('connection-disconnect-dialog') ?? (document.body.querySelector('[data-testid="connection-disconnect-dialog"]') as HTMLElement | null)
    expect(dialog?.textContent).toContain(VERBINDEN_TEXTS.de.disconnect.legacyText.replaceAll('{app}', APP).replaceAll('{partner}', PARTNER))
    await confirmDialog()
    expect(calls.at(-1)).toMatchObject({ path: `/api/connect/partners/${PARTNER}`, method: 'DELETE' })
    await show(<ConnectionCard key="older" app={APP} view={view({ state: 'legacy', account: null, legacy: { ...legacy, can_end: false } })} request={request} defaultOpen />)
    expect(byTest('connection-disconnect')).toBeNull()
  })

  it('speaks English and French', async () => {
    await show(<ConnectionCard app={APP} view={view({ state: 'none' })} request={request} />, 'en')
    expect(byTest('connection-state')?.textContent).toBe('Not connected')
    await show(<ConnectionCard app={APP} view={view({ state: 'none' })} request={request} />, 'fr')
    expect(byTest('connection-state')?.textContent).toBe('Non connecté')
  })
})

describe('the cards of all partners', () => {
  it('loads them once, 24 px apart, each with the mark the module brings (V21)', async () => {
    answers['GET /api/connect/partners'] = [view({ state: 'none' }), view({ partner: 'nexpaper', state: 'unreachable' })]
    await show(<ConnectionsArea app={APP} request={request} />)
    expect(byTest(`connection-${PARTNER}`)).not.toBeNull()
    expect(byTest('connection-nexpaper')).not.toBeNull()
    expect(byTest('connections-area')?.className).toContain('gap-6')
    const mark = byTest(`connection-${PARTNER}`)?.querySelector('img')
    expect(mark?.getAttribute('src')?.startsWith('data:image/svg+xml,')).toBe(true)
    expect(calls.filter((call) => call.path === '/api/connect/partners')).toHaveLength(1)
  })

  it('a refusal from the way to the partner and back stands in its card, once (B6, V47)', async () => {
    answers['GET /api/connect/partners'] = [view({ state: 'none' })]
    expect(carryProblem({ partner: PARTNER, code: 'partner_off' })).toBe(true)
    await show(<ConnectionsArea app={APP} request={request} />)
    expect(byTest('connection-problem')?.textContent).toBe(VERBINDEN_TEXTS.de.errors.partner_off)
    expect(byTest('connections-problem')).toBeNull()
    await show(<ConnectionsArea key="again" app={APP} request={request} />)
    expect(byTest('connection-problem')).toBeNull()
    // A refusal that names no partner of the list stands above the cards.
    carryProblem({ partner: null, code: 'return_invalid' })
    await show(<ConnectionsArea key="none" app={APP} request={request} />)
    expect(byTest('connections-problem')?.textContent).toBe(VERBINDEN_TEXTS.de.errors.return_invalid)
  })
})

describe('the consent page', () => {
  const search = '?client_id=https%3A%2F%2Ftime.example.com&redirect_uri=https%3A%2F%2Ftime.example.com%2Fconnect%2Freturn&state=s1&code_challenge=c&code_challenge_method=S256'
  // The page in this app; the partner asks. What the partner may here is what this app grants (GRANTS).
  const info: ConsentInfo = {
    app: APP,
    partner: PARTNER,
    partner_host: 'partner.example.com',
    account: 'kim',
    account_card: { name: 'Kim Example', username: 'kim', picture: null, color: null },
    partner_may: Object.entries(GRANTS).map(([id, level]) => ({ id, level, areas: true })),
    app_may: Object.entries(USES).map(([id, level]) => ({ id, level, areas: true })),
    areas: [{ id: 11, name: 'Zuhause' }, { id: 12, name: 'Garten' }],
    replaces: false,
  }

  it('shows who asks and both directions, and gives the areas chosen', async () => {
    answers['GET /api/connect/consent'] = info
    answers['POST /api/connect/consent'] = { redirect: 'https://time.example.com/connect/return?code=x&state=s1' }
    await show(<ConsentPage request={request} search={search} navigate={(url) => went.push(url)} />)
    expect(box.textContent).toContain(`${PARTNER} möchte sich mit ${APP} verbinden`)
    // B1 (0.1.8): the account with its shown name, its user name and its picture (the letter, where it has none).
    expect(byTest('consent-account-name')?.textContent).toBe('Kim Example (kim)')
    expect(byTest('consent-account')?.textContent).toContain('Angemeldet als')
    expect(byTest('consent-account-picture')?.textContent).toBe('K')
    expect(box.textContent).not.toContain('Angemeldet als kim.')
    // B4 (0.1.8): a direction in which an app may do nothing has no box.
    if (FIRST_GRANT) expect(byTest('consent-partner-may')?.textContent).toContain(word(APP, FIRST_GRANT))
    else expect(byTest('consent-partner-may')).toBeNull()
    if (FIRST_USE) expect(byTest('consent-app-may')?.textContent).toContain(word(PARTNER, FIRST_USE))
    else expect(byTest('consent-app-may')).toBeNull()
    expect(box.textContent).not.toContain(VERBINDEN_TEXTS.de.card.onlyCheck)
    await click('consent-all-areas')
    await click('consent-area-12')
    await click('consent-allow')
    expect(calls.at(-1)).toMatchObject({ path: '/api/connect/consent', method: 'POST', body: { allow: true, areas: [12], state: 's1' } })
    expect(went).toEqual(['https://time.example.com/connect/return?code=x&state=s1'])
  })

  it('a no goes back as well, and an incomplete call says so', async () => {
    answers['GET /api/connect/consent'] = info
    answers['POST /api/connect/consent'] = { redirect: 'https://time.example.com/connect/return?error=access_denied' }
    await show(<ConsentPage request={request} search={search} navigate={(url) => went.push(url)} />)
    // MCP 20 (0.1.4): "Ablehnen" secondary with X on the left, "Verbinden erlauben" primary with a check on the right.
    const pair = Array.from(box.querySelectorAll<HTMLElement>('[data-testid="consent-decline"], [data-testid="consent-allow"]'))
    expect(pair.map((found) => [found.dataset.testid, found.dataset.kind, found.dataset.icon, found.textContent])).toEqual([
      ['consent-decline', 'secondary', 'X', 'Ablehnen'],
      ['consent-allow', 'primary', 'Check', 'Verbinden erlauben'],
    ])
    await click('consent-decline')
    expect(calls.at(-1)).toMatchObject({ body: { allow: false } })
    await show(<ConsentPage key="broken" request={request} search="?client_id=x" />)
    expect(byTest('consent-problem')?.textContent).toBe(VERBINDEN_TEXTS.de.consent.broken)
  })

  it('stands in the middle of the window, in every app the same (B5, V48)', async () => {
    await show(<ConsentPage request={request} search="?client_id=x" />)
    expect(byTest('connect-consent')?.className.split(' ')).toEqual(expect.arrayContaining(['min-h-dvh', 'items-center', 'justify-center']))
    refuse['POST /api/connect/return'] = { code: 'return_invalid' }
    await show(<ReturnPage app={APP} request={request} search="?code=c&state=s" navigate={() => undefined} />)
    expect(byTest('connect-return')?.className.split(' ')).toEqual(expect.arrayContaining(['min-h-dvh', 'items-center', 'justify-center']))
  })

  it('asks once, also without a way of the app to another page (0.1.9)', async () => {
    answers['GET /api/connect/consent'] = info
    await show(<ConsentPage request={request} search={search} />)
    await show(<ConsentPage request={request} search={search} navigate={(url) => went.push(url)} />)
    await act(async () => {
      await new Promise((done) => setTimeout(done, 50))
    })
    expect(calls.filter((call) => call.path.startsWith('/api/connect/consent'))).toHaveLength(1)
  })

  it('says what the app that asks sends about a person (V53, 0.1.13)', async () => {
    answers['GET /api/connect/consent'] = { ...info, partner_sends_person: true }
    await show(<ConsentPage request={request} search={search} navigate={(url) => went.push(url)} />)
    expect(byTest('consent-partner-sends-person')?.textContent).toBe(
      VERBINDEN_TEXTS.de.card.receivesPerson.replaceAll('{partner}', PARTNER).replaceAll('{app}', APP),
    )
    expect(byTest('consent-app-sends-person')).toBeNull()
  })

  it('a refusal it says itself names the app that refused, and the place there (B14, 0.2.0)', async () => {
    refuse['GET /api/connect/consent'] = { code: 'local_off', app: 'nexfolk' }
    await show(<ConsentPage request={request} search={search} />)
    const said = byTest('consent-problem')?.textContent ?? ''
    expect(said).toBe(VERBINDEN_TEXTS.de.errors.local_off.replaceAll('{app}', 'nexfolk'))
    expect(said.startsWith('nexfolk fragt')).toBe(true)
    expect(said).toContain('Server › Verbindungen › Andere nex-Apps')
    // The app's own name, where it gives one.
    refuse['GET /api/connect/consent'] = { code: 'local_off' }
    await show(<ConsentPage key="own" app={APP} request={request} search={search} />)
    expect(byTest('consent-problem')?.textContent?.startsWith(`${APP} fragt`)).toBe(true)
    for (const words of Object.values(VERBINDEN_TEXTS)) {
      for (const text of Object.values(words.errors)) expect(text).not.toMatch(/Allgemein|General|Général/)
    }
  })

  it('without a way back from the server it offers the page before (B12, 0.2.0)', async () => {
    refuse['GET /api/connect/consent'] = { code: 'client_invalid' }
    await show(<ConsentPage request={request} search={search} back={() => went.push('back')} />)
    expect(byTest('consent-problem')).not.toBeNull()
    await click('consent-back')
    expect(went).toEqual(['back'])
  })

  it('where the app that asks cannot connect here, goes straight back to its card (B6, V47)', async () => {
    const back = 'https://time.example.com/connect/return?error=partner_local_off&state=s1'
    answers['GET /api/connect/consent'] = { back, refused: 'local_off' }
    await show(<ConsentPage request={request} search={search} navigate={(url) => went.push(url)} />)
    expect(went).toEqual([back])
    expect(byTest('consent-problem')).toBeNull()
    expect(byTest('consent-allow')).toBeNull()
  })
})

describe('the page back from the partner', () => {
  it('finishes the connection once and goes to the cards', async () => {
    answers['POST /api/connect/return'] = view()
    await show(<ReturnPage app={APP} request={request} search="?code=c&state=s&iss=https%3A%2F%2Fpartner.example.com" navigate={(url) => went.push(url)} />)
    expect(calls.filter((call) => call.path === '/api/connect/return')).toHaveLength(1)
    expect(calls[0]?.body).toEqual({ code: 'c', state: 's', iss: 'https://partner.example.com' })
    expect(went).toEqual([`/settings/connections#${PARTNER}`])
  })

  it('a refusal, a no or an error mark goes on to the card of the partner (B6, V47)', async () => {
    refuse['POST /api/connect/return'] = { code: 'consent_failed', partner: PARTNER }
    await show(<ReturnPage app={APP} request={request} search="?code=c&state=s" navigate={(url) => went.push(url)} />)
    expect(went).toEqual([`/settings/connections#${PARTNER}`])
    expect(byTest('return-problem')).toBeNull()
    expect(JSON.parse(window.sessionStorage.getItem('nexverbinden.problem') ?? '{}')).toEqual({ partner: PARTNER, code: 'consent_failed' })
    // A no or an error mark of the other app is sent once, with the state, so the start is used up.
    refuse['POST /api/connect/return'] = { code: 'declined', partner: PARTNER }
    await show(<ReturnPage key="no" app={APP} request={request} search="?error=access_denied&state=s2" navigate={(url) => went.push(url)} />)
    expect(calls.at(-1)).toMatchObject({ path: '/api/connect/return', method: 'POST', body: { error: 'access_denied', state: 's2' } })
    expect(went.at(-1)).toBe(`/settings/connections#${PARTNER}`)
  })

  it('says it itself, in the middle, only where the refusal cannot be carried', async () => {
    refuse['POST /api/connect/return'] = { code: 'return_invalid' }
    const storage = Object.getOwnPropertyDescriptor(window, 'sessionStorage')!
    Object.defineProperty(window, 'sessionStorage', { configurable: true, get: () => { throw new Error('blocked') } })
    try {
      await show(<ReturnPage app={APP} request={request} search="?code=c&state=s" navigate={(url) => went.push(url)} />)
    } finally {
      Object.defineProperty(window, 'sessionStorage', storage)
    }
    expect(went).toEqual([])
    expect(byTest('return-problem')?.textContent).toBe(VERBINDEN_TEXTS.de.errors.return_invalid)
  })
})

describe("the operator's card", () => {
  it('comes into view when "Einrichten" led here (#nex-apps, 0.1.10)', async () => {
    const admin: ConnectionsAdmin = { connections: true, partners: [PARTNER], addresses: { [PARTNER]: '' }, local: false }
    answers['GET /api/connect/admin'] = admin
    const seen: Element[] = []
    const kept = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = function (this: Element) {
      seen.push(this)
    }
    try {
      await show(<ConnectionsOperatorCard app={APP} request={request} />)
      expect(seen).toHaveLength(0)
      window.history.replaceState(null, '', '#nex-apps')
      await show(<ConnectionsOperatorCard key="anchor" app={APP} request={request} />)
      expect(seen).toHaveLength(1)
      expect(seen[0]?.id).toBe('nex-apps')
      // 0.1.11: no box around the card; it stands where the app puts it.
      expect(byTest('connections-operator')?.parentElement).toBe(box)
    } finally {
      Element.prototype.scrollIntoView = kept
      window.history.replaceState(null, '', ' ')
    }
  })

  it('one "Speichern" for the switches and every address, each checked at its field (B18, B11, B17, B19, B20)', async () => {
    const admin: ConnectionsAdmin = { connections: true, partners: [PARTNER, SECOND], addresses: { [PARTNER]: '', [SECOND]: '' }, local: false, suggestions: [] }
    answers['GET /api/connect/admin'] = admin
    answers['PUT /api/connect/admin'] = {
      ...admin,
      local: true,
      addresses: { [PARTNER]: 'https://partner.example.com', [SECOND]: 'https://second.example.com' },
      saved: ['local', PARTNER, SECOND],
      checks: {
        [PARTNER]: { ok: true, code: 'found', app: PARTNER, version: '0.9.0' },
        [SECOND]: { ok: false, code: 'wrong_app', app: 'nextime', version: '1.0.0' },
      },
    }
    await show(<ConnectionsOperatorCard app={APP} request={request} />)
    // B19, B20: the mark and the wordmark of the nex apps in the head; B17: the mark of each app at its address.
    expect(byTest('connections-operator')?.querySelector('[data-mark="nex"]')).not.toBeNull()
    expect(byTest('connections-operator')?.querySelector('[data-wordmark="nex"]')).not.toBeNull()
    expect(byTest(`connections-mark-${PARTNER}`)?.getAttribute('src')?.startsWith('data:image/svg+xml,')).toBe(true)
    expect(byTest(`connections-mark-${SECOND}`)).not.toBeNull()
    expect(box.querySelectorAll('[data-testid^="connections-save-"]')).toHaveLength(0)
    // Nothing is kept before "Speichern".
    await click('connections-local')
    await typeInto(`connections-address-${PARTNER}`, 'https://partner.example.com')
    await typeInto(`connections-address-${SECOND}`, 'https://second.example.com')
    expect(calls.filter((call) => call.method === 'PUT')).toHaveLength(0)
    await click('connections-save')
    expect(calls.at(-1)).toEqual({
      path: '/api/connect/admin',
      method: 'PUT',
      body: { connections: true, local: true, addresses: { [PARTNER]: 'https://partner.example.com', [SECOND]: 'https://second.example.com' } },
    })
    expect(byTest('connections-saved')?.textContent).toBe(`Gespeichert: Verbindungen ins eigene Netz, ${PARTNER}, ${SECOND}.`)
    expect(byTest(`connections-field-${PARTNER}`)?.textContent).toContain(`Gefunden: ${PARTNER} 0.9.0`)
    expect(byTest(`connections-field-${SECOND}`)?.textContent).toContain(`dort antwortet nextime, nicht ${SECOND}`)
    expect((byTest('connections-local') as HTMLInputElement).checked).toBe(true)
  })

  it('a field that is no address keeps nothing and says so at the field (B18)', async () => {
    const admin: ConnectionsAdmin = { connections: true, partners: [PARTNER], addresses: { [PARTNER]: '' }, local: false }
    answers['GET /api/connect/admin'] = admin
    refuse['PUT /api/connect/admin'] = { code: 'address_invalid', partner: PARTNER, fields: { [PARTNER]: 'address_invalid' } }
    await show(<ConnectionsOperatorCard app={APP} request={request} />)
    await typeInto(`connections-address-${PARTNER}`, 'ftp://x')
    await click('connections-save')
    expect(byTest(`connections-field-${PARTNER}`)?.textContent).toContain(VERBINDEN_TEXTS.de.errors.address_invalid)
    expect(byTest('connections-saved')?.textContent).toBe(VERBINDEN_TEXTS.de.operator.notSaved)
  })

  it('an address another app passed on waits at its field, taken with a click after a check (B16)', async () => {
    const suggestion = { partner: PARTNER, address: 'https://partner.example.com', from: SECOND }
    const admin: ConnectionsAdmin = { connections: true, partners: [PARTNER], addresses: { [PARTNER]: '' }, local: false, suggestions: [suggestion] }
    answers['GET /api/connect/admin'] = admin
    answers[`POST /api/connect/admin/suggestions/${PARTNER}`] = { ...admin, suggestions: [suggestion], saved: [], checks: { [PARTNER]: { ok: false, code: 'unreachable', app: null, version: null } } }
    await show(<ConnectionsOperatorCard app={APP} request={request} />)
    expect(byTest(`connections-suggestion-${PARTNER}`)?.textContent).toContain(`${SECOND} kennt ${PARTNER} unter https://partner.example.com. Übernehmen?`)
    await click(`connections-take-${PARTNER}`)
    expect(calls.at(-1)).toMatchObject({ path: `/api/connect/admin/suggestions/${PARTNER}`, method: 'POST' })
    expect(byTest(`connections-not-taken-${PARTNER}`)?.textContent).toContain('Nicht übernommen:')
    expect((byTest(`connections-address-${PARTNER}`) as HTMLInputElement).value).toBe('')
    answers[`POST /api/connect/admin/suggestions/${PARTNER}`] = {
      ...admin,
      suggestions: [],
      addresses: { [PARTNER]: 'https://partner.example.com' },
      saved: [PARTNER],
      checks: { [PARTNER]: { ok: true, code: 'found', app: PARTNER, version: '0.9.0' } },
    }
    await click(`connections-take-${PARTNER}`)
    expect(byTest(`connections-suggestion-${PARTNER}`)).toBeNull()
    expect((byTest(`connections-address-${PARTNER}`) as HTMLInputElement).value).toBe('https://partner.example.com')
    expect(byTest(`connections-field-${PARTNER}`)?.textContent).toContain(`Gefunden: ${PARTNER} 0.9.0`)
  })
})
