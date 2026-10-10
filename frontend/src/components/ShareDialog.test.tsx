/**
 * The share dialog on a document, against test data: who it is shared with, who may be added (not the members of the
 * vault), the right, the link with its end and its download switch, copying a link (again), and the operator's switch.
 */
import { dayInDays } from '../lib/dates'
import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { ShareDialog } from './ShareDialog'

const server = new Server()
const page = new Page()
const say = vi.fn()

const jule = { id: 1, name: 'jule', display_name: 'Jule' }
const tom = { id: 2, name: 'tom', display_name: '' }
const lea = { id: 3, name: 'lea', display_name: 'Lea' }
const out = { id: 4, name: 'stranger', display_name: 'Stefan' }
const vault = {
  id: 7, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'manage', documents: 3, size: 0,
  members: [
    { user_id: 1, name: 'jule', display_name: 'Jule', right: 'manage' },
    { user_id: 2, name: 'tom', display_name: '', right: 'edit' },
  ],
}
const link = (over: Record<string, unknown> = {}) => ({
  id: 11, document_id: 5, recipient: 'Steuerbüro', until: '2026-10-31T10:00:00Z', allow_download: true, opened_count: 2, last_opened_at: null,
  created_at: '2026-10-08T10:00:00Z', created_by: jule, revoked_at: null, status: 'active', can_copy: true, ...over,
})

function open() {
  return page.show(<ShareDialog document={{ id: 5, vault_id: 7, title: 'Rechnung' }} onClose={vi.fn()} say={say} />)
}

beforeEach(async () => {
  await changeLanguage('de', false)
  say.mockClear()
  server.answers = {
    'GET /api/v1/documents/5/shares': [{ user: lea, right: 'read', created_at: '2026-10-08T10:00:00Z' }],
    'GET /api/v1/sharing': { links_allowed: true, link_max_days: 30 },
    'GET /api/v1/people': [jule, tom, lea, out],
    'GET /api/v1/vaults': [vault],
    'GET /api/v1/documents/5/links': [link()],
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('sharing with people', () => {
  it('names the vault and who sees it already, lists the shares, and offers only people who are not in yet', async () => {
    await open()
    expect(page.text).toContain('Im Tresor Haushalt sehen es schon: Jule, tom.')
    expect(page.text).toContain('Lea')
    const options = [...page.select('Person wählen')!.querySelectorAll('option')].map((o) => o.textContent)
    expect(options).toEqual(['Person wählen', 'Stefan'])
  })

  it('shares with the person chosen, with the right chosen, and says so', async () => {
    server.answers['PUT /api/v1/documents/5/shares/4'] = { user: out, right: 'edit', created_at: '2026-10-08T11:00:00Z' }
    await open()
    await page.choose(page.select('Person wählen'), '4')
    await page.choose(page.select('Recht'), 'edit')
    const shareButton = [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Teilen')
    await page.click(shareButton)
    expect(server.called('PUT', '/api/v1/documents/5/shares/4')!.body).toEqual({ right: 'edit' })
    expect(say).toHaveBeenCalledWith('Geteilt mit Stefan.')
    expect(page.text).toContain('Stefan')
    expect(page.text).toContain('Alle hier sehen es schon.')
  })

  it('stops sharing with a person', async () => {
    server.answers['DELETE /api/v1/documents/5/shares/3'] = 204
    await open()
    await page.click(page.button('Nicht mehr teilen: Lea'))
    expect(server.changes()).toEqual([])
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Nicht mehr teilen: Lea'))
    await page.inDialog('Freigabe entfernen')
    expect(server.changes()).toEqual(['DELETE /api/v1/documents/5/shares/3'])
    expect(say).toHaveBeenCalledWith('Nicht mehr geteilt mit Lea.')
  })

  it('shows what the server refused', async () => {
    server.fails['PUT /api/v1/documents/5/shares/4'] = { status: 403, code: 'forbidden' }
    await open()
    await page.choose(page.select('Person wählen'), '4')
    await page.click([...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Teilen'))
    expect(page.text).toContain('Dein Recht reicht dafür nicht.')
  })
})

describe('links to the outside', () => {
  it('lists the links with their end and how often they were opened, and revokes one', async () => {
    server.answers['DELETE /api/v1/documents/5/links/11'] = 204
    await open()
    expect(page.text).toContain('Steuerbüro')
    expect(page.text).toContain('bis 31.10.2026 · 2× geöffnet')
    expect(page.text).toContain('Höchstens 30 Tage, so hat es der Betreiber eingestellt.')
    server.answers['GET /api/v1/documents/5/links'] = [link({ revoked_at: '2026-10-08T12:00:00Z', status: 'revoked' })]
    await page.click(page.button('Zurückziehen'))
    expect(server.changes()).toEqual([])
    await page.inDialog('Link zurückziehen')
    expect(server.changes()).toEqual(['DELETE /api/v1/documents/5/links/11'])
    expect(page.text).not.toContain('Steuerbüro')
    expect(say).toHaveBeenCalledWith('Link zurückgezogen.')
  })

  it('makes a link for somebody, with the days up to the chosen day and the download switch, and copies it', async () => {
    const written: string[] = []
    vi.stubGlobal('isSecureContext', true)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => void written.push(text) } })
    server.answers['POST /api/v1/documents/5/links'] = { ...link({ id: 12, recipient: 'Vermieter', allow_download: false }), token: 'lnk_secret', url: 'https://paper.example.com/l/lnk_secret' }
    await open()
    await page.type(document.querySelector<HTMLInputElement>('input[aria-label="Für wen, z. B. Steuerbüro"]'), 'Vermieter')
    await page.type(document.querySelector<HTMLInputElement>('#share-until'), dayInDays(10))
    await page.check(document.querySelector<HTMLInputElement>('input[type="checkbox"]'))
    await page.click(page.button('Link anlegen'))
    expect(server.called('POST', '/api/v1/documents/5/links')!.body).toEqual({ recipient: 'Vermieter', days: 10, allow_download: false })
    expect(written).toEqual(['https://paper.example.com/l/lnk_secret'])
    expect(say).toHaveBeenCalledWith('Link angelegt und kopiert.')
    Reflect.deleteProperty(navigator, 'clipboard')
  })

  it('shows the new link to copy by hand where the clipboard refuses', async () => {
    server.answers['POST /api/v1/documents/5/links'] = { ...link({ id: 12, recipient: 'Vermieter' }), token: 'lnk_secret', url: 'https://paper.example.com/l/lnk_secret' }
    server.answers['GET /api/v1/documents/5/links'] = [link({ id: 12, recipient: 'Vermieter' }), link()]
    vi.stubGlobal('isSecureContext', false)
    await open()
    await page.type(document.querySelector<HTMLInputElement>('input[aria-label="Für wen, z. B. Steuerbüro"]'), 'Vermieter')
    await page.click(page.button('Link anlegen'))
    expect((document.querySelector('input[aria-label="Zum Kopieren"]') as HTMLInputElement).value).toBe('https://paper.example.com/l/lnk_secret')
    expect(say).toHaveBeenCalledWith('Link angelegt. Hier ist er zum Kopieren.')
  })

  it('copies a link again: the address comes from the server on request', async () => {
    const written: string[] = []
    vi.stubGlobal('isSecureContext', true)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => void written.push(text) } })
    server.answers['POST /api/v1/documents/5/links/11/address'] = { url: 'https://paper.example.com/l/lnk_again' }
    await open()
    expect(page.text).not.toContain('lnk_again')
    await page.click(page.button('Link für Steuerbüro kopieren'))
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/links/11/address'])
    expect(written).toEqual(['https://paper.example.com/l/lnk_again'])
    expect(say).toHaveBeenCalledWith('Link kopiert.')
    Reflect.deleteProperty(navigator, 'clipboard')
  })

  it('opens the page behind a link to see how it looks', async () => {
    const tab = { opener: {}, location: { href: '' }, close: vi.fn() }
    const opened = vi.fn(() => tab)
    vi.stubGlobal('open', opened)
    server.answers['POST /api/v1/documents/5/links/11/address'] = { url: 'https://paper.example.com/l/lnk_look' }
    await open()
    await page.click(page.button('So sieht der Link für Steuerbüro aus'))
    expect(opened).toHaveBeenCalledWith('', '_blank')
    expect(tab.location.href).toBe('https://paper.example.com/l/lnk_look')
    expect(tab.opener).toBeNull()
  })

  it('offers no copy where the caller may not copy, and none for a link that does not work', async () => {
    server.answers['GET /api/v1/documents/5/links'] = [link({ can_copy: false }), link({ id: 12, recipient: 'Bank', status: 'ended' })]
    await open()
    expect(page.button('Link für Steuerbüro kopieren')).toBeUndefined()
    expect(page.button('Link für Bank kopieren')).toBeUndefined()
    expect(page.text).toContain('darf nicht mehr teilen')
    expect(page.text).toContain('Steuerbüro')
  })

  it('does not take a link for nobody or past the longest time', async () => {
    await open()
    expect(page.button('Link anlegen')!.disabled).toBe(true)
    const until = document.querySelector<HTMLInputElement>('#share-until')!
    expect(until.max).toBe(dayInDays(30))
    expect(until.min).toBe(dayInDays(1))
  })

  it('says so when the operator has switched links off, and offers none', async () => {
    server.answers['GET /api/v1/sharing'] = { links_allowed: false, link_max_days: 30 }
    await open()
    expect(page.text).toContain('Der Betreiber hat Links nach außen abgeschaltet.')
    expect(page.button('Link anlegen')).toBeUndefined()
    expect(server.calls.some((c) => c.url.endsWith('/links'))).toBe(false)
  })

  it('marks a link that has run out', async () => {
    server.answers['GET /api/v1/documents/5/links'] = [link({ status: 'expired' })]
    await open()
    expect(page.text).toContain('abgelaufen')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    await open()
    expect(page.text).toContain('By link to the outside')
    expect(page.text).toContain('opened 2×')
  })
})
