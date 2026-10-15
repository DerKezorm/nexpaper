/**
 * The trash against a stand-in of the server: what was deleted, until when it stays; restoring for whoever may change a
 * document; deleting for good, after a question, only for the managers of its vault and the person it belongs to.
 */
import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { Page, Server, plain } from '../test/harness'
import { TrashPage } from './TrashPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'member', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

function doc(id: number, title: string, right: string, owner: number) {
  return {
    id, vault_id: 9, owner: { id: owner, name: owner === 1 ? 'jule' : 'tom', display_name: '' }, title, sender: null, kind: null, date: null, amount: null,
    currency: 'EUR', tags: [], dates: [], pages: 1, source: 'upload', status: 'trash', added_at: '2026-10-01T08:00:00Z', trashed_at: `2026-10-0${id}T08:00:00Z`,
    trash_ends_at: `2026-11-0${id}T08:00:00Z`, change_seq: id, current_version: 1, my_right: right, via_share: false, can_share: false, notes: 0,
    process_error: '', duplicate: null,
  }
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = {
    'GET /api/v1/documents?status=trash&after=0&limit=500': {
      items: [doc(1, 'Mein Brief', 'edit', 1), doc(2, 'Toms Brief', 'edit', 2), doc(3, 'Verwalteter Brief', 'manage', 2), doc(4, 'Nur gelesen', 'read', 1)],
      next: null,
    },
    'POST /api/v1/documents/2/restore': {},
    'POST /api/v1/documents/1/purge': 204,
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the trash', () => {
  it('lists what was deleted, newest first, and until when it stays', async () => {
    await page.show(<TrashPage />, '/papierkorb')
    const rows = [...page.box.querySelectorAll('ul li')]
    expect(rows.map((row) => plain(row.querySelector('.font-semibold')!.textContent))).toEqual(['Nur gelesen', 'Verwalteter Brief', 'Toms Brief', 'Mein Brief'])
    expect(plain(rows[3].textContent)).toContain('endgültig weg am 01.11.2026')
  })

  it('offers restoring to whoever may change it, and deleting for good to the managers and the owner', async () => {
    await page.show(<TrashPage />, '/papierkorb')
    const rows = [...page.box.querySelectorAll('ul li')]
    const offers = rows.map((row) => [...row.querySelectorAll('button')].map((b) => plain(b.textContent)?.trim()))
    expect(offers).toEqual([[], ['Wiederherstellen', 'Endgültig löschen'], ['Wiederherstellen'], ['Wiederherstellen', 'Endgültig löschen']])
    await page.click(page.button('Wiederherstellen', rows[2]))
    expect(server.changes()).toEqual(['POST /api/v1/documents/2/restore'])
  })

  it('says it plainly when the document left the trash meanwhile', async () => {
    server.fails['POST /api/v1/documents/1/purge'] = { status: 409, code: 'not_in_trash' }
    await page.show(<TrashPage />, '/papierkorb')
    const rows = [...page.box.querySelectorAll('ul li')]
    await page.click(page.button('Endgültig löschen', rows[3]))
    await page.inDialog('Endgültig löschen')
    // The refusal is told inside the dialog, which stays open.
    expect(plain(page.dialog!.textContent)).toContain('Das Dokument liegt nicht mehr im Papierkorb. Lade die Seite neu.')
  })

  it('asks before deleting for good', async () => {
    await page.show(<TrashPage />, '/papierkorb')
    const rows = [...page.box.querySelectorAll('ul li')]
    await page.click(page.button('Endgültig löschen', rows[3]))
    expect(page.text).toContain('„Mein Brief“ wird samt allen Fassungen und Dateien gelöscht. Das lässt sich nicht zurückholen.')
    expect(server.changes()).toEqual([])
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Endgültig löschen', rows[3]))
    await page.inDialog('Endgültig löschen')
    expect(server.changes()).toEqual(['POST /api/v1/documents/1/purge'])
  })
})
