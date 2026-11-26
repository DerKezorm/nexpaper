// Vorlage nexverbinden 0.1.6
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
  ReturnPage,
  VERBINDEN_TEXTS,
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
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
})

describe('the card of a partner app', () => {
  it('not connected: the address from the operator, then off to the partner', async () => {
    answers[`POST /api/connect/partners/${PARTNER}/start`] = { go: 'https://partner.example.com/connect/app?state=s' }
    await show(<ConnectionCard app={APP} view={view({ state: 'none', account: null, host: '', address_from_operator: true })} request={request} navigate={(url) => went.push(url)} defaultOpen />)
    expect(byTest('connection-state')?.textContent).toBe('Nicht verbunden')
    expect((byTest('connection-address') as HTMLInputElement).value).toBe('https://partner.example.com')
    expect(box.textContent).toContain(VERBINDEN_TEXTS.de.card.fromOperator)
    await click('connection-connect')
    expect(calls.at(-1)).toEqual({ path: `/api/connect/partners/${PARTNER}/start`, method: 'POST', body: { address: 'https://partner.example.com', areas: null } })
    expect(went).toEqual(['https://partner.example.com/connect/app?state=s'])
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
    expect(calls.at(-1)).toMatchObject({ method: 'POST', body: { address: 'https://partner.example.com', areas: [2] } })
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
    await show(<ConnectionCard app={APP} view={view({ state: 'none', account: null })} request={request} manual={<p data-testid="own-form">form</p>} defaultOpen />)
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
})

describe('the consent page', () => {
  const search = '?client_id=https%3A%2F%2Ftime.example.com&redirect_uri=https%3A%2F%2Ftime.example.com%2Fconnect%2Freturn&state=s1&code_challenge=c&code_challenge_method=S256'
  // The page in this app; the partner asks. What the partner may here is what this app grants (GRANTS).
  const info: ConsentInfo = {
    app: APP,
    partner: PARTNER,
    partner_host: 'partner.example.com',
    account: 'kim',
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
    expect(byTest('consent-partner-may')?.textContent).toContain(FIRST_GRANT ? word(APP, FIRST_GRANT) : VERBINDEN_TEXTS.de.card.onlyCheck)
    expect(byTest('consent-app-may')?.textContent).toContain(FIRST_USE ? word(PARTNER, FIRST_USE) : VERBINDEN_TEXTS.de.card.onlyCheck)
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
})

describe('the page back from the partner', () => {
  it('finishes the connection once and goes to the cards', async () => {
    answers['POST /api/connect/return'] = view()
    await show(<ReturnPage app={APP} request={request} search="?code=c&state=s&iss=https%3A%2F%2Fpartner.example.com" navigate={(url) => went.push(url)} />)
    expect(calls.filter((call) => call.path === '/api/connect/return')).toHaveLength(1)
    expect(calls[0]?.body).toEqual({ code: 'c', state: 's', iss: 'https://partner.example.com' })
    expect(went).toEqual([`/settings/connections#${PARTNER}`])
  })

  it('a refusal stands with the way back; a no sends nothing', async () => {
    refuse['POST /api/connect/return'] = { code: 'return_invalid' }
    await show(<ReturnPage app={APP} request={request} search="?code=c&state=s" navigate={(url) => went.push(url)} />)
    expect(byTest('return-problem')?.textContent).toBe(VERBINDEN_TEXTS.de.errors.return_invalid)
    calls = []
    await show(<ReturnPage key="no" app={APP} request={request} search="?error=access_denied" />)
    expect(calls).toEqual([])
  })
})

describe("the operator's card", () => {
  it('switches connections and keeps the addresses', async () => {
    const admin: ConnectionsAdmin = { connections: true, partners: [PARTNER], addresses: { [PARTNER]: '' }, local: false }
    answers['GET /api/connect/admin'] = admin
    answers['PUT /api/connect/admin'] = { ...admin, connections: false }
    await show(<ConnectionsOperatorCard app={APP} request={request} />)
    expect(byTest('connections-saved')).toBeNull()
    await click('connections-switch')
    expect(calls.at(-1)).toMatchObject({ method: 'PUT', body: { connections: false } })
    expect(byTest('connections-saved')?.textContent).toBe('Gespeichert.')
    // V-12 (0.1.4): the own network as a box to tick, kept at once (MCP 21).
    const local = byTest('connections-local') as HTMLInputElement
    expect(local.checked).toBe(false)
    expect(local.parentElement!.textContent).toContain('Verbindungen ins eigene Netz')
    expect(local.parentElement!.textContent).toContain(`Dann kann jedes Konto ${APP} Adressen dort ansprechen lassen.`)
    answers['PUT /api/connect/admin'] = { ...admin, connections: false, local: true }
    await click('connections-local')
    expect(calls.at(-1)).toMatchObject({ method: 'PUT', body: { local: true } })
    expect((byTest('connections-local') as HTMLInputElement).checked).toBe(true)
    expect(byTest('connections-saved')?.textContent).toBe('Gespeichert.')
    await click(`connections-save-${PARTNER}`)
    expect(calls.at(-1)).toMatchObject({ method: 'PUT', body: { addresses: { [PARTNER]: '' } } })
  })
})
