/**
 * nexpaper's words in the cards of the key module (schluessel 1.0.0): "API-Schlüssel" under Connections ends with what a
 * key for uploading may do and the limits of every key (before the cards of the area "API" and of Devices and apps),
 * in German and English, over the module's route.
 */
import type { Me } from '../../api/client'
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { ApiKeys, TryIt } from './KeysCards'

const me = { id: 1, name: 'jule', display_name: 'Jule', role: 'member', sign_in: 'password', language: 'de', profile: { mode: 'system' } } as unknown as Me
const auth = { status: 'signedIn', me: me as Me | null }
vi.mock('../../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = {
    'GET /api/v1/connections/keys': { app: 'nexpaper', api: true, mcp: null, programs: false, api_path: '/api/v1', mcp_path: null, keys_wait: false, warn_days: 7, kinds: [], keys: [], address: 'https://paper.example.com' },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the card API-Schlüssel', () => {
  it('ends with nexpaper\'s lines: what a key for uploading may do, and the limits of every key', async () => {
    await page.show(<ApiKeys />)
    expect(server.calls.some((call) => call.url === '/api/v1/connections/keys')).toBe(true)
    const card = document.querySelector('[data-card="api-keys"]') ?? document.querySelector('[data-testid="api-keys-card"]')!
    expect(card.querySelector('[data-testid="keys-upload-note"]')!.textContent).toBe(
      'Ein Schlüssel zum Hochladen legt Dokumente nur in einen Eingang: in den deines Ziel-Tresors oder, wenn das Programm einen anderen nennt, in den eines Tresors, in dem du ablegen darfst. Lesen, ändern oder löschen kann er nichts.',
    )
    expect(card.querySelector('[data-testid="keys-limits"]')!.textContent).toBe('Grenzen je Schlüssel: 120 Anfragen in der Minute, 50 Uploads in der Stunde. Falsche Schlüssel zählen wie falsche Passwörter.')
    // The word is "API-Schlüssel" everywhere (E3), never "Token".
    expect(card.textContent).not.toContain('Token')
  })

  it('says them in English too', async () => {
    await changeLanguage('en', false)
    await page.show(<ApiKeys />)
    expect(document.querySelector('[data-testid="keys-limits"]')!.textContent).toBe('Limits per key: 120 requests a minute, 50 uploads an hour. Wrong keys count like wrong passwords.')
  })
})

describe('nexpaper\'s parts in the card API-Schlüssel (Bauplan E57, schluessel 1.0.1)', () => {
  afterEach(() => {
    auth.me = me
  })

  it('lets the operator allow keys in the note that they are off, after a question', async () => {
    auth.me = { ...me, role: 'operator' } as Me
    server.answers['GET /api/v1/connections/keys'] = { ...(server.answers['GET /api/v1/connections/keys'] as object), api: false }
    server.answers['PUT /api/v1/connections/interfaces'] = { api: true }
    await page.show(<ApiKeys />)
    const note = document.querySelector('[data-testid="api-keys-off"]')!
    const allow = page.button('Jetzt freigeben', note)!
    expect([allow.dataset.kind, allow.dataset.size]).toEqual(['secondary', 'sm'])
    await page.click(allow)
    expect(document.querySelector('[data-testid="api-keys-allow-dialog"]')).not.toBeNull()
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Jetzt freigeben', document.querySelector('[data-testid="api-keys-off"]')!))
    const loads = server.calls.filter((call) => call.url === '/api/v1/connections/keys').length
    await page.inDialog('Freigeben')
    expect(server.changes()).toEqual(['PUT /api/v1/connections/interfaces'])
    expect(server.calls.find((call) => call.method === 'PUT')!.body).toEqual({ api: true })
    // The card asks again whether keys are on.
    expect(server.calls.filter((call) => call.url === '/api/v1/connections/keys').length).toBeGreaterThan(loads)
  })

  it('offers no such button to a member', async () => {
    server.answers['GET /api/v1/connections/keys'] = { ...(server.answers['GET /api/v1/connections/keys'] as object), api: false }
    await page.show(<ApiKeys />)
    expect(document.querySelector('[data-testid="api-keys-off"]')).not.toBeNull()
    expect(page.button('Jetzt freigeben')).toBeUndefined()
  })

  it('says how long a key should live, at the end of the card', async () => {
    await page.show(<ApiKeys />)
    const lifetime = document.querySelector('[data-testid="keys-lifetime"]')!.textContent!
    expect(lifetime).toContain('Ein Schlüssel, der nie abläuft')
    expect(lifetime).toContain('Ein Schlüssel zum Hochladen kann nur Dokumente in deinen Eingang legen.')
  })

  it.each([
    ['upload', '-F file=@Rechnung.pdf', '/api/v1/documents'],
    ['read', '', '/api/v1/me'],
  ])('shows the curl command of a new key for %s', async (right, part, path) => {
    server.answers['GET /api/v1/connections/keys'] = {
      ...(server.answers['GET /api/v1/connections/keys'] as object),
      keys: [{ id: 3, kind: 'api', name: 'Scanner', right }],
    }
    await page.show(<TryIt name="Scanner" secret="npk_example" />)
    const row = document.querySelector<HTMLInputElement>('[data-testid="key-try-it"] input')!
    expect(row.value).toContain('Authorization: Bearer npk_example')
    expect(row.value).toContain(part)
    expect(row.value.endsWith(path)).toBe(true)
    expect(document.querySelector('[data-testid="key-try-it-part"]')!.textContent).toContain('Zum Ausprobieren')
    expect(row.getAttribute('aria-label')).toBe('Zum Ausprobieren')
  })
})
