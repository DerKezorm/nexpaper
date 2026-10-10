/**
 * The phone's pages against a stand-in of the server: the quick upload (the two ways in, where files go, the latest
 * documents and what waits), files another app shared (shown, and uploaded only on a tap), the camera without a camera,
 * an app asking to be paired, and the start on the quick upload once per visit.
 */
import { act } from 'react'
import { Route, Routes } from 'react-router-dom'

import type { DocumentInfo, Me, Quick } from '../api/client'
import App from '../App'
import { changeLanguage } from '../i18n'
import { ACCEPT, ACCEPT_PHOTOS } from '../lib/formats'
import { openShare, sweepShared } from '../lib/shared'
import { Uploader, type Summary } from '../lib/uploader'
import { UploadProvider } from '../state/uploads'
import { Page, Server } from '../test/harness'
import { idle } from '../test/wait'
import CameraPage from './CameraPage'
import { leave, OAuthPage } from './OAuthPage'
import { QuickPage } from './QuickPage'

const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'member', sign_in: 'password', email: '', language: 'de', email_confirmed: false,
  email_pending: '', oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 8, avatar: null, version: '0.0.1',
  whats_new_seen: '0.0.1', session_stage: 'full', profile: { mode: 'system', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true },
}
const auth = { status: 'signedIn', me: me as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth, AuthProvider: ({ children }: { children: unknown }) => children, safeNext: (next: string | null) => next ?? '/' }))

const server = new Server()
const page = new Page()

function documentOf(id: number, title: string, status: DocumentInfo['status']): DocumentInfo {
  return { id, vault_id: 7, title, status, added_at: new Date().toISOString(), current_version: 1, pages: status === 'processing' ? 0 : 1 } as DocumentInfo
}

const quick: Quick = {
  target_vault_id: 7,
  vaults: [{ id: 7, name: 'Jule', icon: 'user', mine: true }, { id: 9, name: 'Haushalt', icon: 'home', mine: false }],
  recent: [documentOf(31, 'Scan', 'processing'), documentOf(30, 'Stromrechnung', 'inbox'), documentOf(29, 'Kfz-Versicherung', 'filed')],
  inbox: 4,
  processing: 1,
}

let uploader: Uploader

async function show(element: React.ReactNode, at: string): Promise<void> {
  await page.show(
    <UploadProvider uploader={uploader}>
      <Routes>
        <Route path="*" element={element} />
      </Routes>
    </UploadProvider>,
    at,
  )
}

beforeEach(async () => {
  await changeLanguage('de', false)
  auth.me = me
  auth.setMe.mockClear()
  server.answers = { 'GET /api/v1/quick': quick, 'GET /api/v1/auth/methods': { password: true, oidc: false, oidc_name: '' } }
  server.fails = {}
  server.install()
  uploader = new Uploader()
  vi.spyOn(uploader, 'add').mockImplementation(() => undefined)
})

afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the quick upload', () => {
  it('has the two ways in, where files go, the latest documents and what waits, in the words of the mock', async () => {
    await show(<QuickPage />, '/schnell')
    expect(page.text).toContain('Fotografieren')
    expect(page.text).toContain('Brief, Rechnung, Beleg. Mehrere Seiten gehen.')
    expect(page.text).toContain('Datei wählen')
    expect(page.text).toContain('Aus Fotos')
    expect(page.text).toContain('Landet in Mein Tresor')
    const recent = document.querySelector('[data-testid="quick-recent"]')!
    expect([...recent.querySelectorAll('a')].map((link) => link.getAttribute('href'))).toEqual(['/eingang/31', '/eingang/30', '/dokument/29'])
    expect(recent.textContent).toContain('Wird gelesen')
    expect(recent.textContent).toContain('Texterkennung · gerade eben')
    expect(recent.textContent).toContain('im Eingang, wartet aufs Ablegen')
    expect(recent.textContent).toContain('abgelegt')
    expect(document.querySelector('[data-testid="quick-waiting"]')!.textContent).toBe('4 im Eingang warten aufs Ablegen')
    expect(document.querySelector('a[href="/kamera"]')).toBeTruthy()
    expect(document.querySelector('header a[href="/"]')!.textContent).toContain('Alles')
  })

  it('sends chosen files to the vault it names', async () => {
    await show(<QuickPage />, '/schnell')
    const input = document.querySelector<HTMLInputElement>('[data-testid="quick-file"]')!
    expect(input.accept).toBe(ACCEPT)
    const file = new File([new Uint8Array(10)], 'Beleg.pdf', { type: 'application/pdf' })
    Object.defineProperty(input, 'files', { value: [file], configurable: true })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    expect(uploader.add).toHaveBeenCalledWith([file], { vaultId: 7 })
    expect(document.querySelector<HTMLInputElement>('[data-testid="quick-photos"]')!.accept).toBe(ACCEPT_PHOTOS)
    expect(ACCEPT_PHOTOS.split(',').every((type) => type.startsWith('image/'))).toBe(true)
  })

  it('chooses the vault among those one may add to, and keeps it with the account', async () => {
    server.answers['PUT /api/v1/me/preferences'] = { ...me.profile, default_vault: 9 }
    await show(<QuickPage />, '/schnell')
    await page.click(page.button('Tresor für Uploads wählen'))
    const items = [...document.querySelectorAll('[role="menuitemradio"]')].map((item) => item.textContent)
    expect(items).toEqual(['Mein Tresor', 'Haushalt'])
    expect(page.text).toContain('Regeln dürfen danach umlegen')
    await page.click([...document.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')][1])
    expect(server.called('PUT', '/api/v1/me/preferences')!.body).toEqual({ default_vault: 9 })
    expect(page.text).toContain('Landet in Haushalt')
    const input = document.querySelector<HTMLInputElement>('[data-testid="quick-file"]')!
    const file = new File([new Uint8Array(10)], 'a.pdf')
    Object.defineProperty(input, 'files', { value: [file], configurable: true })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    expect(uploader.add).toHaveBeenCalledWith([file], { vaultId: 9 })
  })

  it('shows what is being uploaded on top of the list', async () => {
    vi.mocked(uploader.add).mockRestore()
    vi.spyOn(uploader, 'getSnapshot').mockReturnValue([
      { id: 1, name: 'Rechnung.pdf', size: 100, chunked: false, phase: 'sending', sent: 0, document: null, vaultId: null, duplicate: null, error: null },
      { id: 2, name: 'Kaputt.pdf', size: 100, chunked: false, phase: 'failed', sent: 0, document: null, vaultId: null, duplicate: null, error: { code: 'unsupported_type', values: {} } },
    ])
    await show(<QuickPage />, '/schnell')
    const recent = document.querySelector('[data-testid="quick-recent"]')!
    expect(recent.querySelector('[data-phase="sending"]')!.textContent).toContain('Wird hochgeladen')
    expect(recent.querySelector('[data-phase="failed"]')!.textContent).toContain('Kaputt.pdf')
  })

  it('names a refused file and its reason on the page, since this page has no list of uploads at the corner', async () => {
    let finished: ((summary: Summary) => void) | null = null
    vi.spyOn(uploader, 'whenIdle').mockImplementation((listener) => {
      finished = listener
      return () => undefined
    })
    await show(<QuickPage />, '/schnell')
    await act(async () => finished!({ done: 0, exists: 0, failed: 1, duplicates: 0, vaults: [], failures: [{ name: 'Foto.gif', code: 'unsupported_type', values: {} }] }))
    const notice = document.querySelector('[data-testid="upload-failures"]')!
    expect(notice.textContent).toContain('1 Datei konnte nicht hochgeladen werden:')
    expect(notice.textContent).toContain('Foto.gif')
    expect(notice.textContent).toContain('Erlaubt sind PDF, JPEG, PNG, TIFF, HEIC, WebP, AVIF')
    await page.click(page.button('Schließen'))
    expect(document.querySelector('[data-testid="upload-failures"]')).toBeNull()
  })

  it('says when there is nothing yet', async () => {
    server.answers['GET /api/v1/quick'] = { ...quick, recent: [], inbox: 0 }
    await show(<QuickPage />, '/schnell')
    expect(page.text).toContain('Noch nichts von dir.')
    expect(document.querySelector('[data-testid="quick-waiting"]')!.textContent).toBe('0 im Eingang warten aufs Ablegen')
  })

  it('comes in English too', async () => {
    await changeLanguage('en', false)
    await show(<QuickPage />, '/schnell')
    expect(page.text).toContain('Take a photo')
    expect(page.text).toContain('Goes to My vault')
    expect(page.text).toContain('Latest from you')
  })
})

describe('files shared from another app', () => {
  function cache(entries: { url: string; body: string; type: string; name: string }[]) {
    const stored = new Map(entries.map((entry) => [entry.url, entry]))
    const open = {
      keys: async () => [...stored.keys()].map((url) => new Request(url)),
      match: async (request: Request) => {
        const entry = stored.get(request.url)
        return entry ? { blob: async () => new Blob([entry.body], { type: entry.type }), headers: new Headers({ 'Content-Type': entry.type, 'X-Name': encodeURIComponent(entry.name) }) } : undefined
      },
      delete: async (request: Request) => stored.delete(request.url),
    }
    vi.stubGlobal('caches', { open: async () => open })
    return stored
  }

  const id = 'ab'.repeat(16)

  it('are shown and go up only on a tap, then leave the cache', async () => {
    const stored = cache([
      { url: `http://localhost:3000/teilen/${id}/0?at=1`, body: '%PDF-1.4 a', type: 'application/pdf', name: 'Rechnung März.pdf' },
      { url: `http://localhost:3000/teilen/${id}/1?at=1`, body: 'jpeg', type: 'image/jpeg', name: 'Beleg.jpg' },
      { url: `http://localhost:3000/teilen/${'cd'.repeat(16)}/0?at=1`, body: 'other', type: 'application/pdf', name: 'Fremd.pdf' },
    ])
    await show(<QuickPage shared />, `/teilen?share=${id}`)
    const shared = document.querySelector('[data-testid="shared"]')!
    expect(shared.textContent).toContain('Aus einer anderen App geteilt')
    expect(shared.textContent).toContain('Rechnung März.pdf')
    expect(shared.textContent).toContain('Beleg.jpg')
    expect(shared.textContent).not.toContain('Fremd.pdf')
    expect(uploader.add).not.toHaveBeenCalled()
    await page.click(page.button('Hochladen', shared))
    const [files, target] = vi.mocked(uploader.add).mock.calls[0]
    expect(files.map((file) => file.name)).toEqual(['Rechnung März.pdf', 'Beleg.jpg'])
    expect(target).toEqual({ vaultId: 7, source: 'share' })
    await idle()
    expect([...stored.keys()]).toEqual([`http://localhost:3000/teilen/${'cd'.repeat(16)}/0?at=1`])
    expect(document.querySelector('[data-testid="shared"]')).toBeNull()
  })

  it('can be thrown away', async () => {
    const stored = cache([{ url: `http://localhost:3000/teilen/${id}/0?at=1`, body: 'x', type: 'application/pdf', name: 'Werbung.pdf' }])
    await show(<QuickPage shared />, `/teilen?share=${id}`)
    await page.click(page.button('Verwerfen'))
    expect(uploader.add).not.toHaveBeenCalled()
    await idle()
    expect(stored.size).toBe(0)
  })

  it('are thrown away when the page is left without uploading', async () => {
    const stored = cache([{ url: `http://localhost:3000/teilen/${id}/0?at=1`, body: 'x', type: 'application/pdf', name: 'Liegen gelassen.pdf' }])
    await show(<QuickPage shared />, `/teilen?share=${id}`)
    expect(document.querySelector('[data-testid="shared"]')!.textContent).toContain('Liegen gelassen.pdf')
    page.close()
    await idle()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(stored.size).toBe(0)
    expect(uploader.add).not.toHaveBeenCalled()
    await show(<QuickPage />, '/schnell')
  })

  it('go when any page starts, all but the share that page shows, and that one after a quarter of an hour', async () => {
    const now = 1_800_000_000_000
    const fresh = 'cd'.repeat(16)
    const shown = 'ef'.repeat(16)
    const entries = () => [
      { url: `http://localhost:3000/teilen/${id}/0?at=${now - 60_000}`, body: 'x', type: 'application/pdf', name: 'anderes.pdf' },
      { url: `http://localhost:3000/teilen/${shown}/0?at=${now - 60_000}`, body: 'x', type: 'application/pdf', name: 'offen.pdf' },
      { url: `http://localhost:3000/teilen/${fresh}/0?at=${now - 16 * 60_000}`, body: 'x', type: 'application/pdf', name: 'alt.pdf' },
      { url: 'http://localhost:3000/teilen/kaputt/0', body: 'x', type: 'application/pdf', name: 'ohne-zeit.pdf' },
    ]
    // Any other page: nothing stays, however new.
    let stored = cache(entries())
    expect(openShare({ pathname: '/schnell', search: '' })).toBeNull()
    expect(await sweepShared(null, now)).toBe(4)
    expect(stored.size).toBe(0)
    // The page of a share keeps that share only, and only while it is young.
    stored = cache(entries())
    const keep = openShare({ pathname: '/teilen', search: `?share=${shown}` })
    expect(keep).toBe(shown)
    expect(await sweepShared(keep, now)).toBe(3)
    expect([...stored.keys()]).toEqual([`http://localhost:3000/teilen/${shown}/0?at=${now - 60_000}`])
    expect(await sweepShared(keep, now + 16 * 60_000)).toBe(1)
    expect(openShare({ pathname: '/teilen', search: '?share=../x' })).toBeNull()
    await show(<QuickPage />, '/schnell')
  })

  it('take no made-up id, and say when the worker was not there', async () => {
    cache([{ url: 'http://localhost:3000/teilen/../0', body: 'x', type: 'application/pdf', name: 'x.pdf' }])
    await show(<QuickPage shared />, '/teilen?share=../../x')
    expect(document.querySelector('[data-testid="shared"]')!.textContent).toContain('Hier liegt nichts mehr zum Hochladen.')
    page.close()
    await show(<QuickPage shared />, '/teilen?missed=1')
    expect(document.querySelector('[data-testid="share-missed"]')!.textContent).toContain('Wähl die Datei hier noch einmal.')
  })
})

describe('the camera without a camera', () => {
  it('says so and offers a file instead', async () => {
    vi.stubGlobal('Worker', class {
      onmessage: unknown = null
      onerror: unknown = null
      postMessage() {}
      terminate() {}
    })
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) }, configurable: true })
    vi.mocked(uploader.add).mockRestore()
    const add = vi.spyOn(uploader, 'add').mockImplementation(() => undefined)
    await show(<CameraPage />, '/kamera')
    await idle()
    expect(document.querySelector('[data-testid="camera-none"]')!.textContent).toContain('Keine Kamera')
    expect(page.text).toContain('Erlaube den Zugriff in den Einstellungen des Browsers')
    const input = document.querySelector<HTMLInputElement>('[data-testid="camera-file"]')!
    const file = new File([new Uint8Array(4)], 'Foto.jpg', { type: 'image/jpeg' })
    Object.defineProperty(input, 'files', { value: [file], configurable: true })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    expect(add).toHaveBeenCalledWith([file], undefined)
  })

  it('names https when the page is not on it', async () => {
    vi.stubGlobal('Worker', class {
      postMessage() {}
      terminate() {}
    })
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    await show(<CameraPage />, '/kamera')
    expect(page.text).toContain('Die Kamera geht nur, wenn nexpaper über https erreichbar ist.')
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
  })
})

describe('an app asking to be paired', () => {
  const query = '?response_type=code&client_id=nexpaper-mobile&redirect_uri=nexpaper%3A%2F%2Foauth%2Fcallback&code_challenge=' + 'c'.repeat(43) + '&code_challenge_method=S256&state=xyz&device_name=Pixel'

  it('names the app and what it gets, and goes back to it when allowed', async () => {
    const go = vi.spyOn(leave, 'to').mockImplementation(() => undefined)
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const address = String(url)
      if ((init?.method ?? 'GET') === 'GET' && address.startsWith('/api/v1/oauth/authorize'))
        return new Response(JSON.stringify({ client_id: 'nexpaper-mobile', client_name: 'nexpaper for iPhone and Android', device_name: 'Pixel', redirect_uri: 'nexpaper://oauth/callback' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        expect(body).toMatchObject({ client_id: 'nexpaper-mobile', code_challenge_method: 'S256', state: 'xyz', allow: true })
        return new Response(JSON.stringify({ redirect: 'nexpaper://oauth/callback?code=abc&state=xyz' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }))
    await show(<OAuthPage />, '/oauth/authorize' + query)
    expect(document.querySelector('h1')!.textContent).toBe('die nexpaper-App mit deinem Konto koppeln?')
    expect(page.text).toContain('Das Gerät heißt dann „Pixel“.')
    await page.click(page.button('Erlauben'))
    expect(go).toHaveBeenCalledWith('nexpaper://oauth/callback?code=abc&state=xyz')
    expect(page.text).toContain('Es geht zurück zur App.')
  })

  it('sends nothing anywhere for an address the app may not use', async () => {
    const go = vi.spyOn(leave, 'to').mockImplementation(() => undefined)
    server.fails['GET /api/v1/oauth/authorize?client_id=nexpaper-mobile&redirect_uri=https%3A%2F%2Fevil.example.org&response_type=code&code_challenge=&code_challenge_method=&state=&device_name='] = { status: 400, code: 'oauth_redirect_refused' }
    await show(<OAuthPage />, '/oauth/authorize?client_id=nexpaper-mobile&redirect_uri=https%3A%2F%2Fevil.example.org&response_type=code')
    expect(page.text).toContain('Zu dieser Adresse darf nexpaper die App nicht zurückschicken.')
    expect(page.button('Zurück zur App')).toBeUndefined()
    expect(page.button('Erlauben')).toBeUndefined()
    expect(go).not.toHaveBeenCalled()
  })
})

describe('the phone starts on the quick upload', () => {
  function narrow(width: number) {
    Object.defineProperty(window, 'innerWidth', { value: width, configurable: true })
  }

  it('once per visit, and only when the person wants it', async () => {
    sessionStorage.clear()
    narrow(390)
    server.answers['GET /api/v1/vaults'] = []
    await page.show(<App />, '/')
    expect(page.text).toContain('Fotografieren')
    expect(sessionStorage.getItem('nexpaper.quickShown')).toBe('1')
    page.close()
    await page.show(<App />, '/')
    expect(page.text).not.toContain('Brief, Rechnung, Beleg.')
    page.close()
    sessionStorage.clear()
    auth.me = { ...me, profile: { ...me.profile, quick_start: false } }
    await page.show(<App />, '/')
    expect(page.text).not.toContain('Brief, Rechnung, Beleg.')
    page.close()
    sessionStorage.clear()
    auth.me = me
    narrow(1280)
    await page.show(<App />, '/')
    expect(page.text).not.toContain('Brief, Rechnung, Beleg.')
  })
})
