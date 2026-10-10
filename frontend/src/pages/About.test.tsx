/**
 * The About page against a stand-in of the server: version, licence and links, whether a newer version is out (and the
 * daily question, which only the operator switches or asks now), the written text of 1.0.0 and what nexpaper is built
 * with, in German and in English.
 */
import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { AboutPage } from './AboutPage'

const me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', version: '1.0.0', whats_new_seen: '1.0.0',
  session_stage: 'full', profile: { mode: 'system' },
} as unknown as Me
const auth = { me: me as Me | null }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const about = {
  version: '1.0.0', license: 'AGPL-3.0', repo_url: 'https://github.com/example/nexpaper', releases_url: 'https://github.com/example/nexpaper/releases',
  project_url: 'https://nexpaper.example.com',
}
const current = { update_check: true, checked: true, latest: 'v1.0.0', newer: false, checked_at: '2026-10-10T08:15:00Z', release_url: null }

beforeEach(async () => {
  // jsdom has no modal dialogs: the window opens as a plain element.
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute('open', '')
  }
  await changeLanguage('de', false)
  auth.me = me
  server.answers = { 'GET /api/v1/about': about, 'GET /api/v1/about/updates': current }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the facts', () => {
  it('show the version, the licence, the source, the releases and where to report a problem', async () => {
    await page.show(<AboutPage />)
    const facts = document.querySelector('[data-testid="about-facts"]')!.textContent!
    expect(document.querySelector('[data-testid="about-version"]')?.textContent).toBe('1.0.0')
    expect(facts).toContain('AGPL-3.0')
    expect(facts).toContain('github.com/example/nexpaper')
    expect(facts).toContain('nexpaper.example.com')
    const links = [...document.querySelectorAll('dl a')].map((a) => a.getAttribute('href'))
    expect(links).toContain('https://www.gnu.org/licenses/agpl-3.0.html')
    expect(links).toContain('https://github.com/example/nexpaper/issues/new')
    for (const a of document.querySelectorAll('dl a')) expect(a.getAttribute('rel')).toContain('noopener')
  })

  it('say that this is the newest version', async () => {
    await page.show(<AboutPage />)
    expect(document.querySelector('[data-testid="about-update-state"]')?.textContent).toBe('Das ist die neueste Version.')
  })

  it('say that a newer version is out, with the way to it', async () => {
    server.answers['GET /api/v1/about/updates'] = { ...current, latest: 'v0.1.1', newer: true, release_url: 'https://github.com/example/nexpaper/releases/tag/v0.1.1' }
    await page.show(<AboutPage />)
    expect(document.querySelector('[data-testid="about-update-state"]')?.textContent).toContain('0.1.1')
    expect(page.text).toContain('Version 0.1.1 ist erschienen')
    expect(document.querySelector('[data-testid="about-update-state"] a')?.getAttribute('href')).toBe('https://github.com/example/nexpaper/releases/tag/v0.1.1')
  })
})

describe('the daily question', () => {
  it('is switched and asked now by the operator, and says what goes out', async () => {
    server.answers['PUT /api/v1/about/updates'] = { ...current, update_check: false }
    server.answers['POST /api/v1/about/updates/check'] = current
    await page.show(<AboutPage />)
    expect(page.text).toContain('Hinaus geht nur die Frage')
    await page.click(page.button('Jetzt nachsehen'))
    expect(server.changes()).toEqual(['POST /api/v1/about/updates/check'])
    await page.click(document.querySelector<HTMLElement>('[role="switch"]'))
    expect(server.called('PUT', '/api/v1/about/updates')?.body).toEqual({ update_check: false })
  })

  it('is only shown, not changed, to a member', async () => {
    auth.me = { ...me, role: 'member' } as Me
    await page.show(<AboutPage />)
    expect(document.querySelector('[role="switch"]')).toBeNull()
    expect(page.button('Jetzt nachsehen')).toBeUndefined()
    expect(document.querySelector('[data-testid="about-update-state"]')?.textContent).toBe('Das ist die neueste Version.')
  })
})

describe('what is new', () => {
  it('opens the text of 1.0.0 and reads it again at any time', async () => {
    await page.show(<AboutPage />)
    await page.click(page.button('Neu in nexpaper 1.0.0'))
    const window = document.querySelector('[data-testid="whats-new-window"]')!
    expect(window.textContent).toContain('Das ist nexpaper 1.0')
    expect(window.textContent).toContain('Alles kommt erst in den Eingang')
    expect(window.textContent).toContain('Sicherung und Dateien prüfen')
    expect(window.textContent).toContain('Ordnung')
    expect(window.textContent).not.toMatch(/[–—]/)
  })

  it('has the same text in English', async () => {
    await changeLanguage('en', false)
    await page.show(<AboutPage />)
    await page.click(page.button('New in nexpaper 1.0.0'))
    const window = document.querySelector('[data-testid="whats-new-window"]')!
    expect(window.textContent).toContain('This is nexpaper 1.0')
    expect(window.textContent).toContain('Backup and checking the files')
    expect(window.textContent).not.toMatch(/Eingang|Sicherung|Tresor/)
  })
})

describe('what it is built with', () => {
  it('names the text recognition, the PDF tools, the camera and the fonts with their licences', async () => {
    await page.show(<AboutPage />)
    const built = [...document.querySelectorAll('li')].map((item) => (item.textContent ?? '').replace(/\s+/g, ' ').replace('(', ' ('))
    for (const part of ['OCRmyPDF (MPL-2.0)', 'Tesseract (Apache-2.0)', 'pikepdf (MPL-2.0)', 'img2pdf (LGPL-3.0)', 'PDF.js (Apache-2.0)', 'OpenCV.js (Apache-2.0)', 'jscanify (MIT)', 'Fraunces (OFL-1.1)', 'Figtree (OFL-1.1)']) {
      expect(built, part).toContain(part)
    }
  })
})
