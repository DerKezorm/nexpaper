/**
 * Settings, Mail, laid out as nexnotes' card: the server fields two to a row with Save, below them the test mail, and
 * one line for what both said at the end of the card (no heading of its own for the test).
 */
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { MailCard, useServerSettings } from './ServerCards'

const server = new Server()
const page = new Page()

const settings = {
  public_url: '', password_login: true, two_factor_required: true, backup_schedule: 'daily', backup_keep: 7, smtp_host: 'smtp.example.com', smtp_port: 587,
  smtp_security: 'starttls', smtp_user: 'paper', smtp_password_set: true, smtp_from: 'paper@example.com', api_keys_allowed: false, update_check: true,
}

function Mail() {
  const settings = useServerSettings()
  return <MailCard server={settings} />
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/settings': settings, 'PUT /api/v1/settings': settings, 'POST /api/v1/settings/mail-test': 204 }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the mail card', () => {
  it('has no heading for the test, and says what saving and the test did in the one line at the end', async () => {
    await page.show(<Mail />)
    const card = document.getElementById('mail')!
    expect(card.querySelector('h3')).toBeNull()
    expect(page.text).not.toContain('Ausprobieren')
    await page.click(page.button('Speichern', card))
    expect(card.querySelectorAll('[aria-live]')).toHaveLength(1)
    // The line stands last in the card, below the test mail.
    expect(card.querySelector(':scope > .space-y-3')!.lastElementChild!.getAttribute('aria-live')).toBe('polite')
    expect(card.textContent).toContain('Gespeichert.')
    const to = [...card.querySelectorAll('label')].find((label) => label.textContent?.startsWith('Testmail an'))!.querySelector('input')!
    await page.type(to, 'jule@example.com')
    await page.click(page.button('Senden', card))
    expect(server.called('POST', '/api/v1/settings/mail-test')!.body).toEqual({ to: 'jule@example.com' })
    expect(card.querySelectorAll('[aria-live]')).toHaveLength(1)
    expect(card.textContent).toContain('Die Testmail ist raus.')
    expect(card.textContent).not.toContain('Gespeichert.')
  })

  it('shows a refused test in the same line', async () => {
    server.fails['POST /api/v1/settings/mail-test'] = { status: 502, code: 'mail_failed' }
    await page.show(<Mail />)
    const card = document.getElementById('mail')!
    const to = [...card.querySelectorAll('label')].find((label) => label.textContent?.startsWith('Testmail an'))!.querySelector('input')!
    await page.type(to, 'jule@example.com')
    await page.click(page.button('Senden', card))
    expect(card.querySelectorAll('[role="alert"]')).toHaveLength(1)
  })
})
