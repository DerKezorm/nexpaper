/**
 * Web Push in the interface, against a stand-in of the server and of the browser's push. My account › Notifications,
 * the card "Auf welchem Weg" (ui `NotifyWays`; before "Benachrichtigungen auf deinen Geräten" under Connections): the
 * devices of the person with this one marked, renamed and signed off; "Dieser Browser" says what stands in the way (no
 * https, an iPhone outside the home screen app, a refused permission) and signs this browser up with the server's key;
 * the test notice says what it reached. The notice of a new sign-in is a box to tick under Security. The operator's
 * card under Server › General shows how many devices, never whose.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

import type { Me, PushDevice } from '../../api/client'
import '../../i18n'
import { changeLanguage } from '../../i18n'
import { NotificationsArea } from './NotificationsArea'
import { PushServerCard } from './PushCards'
import { SecurityArea } from './SecurityBoxes'
import { idle } from '../../test/wait'

const setMe = vi.fn()
const me: Me = {
  id: 1, name: 'jule', display_name: 'Jule', role: 'operator', sign_in: 'password', email: 'jule@example.com', language: 'de',
  oidc_linked: false, two_factor: true, totp: true, passkeys: 0, two_factor_recovery_left: 10, avatar: null, version: '0.1.0', whats_new_seen: '0.1.0',
  email_confirmed: true, email_pending: '',
  profile: { mode: 'light', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
vi.mock('../../state/auth', () => ({ useAuth: () => ({ me, setMe, refresh: vi.fn(async () => undefined) }) }))
/** The person without deadlines: Notifications shows its first card and only the short card of the deadlines. */
const noDeadlines: Me = { ...me, profile: { ...me.profile, deadlines: false } }

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
      // What Security asks for besides the box of the notice.
      if (url === '/api/v1/auth/sessions' || url === '/api/v1/auth/passkeys' || url === '/api/v1/oidc/me') return json([])
      if (url === '/api/v1/auth/methods') return json({ password: true, providers: [], passkeys: true })
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

/** The first card of Notifications, and its parts. */
const ways = () => box.querySelector<HTMLElement>('[data-card="notify-ways"]')!
const thisBrowser = () => box.querySelector<HTMLElement>('[data-testid="notify-browser"]')!

describe('the devices, in "Auf welchem Weg"', () => {
  it('lists the own devices with since and last, and signs this browser up with the server key', async () => {
    const push = browserPush()
    await show(<NotificationsArea me={noDeadlines} />)
    // The first card of the area, before nexpaper's own of the deadlines.
    expect(box.querySelector('[data-card]')!.getAttribute('data-card')).toBe('notify-ways')
    expect(ways().textContent).toContain('Handy (nexpaper vom Startbildschirm)')
    expect(ways().textContent).toContain('seit 2. Oktober · zuletzt 6. Oktober')
    const here = box.querySelector('[data-testid="push-here"]')!
    expect(here.textContent).toContain('Noch nicht angemeldet.')
    expect(here.textContent).toContain('Push braucht eine Adresse mit https (oder localhost).')
    expect(thisBrowser().textContent).toContain('Aus')
    const turnOn = box.querySelector<HTMLButtonElement>('[data-testid="notify-browser-on"]')!
    expect([turnOn.textContent, turnOn.dataset.kind]).toEqual(['Mitteilungen einschalten', 'primary'])
    await click(turnOn)
    expect(push.register).toHaveBeenCalledWith('/sw.js', { scope: '/' })
    const key = new Uint8Array(push.subscribe.mock.calls[0][0].applicationServerKey)
    expect(key.length).toBe(65)
    expect(key[0]).toBe(4)
    const sent = calls.find((call) => call.url === '/api/v1/push/devices' && call.method === 'POST')!
    expect(sent.body).toEqual({ endpoint: ENDPOINT, p256dh: 'BPublicKeyOfTheBrowser', auth: 'AuthSecretOfIt', installed: false })
    expect(box.textContent).toContain('Dieses Gerät bekommt jetzt Bescheide.')
    // This browser is on now, marked in the list, and nothing stands in the way any more.
    expect(thisBrowser().textContent).toContain('An')
    expect(box.querySelector('[data-testid="notify-browser-off"]')).toBeTruthy()
    const rows = [...box.querySelectorAll('[data-testid="notify-browser-row"]')]
    expect(rows.find((row) => row.textContent?.includes('Firefox unter Windows'))!.textContent).toContain('Dieser Browser')
    expect(box.querySelector('[data-testid="push-here"]')!.textContent).not.toContain('Noch nicht angemeldet.')
  })

  it('says what stands in the way and offers no button that cannot work', async () => {
    browserPush({ permission: 'denied' })
    await show(<NotificationsArea me={noDeadlines} />)
    expect(box.textContent).toContain('Der Browser hat Benachrichtigungen für nexpaper gesperrt.')
    expect(box.querySelector<HTMLButtonElement>('[data-testid="notify-browser-on"]')!.disabled).toBe(true)
    act(() => root.unmount())
    box.remove()
    browserPush()
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true })
    await show(<NotificationsArea me={noDeadlines} />)
    expect(box.textContent).toContain('Diese Adresse hat kein https')
    expect(box.querySelector<HTMLButtonElement>('[data-testid="notify-browser-on"]')!.disabled).toBe(true)
  })

  it('tells when the person refuses the permission and sends nothing', async () => {
    browserPush({ answer: 'denied' })
    await show(<NotificationsArea me={noDeadlines} />)
    await click(box.querySelector<HTMLButtonElement>('[data-testid="notify-browser-on"]')!)
    expect(box.textContent).toContain('Benachrichtigungen sind nicht erlaubt.')
    expect(calls.some((call) => call.url === '/api/v1/push/devices' && call.method === 'POST')).toBe(false)
  })

  it('marks this browser, renames a device and signs one off, this one also at its push service', async () => {
    const push = browserPush({ permission: 'granted', subscribed: true })
    devices = [PHONE, { id: 'b'.repeat(32), name: 'Firefox unter Windows', phone: false, since: '2026-10-07T18:00:00+00:00', last: null }]
    lookupId = 'b'.repeat(32)
    await show(<NotificationsArea me={noDeadlines} />)
    expect(calls.find((call) => call.url === '/api/v1/push/devices/lookup')!.body).toEqual({ endpoint: ENDPOINT })
    expect(thisBrowser().textContent).toContain('An')
    expect(box.querySelector('[data-testid="push-here"]')!.textContent).not.toContain('Noch nicht angemeldet.')
    // Each row: its own small "rename" and the kit's small red "remove", both named after the device.
    const rename = button(`Gerät umbenennen: ${PHONE.name}`)!
    expect([rename.dataset.kind, rename.dataset.size, rename.dataset.icon]).toEqual(['secondary', 'sm', 'Pencil'])
    await click(rename)
    const naming = document.body.querySelector<HTMLElement>('[role="dialog"]')!
    await type(naming.querySelector<HTMLInputElement>('input')!, 'Mein Handy')
    await click([...naming.querySelectorAll<HTMLButtonElement>('button')].find((item) => item.textContent?.trim() === 'Speichern'))
    expect(calls.find((call) => call.method === 'PUT' && call.url.startsWith('/api/v1/push/devices/'))!.body).toEqual({ name: 'Mein Handy' })
    expect(box.textContent).toContain('Mein Handy')
    const remove = button('Firefox unter Windows entfernen')!
    expect([remove.dataset.kind, remove.dataset.size, remove.dataset.icon]).toEqual(['danger', 'sm', 'Trash2'])
    await click(remove)
    // Asked first: nothing is sent before the person says yes.
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    const asking = document.body.querySelector<HTMLElement>('[role="dialog"]')!
    await click([...asking.querySelectorAll<HTMLButtonElement>('button')].find((item) => item.textContent?.trim() === 'Gerät entfernen'))
    expect(calls.some((call) => call.method === 'DELETE' && call.url.endsWith('b'.repeat(32)))).toBe(true)
    expect(push.subscription.unsubscribe).toHaveBeenCalled()
    expect(box.textContent).toContain('Firefox unter Windows ist abgemeldet.')
  })

  it('turns this browser off after the same question', async () => {
    const push = browserPush({ permission: 'granted', subscribed: true })
    devices = [{ id: 'b'.repeat(32), name: 'Firefox unter Windows', phone: false, since: '2026-10-07T18:00:00+00:00', last: null }]
    lookupId = 'b'.repeat(32)
    await show(<NotificationsArea me={noDeadlines} />)
    const off = box.querySelector<HTMLButtonElement>('[data-testid="notify-browser-off"]')!
    expect(off.dataset.kind).toBe('danger')
    await click(off)
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    const asking = document.body.querySelector<HTMLElement>('[role="dialog"]')!
    await click([...asking.querySelectorAll<HTMLButtonElement>('button')].find((item) => item.textContent?.trim() === 'Gerät entfernen'))
    expect(calls.some((call) => call.method === 'DELETE' && call.url.endsWith('b'.repeat(32)))).toBe(true)
    expect(push.subscription.unsubscribe).toHaveBeenCalled()
  })

  it('says what the test notice reached, also while this browser has none', async () => {
    browserPush()
    await show(<NotificationsArea me={noDeadlines} />)
    await click(button('Probe senden'))
    expect(box.textContent).toContain('Probe verschickt.')
    probe = { sent: 1, gone: 1, failed: 1 }
    await click(button('Probe senden'))
    expect(box.textContent).toContain('Probe an 1 von 3 Geräten verschickt.')
  })

  it('names the mail way with the account\'s address and the iPhone and iPad way', async () => {
    browserPush()
    await show(<NotificationsArea me={noDeadlines} />)
    const mail = box.querySelector('[data-testid="notify-mail"]')!
    expect(mail.textContent).toContain('jule@example.com')
    expect(mail.textContent).toContain('bestätigt')
    expect(box.querySelector('[data-testid="notify-devices-box"]')).toBeTruthy()
  })
})

describe('the notice of a new sign-in', () => {
  it('is a box to tick under Security, on from the start, kept with the account', async () => {
    await show(<SecurityArea me={me} />)
    const row = box.querySelector('[data-testid="security-newSignInMail"]')!
    // The module's words of the part "newSignInMail" (konten 1.1.0).
    expect(row.textContent).toContain('Mail bei neuer Anmeldung')
    expect(row.querySelector('[role="switch"]')).toBeNull()
    const tick = row.querySelector<HTMLInputElement>('input[type="checkbox"]')!
    expect(tick.checked).toBe(true)
    await click(tick)
    expect(calls.find((call) => call.url === '/api/v1/me/preferences')!.body).toEqual({ notify_login: false })
  })
})

describe("the operator's card", () => {
  it('shows how many devices, saves the contact and the push services, and renews the keys only when confirmed', async () => {
    await show(<PushServerCard />)
    expect(box.querySelector('[data-testid="push-ready"]')!.textContent).toContain('Bereit · 3 Geräte angemeldet')
    expect(box.textContent).toContain('BEl6…x2Qk')
    expect(box.querySelector('[data-card="web-push"]')).toBeTruthy()
    const contact = box.querySelector<HTMLInputElement>('input')!
    expect(contact.placeholder).toBe('mailto:admin@example.com')
    await type(contact, 'mailto:paper@example.com')
    // The contact's own Save, level with its field (`Field action`).
    expect(button('Speichern')!.closest('[data-part="field-action"]')).toBeTruthy()
    await click(button('Speichern'))
    expect(calls.find((call) => call.method === 'PUT')!.body).toEqual({ contact: 'mailto:paper@example.com' })
    await type(box.querySelector('textarea')!, 'push.example.com\n\n  other.example.com ')
    await click([...box.querySelectorAll<HTMLButtonElement>('button[type="submit"]')].at(-1))
    expect(calls.filter((call) => call.method === 'PUT').at(-1)!.body).toEqual({ hosts: ['push.example.com', 'other.example.com'] })
    expect(button('Neu erzeugen')!.dataset.kind).toBe('danger')
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
