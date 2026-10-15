/**
 * The order page against a stand-in of the server: the lists with how many documents each entry has, the filter by vault,
 * the search, the entries a person may and may not change, and that rename, merge and delete each ask first (nothing is
 * sent before the answer) and say how many documents they reach.
 */
import { act } from 'react'
import { useLocation } from 'react-router-dom'

import type { Me } from '../api/client'
import { changeLanguage } from '../i18n'
import { Page, Server, plain } from '../test/harness'
import { idle, until } from '../test/wait'
import { OrderPage } from './OrderPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

const vaults = [
  { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 3, size: 1, members: [] },
  { id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'manage', documents: 9, size: 1, members: [] },
  { id: 10, name: 'Ferienwohnung', icon: 'sun', personal_of: null, my_right: 'read', documents: 2, size: 1, members: [] },
]
const entry = (id: number, name: string, vault_id: number | null, documents: number, extra: Record<string, unknown> = {}) => ({
  id, name, vault_id, right: vault_id === 10 ? 'read' : vault_id === null ? null : 'manage', documents, in_trash: 0, can_change: vault_id !== 10 && vault_id !== null, ...extra,
})
const SENDERS = [entry(1, 'Stadtwerke Lindenau', 9, 12), entry(2, 'Stadtwerke', 9, 2, { in_trash: 1 }), entry(3, 'Hansa', 7, 1), entry(4, 'Reinigung Glanz', 10, 4)]

function Where() {
  const at = useLocation()
  return <p data-testid="where">{at.pathname + at.search}</p>
}
const where = () => plain(page.box.querySelector('[data-testid="where"]')!.textContent)
const show = (at = '/ordnung') =>
  page.show(
    <>
      <OrderPage />
      <Where />
    </>,
    at,
  )
const rows = () => [...page.box.querySelectorAll('ul[aria-label] > li')].map((li) => plain(li.textContent))

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/vaults': vaults,
    'GET /api/v1/order/senders?order=name&limit=100': { items: SENDERS, total: 4 },
    'GET /api/v1/order/senders?order=documents&limit=100': { items: [SENDERS[0], SENDERS[3], SENDERS[1], SENDERS[2]], total: 4 },
    'GET /api/v1/order/senders?q=stadt&order=name&limit=100': { items: SENDERS.slice(0, 2), total: 2 },
    'GET /api/v1/order/senders?vault_id=9&order=name&limit=100': { items: SENDERS.slice(0, 2), total: 2 },
    'GET /api/v1/order/tags?order=name&limit=100': { items: [entry(20, 'strom', 9, 5), entry(21, 'energie', 9, 0)], total: 2 },
    'GET /api/v1/order/kinds?order=name&limit=500': {
      items: [
        entry(30, 'Rechnung', null, 40, { key: 'invoice', hue: 28, position: 0, can_change: true }),
        entry(31, 'Mietvertrag', 9, 2, { key: '', hue: 120, position: 0 }),
      ],
      total: 2,
    },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the lists', () => {
  it('show every entry with how many documents have it, and what is in the trash', async () => {
    await show()
    expect(page.box.querySelector('h1')!.textContent).toBe('Ordnung')
    const list = rows()
    expect(list).toHaveLength(4)
    expect(list[0]).toContain('Stadtwerke Lindenau')
    expect(list[0]).toContain('Haushalt')
    expect(list[0]).toContain('12 Dokumente')
    expect(list[1]).toContain('2 Dokumente · 1 im Papierkorb')
    expect(list[2]).toContain('Mein Tresor')
    expect(list[2]).toContain('1 Dokument')
    expect(page.text).not.toContain('1 Dokumente')
  })

  it('say "kein Dokument" for an unused tag, on the tab for tags', async () => {
    await show('/ordnung?tab=tags')
    expect(rows().join('|')).toContain('energie')
    expect(rows().find((r) => r.includes('energie'))).toContain('kein Dokument')
  })

  it('filter by vault, search by name, and sort by use, each as a request to the server', async () => {
    await show()
    await page.click(page.button('Haushalt'))
    expect(server.called('GET', '/api/v1/order/senders?vault_id=9&order=name&limit=100')).toBeTruthy()
    expect(where()).toBe('/ordnung?vault=9')
    expect(rows()).toHaveLength(2)
    await page.click(page.button('Alle'))
    await page.choose(page.box.querySelector<HTMLSelectElement>('select[aria-label="Sortierung"]'), 'documents')
    expect(server.called('GET', '/api/v1/order/senders?order=documents&limit=100')).toBeTruthy()
    expect(rows()[1]).toContain('Reinigung Glanz')
    await page.choose(page.box.querySelector<HTMLSelectElement>('select[aria-label="Sortierung"]'), 'name')
    await page.type(page.box.querySelector<HTMLInputElement>('input[aria-label="Absender suchen"]'), 'stadt')
    await act(async () => void (await new Promise((resolve) => setTimeout(resolve, 400))))
    await idle()
    expect(server.called('GET', '/api/v1/order/senders?q=stadt&order=name&limit=100')).toBeTruthy()
    expect(rows()).toHaveLength(2)
  })

  it('keep the tab in the address', async () => {
    await show()
    await page.click(page.box.querySelector<HTMLElement>('[role="tab"][aria-selected="false"]'))
    expect(where()).toBe('/ordnung?tab=kinds')
    await page.click([...page.box.querySelectorAll<HTMLElement>('[role="tab"]')].find((tab) => tab.textContent === 'Tags'))
    expect(where()).toBe('/ordnung?tab=tags')
  })
})

describe('what a person may change', () => {
  it('shows the tools only on entries of vaults they manage, and says why not elsewhere', async () => {
    await show()
    expect(page.button('Löschen: Stadtwerke Lindenau')).toBeTruthy()
    expect(page.button('Umbenennen: Hansa')).toBeTruthy()
    expect(page.button('Zusammenführen: Hansa')).toBeTruthy()
    expect(page.button('Löschen: Reinigung Glanz')).toBeUndefined()
    expect(page.text).toContain('In diesem Tresor darfst du nur ansehen.')
  })

  it('leaves the kinds that come with nexpaper to the operator', async () => {
    auth.me = { ...me, role: 'member' }
    server.answers['GET /api/v1/order/kinds?order=name&limit=500'] = {
      items: [entry(30, 'Rechnung', null, 40, { key: 'invoice', hue: 28, position: 0, can_change: false }), entry(31, 'Mietvertrag', 9, 2, { key: '', hue: 120, position: 0 })],
      total: 2,
    }
    await show('/ordnung?tab=kinds')
    expect(page.button('Löschen: Rechnung')).toBeUndefined()
    expect(page.button('Löschen: Mietvertrag')).toBeTruthy()
    expect(page.text).toContain('Die Arten für alle Tresore pflegt der Betreiber.')
  })

  it('filters kinds "for all vaults" without asking the server for a vault', async () => {
    await show('/ordnung?tab=kinds&vault=server')
    expect(rows()).toHaveLength(1)
    expect(rows()[0]).toContain('Rechnung')
    expect(rows()[0]).toContain('Für alle Tresore')
  })
})

describe('changing asks first', () => {
  it('deletes after a question that names the number of documents, and not before', async () => {
    server.answers['DELETE /api/v1/senders/1'] = 204
    await show()
    await page.click(page.button('Löschen: Stadtwerke Lindenau'))
    expect(server.changes()).toEqual([])
    expect(plain(page.dialog!.textContent)).toContain('12 Dokumente haben „Stadtwerke Lindenau“ als Absender.')
    // Cancel sends nothing either.
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Löschen: Stadtwerke Lindenau'))
    await page.inDialog('Trotzdem löschen')
    expect(server.changes()).toEqual(['DELETE /api/v1/senders/1'])
  })

  it('asks the other way for an entry nobody uses', async () => {
    server.answers['DELETE /api/v1/tags/21'] = 204
    await show('/ordnung?tab=tags')
    await page.click(page.button('Löschen: energie'))
    expect(server.changes()).toEqual([])
    expect(plain(page.dialog!.textContent)).toContain('Der Tag „energie“ geht aus dem Tresor.')
    await page.inDialog('Tag löschen')
    expect(server.changes()).toEqual(['DELETE /api/v1/tags/21'])
  })

  it('says of a kind for all vaults that it reaches vaults the person does not see', async () => {
    server.answers['DELETE /api/v1/kinds/30'] = 204
    await show('/ordnung?tab=kinds')
    await page.click(page.button('Löschen: Rechnung'))
    expect(plain(page.dialog!.textContent)).toContain('auch in Tresoren, die du nicht siehst')
    expect(server.changes()).toEqual([])
    await page.inDialog('Art löschen')
    expect(server.changes()).toEqual(['DELETE /api/v1/kinds/30'])
  })

  it('merges in two steps: choose where, then confirm with the numbers', async () => {
    server.answers['GET /api/v1/order/senders?vault_id=9&limit=50'] = { items: SENDERS.slice(0, 2), total: 2 }
    server.answers['POST /api/v1/senders/2/merge'] = { id: 1, name: 'Stadtwerke Lindenau' }
    await show()
    await page.click(page.button('Zusammenführen: Stadtwerke'))
    const dialog = await until(() => page.dialog)
    // Only the other entries of the same vault are offered, not the entry itself.
    await until(() => dialog.querySelectorAll('li button').length > 0)
    expect([...dialog.querySelectorAll('li button')].map((b) => plain(b.textContent))).toEqual(['Stadtwerke Lindenau12 Dokumente'])
    expect(server.changes()).toEqual([])
    await page.click(dialog.querySelector<HTMLElement>('li button'))
    expect(server.changes()).toEqual([])
    expect(plain(page.dialog!.textContent)).toContain('Die 3 Dokumente von „Stadtwerke“ bekommen „Stadtwerke Lindenau“ als Absender.')
    await page.inDialog('Zusammenführen')
    expect(server.called('POST', '/api/v1/senders/2/merge')!.body).toEqual({ into: 1 })
  })

  it('renames, and refuses a name the vault has already (that is a merge)', async () => {
    server.answers['GET /api/v1/order/senders?vault_id=9&q=stadtwerke+LINDENAU&limit=50'] = { items: [SENDERS[0]], total: 1 }
    server.answers['GET /api/v1/order/senders?vault_id=9&q=Stadtwerke+Nord&limit=50'] = { items: [], total: 0 }
    server.answers['PATCH /api/v1/senders/2'] = { id: 2, name: 'Stadtwerke Nord' }
    await show()
    await page.click(page.button('Umbenennen: Stadtwerke'))
    const field = page.dialog!.querySelector<HTMLInputElement>('input')!
    await page.type(field, 'stadtwerke LINDENAU')
    await page.inDialog('Speichern')
    expect(page.text).toContain('Diesen Namen gibt es schon.')
    expect(server.changes()).toEqual([])
    await page.type(field, 'Stadtwerke Nord')
    await page.inDialog('Speichern')
    expect(server.called('PATCH', '/api/v1/senders/2')!.body).toEqual({ name: 'Stadtwerke Nord' })
  })
})

describe('a new kind', () => {
  it('goes to the vault the person chose, or to all vaults for the operator', async () => {
    server.answers['POST /api/v1/kinds'] = { id: 40, key: '', name: 'Garantie', hue: 94, position: 2 }
    await show('/ordnung?tab=kinds')
    const form = page.box.querySelector('form[aria-label="Neue Art"]')!
    await page.type(form.querySelector('input'), 'Garantie')
    await page.click(page.button('Hinzufügen'))
    expect(server.called('POST', '/api/v1/kinds')!.body).toEqual({ name: 'Garantie', hue: 94 })
  })

  it('offers a member only the vaults they may add to', async () => {
    auth.me = { ...me, role: 'member' }
    await show('/ordnung?tab=kinds')
    const choices = [...page.box.querySelectorAll('form[aria-label="Neue Art"] option')].map((o) => plain(o.textContent))
    expect(choices).toEqual(['Jule (persönlich)', 'Haushalt'])
  })
})
