/**
 * The vaults page against test data: the cards with their members and rights, the documents shared one by one, the open
 * links, the dialog that changes who is in (sent on "Save", the owner of a personal vault staying), the operator's button
 * for a shared vault, and the operator's settings for links to the outside.
 */
import { act } from 'react'

import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { INBOX_CHANGED } from '../lib/say'
import { Page, Server, plain } from '../test/harness'
import { idle } from '../test/wait'
import { SharingCard } from './settings/SharingCard'
import { VaultsPage } from './VaultsPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: 7, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const people = [
  { id: 1, name: 'jule', display_name: 'Jule' },
  { id: 2, name: 'tom', display_name: 'Tom' },
  { id: 3, name: 'lea', display_name: 'Lea' },
]
const mineVault = { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 1, size: 1.2e9, members: [{ user_id: 1, name: 'jule', display_name: 'Jule', right: 'manage' }] }
const toms = { id: 8, name: 'Tom', icon: 'user', personal_of: 2, my_right: 'read', documents: 167, size: 900e6, members: [{ user_id: 2, name: 'tom', display_name: 'Tom', right: 'manage' }, { user_id: 1, name: 'jule', display_name: 'Jule', right: 'read' }] }
const house = {
  id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'manage', documents: 1637, size: 5e9,
  members: [{ user_id: 1, name: 'jule', display_name: 'Jule', right: 'manage' }, { user_id: 2, name: 'tom', display_name: 'Tom', right: 'edit' }, { user_id: 3, name: 'lea', display_name: 'Lea', right: 'read' }],
}
const doc = { id: 30, vault_id: 99, owner: { id: 3, name: 'lea', display_name: 'Lea' }, title: 'Zahnreinigung', sender: { id: 1, name: 'Zahnarztpraxis' }, date: '2026-10-02', my_right: 'read', via_share: true }

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/vaults': [mineVault, toms, house],
    'GET /api/v1/people': people,
    // Only the documents seen through a share alone: the server filters (the page asks for no other).
    'GET /api/v1/documents?via_share=true&after=0&limit=500': { items: [doc], next: null },
    'GET /api/v1/links': [
      { id: 4, document_id: 30, document_title: 'Mietvertrag', recipient: 'Steuerbüro', until: '2026-10-31T10:00:00Z', opened_count: 3, status: 'active' },
      { id: 5, document_id: 30, document_title: 'Alt', recipient: 'X', until: '2026-01-01T10:00:00Z', opened_count: 0, status: 'expired' },
    ],
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the cards', () => {
  it('show every vault with its size, who is in and with which right, and the own one as mine', async () => {
    await page.show(<VaultsPage />, '/tresore')
    const text = page.box.textContent ?? ''
    expect(page.box.querySelector('h1')!.textContent).toBe('Tresore')
    expect(text).toContain('Mein Tresor')
    // Sizes as a disk counts them (1.2e9 bytes are 1,2 GB), numbers with the separator of the language.
    expect(text).toContain('persönlich · 1 Dokument · 1,2 GB')
    expect(text).toContain('persönlicher Tresor von Tom · 167 Dokumente · 900 MB')
    expect(text).toContain('gemeinsam · 1.637 Dokumente · 5 GB')
    expect(text).toContain('hierhin gehen deine Uploads')
    const cards = page.box.querySelectorAll('section.card')
    expect([...cards[1].querySelectorAll('li')].map((li) => li.textContent)).toEqual(['TTomVerwalten', 'JDuLesen'])
  })

  it('offer to change the rights only where the person manages', async () => {
    await page.show(<VaultsPage />, '/tresore')
    expect(page.button('Freigaben ändern: Mein Tresor')).toBeTruthy()
    expect(page.button('Freigaben ändern: Haushalt')).toBeTruthy()
    expect(page.button('Freigaben ändern: Tom')).toBeUndefined()
  })

  it('list the documents shared one by one and the open links, and revoke a link', async () => {
    server.answers['DELETE /api/v1/documents/30/links/4'] = 204
    await page.show(<VaultsPage />, '/tresore')
    expect(page.text).toContain('Einzeln mit dir geteilt')
    expect(page.text).toContain('von Lea · Zahnarztpraxis · 02.10.2026')
    expect(page.text).not.toContain('Alt für X')
    expect(page.text).toContain('Mietvertrag für Steuerbüro')
    expect(page.text).toContain('bis 31.10.2026 · 3× geöffnet')
    await page.click(page.button('Zurückziehen'))
    expect(server.changes()).toEqual([])
    await page.inDialog('Link zurückziehen')
    expect(server.changes()).toEqual(['DELETE /api/v1/documents/30/links/4'])
    expect(page.text).not.toContain('Mietvertrag für Steuerbüro')
  })

  it('open the document from the whole row, and show the right as a note, not as a button', async () => {
    await page.show(<VaultsPage />, '/tresore')
    const row = [...page.box.querySelectorAll('a')].find((a) => a.textContent?.includes('Zahnreinigung'))!
    expect(row.getAttribute('href')).toBe('/dokument/30')
    expect(row.textContent).toContain('nur lesen')
    // Nothing on the row is a button of its own that does nothing.
    expect(row.querySelector('button')).toBeNull()
  })

  it('fetch every document shared one by one, page after page', async () => {
    server.answers['GET /api/v1/documents?via_share=true&after=0&limit=500'] = { items: [doc], next: 30 }
    server.answers['GET /api/v1/documents?via_share=true&after=30&limit=500'] = { items: [{ ...doc, id: 640, title: 'Spät geteilt' }], next: null }
    await page.show(<VaultsPage />, '/tresore')
    expect(page.text).toContain('Zahnreinigung')
    expect(page.text).toContain('Spät geteilt')
  })

  it('say where uploads go when the person chose no vault: into their own', async () => {
    auth.me = { ...me, profile: { ...me.profile, default_vault: null } }
    await page.show(<VaultsPage />, '/tresore')
    const cards = page.box.querySelectorAll('section.card')
    expect(cards[0].textContent).toContain('hierhin gehen deine Uploads')
    expect(cards[2].textContent).not.toContain('hierhin gehen deine Uploads')
  })

  it('say what a personal vault means', async () => {
    await page.show(<VaultsPage />, '/tresore')
    expect(page.text).toContain('Ein persönlicher Tresor heißt, dass nexpaper ihn niemand anderem zeigt.')
  })

  it('show a problem instead of nothing when the server does not answer', async () => {
    server.fails['GET /api/v1/vaults'] = { status: 500, code: 'internal_error' }
    await page.show(<VaultsPage />, '/tresore')
    expect(page.box.querySelector('[role="alert"]')).toBeTruthy()
  })
})

describe('who is in a vault', () => {
  it('is changed in a dialog and sent on Save, all of it in one call', async () => {
    server.answers['PUT /api/v1/vaults/9/members'] = house
    await page.show(<VaultsPage />, '/tresore')
    await page.click(page.button('Freigaben ändern: Haushalt'))
    expect(page.text).toContain('Haushalt: wer darf was')
    await page.choose(page.select('Recht von Tom'), 'manage')
    await page.click(page.button('Entfernen: Lea'))
    await page.click(page.button('Speichern'))
    // Taking somebody out asks first, and says who loses the vault; Abbrechen sends nothing.
    expect(server.changes()).toEqual([])
    expect(plain(page.dialog!.textContent)).toContain('Lea sieht danach nichts mehr in diesem Tresor.')
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Speichern'))
    await page.inDialog('Entfernen')
    expect(server.changes()).toEqual(['PUT /api/v1/vaults/9/members'])
    expect(server.called('PUT', '/api/v1/vaults/9/members')!.body).toEqual({
      members: [
        { user_id: 1, right: 'manage' },
        { user_id: 2, right: 'manage' },
      ],
    })
  })

  it('can add a person who is not in, with the right to read at first', async () => {
    server.answers['PUT /api/v1/vaults/7/members'] = mineVault
    await page.show(<VaultsPage />, '/tresore')
    await page.click(page.button('Freigaben ändern: Mein Tresor'))
    expect(page.text).toContain('Meinen Tresor teilen')
    expect(page.text).toContain('Besitzer, immer Verwalten')
    await page.click([...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Lea'))
    await page.click(page.button('Speichern'))
    expect(server.called('PUT', '/api/v1/vaults/7/members')!.body).toEqual({
      members: [
        { user_id: 1, right: 'manage' },
        { user_id: 3, right: 'read' },
      ],
    })
  })

  it('leaves the owner of a personal vault no choice', async () => {
    await page.show(<VaultsPage />, '/tresore')
    await page.click(page.button('Freigaben ändern: Mein Tresor'))
    expect(page.select('Recht von Jule')).toBeNull()
    expect(page.button('Entfernen: Jule')).toBeUndefined()
  })

  it('shows what the server refuses and keeps the dialog open', async () => {
    server.fails['PUT /api/v1/vaults/9/members'] = { status: 409, code: 'last_manager' }
    await page.show(<VaultsPage />, '/tresore')
    await page.click(page.button('Freigaben ändern: Haushalt'))
    await page.click(page.button('Entfernen: Lea'))
    await page.click(page.button('Speichern'))
    await page.inDialog('Entfernen')
    expect(page.text).toContain('Ein Tresor braucht mindestens einen, der ihn verwaltet.')
    expect(page.button('Speichern')).toBeTruthy()
  })
})

describe('a shared vault', () => {
  it('is made by the operator, who has the button, and by nobody else', async () => {
    server.answers['POST /api/v1/vaults'] = { ...house, id: 10, name: 'Auto' }
    await page.show(<VaultsPage />, '/tresore')
    await page.click(page.button('Gemeinsamen Tresor anlegen'))
    await page.type(document.querySelector<HTMLInputElement>('input[placeholder="Auto"]'), '  Auto ')
    await page.click(page.button('Anlegen'))
    expect(server.called('POST', '/api/v1/vaults')!.body).toEqual({ name: 'Auto', icon: 'folder' })
    page.close()
    auth.me = { ...me, role: 'member' }
    await page.show(<VaultsPage />, '/tresore')
    expect(page.button('Gemeinsamen Tresor anlegen')).toBeUndefined()
  })
})

describe('the settings for links to the outside', () => {
  const settings = { links_allowed: true, link_max_days: 30, public_url: '', password_login: true, two_factor_required: false, oidc_second_factor_by_provider: false, backup_schedule: 'daily', backup_keep: 7, smtp_host: '', smtp_port: 587, smtp_security: 'starttls', smtp_user: '', smtp_password_set: false, smtp_from: '', api_keys_allowed: false, update_check: true }

  it('show the switch, the longest time and who has links open', async () => {
    server.answers['GET /api/v1/settings'] = settings
    server.answers['GET /api/v1/sharing/overview'] = { open_links: 2, people: 2, next_end: '2026-10-31T10:00:00Z' }
    await page.show(<SharingCard />, '/einstellungen?tab=sharing')
    expect(page.text).toContain('Links nach außen erlauben')
    expect(page.text).toContain('2 Links von 2 Personen, der nächste läuft am 31.10.2026 ab.')
    expect((document.querySelector('select') as HTMLSelectElement).value).toBe('30')
  })

  it('switch links off at once, and send the longest time chosen', async () => {
    server.answers['GET /api/v1/settings'] = settings
    server.answers['GET /api/v1/sharing/overview'] = { open_links: 0, people: 0, next_end: null }
    server.answers['PUT /api/v1/settings'] = { ...settings, link_max_days: 14 }
    await page.show(<SharingCard />, '/einstellungen?tab=sharing')
    expect(page.text).toContain('Gerade ist kein Link offen.')
    await page.choose(document.querySelector('select'), '14')
    expect(server.called('PUT', '/api/v1/settings')!.body).toEqual({ link_max_days: 14 })
    server.answers['PUT /api/v1/settings'] = { ...settings, links_allowed: false }
    await page.click(document.querySelector<HTMLElement>('[role="switch"]'))
    expect(server.calls.filter((c) => c.method === 'PUT').at(-1)!.body).toEqual({ links_allowed: false })
    expect(document.querySelector('select')).toBeNull()
  })
})

describe('after an upload', () => {
  it('the cards count anew at once', async () => {
    await page.show(<VaultsPage />, '/tresore')
    const before = server.calls.filter((c) => c.url === '/api/v1/vaults').length
    server.answers['GET /api/v1/vaults'] = [{ ...mineVault, documents: 2 }, toms, house]
    await act(async () => window.dispatchEvent(new Event(INBOX_CHANGED)))
    await idle()
    expect(server.calls.filter((c) => c.url === '/api/v1/vaults').length).toBe(before + 1)
    expect(page.box.textContent).toContain('persönlich · 2 Dokumente')
  })
})
