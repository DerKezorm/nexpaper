/**
 * Deleting an account under Settings, Accounts, against a stand-in of the server: the dialog names the number of
 * documents in the person's own vault and offers the three ways (another person, a shared vault, away for good), the
 * name has to be typed as it is, and what is sent is exactly the choice.
 */
import type { Me } from '../../api/client'
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { AccountsCard } from './ServerCards'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()
const row = (over: Record<string, unknown>) => ({ ...me, locked: false, has_password: true, created_at: '2026-10-01T10:00:00Z', last_seen_at: null, ai_allowed: true, ...over })

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.me = me
  server.answers = {
    'GET /api/v1/accounts': [row({}), row({ id: 2, name: 'tom', display_name: 'Tom', role: 'member' }), row({ id: 3, name: 'lea', display_name: 'Lea', role: 'member' })],
    'GET /api/v1/invites': [],
    'GET /api/v1/people': [
      { id: 1, name: 'jule', display_name: 'Jule' },
      { id: 2, name: 'tom', display_name: 'Tom' },
      { id: 3, name: 'lea', display_name: 'Lea' },
    ],
    'GET /api/v1/accounts/2/leaving': { documents: 1637, sole_manager_of: [], shared_vaults: [{ id: 9, name: 'Haushalt', you_see: true }, { id: 10, name: 'Werkstatt', you_see: false }], heirs_you_see: [1] },
    'DELETE /api/v1/accounts/2': 204,
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

async function openFor(name: string): Promise<HTMLElement> {
  await page.show(<AccountsCard />, '/einstellungen?tab=accounts')
  await page.click(page.button(`Mehr für ${name}`))
  await page.click(page.button('Konto löschen'))
  return document.querySelector<HTMLElement>('[role="dialog"]')!
}

function field(dialog: HTMLElement, label: string): HTMLInputElement {
  const found = [...dialog.querySelectorAll('label')].find((l) => l.textContent?.startsWith(label))
  return found!.querySelector('input')!
}

function choose(dialog: HTMLElement, label: string): HTMLInputElement {
  return [...dialog.querySelectorAll('label')].find((l) => l.textContent?.startsWith(label))!.querySelector<HTMLInputElement>('input[type="radio"]')!
}

const deleteButton = (dialog: HTMLElement) => [...dialog.querySelectorAll('button')].find((b) => b.textContent === 'Konto löschen')!

describe('deleting an account', () => {
  it('names the number of documents and offers the three ways, sends nothing until a way, the name and the password are given', async () => {
    const dialog = await openFor('tom')
    expect(dialog.textContent).toContain('Im eigenen Tresor liegen 1.637 Dokumente, der Papierkorb mitgezählt. Wohin sollen sie?')
    expect(dialog.textContent).toContain('An eine andere Person')
    expect(dialog.textContent).toContain('In einen gemeinsamen Tresor')
    expect(dialog.textContent).toContain('Mitlöschen, samt Dateien')
    expect(deleteButton(dialog).disabled).toBe(true)
    await page.click(choose(dialog, 'Mitlöschen'))
    await page.type(field(dialog, 'Zum Bestätigen'), 'Tom')
    await page.type(field(dialog, 'Dein eigenes Passwort'), 'own password')
    expect(deleteButton(dialog).disabled).toBe(true)
    await page.type(field(dialog, 'Zum Bestätigen'), 'tom')
    expect(deleteButton(dialog).disabled).toBe(false)
    await page.click(deleteButton(dialog))
    expect(server.called('DELETE', '/api/v1/accounts/2')!.body).toEqual({ current_password: 'own password', confirm_name: 'tom', documents: 'delete_documents' })
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })

  it('waits for a way, and for the person or vault of that way, before it deletes anything', async () => {
    const dialog = await openFor('tom')
    await page.type(field(dialog, 'Zum Bestätigen'), 'tom')
    await page.type(field(dialog, 'Dein eigenes Passwort'), 'own password')
    expect(deleteButton(dialog).disabled).toBe(true)
    await page.click(choose(dialog, 'An eine andere Person'))
    expect(deleteButton(dialog).disabled).toBe(true)
    await page.click(choose(dialog, 'In einen gemeinsamen Tresor'))
    expect(deleteButton(dialog).disabled).toBe(true)
    await page.choose(dialog.querySelector<HTMLSelectElement>('select'), '9')
    expect(deleteButton(dialog).disabled).toBe(false)
  })

  it('says plainly who will see the documents, and when that is the operator', async () => {
    const dialog = await openFor('tom')
    expect(dialog.textContent).toContain('Sehen werden sie die Person und alle, die Rechte in ihrem Tresor haben.')
    expect(dialog.textContent).toContain('Sehen werden sie alle Mitglieder dieses Tresors.')
    await page.click(choose(dialog, 'An eine andere Person'))
    await page.choose(dialog.querySelector<HTMLSelectElement>('select'), '3')
    expect(dialog.textContent).not.toContain('Du siehst die Dokumente danach selbst.')
    await page.choose(dialog.querySelector<HTMLSelectElement>('select'), '1')
    expect(dialog.querySelector('[role="note"]')!.textContent).toBe('Du siehst die Dokumente danach selbst.')
    await page.click(choose(dialog, 'In einen gemeinsamen Tresor'))
    await page.choose(dialog.querySelector<HTMLSelectElement>('select'), '10')
    expect(dialog.querySelector('[role="note"]')).toBeNull()
    await page.choose(dialog.querySelector<HTMLSelectElement>('select'), '9')
    expect(dialog.querySelector('[role="note"]')!.textContent).toBe('Du siehst die Dokumente danach selbst.')
  })

  it('hands the documents to another person, chosen from the others', async () => {
    const dialog = await openFor('tom')
    await page.click(choose(dialog, 'An eine andere Person'))
    const people = dialog.querySelector<HTMLSelectElement>('select')!
    // The operator may choose themselves too (in the open, see above).
    expect([...people.options].map((o) => o.textContent)).toEqual(['', 'Jule', 'Lea'])
    await page.choose(people, '3')
    await page.type(field(dialog, 'Zum Bestätigen'), 'tom')
    await page.type(field(dialog, 'Dein eigenes Passwort'), 'own password')
    await page.click(deleteButton(dialog))
    expect(server.called('DELETE', '/api/v1/accounts/2')!.body).toEqual({ current_password: 'own password', confirm_name: 'tom', documents: 'transfer_to_user', target_user_id: 3 })
  })

  it('puts the documents into a shared vault', async () => {
    const dialog = await openFor('tom')
    await page.click(choose(dialog, 'In einen gemeinsamen Tresor'))
    await page.choose(dialog.querySelector<HTMLSelectElement>('select'), '9')
    await page.type(field(dialog, 'Zum Bestätigen'), 'tom')
    await page.type(field(dialog, 'Dein eigenes Passwort'), 'own password')
    await page.click(deleteButton(dialog))
    expect(server.called('DELETE', '/api/v1/accounts/2')!.body).toEqual({ current_password: 'own password', confirm_name: 'tom', documents: 'transfer_to_vault', target_vault_id: 9 })
  })

  it('asks for no way where the vault is empty, and says what keeps an account', async () => {
    server.answers['GET /api/v1/accounts/3/leaving'] = { documents: 0, sole_manager_of: [{ id: 9, name: 'Haushalt' }], shared_vaults: [], heirs_you_see: [] }
    const dialog = await openFor('lea')
    expect(dialog.textContent).toContain('Im eigenen Tresor liegen keine Dokumente.')
    expect(dialog.textContent).toContain('lea verwaltet „Haushalt“ allein.')
    expect(dialog.querySelector('input[type="radio"]')).toBeNull()
    await page.type(field(dialog, 'Zum Bestätigen'), 'lea')
    await page.type(field(dialog, 'Dein eigenes Passwort'), 'own password')
    expect(deleteButton(dialog).disabled).toBe(true)
  })

  it('shows what the server refused and keeps the dialog', async () => {
    server.fails['DELETE /api/v1/accounts/2'] = { status: 422, code: 'name_mismatch' }
    const dialog = await openFor('tom')
    await page.click(choose(dialog, 'Mitlöschen'))
    await page.type(field(dialog, 'Zum Bestätigen'), 'tom')
    await page.type(field(dialog, 'Dein eigenes Passwort'), 'own password')
    await page.click(deleteButton(dialog))
    expect(dialog.textContent).toContain('Der Name stimmt nicht.')
    expect(document.querySelector('[role="dialog"]')).toBeTruthy()
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    await page.show(<AccountsCard />, '/einstellungen?tab=accounts')
    await page.click(page.button('More for tom'))
    await page.click(page.button('Delete account'))
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!
    expect(dialog.textContent).toContain('The own vault holds 1,637 documents, the trash included.')
    expect(dialog.textContent).toContain('To another person')
  })
})
