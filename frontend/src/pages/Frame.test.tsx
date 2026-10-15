/**
 * The frame of the app and the pages around it, against a stand-in of the server: after the sign-in the archive and the
 * menu of the mock with the count of the inbox; the settings as one row of nine tabs for the operator and
 * nothing for a member; the page of the link in the mail to a new address (one press confirms, a link that does not
 * hold says so).
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

import type { Me } from '../api/client'
import App from '../App'
import '../i18n'
import { changeLanguage } from '../i18n'
import { idle, until } from '../test/wait'

const operator: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: '', language: 'de', email_confirmed: false, email_pending: '',
  oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1', whats_new_seen: '0.0.1',
  session_stage: 'full', second_factor_required: false, mail: false,
  profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const auth = { status: 'signedIn' as string, me: operator as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth, safeNext: (next: string | null) => next ?? '/' }))

type Call = { method: string; url: string; body: Record<string, unknown> | undefined }
let calls: Call[] = []
let answers: Record<string, unknown> = {}
let fails: Record<string, number> = {}

function serve(): void {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      const status = fails[`${method} ${url}`]
      if (status) return new Response(JSON.stringify({ detail: { code: 'email_link_invalid' } }), { status, headers: { 'Content-Type': 'application/json' } })
      return new Response(JSON.stringify(answers[`${method} ${url}`] ?? (url.includes('/api/v1/locales') || url.includes('/api/v1/accounts') || url.includes('/api/v1/invites') ? [] : {})), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

let root: Root
let box: HTMLDivElement

async function show(at: string | { pathname: string; state: unknown }): Promise<void> {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  await act(async () => root.render(<MemoryRouter initialEntries={[at]}><App /></MemoryRouter>))
  await idle()
}

async function click(target: Element | null | undefined): Promise<void> {
  expect(target).toBeTruthy()
  await act(async () => (target as HTMLElement).click())
  await idle()
}

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.status = 'signedIn'
  auth.me = operator
  answers = {}
  fails = {}
  sessionStorage.removeItem('nexpaper.startShown')
  serve()
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  vi.unstubAllGlobals()
})

describe('after the sign-in', () => {
  it('opens on the archive, with the menu of the mock: archive, inbox with its count, vaults', async () => {
    answers['GET /api/v1/counts'] = { inbox: 2, reading: 1, trash: 4, deadlines: 6, deadlines_overdue: 1 }
    sessionStorage.setItem('nexpaper.startShown', '1')
    await show('/')
    expect(box.querySelector('h1')!.textContent).toBe('Archiv')
    // The sidebar holds the mark, the camera under the upload button (as the mock), archive, inbox and vaults, and the
    // person's menu. The round button of the phone leads to the quick upload.
    const side = box.querySelector('aside')!
    expect([...side.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual(['/kamera', '/eingang', '/', '/fristen', '/tresore', '/ordnung', '/papierkorb'])
    expect(side.textContent).toContain('NEXPAPER')
    expect(side.querySelector('[data-testid="inbox-count"]')!.textContent).toBe('3')
    expect(side.querySelector('[data-testid="trash-count"]')!.textContent).toBe('4')
    // Deadlines: overdue and the next 14 days; something is overdue, so the number is drawn in the warning colour.
    const deadlines = side.querySelector('[data-testid="deadline-count"]')!
    expect(deadlines.textContent).toBe('6')
    expect(deadlines.className).toContain('bg-warn')
    expect(deadlines.getAttribute('title')).toBe('Etwas ist überfällig')
    // "Darf weg" (the keeping time is over) is no deadline: the menu does not count it. The archive asks for its own
    // number (one document, for the chip and the hint), nothing else.
    expect(calls.filter((c) => c.url.startsWith('/api/v1/keeping')).map((c) => c.url)).toEqual(['/api/v1/keeping?limit=1'])
    // The phone's bar: five, the deadlines instead of Order.
    const bar = box.querySelector('main ~ nav')!
    expect([...bar.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual(['/eingang', '/', '/fristen', '/tresore', '/papierkorb'])
    expect(box.querySelector('main a[href="/schnell"]')!.getAttribute('aria-label')).toBe('Hochladen')
  })

  it('has no deadlines for somebody who switched them off: no menu item, no number, Order in the phone bar, the page leads to the archive', async () => {
    auth.me = { ...operator, profile: { ...operator.profile, deadlines: false } }
    answers['GET /api/v1/counts'] = { inbox: 2, reading: 1, trash: 4, deadlines: 0, deadlines_overdue: 0 }
    sessionStorage.setItem('nexpaper.startShown', '1')
    await show('/')
    const side = box.querySelector('aside')!
    expect([...side.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual(['/kamera', '/eingang', '/', '/tresore', '/ordnung', '/papierkorb'])
    expect(side.querySelector('[data-testid="deadline-count"]')).toBeNull()
    expect(side.textContent).not.toContain('Fristen')
    // The bar of the phone gets Order back, and the account menu does not list it a second time.
    const bar = box.querySelector('main ~ nav')!
    expect([...bar.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual(['/eingang', '/', '/tresore', '/ordnung', '/papierkorb'])
    await click(box.querySelector('aside button[aria-haspopup="true"]'))
    const hidden = [...document.querySelectorAll('aside .card a')].find((a) => a.getAttribute('href') === '/ordnung')!
    expect(hidden.className).toContain('hidden')
    expect(hidden.className).not.toContain('lg:hidden')
    // The old address and a bookmark lead to the archive; the deadlines are not even asked for.
    act(() => root.unmount())
    box.remove()
    await show('/fristen')
    expect(box.querySelector('h1')!.textContent).toBe('Archiv')
    expect(calls.some((c) => c.url.startsWith('/api/v1/deadlines'))).toBe(false)
  })

  it('shows the deadlines page and the menu item to everybody else', async () => {
    answers['GET /api/v1/deadlines?done=true'] = { today: '2026-10-08', soon_days: 14, overdue: { total: 0, items: [] }, soon: { total: 0, items: [] }, later: { total: 0, items: [] }, done: null, counts: {}, shared: 0 }
    await show('/fristen')
    expect(box.querySelector('h1')!.textContent).toBe('Fristen')
    expect(box.querySelector('aside a[href="/fristen"]')).toBeTruthy()
  })

  it('opens on the inbox when something waits there, once per visit, and the menu still reaches the archive', async () => {
    sessionStorage.removeItem('nexpaper.startShown')
    answers['GET /api/v1/counts'] = { inbox: 2, reading: 0, trash: 0 }
    await show('/')
    await until(() => box.querySelector('h1')?.textContent === 'Eingang')
    // The archive is one click away, and it stays: the visit has had its start.
    await click(box.querySelector('aside a[href="/"]'))
    expect(box.querySelector('h1')!.textContent).toBe('Archiv')
  })

  it('stays on the archive when the inbox is empty', async () => {
    sessionStorage.removeItem('nexpaper.startShown')
    answers['GET /api/v1/counts'] = { inbox: 0, reading: 0, trash: 0 }
    await show('/')
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(box.querySelector('h1')!.textContent).toBe('Archiv')
  })

  it('sends an address that is nothing back to the start', async () => {
    await show('/nowhere')
    expect(box.querySelector('h1')!.textContent).toBe('Archiv')
  })

  it('has the menu of the person: account, settings for the operator, about, sign out', async () => {
    await show('/')
    await click(box.querySelector('aside button[aria-haspopup="true"]'))
    const items = [...document.querySelectorAll('aside .card a, aside .card button')].map((item) => item.textContent?.trim())
    expect(items).toEqual(['Mein Konto', 'Ordnung', 'Einstellungen', 'Über nexpaper', 'Abmelden'])
  })

  it('leaves the settings out of the menu of a member', async () => {
    auth.me = { ...operator, role: 'member' }
    await show('/')
    await click(box.querySelector('aside button[aria-haspopup="true"]'))
    const items = [...document.querySelectorAll('aside .card a, aside .card button')].map((item) => item.textContent?.trim())
    expect(items).toEqual(['Mein Konto', 'Ordnung', 'Über nexpaper', 'Abmelden'])
  })
})

describe('the sentence after something was done', () => {
  it('can lead on: "Papierkorb öffnen" opens the trash', async () => {
    sessionStorage.setItem('nexpaper.startShown', '1')
    await show({ pathname: '/', state: { notice: 'In den Papierkorb gelegt.', link: { to: '/papierkorb', label: 'Papierkorb öffnen' } } })
    const toast = box.querySelector('[role="status"]')!
    expect(toast.textContent).toContain('In den Papierkorb gelegt.')
    await click(toast.querySelector('a'))
    expect(box.querySelector('h1')!.textContent).toBe('Papierkorb')
  })
})

describe('a link to a document', () => {
  it('opens for somebody who is not signed in, without being sent to the sign-in', async () => {
    auth.status = 'signedOut'
    auth.me = null
    answers['GET /api/v1/l/lnk_abc123456789'] = { shared_by: 'Jule', recipient: 'x', title: 'Rechnung', sender: null, kind: null, date: null, pages: 1, until: '2026-10-31T10:00:00Z', allow_download: true, has_file: true }
    await show('/l/lnk_abc123456789')
    expect(box.querySelector('h1')!.textContent).toBe('Rechnung')
  })
})

describe('the settings', () => {
  it('are one row of thirteen tabs for the operator, in the order of the mock, and the part is in the address', async () => {
    await show('/einstellungen')
    expect([...box.querySelectorAll('[role="tab"]')].map((item) => item.textContent?.trim())).toEqual([
      'Konten', 'Anmeldung', 'Mail', 'KI', 'Ablage', 'Eingänge', 'Teilen', 'Web Push', 'Sicherung', 'Sprachen', 'Import', 'Log', 'API',
    ])
    expect(box.querySelector('[role="tab"][aria-selected="true"]')!.textContent).toContain('Konten')
    act(() => root.unmount())
    box.remove()
    await show('/einstellungen?tab=api')
    expect(box.querySelector('[role="tab"][aria-selected="true"]')!.textContent).toContain('API')
    expect(box.textContent).toContain('Schnittstelle')
    expect(box.textContent).toContain('/api/v1/docs')
  })

  it('send a member to the own account', async () => {
    auth.me = { ...operator, role: 'member' }
    await show('/einstellungen')
    expect(box.querySelector('h1')!.textContent).toBe('Mein Konto')
  })
})

describe('the page of the link to a new mail address', () => {
  it('says whom it is for and confirms only on a press', async () => {
    auth.status = 'signedOut'
    auth.me = null
    answers['GET /api/v1/email/confirm/' + 'a'.repeat(30)] = { name: 'jule', address: 'new@example.com' }
    answers['POST /api/v1/email/confirm/' + 'a'.repeat(30)] = { name: 'jule', address: 'new@example.com' }
    await show('/mail/' + 'a'.repeat(30))
    expect(box.querySelector('h1')!.textContent).toBe('Mailadresse bestätigen')
    expect(box.textContent).toContain('Für das Konto jule wurde new@example.com angegeben.')
    expect(calls.some((call) => call.method === 'POST')).toBe(false)
    await click([...box.querySelectorAll('button')].find((item) => item.textContent === 'Adresse bestätigen'))
    expect(calls.some((call) => call.method === 'POST' && call.url === '/api/v1/email/confirm/' + 'a'.repeat(30))).toBe(true)
    expect(box.querySelector('h1')!.textContent).toBe('Adresse bestätigt')
    expect(box.textContent).toContain('new@example.com gilt jetzt für dein Konto.')
  })

  it('says so when the link does not hold', async () => {
    auth.status = 'signedOut'
    auth.me = null
    fails['GET /api/v1/email/confirm/' + 'b'.repeat(30)] = 404
    await show('/mail/' + 'b'.repeat(30))
    expect(box.querySelector('h1')!.textContent).toBe('Link nicht gültig')
    expect(box.textContent).toContain('Schick dir unter Mein Konto einen neuen.')
  })
})
