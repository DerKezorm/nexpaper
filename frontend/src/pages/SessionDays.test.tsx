/**
 * How long a sign-in lasts is the server's setting (`NEXPAPER_SESSION_DAYS`): the sign-in page, the signed-in devices
 * and "Ready for the internet?" name the number the server gives, never a fixed one. The card of the disk says that the
 * folders without a date, a sender or a kind have English names there.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import type { Me } from '../api/client'
import '../i18n'
import { changeLanguage } from '../i18n'
import { LoginPage } from './AuthPages'
import { SignInNoticeCard } from './settings/PushCards'
import { ReadinessCard } from './settings/ReadinessCards'
import { DiskCard } from './settings/StorageCards'
import { idle } from '../test/wait'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: 'jule@example.com', language: 'de',
  oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.1.0', whats_new_seen: '0.1.0',
  session_stage: 'full', second_factor_required: true,
  email_confirmed: true, email_pending: '',
  profile: { mode: 'light', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true },
}
const auth = { status: 'signedOut' as string, me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth, safeNext: (next: string | null) => next ?? '/' }))

let answers: Record<string, unknown> = {}

function serve(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const found = answers[`${init?.method ?? 'GET'} ${url}`]
      return new Response(JSON.stringify(found ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
}

let root: Root
let box: HTMLDivElement

async function show(element: React.ReactNode, at = '/login'): Promise<void> {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  await act(async () =>
    root.render(
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="*" element={element} />
        </Routes>
      </MemoryRouter>,
    ),
  )
  await idle()
}

function methods(days?: number): Record<string, unknown> {
  return { password: true, providers: [], passkeys: false, forgot: false, ...(days === undefined ? {} : { session_days: days }) }
}

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.status = 'signedOut'
  answers = {}
  serve()
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('the length of a sign-in', () => {
  it('on the sign-in page is the number the server gives', async () => {
    answers['GET /api/v1/auth/methods'] = methods(7)
    await show(<LoginPage />)
    expect(box.textContent).toContain('Bis du 7 Tage nicht hier warst. Gut fürs eigene Handy, nicht für fremde Geräte.')
    expect(box.textContent).not.toContain('30 Tage')
  })

  it('says one day as one day, in English too', async () => {
    await changeLanguage('en', false)
    answers['GET /api/v1/auth/methods'] = methods(1)
    await show(<LoginPage />)
    expect(box.textContent).toContain('Until you have not been here for 1 day. Good for your own phone')
  })

  it('names no number before the server said one', async () => {
    answers['GET /api/v1/auth/methods'] = methods()
    await show(<LoginPage />)
    expect(box.textContent).toContain('Gut fürs eigene Handy, nicht für fremde Geräte.')
    expect(box.textContent).not.toMatch(/\d+ Tage|NaN|undefined|ends/)
  })

  it('under Security, with the signed-in devices', async () => {
    answers['GET /api/v1/auth/methods'] = methods(90)
    await show(<SignInNoticeCard me={me} />, '/konto')
    expect(box.textContent).toContain('Wo du gerade angemeldet bist. Eine Anmeldung läuft nach 90 Tagen ohne Nutzung von selbst ab.')
  })

  it('in "Ready for the internet?"', async () => {
    answers['GET /api/v1/settings/readiness'] = { open: 0, points: [{ key: 'cookies', state: 'ok', values: { mode: 'auto', days: 14 } }] }
    await show(<ReadinessCard />, '/einstellungen')
    expect(box.textContent).toContain('eine Anmeldung läuft nach 14 Tagen ohne Nutzung ab.')
  })
})

describe('the disk', () => {
  it('says that missing parts have English names on the disk', async () => {
    await show(<DiskCard />, '/einstellungen')
    expect(box.textContent).toContain('„undated“, „no sender“, „Document“')
    await act(async () => changeLanguage('en', false))
    expect(box.textContent).toContain('the folders and files on the disk have English names')
  })
})
