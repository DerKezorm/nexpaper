/**
 * AI tools in nexpaper (the shared MCP module, mcp 1.1.0): the card "KI-Werkzeuge (MCP)" in My account › Connections
 * with "Rechte je Werkzeug" at an MCP key (not at an API key) in nexpaper's words and the requests waiting for a yes;
 * the operator's settings after "MCP-Zugang" in Server › General › Schnittstellen; the consent page under
 * `/mcp/authorize` asks the module's OAuth under `/api/oauth` and names the vaults.
 */
import type { Me } from '../../api/client'
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { Interfaces } from './KeysCards'
import { AiTools, McpConsentPage } from './McpCards'

const me = { id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', language: 'de', profile: { mode: 'system' } } as unknown as Me
const auth = { status: 'signedIn', me: me as Me | null }
vi.mock('../../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const kind = (id: string, prefix: string, rights: string[]) => ({
  id, prefix, creatable: true, editable: true, rights, default_right: 'read', options: [], retired_options: [], areas: id === 'mcp' ? [{ id: 1, name: 'Jule' }] : null,
  areas_required: false, expiry_days: [30, 90, 365, null], default_days: 90, default_days_by_right: {}, max_keys: 20, count: 1, name_max: 100,
})
const entry = (id: number, kindId: string, name: string) => ({
  id, kind: kindId, name, right: 'read', options: {}, areas: null, prefix: `${kindId === 'mcp' ? 'npm_' : 'npk_'}AbCd`, created_at: '2026-11-26T09:00:00+00:00',
  last_used_at: null, expires_at: null, expired: false, expiring: false, blocked: false, legacy: null, program: false,
})
const listing = {
  app: 'nexpaper', api: true, mcp: true, programs: true, api_path: '/api/v1', mcp_path: '/api/mcp', keys_wait: false, ai_allowed: true, warn_days: 7,
  kinds: [kind('api', 'npk_', ['read', 'upload']), kind('mcp', 'npm_', ['read', 'write'])],
  keys: [entry(1_000_000_000, 'mcp', 'Notebook'), entry(4, 'api', 'Dashboard')],
  address: 'https://paper.example.com',
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = {
    'GET /api/v1/connections/keys': listing,
    'GET /api/v1/connections/mcp/requests?status=waiting': [],
    'GET /api/v1/connections/interfaces': { api: true, mcp: true },
    'GET /api/v1/connections/mcp/admin': {
      programs: true, levels: ['read', 'write'], max_level: 'write', blocked_tools: [],
      tools: [{ name: 'read_document', group: 'read', level: 'read' }, { name: 'trash_document', group: 'risky', level: 'write' }],
    },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the card "KI-Werkzeuge (MCP)"', () => {
  it('stands under Connections with the MCP key, rights per tool only there, and asks for waiting requests', async () => {
    await page.show(<AiTools />)
    const card = document.querySelector('[data-card="ai-tools"]')!
    expect(card.textContent).toContain('Notebook')
    // The table stands twice in the page (desk and phone, E56): one button per row and view, none at the API key.
    expect(card.querySelectorAll('[data-testid="tool-rights"]').length).toBe(2)
    expect(card.textContent).not.toContain('Dashboard')
    expect(server.called('GET', '/api/v1/connections/mcp/requests?status=waiting')).toBeTruthy()
  })

  it('opens the rights of the key in nexpaper\'s words', async () => {
    server.answers['GET /api/v1/connections/mcp/keys/1000000000/rights'] = {
      key: { id: 1_000_000_000, name: 'Notebook', program: false }, level: 'write',
      tools: [
        { name: 'read_document', group: 'read', right: 'allow', asks_never: true, reason: null, always: false },
        { name: 'trash_document', group: 'risky', right: 'allow', asks_never: false, reason: null, always: false },
      ],
    }
    await page.show(<AiTools />)
    await page.click(document.querySelector<HTMLElement>('[data-card="ai-tools"] [data-testid="tool-rights"]'))
    expect(page.text).toContain('Dokument lesen')
    expect(page.text).toContain('In den Papierkorb legen')
  })
})

describe('the operator\'s settings of MCP', () => {
  it('follow the switch "MCP-Zugang" in Schnittstellen, with the tools in nexpaper\'s words', async () => {
    await page.show(<Interfaces />)
    const card = document.querySelector('[data-card="interfaces"]') ?? document.querySelector('[data-testid="interfaces-card"]')!
    expect(card.querySelector('[data-testid="mcp-operator"]')).toBeTruthy()
    expect(server.called('GET', '/api/v1/connections/mcp/admin')).toBeTruthy()
  })
})

describe('the consent page', () => {
  it('asks the module\'s OAuth under /api/oauth and names the vaults', async () => {
    const search = '?client_id=c1&redirect_uri=http%3A%2F%2F127.0.0.1%3A33418%2Fcallback&response_type=code&code_challenge=x&code_challenge_method=S256&state=s1'
    window.history.replaceState(null, '', `/mcp/authorize${search}`)
    server.answers[`GET /api/oauth/authorize${search}`] = {
      client: { id: 'c1', name: 'Probe client' }, redirect_uri: 'http://127.0.0.1:33418/callback', host: '127.0.0.1', levels: ['read', 'write'],
      max_level: 'write', areas: [{ id: 1, name: 'Jule' }], extras: [], ai_allowed: true, account: 'jule',
    }
    await page.show(<McpConsentPage />, `/mcp/authorize${search}`)
    expect(server.calls.some((call) => call.url.startsWith('/api/oauth/authorize?'))).toBe(true)
    window.history.replaceState(null, '', '/')
  })
})
