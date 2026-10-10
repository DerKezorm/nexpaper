/**
 * The account's looks win over what the browser remembered: after the page has asked the server, the colour and
 * light or dark of the account are painted, whatever an earlier visit (or another account on this browser) left behind.
 * And the script that paints a remembered choice before the first frame knows the three modes and nothing else.
 */
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import '../i18n'
import script from '../../public/theme.js?raw'
import { AuthProvider, useAuth } from './auth'
import { idle } from '../test/wait'
import { SIGNED_OUT_EVENT } from '../api/client'

let root: Root
let box: HTMLDivElement
let kept: Map<string, string>

function Probe() {
  const { status } = useAuth()
  return <p>{status}</p>
}

function serve(profile: Record<string, unknown>): void {
  const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/v1/setup') return json({ needs_setup: false, code_required: false, signed_in: true, version: '0.1.0', min_password: 12 })
      if (url === '/api/v1/auth/me') {
        return json({ id: 1, name: 'jule', display_name: 'Jule', role: 'user', language: 'de', version: '0.1.0', whats_new_seen: '0.1.0', profile: { timezone: 'Europe/Berlin', timezone_source: 'manual', ...profile } })
      }
      return json({})
    }),
  )
}

async function start(inside: ReactNode = <Probe />): Promise<void> {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  await act(async () => root.render(<AuthProvider>{inside}</AuthProvider>))
  await idle()
}

beforeEach(() => {
  kept = new Map()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => kept.get(key) ?? null,
    setItem: (key: string, value: string) => void kept.set(key, value),
    removeItem: (key: string) => void kept.delete(key),
  })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: () => undefined }))
    document.documentElement.removeAttribute('data-theme')
})

afterEach(async () => {
  await act(async () => root.unmount())
  box.remove()
  vi.unstubAllGlobals()
})

describe('the looks of the account', () => {
  it('are painted once the server has said them, over what an earlier visit left in the browser', async () => {
    kept.set('nexpaper.theme', 'light')
    serve({ mode: 'dark' })
    await start()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(kept.get('nexpaper.theme')).toBe('dark')
  })

  it('bring light back when the account has light and the browser remembered dark', async () => {
    kept.set('nexpaper.theme', 'dark')
    document.documentElement.setAttribute('data-theme', 'dark')
    serve({ mode: 'light' })
    await start()
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(kept.get('nexpaper.theme')).toBe('light')
  })

  it('ignore a mode that is none of the three', async () => {
    serve({ mode: 'sepia' })
    await start()
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })
})

describe('the script before the first frame', () => {
  function run(stored: Record<string, string>, dark = false): void {
        document.documentElement.removeAttribute('data-theme')
    document.head.innerHTML = '<meta name="theme-color" content="#f7f3ec">'
    vi.stubGlobal('localStorage', { getItem: (key: string) => stored[key] ?? null })
    vi.stubGlobal('matchMedia', () => ({ matches: dark }))
    new Function(script)()
  }

  it('paints the mode of the last visit', () => {
    run({ 'nexpaper.theme': 'dark' })
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(document.querySelector('meta[name="theme-color"]')!.getAttribute('content')).toBe('#171310')
  })

  it('paints nothing for light, for nothing remembered and for a value that is no mode', () => {
    const cases: Record<string, string>[] = [{ 'nexpaper.theme': 'light' }, {}, { 'nexpaper.theme': '"><script>' }, { 'nexpaper.theme': 'neon' }]
    for (const stored of cases) {
      run(stored)
      expect(document.documentElement.hasAttribute('data-theme'), JSON.stringify(stored)).toBe(false)
    }
  })

  it('still follows the system for light or dark', () => {
    run({}, true)
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })
})

function SignOut() {
  const { signOut } = useAuth()
  return (
    <button type="button" onClick={() => void signOut()}>
      out
    </button>
  )
}

describe('signing out', () => {
  it('forgets the pictures of pages fetched for this person', async () => {
    serve({ mode: 'system' })
    const { loadPicture, keptPicture } = await import('../lib/pictures')
    await start(<SignOut />)
    await loadPicture('/api/v1/documents/7/versions/1/preview')
    expect(keptPicture('/api/v1/documents/7/versions/1/preview')).toBeTruthy()
    await act(async () => box.querySelector('button')!.click())
    await idle()
    expect(keptPicture('/api/v1/documents/7/versions/1/preview')).toBeNull()
  })

  it('forgets them too when a request finds the session gone', async () => {
    serve({ mode: 'system' })
    const { loadPicture, keptPicture } = await import('../lib/pictures')
    await start()
    await loadPicture('/api/v1/documents/8/versions/1/preview')
    expect(keptPicture('/api/v1/documents/8/versions/1/preview')).toBeTruthy()
    await act(async () => window.dispatchEvent(new Event(SIGNED_OUT_EVENT)))
    await idle()
    expect(keptPicture('/api/v1/documents/8/versions/1/preview')).toBeNull()
  })
})
