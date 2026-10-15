/**
 * Web Push in the interface, against a stand-in of the server and of the browser's push: the devices of the person
 * with this one marked, renamed and signed off; "Dieses Gerät" says what stands in the way (no https, an iPhone outside
 * the home screen app, a refused permission) and signs this browser up with the server's key; the probe says what it
 * reached; the notice of a new sign-in is a switch under Security; the operator's card shows how many devices, never
 * whose.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

import type { Me, PushDevice } from '../../api/client'
import '../../i18n'
import { changeLanguage } from '../../i18n'
import { PushDevicesCard, PushServerCard, SignInNoticeCard } from './PushCards'
import { idle } from '../../test/wait'

const setMe = vi.fn()
const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: 'jule@example.com', language: 'de',
  oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 10, avatar: null, version: '0.1.0', whats_new_seen: '0.1.0',
  email_confirmed: true, email_pending: '',
  profile: { mode: 'light', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
vi.mock('../../state/auth', () => ({ useAuth: () => ({ me, setMe }) }))

const ENDPOINT = 'https://push.example.com/wpush/v2/this-browser'
// A key of the form the server hands out, made for the run: 65 bytes, base64url.
const SERVER_KEY = btoa(String.fromCharCode(4, ...Array.from({ length: 64 }, (_, index) => index))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')

type Call = { method: string; url: string; body: Record<string, unknown> | undefined }
let calls: Call[] = []
let devices: PushDevice[]
let lookupId: string | null
let probe: { sent: number; gone: number; failed: number }

function serve(): void {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, url, body })
      const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
      if (url === '/api/v1/push' && method === 'GET') return json({ key: SERVER_KEY, devices })
      if (url === '/api/v1/push/devices/lookup') return json({ id: lookupId })
      if (url === '/api/v1/push/devices' && method === 'POST') {
        const made = { id: 'c'.repeat(32), name: 'Firefox unter Windows', phone: false, since: '2026-10-07T18:00:00+00:00', last: null }
        devices = [...devices, made]
        lookupId = made.id
        return json(made, 201)
      }
      if (url.startsWith('/api/v1/push/devices/') && method === 'PUT') {
        devices = devices.map((device) => (url.endsWith(device.id) ? { ...device, name: String(body!.name) } : device))
        return json(devices.find((device) => url.endsWith(device.id)))
      }
      if (url.startsWith('/api/v1/push/devices/') && method === 'DELETE') {
        devices = devices.filter((device) => !url.endsWith(device.id))
        return new Response(null, { status: 204 })
      }
      if (url === '/api/v1/push/test') return json(probe)
      if (url === '/api/v1/me/preferences') return json({ ...me.profile, ...body })
      if (url === '/api/v1/settings/push' && method === 'GET') return json({ devices: 3, key: 'BEl6…x2Qk', contact: '', contact_used: 'mailto:admin@example.com', known: [], hosts: [] })
      if (url === '/api/v1/settings/push' && method === 'PUT') return json({ devices: 3, key: 'BEl6…x2Qk', contact: body!.contact ?? '', contact_used: body!.contact || 'mailto:admin@example.com', known: [], hosts: body!.hosts ?? [] })
      if (url === '/api/v1/settings/push/renew') return json({ devices: 0, key: 'BNew…key1', contact: '', contact_used: 'mailto:admin@example.com', known: [], hosts: [] })
      return json({})
    }),
  )
}

/** The browser's push, as far as the page uses it. */
function browserPush({ permission = 'default' as NotificationPermission, answer = 'granted' as NotificationPermission, subscribed = false } = {}) {
  const subscription = {
    endpoint: ENDPOINT,
    options: { applicationServerKey: null as ArrayBuffer | null },
    toJSON: () => ({ endpoint: ENDPOINT, keys: { p256dh: 'BPublicKeyOfTheBrowser', auth: 'AuthSecretOfIt' } }),
    unsubscribe: vi.fn(async () => true),
  }
  let current = subscribed ? subscription : null
  const subscribe = vi.fn(async (options: { applicationServerKey: Uint8Array }) => {
    subscription.options.applicationServerKey = options.applicationServerKey.buffer as ArrayBuffer
    current = subscription
    return subscription
  })
  const registration = { pushManager: { getSubscription: vi.fn(async () => current), subscribe } }
  const register = vi.fn(async () => registration)
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
  vi.stubGlobal('PushManager', function PushManager() {})
  vi.stubGlobal('Notification', Object.assign(function Notification() {}, { permission, requestPermission: vi.fn(async () => answer) }))
  Object.defineProperty(navigator, 'serviceWorker', {
    value: { register, ready: Promise.resolve(registration), getRegistration: vi.fn(async () => registration) },
    configurable: true,
  })
  return { register, subscribe, subscription }
}

let root: Root
let box: HTMLDivElement

async function show(element: React.ReactNode): Promise<void> {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  await act(async () => root.render(<MemoryRouter>{element}</MemoryRouter>))
  await idle()
}


function button(text: string): HTMLButtonElement | undefined {
  return [...box.querySelectorAll<HTMLButtonElement>('button')].find((item) => item.textContent?.trim() === text || item.getAttribute('aria-label') === text)
}

async function click(target: HTMLElement | undefined): Promise<void> {
  expect(target).toBeTruthy()
  await act(async () => target!.click())
  await idle()
}

async function type(input: HTMLInputElement | HTMLTextAreaElement, value: string): Promise<void> {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value')!.set!
  await act(async () => {
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await idle()
}

const PHONE: PushDevice = { id: 'a'.repeat(32), name: 'Handy (nexpaper vom Startbildschirm)', phone: true, since: '2026-10-02T08:00:00+00:00', last: '2026-10-06T18:30:00+00:00' }

beforeEach(async () => {
  await changeLanguage('de', false)
  devices = [PHONE]
  lookupId = null
  probe = { sent: 1, gone: 0, failed: 0 }
  setMe.mockClear()
  serve()
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  vi.unstubAllGlobals()
})

describe('the devices', () => {
  it('lists the own devices with since and last, and signs this browser up with the server key', async () => {
    const push = browserPush()
    await show(<PushDevicesCard me={me} />)
    expect(box.textContent).toContain('Handy (nexpaper vom Startbildschirm)')
    expect(box.textContent).toContain('seit 2. Oktober · zuletzt 6. Oktober')
    const here = box.querySelector('[data-testid="push-here"]')!
    expect(here.textContent).toContain('Noch nicht angemeldet.')
    expect(here.textContent).toContain('Push braucht eine Adresse mit https (oder localhost).')
    await click(button('Auf diesem Gerät einschalten'))
    expect(push.register).toHaveBeenCalledWith('/sw.js', { scope: '/' })
    const key = new Uint8Array(push.subscribe.mock.calls[0][0].applicationServerKey)
    expect(key.length).toBe(65)
    expect(key[0]).toBe(4)
    const sent = calls.find((call) => call.url === '/api/v1/push/devices' && call.method === 'POST')!
    expect(sent.body).toEqual({ endpoint: ENDPOINT, p256dh: 'BPublicKeyOfTheBrowser', auth: 'AuthSecretOfIt', installed: false })
    expect(box.textContent).toContain('Dieses Gerät bekommt jetzt Bescheide.')
    expect(box.textContent).toContain('dieses Gerät')
    expect(box.querySelector('[data-testid="push-here"]')).toBeNull()
  })

  it('says what stands in the way and offers no button that cannot work', async () => {
    browserPush({ permission: 'denied' })
    await show(<PushDevicesCard me={me} />)
    expect(box.textContent).toContain('Der Browser hat Benachrichtigungen für nexpaper gesperrt.')
    expect(button('Auf diesem Gerät einschalten')!.disabled).toBe(true)
    act(() => root.unmount())
    box.remove()
    browserPush()
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    await show(<PushDevicesCard me={me} />)
    expect(box.textContent).toContain('Diese Adresse hat kein https')
    expect(button('Auf diesem Gerät einschalten')!.disabled).toBe(true)
  })

  it('tells when the person refuses the permission and sends nothing', async () => {
    browserPush({ answer: 'denied' })
    await show(<PushDevicesCard me={me} />)
    await click(button('Auf diesem Gerät einschalten'))
    expect(box.textContent).toContain('Benachrichtigungen sind nicht erlaubt.')
    expect(calls.some((call) => call.url === '/api/v1/push/devices' && call.method === 'POST')).toBe(false)
  })

  it('marks this browser, renames a device and signs one off, this one also at its push service', async () => {
    const push = browserPush({ permission: 'granted', subscribed: true })
    devices = [PHONE, { id: 'b'.repeat(32), name: 'Firefox unter Windows', phone: false, since: '2026-10-07T18:00:00+00:00', last: null }]
    lookupId = 'b'.repeat(32)
    await show(<PushDevicesCard me={me} />)
    expect(calls.find((call) => call.url === '/api/v1/push/devices/lookup')!.body).toEqual({ endpoint: ENDPOINT })
    expect(box.textContent).toContain('dieses Gerät')
    expect(box.querySelector('[data-testid="push-here"]')).toBeNull()
    await click([...box.querySelectorAll<HTMLButtonElement>('button[aria-label="Gerät umbenennen"]')][0])
    await type(box.querySelector<HTMLInputElement>('input')!, 'Mein Handy')
    await click(button('Speichern'))
    expect(calls.find((call) => call.method === 'PUT' && call.url.startsWith('/api/v1/push/devices/'))!.body).toEqual({ name: 'Mein Handy' })
    expect(box.textContent).toContain('Mein Handy')
    await click([...box.querySelectorAll<HTMLButtonElement>('button[aria-label="Gerät abmelden"]')][1])
    // Asked first: nothing is sent before the person says yes.
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    const asking = document.body.querySelector<HTMLElement>('[role="dialog"]')!
    await click([...asking.querySelectorAll<HTMLButtonElement>('button')].find((item) => item.textContent?.trim() === 'Gerät entfernen'))
    expect(calls.some((call) => call.method === 'DELETE' && call.url.endsWith('b'.repeat(32)))).toBe(true)
    expect(push.subscription.unsubscribe).toHaveBeenCalled()
    expect(box.textContent).toContain('Firefox unter Windows ist abgemeldet.')
  })

  it('says what the probe reached', async () => {
    browserPush()
    await show(<PushDevicesCard me={me} />)
    await click(button('Probe senden'))
    expect(box.textContent).toContain('Probe verschickt.')
    probe = { sent: 1, gone: 1, failed: 1 }
    await click(button('Probe senden'))
    expect(box.textContent).toContain('Probe an 1 von 3 Geräten verschickt.')
  })
})

describe('the notice of a new sign-in', () => {
  it('is a switch, on from the start, kept with the account', async () => {
    await show(<SignInNoticeCard me={me} />)
    expect(box.textContent).toContain('Bei einer neuen Anmeldung Bescheid geben')
    const toggle = box.querySelector<HTMLButtonElement>('button[role="switch"]')!
    expect(toggle.getAttribute('aria-checked')).toBe('true')
    await click(toggle)
    expect(calls.find((call) => call.url === '/api/v1/me/preferences')!.body).toEqual({ notify_login: false })
  })
})

describe("the operator's card", () => {
  it('shows how many devices, saves the contact and the push services, and renews the keys only when confirmed', async () => {
    await show(<PushServerCard />)
    expect(box.querySelector('[data-testid="push-ready"]')!.textContent).toContain('Bereit · 3 Geräte angemeldet')
    expect(box.textContent).toContain('BEl6…x2Qk')
    const contact = box.querySelector<HTMLInputElement>('input')!
    expect(contact.placeholder).toBe('mailto:admin@example.com')
    await type(contact, 'mailto:paper@example.com')
    await click(button('Speichern'))
    expect(calls.find((call) => call.method === 'PUT')!.body).toEqual({ contact: 'mailto:paper@example.com' })
    await type(box.querySelector('textarea')!, 'push.example.com\n\n  other.example.com ')
    await click([...box.querySelectorAll<HTMLButtonElement>('button[type="submit"]')].at(-1))
    expect(calls.filter((call) => call.method === 'PUT').at(-1)!.body).toEqual({ hosts: ['push.example.com', 'other.example.com'] })
    await click(button('Neu erzeugen'))
    expect(calls.some((call) => call.url === '/api/v1/settings/push/renew')).toBe(false)
    const dialog = document.querySelector('[role="dialog"]')!
    await type(dialog.querySelector<HTMLInputElement>('input[type="password"]')!, 'the own password')
    await act(async () => dialog.querySelector('form')!.requestSubmit())
    await idle()
    expect(calls.find((call) => call.url === '/api/v1/settings/push/renew')!.body).toEqual({ current_password: 'the own password' })
    expect(box.textContent).toContain('Neues Schlüsselpaar erzeugt. Alle Geräte sind abgemeldet.')
    expect(box.textContent).toContain('Bereit · 0 Geräte angemeldet')
  })
})
