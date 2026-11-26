/**
 * Server › Mail: the post module's card (post 1.1.0) with nexpaper's client and words: its routes under
 * `/api/v1/server/mail`, its sentence naming every mail it sends, and one line for what saving and the test said at
 * the end of the card (no heading of its own for the test).
 */
import { changeLanguage } from '../../i18n'
import german from '../../i18n/de.json'
import { Page, Server } from '../../test/harness'
import { MailArea } from './ServerCards'

const server = new Server()
const page = new Page()

const view = {
  host: 'smtp.example.com', port: 587, security: 'starttls', user: 'paper', password_set: true, sender: 'paper@example.com', sender_name: '', sender_name_default: 'nexpaper',
  ca_file: '', configured: true, warnings: [], last_ok_at: null, last_error: '', last_error_at: null, waiting: 0,
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/server/mail': view, 'PUT /api/v1/server/mail': view, 'POST /api/v1/server/mail/test': 204 }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

const card = () => document.querySelector<HTMLElement>('[data-card="mail"]')!
const results = () => card().querySelectorAll('[data-testid="mail-done"], [data-testid="mail-problem"]')

describe('the mail card', () => {
  it('says nexpaper\'s sentence of every mail it sends, and the sender name falls back to nexpaper', async () => {
    await page.show(<MailArea />)
    expect(card().textContent).toContain(german.server.mailHint)
    expect(card().querySelector<HTMLInputElement>('[data-testid="mail-sender-name"]')!.placeholder).toBe('nexpaper')
    expect(card().querySelector<HTMLInputElement>('[data-testid="mail-sender"]')!.placeholder).toBe('paper@example.com')
  })

  it('has no heading for the test, and says what saving and the test did in the one line at the end', async () => {
    await page.show(<MailArea />)
    expect(card().querySelector('h3')).toBeNull()
    expect(page.text).not.toContain('Ausprobieren')
    await page.click(card().querySelector<HTMLButtonElement>('[data-testid="mail-save"]'))
    expect(server.called('PUT', '/api/v1/server/mail')).toBeTruthy()
    expect(results()).toHaveLength(1)
    // The line stands last in the card, below the test mail.
    expect(card().querySelector(':scope > div:last-child')!.lastElementChild!.getAttribute('data-testid')).toBe('mail-done')
    expect(card().textContent).toContain('Gespeichert.')
    await page.type(card().querySelector<HTMLInputElement>('[data-testid="mail-test-to"]'), 'jule@example.com')
    await page.click(card().querySelector<HTMLButtonElement>('[data-testid="mail-test"]'))
    expect(server.called('POST', '/api/v1/server/mail/test')!.body).toEqual({ to: 'jule@example.com', language: 'de' })
    expect(results()).toHaveLength(1)
    expect(card().textContent).toContain('jule@example.com')
    expect(card().textContent).not.toContain('Gespeichert.')
    // The old way of before is not taken any more by the card (it stays on the server for scripts).
    expect(server.called('POST', '/api/v1/settings/mail-test')).toBeUndefined()
  })

  it('shows a refused test in the same line', async () => {
    server.fails['POST /api/v1/server/mail/test'] = { status: 502, code: 'mail_failed' }
    await page.show(<MailArea />)
    await page.type(card().querySelector<HTMLInputElement>('[data-testid="mail-test-to"]'), 'jule@example.com')
    await page.click(card().querySelector<HTMLButtonElement>('[data-testid="mail-test"]'))
    expect(card().querySelectorAll('[role="alert"]')).toHaveLength(1)
    expect(results()).toHaveLength(1)
  })
})
