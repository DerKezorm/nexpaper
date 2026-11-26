// Vorlage nexschluessel 1.0.2
// @vitest-environment jsdom
/**
 * The cards of the module in the app: "API-Schlüssel", "KI-Werkzeuge (MCP)", "Schnittstellen" and "API-Schlüssel aller
 * Konten", built from the ui kit, the module's words in German, English and French, a key shown once, the hint for
 * keys that rest, locking and unlocking, the switches. Copied once by bauplaene/schluessel/tools/sync.py to
 * `frontend/src/nexschluessel.test.tsx`; then the app's file. Fill in the places marked APP. Needs react-dom (in every
 * app).
 */
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { NexuiLanguage } from './vendor/nexui'
import { AllKeysCard, ApiKeysCard, InterfacesCard, KEY_TEXTS, ToolsCard, type AdminKey, type Interfaces, type KeyEntry, type KeyListing, type KeyRequest } from './vendor/nexschluessel'

// APP: where the app mounts the module's routes, and its word for what it keeps (German, in the form of the sentence).
const BASE = '/api/v1/connections'
const THINGS = 'Dokumenten'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Call = { path: string; method: string; body: unknown }

let root: Root
let box: HTMLDivElement
let calls: Call[]
let listing: KeyListing
let admin: AdminKey[]
let switches: Interfaces
let refuse: Record<string, unknown> | null

const SECRET = 'nn_api_' + 'Q'.repeat(43)

function key(id: number, extra: Partial<KeyEntry> = {}): KeyEntry {
  return {
    id,
    kind: 'api',
    name: `Key ${id}`,
    right: 'read',
    options: { mcp: false },
    areas: null,
    prefix: 'nn_api_Ab' + id,
    created_at: '2026-11-20T09:00:00+00:00',
    last_used_at: id === 1 ? '2026-11-24T09:00:00+00:00' : null,
    expires_at: '2027-02-20T09:00:00+00:00',
    expired: false,
    expiring: false,
    blocked: false,
    legacy: null,
    program: false,
    ...extra,
  }
}

function freshListing(): KeyListing {
  return {
    app: 'nexapp',
    api: true,
    mcp: true,
    programs: true,
    api_path: '/api/v1',
    mcp_path: '/api/mcp',
    keys_wait: false,
    warn_days: 7,
    address: 'https://notes.example.com',
    kinds: [
      {
        id: 'api',
        prefix: 'nn_api_',
        creatable: true,
        editable: true,
        rights: ['read', 'write'],
        default_right: 'read',
        options: ['mcp'],
        areas: [
          { id: 1, name: 'Inbox' },
          { id: 2, name: 'Work' },
        ],
        areas_required: false,
        expiry_days: [30, 90, 365, null],
        default_days: 90,
        default_days_by_right: {},
        max_keys: 20,
        count: 2,
        name_max: 100,
      },
      {
        id: 'mcp',
        prefix: 'nxl_',
        creatable: true,
        editable: true,
        rights: ['read', 'write'],
        default_right: 'read',
        options: [],
        areas: null,
        areas_required: false,
        expiry_days: null,
        default_days: null,
        default_days_by_right: {},
        max_keys: 20,
        count: 1,
        name_max: 100,
      },
    ],
    keys: [
      key(1),
      key(2, { legacy: 'card', right: 'read' }),
      key(3, { kind: 'mcp', name: 'Notebook', program: true, right: 'write', expires_at: null }),
      key(4, { kind: 'mcp', name: 'Editor', prefix: 'nxl_Abcd', expires_at: null }),
    ],
  }
}

const request: KeyRequest = async <T,>(path: string, init: { method?: string; body?: unknown } = {}) => {
  const method = init.method ?? 'GET'
  calls.push({ path, method, body: init.body })
  if (refuse && method !== 'GET') {
    const detail = refuse
    refuse = null
    throw Object.assign(new Error('refused'), { detail })
  }
  if (path === `${BASE}/keys` && method === 'POST') {
    const body = init.body as { name: string; kind: 'api' | 'mcp' }
    const made = key(9, { name: body.name, kind: body.kind })
    listing = { ...listing, keys: [made, ...listing.keys] }
    return { key: made, secret: SECRET } as T
  }
  if (path.startsWith(`${BASE}/keys/`) && method === 'DELETE') {
    listing = { ...listing, keys: listing.keys.filter((found) => `${BASE}/keys/${found.id}` !== path) }
    return undefined as T
  }
  if (path.startsWith(`${BASE}/keys/`) && method === 'PATCH') return { ...listing.keys[0], ...(init.body as object) } as T
  if (path === `${BASE}/keys`) return listing as T
  if (path === `${BASE}/admin/keys`) return { keys: admin } as T
  if (path.endsWith('/block') || path.endsWith('/unblock')) {
    const found = admin.find((row) => path.includes(`/admin/keys/${row.id}/`))!
    return { ...found, blocked: path.endsWith('/block') } as T
  }
  if (path === `${BASE}/interfaces` && method === 'PUT') {
    switches = { ...switches, ...(init.body as Interfaces) }
    return switches as T
  }
  if (path === `${BASE}/interfaces`) return switches as T
  throw new Error(`unexpected ${method} ${path}`)
}

function show(node: ReactNode, language = 'de'): void {
  act(() => root.render(<NexuiLanguage language={language}>{node}</NexuiLanguage>))
}

async function settle(): Promise<void> {
  await act(async () => await new Promise((resolve) => setTimeout(resolve, 0)))
}

function click(element: Element | null): void {
  expect(element).not.toBeNull()
  act(() => (element as HTMLElement).click())
}

function type(input: HTMLInputElement, value: string): void {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const find = <T extends Element = HTMLElement>(selector: string) => document.querySelector<T>(selector)
const all = (selector: string) => Array.from(document.querySelectorAll<HTMLElement>(selector))
const button = (testId: string) => find<HTMLButtonElement>(`[data-testid="${testId}"]`)

beforeEach(() => {
  calls = []
  refuse = null
  listing = freshListing()
  switches = { api: true, mcp: false }
  // As the operator's route answers since E36: no start of the key, the app's own values in `extra`.
  const operatorRow = (entry: KeyEntry, account: AdminKey['account'], extra: Record<string, unknown>): AdminKey => {
    const { prefix, ...row } = entry
    void prefix
    return { ...row, account, extra }
  }
  admin = [
    operatorRow(key(1), { id: 1, name: 'anna', display_name: 'Anna', out: false }, { folders: 3 }),
    operatorRow(key(5, { blocked: true, name: null }), { id: 2, name: 'ben', display_name: 'Ben', out: false }, { folders: 0 }),
  ]
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
    expect(shape(KEY_TEXTS.en)).toEqual(shape(KEY_TEXTS.de))
    expect(shape(KEY_TEXTS.fr)).toEqual(shape(KEY_TEXTS.de))
    expect(KEY_TEXTS.de.apiKeys.title).toBe('API-Schlüssel')
    expect(KEY_TEXTS.de.tools.title).toBe('KI-Werkzeuge (MCP)')
    expect(KEY_TEXTS.de.interfaces.api).toBe('Programmschnittstelle (API) für Mitglieder')
    expect(KEY_TEXTS.de.interfaces.mcp).toBe('MCP-Zugang')
    expect(KEY_TEXTS.de.interfaces.app).toBe('iPhone-App erlauben')
    expect(KEY_TEXTS.de.interfaces.pairing).toBe('Neue Geräte verbinden')
    expect(KEY_TEXTS.de.interfaces.docs).toBe('Beschreibung der Schnittstelle')
    expect(KEY_TEXTS.de.allKeys.title).toBe('API-Schlüssel aller Konten')
    expect(KEY_TEXTS.de.key.wait).toBe('Wirkt erst, wenn du einen zweiten Faktor einrichtest.')
    expect(KEY_TEXTS.de.key.revoke).toBe('Widerrufen')
    expect(KEY_TEXTS.de.allKeys.block).toBe('Sperren')
    expect(KEY_TEXTS.de.allKeys.unblock).toBe('Entsperren')
  })
})

describe('the card API-Schlüssel', () => {
  it('says "mit deinen" with the dative form of the app\'s word (since E34), the plain form without one', async () => {
    show(<ApiKeysCard request={request} base={BASE} things="Kalender" thingsDative="Kalendern" />)
    await settle()
    expect(find('[data-card="api-keys"]')!.textContent).toContain('mit deinen Kalendern arbeiten')
    show(<ApiKeysCard request={request} base={BASE} things="Kalender" />)
    await settle()
    expect(find('[data-card="api-keys"]')!.textContent).toContain('mit deinen Kalender arbeiten')
  })

  it('lists the API keys with their start, never a secret, with small buttons', async () => {
    show(<ApiKeysCard request={request} base={BASE} things={THINGS} />)
    await settle()
    const card = find('[data-card="api-keys"]')!
    expect(card.textContent).toContain('API-Schlüssel')
    expect(card.textContent).toContain(THINGS)
    const rows = all('[data-testid="api-keys-table"] [data-part="table-row"]')
    expect(rows.map((row) => row.getAttribute('data-kind'))).toEqual(['api', 'api'])
    expect(card.textContent).toContain('nn_api_Ab1…')
    expect(card.textContent).toContain('nur nexdeck-Karte (älterer Schlüssel)')
    const revoke = all('[data-testid="key-revoke"]')[0]!
    expect([revoke.dataset.kind, revoke.dataset.size, revoke.dataset.icon]).toEqual(['danger', 'sm', 'Trash2'])
    const edit = all('[data-testid="key-edit"]')
    expect(edit).toHaveLength(2)
    expect([edit[0]!.dataset.kind, edit[0]!.dataset.size]).toEqual(['secondary', 'sm'])
    expect([button('api-keys-new')!.dataset.kind, button('api-keys-new')!.dataset.icon]).toEqual(['primary', 'Plus'])
    expect(find<HTMLInputElement>('[data-testid="api-keys-address"] input')!.value).toBe('https://notes.example.com/api/v1')
  })

  it('makes a key and shows it once, to copy', async () => {
    show(<ApiKeysCard request={request} base={BASE} things={THINGS} />)
    await settle()
    click(button('api-keys-new'))
    const dialog = find('[data-testid="key-dialog"]')!
    expect(dialog.textContent).toContain('Neuer API-Schlüssel')
    expect(find<HTMLSelectElement>('[data-testid="key-expiry"]')!.value).toBe('90')
    type(find<HTMLInputElement>('[data-testid="key-name"]')!, 'n8n')
    click(find('[data-testid="key-option-mcp"]'))
    click(button('key-submit'))
    await settle()
    const sent = calls.find((call) => call.method === 'POST')!
    expect(sent.body).toMatchObject({ kind: 'api', name: 'n8n', right: 'read', areas: 'all', options: { mcp: true }, days: 90 })
    expect(find<HTMLInputElement>('[data-testid="key-secret"] input')!.value).toBe(SECRET)
    expect(find<HTMLInputElement>('[data-testid="key-header"] input')!.value).toBe(`Authorization: Bearer ${SECRET}`)
    click(button('key-done'))
    await settle()
    expect(document.body.textContent).not.toContain(SECRET)
  })

  it('says why a key was refused', async () => {
    show(<ApiKeysCard request={request} base={BASE} things={THINGS} />)
    await settle()
    click(button('api-keys-new'))
    type(find<HTMLInputElement>('[data-testid="key-name"]')!, 'one more')
    refuse = { code: 'tokens_too_many', key_code: 'too_many_keys', max: 20 }
    click(button('key-submit'))
    await settle()
    expect(find('[data-testid="key-error"]')!.textContent).toContain('20')
  })

  it('asks before revoking and then revokes', async () => {
    show(<ApiKeysCard request={request} base={BASE} things={THINGS} />)
    await settle()
    click(all('[data-testid="key-revoke"]')[0]!)
    const dialog = find('[data-testid="key-revoke-dialog"]')!
    expect(dialog.textContent).toContain('„Key 1“ widerrufen?')
    click(dialog.querySelector('button[type="submit"]'))
    await settle()
    expect(calls.some((call) => call.method === 'DELETE' && call.path === `${BASE}/keys/1`)).toBe(true)
  })

  it('says when keys rest until a second factor, and still lets the account make one', async () => {
    listing.keys_wait = true
    show(<ApiKeysCard request={request} base={BASE} things={THINGS} />)
    await settle()
    expect(find('[data-testid="keys-wait"]')!.textContent).toContain('Wirkt erst, wenn du einen zweiten Faktor einrichtest.')
    expect(find<HTMLAnchorElement>('[data-testid="keys-wait"] a')!.getAttribute('href')).toBe('/settings/security')
    expect(all('[data-testid="key-wait"]').length).toBeGreaterThan(0)
    expect(button('api-keys-new')!.disabled).toBe(false)
  })

  it('says when the operator switched the interface off', async () => {
    listing.api = false
    show(<ApiKeysCard request={request} base={BASE} things={THINGS} operator />)
    await settle()
    expect(find('[data-testid="api-keys-off"]')!.textContent).toContain('Server › Allgemein › Schnittstellen')
    expect(button('api-keys-new')!.disabled).toBe(true)
  })

  it('has places for the app: a button per key, one in the note "switched off", parts with a new key, and at the end (E57)', async () => {
    const curl = (secret: string) => <span data-testid="app-curl">{`curl -H "Authorization: Bearer ${secret}" …`}</span>
    show(
      <ApiKeysCard
        request={request}
        base={BASE}
        things={THINGS}
        extra={(key) => <span data-testid="app-per-key">{key.name}</span>}
        made={(made) => curl(made.secret)}
        offAction={<span data-testid="app-switch-on">on</span>}
      >
        <span data-testid="app-end">own tokens</span>
      </ApiKeysCard>,
    )
    await settle()
    expect(all('[data-testid="api-keys-table"] [data-testid="app-per-key"]').length).toBeGreaterThan(0)
    expect(find('[data-card="api-keys"] [data-testid="app-end"]')).not.toBeNull()
    expect(find('[data-testid="app-switch-on"]')).toBeNull()
    expect(find('[data-testid="app-curl"]')).toBeNull()
    click(button('api-keys-new'))
    type(find<HTMLInputElement>('[data-testid="key-name"]')!, 'curl')
    click(button('key-submit'))
    await settle()
    expect(find('[data-testid="key-made"] [data-testid="app-curl"]')!.textContent).toContain(SECRET)
    click(button('key-done'))
    await settle()
    expect(find('[data-testid="app-curl"]')).toBeNull()
  })

  it('shows the app part in the note "switched off" only while it is off', async () => {
    listing.api = false
    show(<ApiKeysCard request={request} base={BASE} things={THINGS} operator offAction={<span data-testid="app-switch-on">on</span>} />)
    await settle()
    expect(find('[data-testid="api-keys-off"] [data-testid="app-switch-on"]')).not.toBeNull()
  })

  it('speaks English and French', async () => {
    show(<ApiKeysCard request={request} base={BASE} things="notes" />, 'en')
    await settle()
    expect(find('[data-card="api-keys"]')!.textContent).toContain('API keys')
    show(<ApiKeysCard request={request} base={BASE} things="notes" />, 'fr')
    await settle()
    expect(find('[data-card="api-keys"]')!.textContent).toContain('Clés d’API')
  })
})

describe('the card KI-Werkzeuge (MCP)', () => {
  it('shows the connected programs and the MCP keys, each to revoke', async () => {
    show(<ToolsCard request={request} base={BASE} />)
    await settle()
    const card = find('[data-card="ai-tools"]')!
    expect(card.textContent).toContain('KI-Werkzeuge (MCP)')
    expect(all('[data-testid="tools-programs-table"] [data-part="table-row"]').map((row) => row.dataset.program)).toEqual(['true'])
    expect(all('[data-testid="tools-keys-table"] [data-part="table-row"]')).toHaveLength(1)
    expect(card.textContent).toContain('Notebook')
    expect(find<HTMLInputElement>('[data-testid="tools-address"] input')!.value).toBe('https://notes.example.com/api/mcp')
    // Plan E48: "Neuer MCP-Schlüssel" is an md secondary Plus, the API key's "Neuer API-Schlüssel" stays primary.
    expect([button('tools-new')!.dataset.kind, button('tools-new')!.dataset.size, button('tools-new')!.dataset.icon]).toEqual(['secondary', 'md', 'Plus'])
    expect(button('tools-new')!.textContent).toBe('Neuer MCP-Schlüssel')
    expect(all('[data-testid="tools-keys"] [data-kind="primary"]')).toHaveLength(0)
  })

  it('names an app without MCP', async () => {
    listing.mcp = null
    show(<ToolsCard request={request} base={BASE} />)
    await settle()
    expect(find('[data-testid="tools-none"]')!.textContent).toContain('nexapp hat noch keinen MCP-Zugang.')
  })
})

describe('the card Schnittstellen', () => {
  it('shows the switches the app has, as boxes to tick, and changes them', async () => {
    show(<InterfacesCard request={request} base={BASE} docsHref="/api/v1/docs" />)
    await settle()
    expect(find('[data-card="interfaces"]')!.textContent).toContain('Programmschnittstelle (API) für Mitglieder')
    expect(find('[data-testid="interfaces-app"]')).toBeNull()
    const mcp = find<HTMLInputElement>('[data-testid="interfaces-mcp"]')!
    expect(mcp.type).toBe('checkbox')
    expect(mcp.checked).toBe(false)
    click(mcp)
    await settle()
    expect(calls.at(-1)).toMatchObject({ method: 'PUT', body: { mcp: true } })
    expect(find<HTMLInputElement>('[data-testid="interfaces-mcp"]')!.checked).toBe(true)
    expect(find('[data-testid="interfaces-docs"]')!.textContent).toContain('Beschreibung der Schnittstelle')
    expect(document.querySelector('[role="switch"]')).toBeNull()
  })
})

describe('the card API-Schlüssel aller Konten', () => {
  it("never shows the start of a key, and shows the app's own columns before the button (since E36)", async () => {
    show(<AllKeysCard request={request} base={BASE} extra={[{ key: 'folders', label: 'Ordner', width: '6rem' }]} />)
    await settle()
    const card = find('[data-card="all-api-keys"]')!
    expect(card.textContent).not.toContain('nn_api_')
    const heads = all('[data-testid="all-keys-table"] thead th').map((cell) => cell.textContent)
    expect(heads.indexOf('Ordner')).toBe(heads.length - 2)
    const rows = all('[data-testid="all-keys-table"] [data-part="table-row"]')
    expect(rows.map((row) => row.textContent?.includes('3'))).toEqual([true, false])
    click(button('all-keys-block')!)
    expect(find('[data-testid="all-keys-block-dialog"]')!.textContent).toContain('„Key 1“ von Anna sperren?')
  })

  it('has a place for the app at the end of the card, after the table (E58)', async () => {
    show(
      <AllKeysCard request={request} base={BASE}>
        <a href="/settings/connections" data-testid="app-own-keys">Eigene API-Schlüssel anlegen</a>
      </AllKeysCard>,
    )
    await settle()
    const card = find('[data-card="all-api-keys"]')!
    const own = card.querySelector('[data-testid="app-own-keys"]')!
    expect(own.textContent).toBe('Eigene API-Schlüssel anlegen')
    const table = card.querySelector('[data-testid="all-keys-table"]')!
    expect(table.compareDocumentPosition(own) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('shows no start of a key even when a server still sends one', async () => {
    admin = admin.map((row) => ({ ...row, prefix: 'nn_api_Zz9' }) as AdminKey)
    show(<AllKeysCard request={request} base={BASE} />)
    await settle()
    expect(find('[data-card="all-api-keys"]')!.textContent).not.toContain('nn_api_Zz9')
  })

  it('locks after asking and unlocks at once', async () => {
    show(<AllKeysCard request={request} base={BASE} />)
    await settle()
    const rows = all('[data-testid="all-keys-table"] [data-part="table-row"]')
    expect(rows.map((row) => row.dataset.blocked)).toEqual(['false', 'true'])
    expect(find('[data-card="all-api-keys"]')!.textContent).toContain('Name nur für das Konto')
    const lock = button('all-keys-block')!
    expect([lock.dataset.kind, lock.dataset.size, lock.dataset.icon]).toEqual(['danger', 'sm', 'Ban'])
    const unlock = button('all-keys-unblock')!
    expect([unlock.dataset.kind, unlock.dataset.size, unlock.dataset.icon]).toEqual(['secondary', 'sm', 'CircleCheck'])
    click(lock)
    expect(find('[data-testid="all-keys-block-dialog"]')!.textContent).toContain('„Key 1“ von Anna sperren?')
    click(find('[data-testid="all-keys-block-dialog"] button[type="submit"]'))
    await settle()
    expect(calls.at(-1)).toMatchObject({ method: 'POST', path: `${BASE}/admin/keys/1/block` })
    click(all('[data-testid="all-keys-unblock"]').at(-1)!)
    await settle()
    expect(calls.at(-1)).toMatchObject({ method: 'POST', path: `${BASE}/admin/keys/5/unblock` })
  })
})

describe('every button of the cards', () => {
  it('has a kind of three, a size, a symbol and words', async () => {
    show(
      <>
        <ApiKeysCard request={request} base={BASE} things={THINGS} docsHref="/api/v1/docs" />
        <ToolsCard request={request} base={BASE} />
        <InterfacesCard request={request} base={BASE} docsHref="/api/v1/docs" />
        <AllKeysCard request={request} base={BASE} />
      </>,
    )
    await settle()
    const buttons = all('[data-size]')
    expect(buttons.length).toBeGreaterThan(10)
    for (const found of buttons) {
      expect(['primary', 'secondary', 'danger']).toContain(found.dataset.kind)
      expect(['md', 'sm']).toContain(found.dataset.size)
      expect(found.dataset.icon).toBeTruthy()
      expect(found.textContent?.trim()).toBeTruthy()
    }
    for (const word of ['Widerrufen', 'Sperren']) {
      for (const found of buttons.filter((item) => item.textContent?.trim() === word)) expect(found.dataset.kind).toBe('danger')
    }
  })
})
