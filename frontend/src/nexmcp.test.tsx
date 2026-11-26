// Vorlage nexmcp 1.1.2
// @vitest-environment jsdom
/**
 * The parts of the module in the app: "Rechte je Werkzeug", "Wartende Rückfragen", the page of one request, the row in
 * the bell, the consent page "Programm verbinden" and the operator's settings, built from the ui kit, the module's
 * words in German, English and French. What each part shows and what it sends: the rights of every tool at once, a
 * dangerous request only with `confirm` after a second question, the consent with level, areas and extras, then on to
 * the program's address. Copied once by bauplaene/mcp/tools/sync.py to `frontend/src/nexmcp.test.tsx`; then the app's
 * file. Fill in the places marked APP. Needs react-dom (in every app).
 */
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { NexuiLanguage } from './vendor/nexui'
import {
  ConsentPage,
  MCP_TEXTS,
  McpOperatorSettings,
  PendingRequests,
  RequestBellRow,
  RequestPage,
  ToolRights,
  type ConsentInfo,
  type KeyRights,
  type McpAdmin,
  type McpRequest,
  type McpWords,
  type ToolRequest,
} from './vendor/nexmcp'

// APP: where the app mounts the module's routes (`AppConfig.prefix`, `oauth_prefix`), its levels (lowest first), an
// extra of its keys (or none: then the test of extras says so), and its words for a few tools.
const BASE = '/api/v1/connections/mcp'
const OAUTH = '/api/oauth'
const LEVELS = ['read', 'write']
// nexpaper's keys have no extra (yet): the tests of extras say so.
const EXTRA: string = ''
const WORDS: McpWords = { tools: { read_note: 'Notiz lesen', write_note: 'Notiz schreiben' }, extras: {} }

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Call = { path: string; method: string; body: unknown }

let root: Root
let box: HTMLDivElement
let calls: Call[]
let rights: KeyRights
let waiting: ToolRequest[]
let consent: ConsentInfo
let admin: McpAdmin
let refuse: Record<string, unknown> | null
let refuseGet: Record<string, unknown> | null

function ask(id: number, extra: Partial<ToolRequest> = {}): ToolRequest {
  return {
    id,
    key_id: 3,
    key_name: 'Notebook',
    tool: 'write_note',
    arguments: { path: 'Inbox/Plan.md', text: 'Hello' },
    summary: null,
    dangerous: false,
    status: 'waiting',
    created_at: '2026-11-25T09:00:00+00:00',
    expires_at: '2026-11-26T09:00:00+00:00',
    decided_at: null,
    decided_by: null,
    result: null,
    ...extra,
  }
}

function freshRights(): KeyRights {
  return {
    key: { id: 3, name: 'Notebook', program: true },
    level: 'read',
    tools: [
      { name: 'read_note', group: 'read', right: 'allow', asks_never: true, reason: null, always: false },
      { name: 'write_note', group: 'change', right: 'allow', asks_never: false, reason: null, always: false },
      { name: 'delete_note', group: 'risky', right: 'ask', asks_never: false, reason: 'blocked', always: false },
      { name: 'list_accounts', group: 'admin', right: 'allow', asks_never: true, reason: 'admin', always: false },
      { name: 'request_status', group: 'read', right: 'allow', asks_never: true, reason: null, always: true },
    ],
  }
}

const request: McpRequest = async <T,>(path: string, init: { method?: string; body?: unknown } = {}) => {
  const method = init.method ?? 'GET'
  calls.push({ path, method, body: init.body })
  if (refuseGet && method === 'GET') {
    const detail = refuseGet
    refuseGet = null
    throw Object.assign(new Error('refused'), { detail })
  }
  if (refuse && method !== 'GET') {
    const detail = refuse
    refuse = null
    throw Object.assign(new Error('refused'), { detail })
  }
  if (path === `${BASE}/keys/3/rights` && method === 'PUT') {
    const wanted = (init.body as { rights: Record<string, KeyRights['tools'][number]['right']> }).rights
    rights = { ...rights, tools: rights.tools.map((row) => ({ ...row, right: wanted[row.name] ?? row.right })) }
    return rights as T
  }
  if (path === `${BASE}/keys/3/rights`) return rights as T
  if (path === `${BASE}/requests?status=waiting`) return waiting.filter((entry) => entry.status === 'waiting') as T
  const one = path.match(new RegExp(`^${BASE}/requests/(\\d+)(?:/(approve|decline))?$`))
  if (one) {
    const found = waiting.find((entry) => String(entry.id) === one[1])!
    if (!one[2]) return found as T
    const done = { ...found, status: one[2] === 'approve' ? 'done' : 'declined', decided_at: '2026-11-25T10:00:00+00:00', decided_by: 'anna' } as ToolRequest
    waiting = waiting.map((entry) => (entry.id === found.id ? done : entry))
    return done as T
  }
  if (path.startsWith(`${OAUTH}/authorize?`)) return consent as T
  if (path === `${OAUTH}/authorize` && method === 'POST') {
    const body = init.body as { allow: boolean; state?: string }
    return { redirect: `http://127.0.0.1:3334/callback?${body.allow ? 'code=abc' : 'error=access_denied'}&state=${body.state ?? ''}` } as T
  }
  if (path === `${BASE}/admin` && method === 'PUT') {
    admin = { ...admin, ...(init.body as Partial<McpAdmin>) }
    return admin as T
  }
  if (path === `${BASE}/admin`) return admin as T
  throw new Error(`unexpected ${method} ${path}`)
}

function show(node: ReactNode, language = 'de'): void {
  act(() => root.render(<NexuiLanguage language={language}>{node}</NexuiLanguage>))
}

async function settle(): Promise<void> {
  await act(async () => await new Promise((resolve) => setTimeout(resolve, 0)))
}

function click(element: Element | null | undefined): void {
  expect(element).toBeTruthy()
  act(() => (element as HTMLElement).click())
}

const find = <T extends Element = HTMLElement>(selector: string) => document.querySelector<T>(selector)
const all = (selector: string) => Array.from(document.querySelectorAll<HTMLElement>(selector))
const byTestId = (testId: string) => find<HTMLButtonElement>(`[data-testid="${testId}"]`)
const posts = () => calls.filter((call) => call.method !== 'GET')
/** A row of the list "Rechte je Werkzeug" (since 1.1.2 a list of rows, no table). */
const rightRow = (tool: string) => find(`[data-testid="tool-rights-table"] [data-tool="${tool}"]`)!
const SEARCH = '?client_id=c1&redirect_uri=http%3A%2F%2F127.0.0.1%3A3334%2Fcallback&response_type=code&code_challenge=x1&code_challenge_method=S256&state=s1&resource=https%3A%2F%2Fnotes.example.com%2Fapi%2Fmcp'

beforeEach(() => {
  calls = []
  refuse = null
  refuseGet = null
  rights = freshRights()
  waiting = [ask(1, { summary: 'Write “Plan” in Inbox' }), ask(2, { dangerous: true, tool: 'delete_note', arguments: { path: 'Old.md' } })]
  consent = {
    app: 'nexapp',
    client: { id: 'c1', name: 'Notebook' },
    redirect_uri: 'http://127.0.0.1:3334/callback',
    redirect_host: '127.0.0.1:3334',
    levels: LEVELS,
    level: LEVELS[0]!,
    areas: [
      { id: 1, name: 'Inbox' },
      { id: 2, name: 'Work' },
    ],
    extras: EXTRA ? [EXTRA] : [],
    ai_allowed: true,
  }
  admin = {
    programs: true,
    levels: LEVELS,
    max_level: LEVELS.at(-1)!,
    blocked_tools: [],
    tools: [
      { name: 'read_note', group: 'read', level: 'read' },
      { name: 'delete_note', group: 'risky', level: 'write' },
    ],
  }
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  document.body.innerHTML = ''
})

describe('the words of the module', () => {
  it("have the same keys in German, English and French, and the plan's words in German", () => {
    const shape = (value: unknown): unknown =>
      typeof value === 'object' && value ? Object.fromEntries(Object.entries(value).map(([name, inner]) => [name, shape(inner)])) : typeof value
    expect(shape(MCP_TEXTS.en)).toEqual(shape(MCP_TEXTS.de))
    expect(shape(MCP_TEXTS.fr)).toEqual(shape(MCP_TEXTS.de))
    expect(MCP_TEXTS.de.rights.open).toBe('Rechte je Werkzeug')
    expect([MCP_TEXTS.de.rights.allow, MCP_TEXTS.de.rights.ask, MCP_TEXTS.de.rights.deny]).toEqual(['Erlauben', 'Fragen', 'Verweigern'])
    expect(Object.values(MCP_TEXTS.de.groups)).toEqual(['Lesen', 'Entwerfen', 'Ändern', 'Riskant', 'Verwaltung'])
    expect(MCP_TEXTS.de.requests.title).toBe('Wartende Rückfragen')
    expect(MCP_TEXTS.de.requests.none).toBe('Nichts wartet.')
    expect([MCP_TEXTS.de.requests.approve, MCP_TEXTS.de.requests.decline]).toEqual(['Erlauben', 'Ablehnen'])
    expect(MCP_TEXTS.de.operator.programs).toBe('Programme dürfen sich verbinden')
    expect(MCP_TEXTS.de.consent.after).toContain('Mein Konto › Verbindungen')
  })
})

describe('Rechte je Werkzeug', () => {
  it('opens with a small secondary button and lists every tool but request_status, in the app\'s words', async () => {
    show(<ToolRights request={request} keyId={3} base={BASE} words={WORDS} />)
    const open = byTestId('tool-rights')!
    expect([open.dataset.kind, open.dataset.size, open.dataset.icon, open.textContent]).toEqual(['secondary', 'sm', 'SlidersHorizontal', 'Rechte je Werkzeug'])
    click(open)
    await settle()
    expect(find('[data-testid="tool-rights-dialog"]')!.textContent).toContain('Rechte für „Notebook“')
    expect(find('[data-testid="tool-rights-dialog"] [data-part="table"]')).toBeNull()
    expect(find('[data-testid="tool-rights-search"]')).toBeNull()
    const rows = all('[data-testid="tool-rights-table"] [data-testid="tool-right-row"]')
    expect(rows.map((row) => row.dataset.tool)).toEqual(['read_note', 'write_note', 'delete_note', 'list_accounts'])
    expect(rightRow('read_note').textContent).toContain('Notiz lesen')
    expect(rightRow('write_note').textContent).toContain('Ändern')
    expect(rightRow('list_accounts').textContent).toContain('Verwaltung')
  })

  it('greys out a tool out of reach, with the reason, and offers no "Fragen" for a tool that only looks', async () => {
    show(<ToolRights request={request} keyId={3} base={BASE} words={WORDS} />)
    click(byTestId('tool-rights'))
    await settle()
    const blocked = rightRow('delete_note')
    expect(blocked.dataset.disabled).toBe('true')
    expect(blocked.textContent).toContain('Vom Betreiber gesperrt.')
    expect(rightRow('list_accounts').textContent).toContain('Nur für Betreiber.')
    for (const radio of Array.from(blocked.querySelectorAll<HTMLButtonElement>('[role="radio"]'))) expect(radio.disabled).toBe(true)
    const open = rightRow('write_note')
    expect(open.dataset.disabled).toBe('false')
    expect(Array.from(open.querySelectorAll<HTMLButtonElement>('[role="radio"]')).map((radio) => [radio.dataset.value, radio.disabled])).toEqual([
      ['allow', false],
      ['ask', false],
      ['deny', false],
    ])
    expect(Array.from(rightRow('read_note').querySelectorAll<HTMLElement>('[role="radio"]')).map((radio) => radio.dataset.value)).toEqual(['allow', 'deny'])
  })

  it('keeps a choice at once with the rights of every tool, says so shortly, and nothing for request_status (MCP 21)', async () => {
    show(<ToolRights request={request} keyId={3} base={BASE} words={WORDS} />)
    click(byTestId('tool-rights'))
    await settle()
    expect(byTestId('tool-rights-save')).toBeNull()
    expect(find('[data-testid="tool-rights-saved"]')).toBeNull()
    click(rightRow('write_note').querySelector('[data-value="ask"]'))
    await settle()
    expect(find('[data-testid="tool-rights-saved"]')!.textContent).toBe('Gespeichert.')
    click(rightRow('read_note').querySelector('[data-value="deny"]'))
    await settle()
    expect(posts()).toEqual([
      { path: `${BASE}/keys/3/rights`, method: 'PUT', body: { rights: { read_note: 'allow', write_note: 'ask', delete_note: 'ask', list_accounts: 'allow' } } },
      { path: `${BASE}/keys/3/rights`, method: 'PUT', body: { rights: { read_note: 'deny', write_note: 'ask', delete_note: 'ask', list_accounts: 'allow' } } },
    ])
    expect(rightRow('read_note').querySelector<HTMLElement>('[data-value="deny"]')!.getAttribute('aria-checked')).toBe('true')
    const close = byTestId('tool-rights-close')!
    expect([close.dataset.kind, close.dataset.icon, close.textContent]).toEqual(['secondary', 'X', 'Schließen'])
    click(close)
    expect(find('[data-testid="tool-rights-dialog"]')).toBeNull()
  })

  it('says why a change was refused and shows the right the server keeps', async () => {
    show(<ToolRights request={request} keyId={3} base={BASE} />)
    click(byTestId('tool-rights'))
    await settle()
    refuse = { code: 'key_unknown' }
    click(rightRow('write_note').querySelector('[data-value="deny"]'))
    await settle()
    expect(find('[data-testid="tool-rights-problem"]')!.textContent).toBe('Diesen Zugang gibt es nicht mehr.')
    expect(find('[data-testid="tool-rights-saved"]')).toBeNull()
    expect(rightRow('write_note').querySelector<HTMLElement>('[data-value="allow"]')!.getAttribute('aria-checked')).toBe('true')
  })

  it('has a search field from 15 tools that finds a tool by its word or its name (M-11)', async () => {
    const many = Array.from({ length: 14 }, (_, at) => ({ name: `tool_${at}`, group: 'read', right: 'allow', asks_never: true, reason: null, always: false }) as const)
    rights = { ...rights, tools: [...rights.tools, ...many] }
    show(<ToolRights request={request} keyId={3} base={BASE} words={WORDS} />)
    click(byTestId('tool-rights'))
    await settle()
    const search = find<HTMLInputElement>('[data-testid="tool-rights-search"]')!
    expect(search.type).toBe('search')
    const type = (value: string) =>
      act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(search, value)
        search.dispatchEvent(new Event('input', { bubbles: true }))
      })
    type('notiz')
    expect(all('[data-testid="tool-right-row"]').map((row) => row.dataset.tool)).toEqual(['read_note', 'write_note'])
    type('TOOL_1')
    expect(all('[data-testid="tool-right-row"]').map((row) => row.dataset.tool)).toEqual(['tool_1', 'tool_10', 'tool_11', 'tool_12', 'tool_13'])
  })
})

describe('Wartende Rückfragen', () => {
  it('lists what waits; a plain one is allowed in the row without confirm, a dangerous one only on its page', async () => {
    show(<PendingRequests request={request} base={BASE} words={WORDS} viewHref={(entry) => `/settings/connections/requests/${entry.id}`} />)
    await settle()
    const rows = all('[data-testid="pending-request"]')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.textContent).toContain('Notebook')
    expect(rows[0]!.textContent).toContain('Notiz schreiben')
    expect(rows[0]!.textContent).toContain('Write “Plan” in Inbox')
    expect(rows[1]!.textContent).toContain('path: Old.md')
    expect(rows[1]!.querySelector('[data-testid="request-dangerous"]')).not.toBeNull()
    expect(rows[1]!.querySelector('[data-testid="request-approve"]')).toBeNull()
    const view = rows[1]!.querySelector<HTMLAnchorElement>('[data-testid="request-view"]')!
    expect(view.getAttribute('href')).toBe('/settings/connections/requests/2')
    const approve = rows[0]!.querySelector<HTMLElement>('[data-testid="request-approve"]')!
    expect([approve.dataset.kind, approve.dataset.size, approve.dataset.icon]).toEqual(['primary', 'sm', 'Check'])
    expect(Array.from(rows[0]!.querySelectorAll<HTMLElement>('[data-size]')).map((found) => found.dataset.testid)).toEqual(['request-decline', 'request-approve'])
    expect(Array.from(rows[1]!.querySelectorAll<HTMLElement>('[data-size]')).map((found) => found.dataset.testid)).toEqual(['request-decline', 'request-view'])
    click(approve)
    await settle()
    expect(posts()).toEqual([{ path: `${BASE}/requests/1/approve`, method: 'POST', body: undefined }])
    expect(all('[data-testid="pending-request"]')).toHaveLength(1)
  })

  it('declines, and says when nothing waits', async () => {
    show(<PendingRequests request={request} base={BASE} />)
    await settle()
    for (const decline of all('[data-testid="request-decline"]')) expect([decline.dataset.kind, decline.dataset.size, decline.dataset.icon]).toEqual(['secondary', 'sm', 'X'])
    click(all('[data-testid="request-decline"]')[1])
    await settle()
    click(all('[data-testid="request-decline"]')[0])
    await settle()
    expect(posts().map((call) => call.path)).toEqual([`${BASE}/requests/2/decline`, `${BASE}/requests/1/decline`])
    expect(find('[data-testid="pending-requests-none"]')!.textContent).toBe('Nichts wartet.')
  })
})

describe('the page of one request', () => {
  it('shows everything about it and allows a plain one at once, without confirm', async () => {
    show(<RequestPage request={request} id={1} base={BASE} words={WORDS} />)
    await settle()
    const page = find('[data-testid="request-page"]')!
    expect(page.textContent).toContain('Rückfrage von „Notebook“')
    expect(page.textContent).toContain('Notiz schreiben')
    expect(find('[data-testid="request-status"]')!.textContent).toBe('Wartet')
    expect(JSON.parse(find('[data-testid="request-arguments"] pre')!.textContent!)).toEqual({ path: 'Inbox/Plan.md', text: 'Hello' })
    const approve = byTestId('request-approve')!
    expect([approve.dataset.kind, approve.dataset.icon]).toEqual(['primary', 'Check'])
    const decline = byTestId('request-decline')!
    expect([decline.dataset.kind, decline.dataset.icon]).toEqual(['secondary', 'X'])
    expect(all('[data-testid="request-page"] [data-size]').map((found) => found.dataset.testid)).toEqual(['request-decline', 'request-approve'])
    click(approve)
    await settle()
    expect(posts()).toEqual([{ path: `${BASE}/requests/1/approve`, method: 'POST', body: undefined }])
    expect(find('[data-testid="request-status"]')!.textContent).toBe('Ausgeführt')
    expect(byTestId('request-approve')).toBeNull()
  })

  it('asks a second time before allowing a dangerous one, and only then sends confirm', async () => {
    show(<RequestPage request={request} id={2} base={BASE} />)
    await settle()
    expect(find('[data-testid="request-dangerous-note"]')).not.toBeNull()
    click(byTestId('request-approve'))
    await settle()
    expect(posts()).toEqual([])
    const dialog = find('[data-testid="request-confirm-dialog"]')!
    expect(dialog.textContent).toContain('wirklich erlauben?')
    const yes = find<HTMLElement>('[data-testid="request-confirm-dialog"] button[type="submit"]')!
    expect([yes.dataset.kind, yes.dataset.icon, yes.textContent]).toEqual(['danger', 'Check', 'Ja, wirklich erlauben'])
    click(Array.from(dialog.querySelectorAll('button')).find((found) => found.textContent === 'Abbrechen'))
    await settle()
    expect(posts()).toEqual([])
    click(byTestId('request-approve'))
    click(find('[data-testid="request-confirm-dialog"] button[type="submit"]'))
    await settle()
    expect(posts()).toEqual([{ path: `${BASE}/requests/2/approve`, method: 'POST', body: { confirm: true } }])
  })

  it('declines, and says when the request was decided meanwhile', async () => {
    show(<RequestPage request={request} id={1} base={BASE} />)
    await settle()
    refuse = { code: 'request_decided' }
    click(byTestId('request-decline'))
    await settle()
    expect(find('[data-testid="request-problem"]')!.textContent).toBe('Diese Rückfrage ist schon entschieden.')
    click(byTestId('request-decline'))
    await settle()
    expect(posts().at(-1)).toEqual({ path: `${BASE}/requests/1/decline`, method: 'POST', body: undefined })
  })
})

describe('the row in the bell', () => {
  it('allows and declines a plain one; a dangerous one only leads to its page', async () => {
    const decided: ToolRequest[] = []
    const seen: ToolRequest[] = []
    show(
      <>
        <RequestBellRow request={request} entry={waiting[0]!} base={BASE} words={WORDS} onDecided={(entry) => decided.push(entry)} testId="bell-1" />
        <RequestBellRow request={request} entry={waiting[1]!} base={BASE} onView={(entry) => seen.push(entry)} testId="bell-2" />
      </>,
    )
    expect(find('[data-testid="bell-1"]')!.textContent).toContain('Notiz schreiben')
    expect(find('[data-testid="bell-2"] [data-testid="request-approve"]')).toBeNull()
    click(find('[data-testid="bell-2"] [data-testid="request-view"]'))
    expect(seen.map((entry) => entry.id)).toEqual([2])
    click(find('[data-testid="bell-1"] [data-testid="request-approve"]'))
    await settle()
    expect(posts()).toEqual([{ path: `${BASE}/requests/1/approve`, method: 'POST', body: undefined }])
    expect(decided.map((entry) => entry.status)).toEqual(['done'])
    click(find('[data-testid="bell-2"] [data-testid="request-decline"]'))
    await settle()
    expect(posts().at(-1)).toEqual({ path: `${BASE}/requests/2/decline`, method: 'POST', body: undefined })
  })
})

describe('Programm verbinden', () => {
  it('shows the program, where it goes back to, the lowest level and the extras off', async () => {
    const went: string[] = []
    show(<ConsentPage request={request} oauthBase={OAUTH} search={SEARCH} words={WORDS} navigate={(url) => went.push(url)} />)
    await settle()
    expect(calls[0]!.path).toBe(`${OAUTH}/authorize${SEARCH}`)
    const page = find('[data-testid="mcp-consent"]')!
    expect(page.textContent).toContain('Notebook möchte nexapp nutzen')
    expect(find('[data-testid="consent-host"]')!.textContent).toBe('127.0.0.1:3334')
    // M-6: where it goes back to stands once, in the line under the title.
    expect(page.textContent!.split('127.0.0.1:3334')).toHaveLength(2)
    expect(find('[data-testid="consent-return-to"]')).toBeNull()
    expect([byTestId('consent-areas-all')!.textContent, byTestId('consent-areas-some')!.textContent]).toEqual(['Alle Bereiche, auch spätere', 'Nur diese Bereiche'])
    expect(find(`[data-testid="consent-level-${LEVELS[0]}"]`)!.getAttribute('aria-checked')).toBe('true')
    for (const extra of all('[data-testid^="consent-extra-"]')) expect((extra as HTMLInputElement).checked).toBe(false)
    if (EXTRA) expect(page.textContent).toContain(WORDS.extras![EXTRA])
    expect(went).toEqual([])
  })

  it('sends allow, the level, the chosen areas and extras with the values of the address, and goes on', async () => {
    const went: string[] = []
    show(<ConsentPage request={request} oauthBase={OAUTH} search={SEARCH} areaWord="Ordner" navigate={(url) => went.push(url)} />)
    await settle()
    expect(find('[data-testid="consent-areas"]')!.textContent).toContain('Ordner')
    expect([byTestId('consent-areas-all')!.textContent, byTestId('consent-areas-some')!.textContent]).toEqual(['Alle Ordner, auch spätere', 'Nur diese Ordner'])
    click(find(`[data-testid="consent-level-${LEVELS.at(-1)}"]`))
    click(byTestId('consent-areas-some'))
    expect(byTestId('consent-allow')!.disabled).toBe(true)
    click(find('[data-testid="consent-area-2"]'))
    if (EXTRA) click(find(`[data-testid="consent-extra-${EXTRA}"]`))
    const allow = byTestId('consent-allow')!
    expect([allow.dataset.kind, allow.dataset.icon, allow.disabled]).toEqual(['primary', 'Check', false])
    click(allow)
    await settle()
    expect(posts()).toEqual([
      {
        path: `${OAUTH}/authorize`,
        method: 'POST',
        body: {
          client_id: 'c1',
          redirect_uri: 'http://127.0.0.1:3334/callback',
          response_type: 'code',
          code_challenge: 'x1',
          code_challenge_method: 'S256',
          state: 's1',
          resource: 'https://notes.example.com/api/mcp',
          allow: true,
          level: LEVELS.at(-1),
          areas: [2],
          options: EXTRA ? { [EXTRA]: true } : {},
        },
      },
    ])
    expect(went).toEqual(['http://127.0.0.1:3334/callback?code=abc&state=s1'])
  })

  it('sends every area as null and declines on "Ablehnen"', async () => {
    const went: string[] = []
    show(<ConsentPage request={request} oauthBase={OAUTH} search={SEARCH} navigate={(url) => went.push(url)} />)
    await settle()
    const refuseButton = byTestId('consent-refuse')!
    expect([refuseButton.dataset.kind, refuseButton.dataset.icon]).toEqual(['secondary', 'X'])
    expect(all('[data-testid="mcp-consent"] [data-size]').filter((found) => found.dataset.testid?.startsWith('consent-')).map((found) => found.dataset.testid)).toEqual(['consent-refuse', 'consent-allow'])
    click(refuseButton)
    await settle()
    expect(posts()[0]!.body).toMatchObject({ allow: false, areas: null })
    expect(went).toEqual(['http://127.0.0.1:3334/callback?error=access_denied&state=s1'])
  })

  it('offers only "Ablehnen" when the operator lets the account use no AI', async () => {
    consent.ai_allowed = false
    show(<ConsentPage request={request} oauthBase={OAUTH} search={SEARCH} navigate={() => undefined} />)
    await settle()
    expect(find('[data-testid="consent-ai-off"]')!.textContent).toContain('Der Betreiber erlaubt deinem Konto keine KI.')
    expect(byTestId('consent-allow')).toBeNull()
    expect(byTestId('consent-refuse')).not.toBeNull()
  })

  it('says in its own words why the sign-in cannot go on', async () => {
    refuseGet = { code: 'redirect_invalid' }
    show(<ConsentPage request={request} oauthBase={OAUTH} search={SEARCH} navigate={() => undefined} />)
    await settle()
    expect(find('[data-testid="consent-problem"]')!.textContent).toBe('Die Rücksprungadresse gehört nicht zu diesem Programm.')
    act(() => root.unmount())
    root = createRoot(box)
    calls = []
    show(<ConsentPage request={request} oauthBase={OAUTH} search="?state=s1" navigate={() => undefined} />)
    await settle()
    expect(calls).toEqual([])
    expect(find('[data-testid="consent-problem"]')!.textContent).toContain('Der Adresse fehlen Angaben.')
  })
})

describe('the operator', () => {
  it('switches programs, sets the highest level and blocks a tool, each at once', async () => {
    show(<McpOperatorSettings request={request} base={BASE} words={WORDS} />)
    await settle()
    const programs = find<HTMLInputElement>('[data-testid="mcp-operator-programs"]')!
    expect([programs.type, programs.checked]).toEqual(['checkbox', true])
    expect(find('[data-testid="mcp-operator-saved"]')).toBeNull()
    click(programs)
    await settle()
    // MCP 21 (1.1.2): each change is kept at once and says so shortly.
    expect(find('[data-testid="mcp-operator-saved"]')!.textContent).toBe('Gespeichert.')
    click(find(`[data-testid="mcp-operator-level-${LEVELS[0]}"]`))
    await settle()
    click(find('[data-testid="mcp-operator-blocked"] button[aria-expanded]'))
    expect(find('[data-testid="mcp-operator-blocked"]')!.textContent).toContain('Notiz lesen')
    click(find('[data-testid="mcp-operator-block-delete_note"]'))
    await settle()
    expect(posts().map((call) => call.body)).toEqual([{ programs: false }, { max_level: LEVELS[0] }, { blocked_tools: ['delete_note'] }])
    expect(find('[data-testid="mcp-operator-blocked-count"]')!.textContent).toBe('1 gesperrt')
    expect(document.querySelector('[role="switch"]')).toBeNull()
  })
})

describe('every button of the parts', () => {
  it('has a kind of three, a size, a symbol and words', async () => {
    show(
      <>
        <ToolRights request={request} keyId={3} base={BASE} />
        <PendingRequests request={request} base={BASE} onView={() => undefined} />
        <RequestPage request={request} id={2} base={BASE} />
        <ConsentPage request={request} oauthBase={OAUTH} search={SEARCH} navigate={() => undefined} />
      </>,
    )
    await settle()
    click(byTestId('tool-rights'))
    await settle()
    const buttons = all('[data-size]')
    expect(buttons.length).toBeGreaterThan(8)
    for (const found of buttons) {
      expect(['primary', 'secondary', 'danger']).toContain(found.dataset.kind)
      expect(['md', 'sm']).toContain(found.dataset.size)
      expect(found.dataset.icon).toBeTruthy()
      expect(found.textContent?.trim()).toBeTruthy()
    }
    // MCP 20: "Ablehnen" is secondary with X everywhere, "Erlauben" primary with Check.
    const declines = buttons.filter((item) => item.textContent?.trim() === 'Ablehnen')
    expect(declines.length).toBeGreaterThan(2)
    for (const found of declines) expect([found.dataset.kind, found.dataset.icon]).toEqual(['secondary', 'X'])
    for (const found of buttons.filter((item) => item.textContent?.trim() === 'Erlauben' && item.dataset.size)) expect([found.dataset.kind, found.dataset.icon]).toEqual(['primary', 'Check'])
  })

  it('speak English and French', async () => {
    show(<PendingRequests request={request} base={BASE} />, 'en')
    await settle()
    expect(find('[data-testid="pending-requests"]')!.textContent).toContain('Waiting requests')
    show(<PendingRequests request={request} base={BASE} />, 'fr')
    await settle()
    expect(find('[data-testid="pending-requests"]')!.textContent).toContain('Demandes en attente')
  })
})
