/**
 * The setup of a new nexpaper asks once whether to look for new versions (updates U1): the box "Nach neuen Versionen
 * sehen" stands ticked, its hint says where nexpaper asks and that it asks when an operator opens the about page (no
 * bell in nexpaper, U19), and its answer goes along with the setup.
 */
import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { SetupPage } from './AuthPages'

const auth = { status: 'setup' as string, me: null as Me | null, setMe: vi.fn() }
vi.mock('../state/auth', () => ({ useAuth: () => auth, safeNext: (next: string | null) => next ?? '/' }))

const server = new Server()
const page = new Page()

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/setup': { needs_setup: true, code_required: true, signed_in: false, version: '1.12.0', min_password: 12 } }
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

async function setUp(): Promise<void> {
  for (const input of document.querySelectorAll<HTMLInputElement>('input[type="password"]')) {
    await page.type(input, 'a long enough password')
  }
  await page.click(document.querySelector<HTMLButtonElement>('button[type="submit"]'))
}

describe('the box "Nach neuen Versionen sehen" (U1)', () => {
  it('stands ticked, says where nexpaper asks and when, and goes along with the setup', async () => {
    await page.show(<SetupPage />, '/setup')
    const box = document.querySelector<HTMLInputElement>('[data-testid="setup-update-check"]')!
    expect(box.checked).toBe(true)
    expect(page.text).toContain('Nach neuen Versionen sehen')
    expect(page.text).toContain('api.github.com')
    // The module's hint for an app without a bell (updates 0.1.2, U19).
    expect(page.text).toContain('Wenn du Einstellungen › Über nexpaper öffnest')
    expect(page.text).not.toContain('Glocke')
    await setUp()
    expect(server.called('POST', '/api/v1/setup')?.body).toMatchObject({ update_check: true })
  })

  it('sends no when it is unticked', async () => {
    await page.show(<SetupPage />, '/setup')
    await page.click(document.querySelector<HTMLInputElement>('[data-testid="setup-update-check"]'))
    await setUp()
    expect(server.called('POST', '/api/v1/setup')?.body).toMatchObject({ update_check: false })
  })
})
