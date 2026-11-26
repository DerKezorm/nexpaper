/**
 * The frame of the app and the pages around it, against a stand-in of the server: after the sign-in the archive and the
 * sidebar with the count of the inbox; the settings in areas as in nexnotes, the server's only for the operator; the page of the link in the mail to a new address (one press confirms, a link that does not
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
import { GENERAL_PARTS } from './settings/areas'

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
  answers = { 'GET /api/connect/partners': [], 'GET /api/connect/admin': { connections: true, addresses: {}, partners: ['nexmail', 'nextasks', 'nextime'] }, 'GET /api/v1/connections/mcp/requests?status=waiting': [] }
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
  it('opens on the archive, with the menu: archive, inbox with its count, vaults', async () => {
    answers['GET /api/v1/counts'] = { inbox: 2, reading: 1, trash: 4, deadlines: 6, deadlines_overdue: 1 }
    sessionStorage.setItem('nexpaper.startShown', '1')
    await show('/')
    expect(box.querySelector('h1')!.textContent).toBe('Archiv')
    // The sidebar as nexnotes': the mark, the search field (to the archive), the camera, inbox, archive and deadlines,
    // below a line the vaults' page, order and trash, at the foot the account's row to the settings. The round button
    // of the phone leads to the quick upload.
    const side = box.querySelector('aside')!
    expect([...side.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual(['/', '/', '/kamera', '/eingang', '/', '/fristen', '/tresore', '/ordnung', '/papierkorb', '/settings'])
    expect(side.querySelector('[data-testid="sidebar-search"]')!.textContent).toContain('Strg K')
    expect(side.textContent).toContain('NEXPAPER')
    expect(side.querySelector('[data-testid="inbox-count"]')!.textContent).toBe('3')
    expect(side.querySelector('[data-testid="trash-count"]')!.textContent).toBe('4')
    // Deadlines: overdue and the next 14 days; something is overdue, so the number is drawn in the warning colour.
    const deadlines = side.querySelector('[data-testid="deadline-count"]')!
    expect(deadlines.textContent).toBe('6')
    expect(deadlines.className).toContain('text-warn')
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
    expect([...side.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual(['/', '/', '/kamera', '/eingang', '/', '/tresore', '/ordnung', '/papierkorb', '/settings'])
    expect(side.querySelector('[data-testid="deadline-count"]')).toBeNull()
    expect(side.textContent).not.toContain('Fristen')
    // The bar of the phone gets Order back, and the phone's header does not offer it a second time.
    const bar = box.querySelector('main ~ nav')!
    expect([...bar.querySelectorAll('a')].map((a) => a.getAttribute('href'))).toEqual(['/eingang', '/', '/tresore', '/ordnung', '/papierkorb'])
    expect(box.querySelector('main a[href="/ordnung"]')).toBeNull()
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

  it('has at its foot the account with the gear, the way into the settings, as nexnotes', async () => {
    await show('/')
    const account = box.querySelector('[data-testid="sidebar-account"]')!
    expect(account.getAttribute('href')).toBe('/settings')
    expect(account.textContent).toContain('Jule')
    expect(account.getAttribute('aria-label')).toBe('Jule · Einstellungen')
    // No menu of the person any more: signing out stands in the profile.
    expect(box.querySelector('aside [aria-haspopup]')).toBeNull()
    await click(account)
    expect(box.querySelector('h1')!.textContent).toBe('Profil')
    expect(box.querySelector('[data-testid="sign-out-card"]')).toBeTruthy()
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

/** The names of a group of the settings' navigation, in their order. */
function group(name: 'account' | 'server'): (string | undefined)[] {
  return [...box.querySelectorAll(`[aria-labelledby="settings-group-${name}"] a`)].map((item) => item.textContent?.trim())
}

describe('the settings', () => {
  it('are the areas of the plan for the operator, nexpaper\'s own at their places, each with its address', async () => {
    answers['GET /api/v1/settings/push'] = { devices: 0, key: '', contact: '', contact_used: '', known: [], hosts: [] }
    answers['GET /api/v1/about'] = { version: '0.0.1', license: 'AGPL-3.0', repo_url: 'https://example.com/nexpaper', releases_url: 'https://example.com/nexpaper/releases', project_url: '' }
    await show('/settings/general')
    // Plan "Einstellungen": Mein Konto with nexpaper's Upload and AI before Notifications and Connections; Server with
    // nexpaper's own between Storage and Accounts, the server's AI as "KI-Anbieter"; no area "API" any more.
    expect(group('account')).toEqual(['Profil', 'Sicherheit', 'Darstellung', 'Hochladen', 'KI', 'Benachrichtigungen', 'Verbindungen'])
    expect(group('server')).toEqual(['Allgemein', 'Anmeldung', 'Mail', 'Speicher und Sicherung', 'Texterkennung', 'KI-Anbieter', 'Ablage', 'Eingänge', 'Import', 'Konten', 'Log'])
    expect([...box.querySelectorAll('[aria-labelledby="settings-group-server"] a')].map((a) => a.getAttribute('href'))).toEqual(
      ['general', 'sign-in', 'mail', 'storage', 'ocr', 'ai-provider', 'filing', 'inputs', 'import', 'accounts', 'log'].map((slug) => `/settings/${slug}`),
    )
    // The frame of the ui kit: its navigation, the area's title and line, then only cards.
    expect(box.querySelector('[data-testid="settings-nav"]')).toBeTruthy()
    expect(box.querySelector('h1')!.textContent).toBe('Allgemein')
    // ui 1.1.3 (U-3): the line names exactly the cards of General, in their order.
    expect(box.querySelector('[data-testid="settings-area-general"] p')!.textContent).toBe('Grenzen, Funktionen für alle Konten, Schnittstellen, andere nex-Apps, Web Push und eigene Sprachen.')
    expect(box.querySelector('[data-testid="settings-about"], [data-part="settings-about"] a')!.textContent).toContain('Über nexpaper')
    // The cards of General in the plan's order, under the plan's names (Bauplan Allgemein, E48: `features`, `web-push`);
    // the operator's card of the other nex apps (verbinden 0.1.1, V14) after the interfaces.
    expect([...box.querySelectorAll('[data-testid="settings-area-general"] section[data-card]')].map((card) => card.getAttribute('data-card'))).toEqual(
      ['limits', 'features', 'interfaces', 'nex-apps', 'web-push', 'languages'],
    )
    expect(GENERAL_PARTS.map((part) => part.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`))).toEqual(
      ['limits', 'features', 'interfaces', 'nex-apps', 'web-push', 'languages'],
    )
    act(() => root.unmount())
    box.remove()
    // An address of before leads to its area: the interface is a card under General now.
    await show('/einstellungen?tab=api')
    expect(box.querySelector('[data-testid^="settings-nav-"][aria-current="page"]')!.getAttribute('data-testid')).toBe('settings-nav-general')
    act(() => root.unmount())
    box.remove()
    await show('/ueber')
    expect(box.querySelector('h1')!.textContent).toBe('Über nexpaper')
  })

  it('show a member only the own account, and an area of the server leads to the settings\' start', async () => {
    auth.me = { ...operator, role: 'member' }
    await show('/settings/general')
    expect(box.querySelector('h1')!.textContent).toBe('Profil')
    expect(box.querySelector('[aria-labelledby="settings-group-server"]')).toBeNull()
  })

  it('are a list on a phone at /settings, with the way back from an area', async () => {
    await show('/settings')
    expect(box.querySelector('[data-testid="settings"]')!.getAttribute('data-list')).toBe('true')
    act(() => root.unmount())
    box.remove()
    await show('/settings/profile')
    expect(box.querySelector('[data-testid="settings"]')!.hasAttribute('data-list')).toBe(false)
    expect(box.querySelector('[data-testid="settings-back"]')!.getAttribute('href')).toBe('/settings')
  })
})

/** Where the app is after opening an address (the area marked in the navigation). */
async function landing(at: string): Promise<string | null> {
  await show(at)
  const here = box.querySelector('[data-testid^="settings-nav-"][aria-current="page"]')?.getAttribute('data-testid') ?? null
  act(() => root.unmount())
  box.remove()
  return here
}

describe('the addresses of before lead on for good', () => {
  // Deadlines off: Notifications then shows its cards without the reminders the stand-in does not answer.
  beforeEach(() => {
    auth.me = { ...operator, profile: { ...operator.profile, deadlines: false } }
  })

  // Each mapping is held by `settings/areas.test.ts`; here the app routes them, once per kind of address.
  it('a slug of before, a tab of "Mein Konto" and a provider\'s answer', async () => {
    answers['GET /api/v1/auth/sessions'] = []
    answers['GET /api/v1/auth/passkeys'] = []
    answers['GET /api/v1/oidc/me'] = []
    expect(await landing('/settings/reminders')).toBe('settings-nav-notifications')
    expect(await landing('/konto?tab=erinnerungen')).toBe('settings-nav-notifications')
    expect(await landing('/konto?linked=authentik')).toBe('settings-nav-security')
  })

  it('a tab of the settings of before', async () => {
    answers['GET /api/v1/settings/push'] = { devices: 0, key: '', contact: '', contact_used: '', known: [], hosts: [] }
    expect(await landing('/einstellungen?tab=push')).toBe('settings-nav-general')
    expect(await landing('/settings/api')).toBe('settings-nav-general')
  })

  it('a member sent to a server slug of before lands on the settings\' start', async () => {
    auth.me = { ...operator, role: 'member', profile: { ...operator.profile, deadlines: false } }
    expect(await landing('/settings/ai-setup')).toBe('settings-nav-profile')
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
    expect(box.textContent).toContain('Schick dir unter Mein Konto › Profil einen neuen.')
  })
})
