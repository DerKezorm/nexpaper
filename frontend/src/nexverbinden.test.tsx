// Vorlage nexverbinden 0.1.1
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
  type ConnectionsAdmin,
  type ConsentInfo,
  type PartnerView,
  type VerbindenRequest,
} from './vendor/nexverbinden'

// APP: this app's name and a partner of it in the catalog, with what each may do at the other (purpose ids).
const APP = 'nexpaper'
const PARTNER = 'nextasks'
const USES: Record<string, string> = { 'tasks.read': 'read', 'tasks.write': 'write' }
const GRANTS: Record<string, string> = {}

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
    address: 'https://tasks.example.com',
    address_from_operator: false,
    host: 'tasks.example.com',
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
    answers[`POST /api/connect/partners/${PARTNER}/start`] = { go: 'https://tasks.example.com/connect/app?state=s' }
    await show(<ConnectionCard app={APP} view={view({ state: 'none', account: null, host: '', address_from_operator: true })} request={request} navigate={(url) => went.push(url)} defaultOpen />)
    expect(byTest('connection-state')?.textContent).toBe('Nicht verbunden')
    expect((byTest('connection-address') as HTMLInputElement).value).toBe('https://tasks.example.com')
    expect(box.textContent).toContain(VERBINDEN_TEXTS.de.card.fromOperator)
    await click('connection-connect')
    expect(calls.at(-1)).toEqual({ path: `/api/connect/partners/${PARTNER}/start`, method: 'POST', body: { address: 'https://tasks.example.com', areas: null } })
    expect(went).toEqual(['https://tasks.example.com/connect/app?state=s'])
  })

  it('where the partner reads areas here, the card asks for them before the click (all at first)', async () => {
    answers[`POST /api/connect/partners/${PARTNER}/start`] = { go: 'https://tasks.example.com/connect/app?state=s' }
    const choice = [{ id: 1, name: 'Arbeit' }, { id: 2, name: 'Familie' }]
    await show(<ConnectionCard app={APP} view={view({ state: 'none', account: null, areas_choice: choice })} request={request} navigate={(url) => went.push(url)} defaultOpen />)
    expect(byTest('connection-areas')).not.toBeNull()
    expect((byTest('connection-all-areas') as HTMLInputElement).checked).toBe(true)
    expect(byTest('connection-area-1')).toBeNull()
    await click('connection-all-areas')
    expect((byTest('connection-connect') as HTMLButtonElement).disabled).toBe(true)
    await click('connection-area-2')
    await click('connection-connect')
    expect(calls.at(-1)).toMatchObject({ method: 'POST', body: { address: 'https://tasks.example.com', areas: [2] } })
    await show(<ConnectionCard key="plain" app={APP} view={view({ state: 'none', account: null })} request={request} navigate={(url) => went.push(url)} defaultOpen />)
    expect(byTest('connection-areas')).toBeNull()
    await click('connection-connect')
    expect(calls.at(-1)).toMatchObject({ body: { areas: null } })
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
    expect(byTest('connection-state')?.textContent).toBe('Verbunden')
    expect(byTest('connection-summary')?.textContent).toContain('tasks.example.com')
    expect(byTest('connection-app-may')?.textContent).toContain(VERBINDEN_TEXTS.de.purposes.nextasks['tasks.read'])
    expect(byTest('connection-account')?.textContent).toContain('kim')
    expect(byTest('own-part')).not.toBeNull()
    expect(byTest('connection-renew')).not.toBeNull()
    await click('connection-disconnect')
    await confirmDialog()
    expect(calls.at(-1)).toMatchObject({ path: `/api/connect/partners/${PARTNER}`, method: 'DELETE' })
    expect(changed.at(-1)?.state).toBe('none')
  })

  it('a partner that only uses this app: "Nutzt" and "Zugriff beenden"', async () => {
    await show(<ConnectionCard app={APP} view={view({ uses: [], uses_levels: {}, grants: ['tasks.read'], grants_levels: { 'tasks.read': 'read' } })} request={request} defaultOpen />)
    expect(byTest('connection-state')?.textContent).toBe(`Nutzt ${APP}`)
    expect(byTest('connection-disconnect')?.textContent).toBe('Zugriff beenden')
    expect(byTest('connection-renew')).toBeNull()
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
  })

  it('speaks English and French', async () => {
    await show(<ConnectionCard app={APP} view={view({ state: 'none' })} request={request} />, 'en')
    expect(byTest('connection-state')?.textContent).toBe('Not connected')
    await show(<ConnectionCard app={APP} view={view({ state: 'none' })} request={request} />, 'fr')
    expect(byTest('connection-state')?.textContent).toBe('Non connecté')
  })
})

describe('the cards of all partners', () => {
  it('loads them once and keeps a card as the server answers', async () => {
    answers['GET /api/connect/partners'] = [view({ state: 'none' }), view({ partner: 'nexpaper', state: 'unreachable' })]
    await show(<ConnectionsArea app={APP} request={request} logos={{ [PARTNER]: '/apps/nextasks.svg' }} />)
    expect(byTest(`connection-${PARTNER}`)).not.toBeNull()
    expect(byTest('connection-nexpaper')).not.toBeNull()
    expect(calls.filter((call) => call.path === '/api/connect/partners')).toHaveLength(1)
  })
})

describe('the consent page', () => {
  const search = '?client_id=https%3A%2F%2Ftime.example.com&redirect_uri=https%3A%2F%2Ftime.example.com%2Fconnect%2Freturn&state=s1&code_challenge=c&code_challenge_method=S256'
  const info: ConsentInfo = {
    app: PARTNER,
    partner: APP,
    partner_host: 'time.example.com',
    account: 'kim',
    partner_may: [{ id: 'tasks.read', level: 'read', areas: true }],
    app_may: [],
    areas: [{ id: 11, name: 'Zuhause' }, { id: 12, name: 'Garten' }],
    replaces: false,
  }

  it('shows who asks and both directions, and gives the areas chosen', async () => {
    answers['GET /api/connect/consent'] = info
    answers['POST /api/connect/consent'] = { redirect: 'https://time.example.com/connect/return?code=x&state=s1' }
    await show(<ConsentPage request={request} search={search} navigate={(url) => went.push(url)} />)
    expect(box.textContent).toContain(`${APP} möchte sich mit ${PARTNER} verbinden`)
    expect(byTest('consent-partner-may')?.textContent).toContain(VERBINDEN_TEXTS.de.purposes.nextasks['tasks.read'])
    expect(byTest('consent-app-may')?.textContent).toContain(VERBINDEN_TEXTS.de.card.onlyCheck)
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
    await click('consent-decline')
    expect(calls.at(-1)).toMatchObject({ body: { allow: false } })
    await show(<ConsentPage key="broken" request={request} search="?client_id=x" />)
    expect(byTest('consent-problem')?.textContent).toBe(VERBINDEN_TEXTS.de.consent.broken)
  })
})

describe('the page back from the partner', () => {
  it('finishes the connection once and goes to the cards', async () => {
    answers['POST /api/connect/return'] = view()
    await show(<ReturnPage app={APP} request={request} search="?code=c&state=s&iss=https%3A%2F%2Ftasks.example.com" navigate={(url) => went.push(url)} />)
    expect(calls.filter((call) => call.path === '/api/connect/return')).toHaveLength(1)
    expect(calls[0]?.body).toEqual({ code: 'c', state: 's', iss: 'https://tasks.example.com' })
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
    const admin: ConnectionsAdmin = { connections: true, partners: [PARTNER], addresses: { [PARTNER]: '' } }
    answers['GET /api/connect/admin'] = admin
    answers['PUT /api/connect/admin'] = { ...admin, connections: false }
    await show(<ConnectionsOperatorCard app={APP} request={request} />)
    await click('connections-switch')
    expect(calls.at(-1)).toMatchObject({ method: 'PUT', body: { connections: false } })
    await click(`connections-save-${PARTNER}`)
    expect(calls.at(-1)).toMatchObject({ method: 'PUT', body: { addresses: { [PARTNER]: '' } } })
  })
})
