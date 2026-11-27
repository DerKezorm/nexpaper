// Vorlage nexgeraete 0.1.1
// @vitest-environment jsdom
/**
 * The parts of the module in the app: the card "Geräte" with the pairing window, renaming and disconnecting, the card
 * "Mitteilungen auf deinen Geräten", the operator's part in Server › Konten › Verwalten, the page /app-connect in both
 * forms and the row "iPhone und iPad" of NotifyWays, built from the ui kit, the module's words in German, English and
 * French. Copied once by bauplaene/geraete/tools/sync.py to `frontend/src/nexgeraete.test.tsx`; then the app's file.
 * Fill in the places marked APP. Needs react-dom (in every app).
 */
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NexuiLanguage, NotifyWays } from './vendor/nexui'
import {
  AccountDevicesPart,
  AppConnectPage,
  DEVICE_TEXTS,
  DevicePushCard,
  DevicesCard,
  devicesWay,
  type AccountDevices,
  type Device,
  type DeviceRequest,
  type PairingState,
  type PushKind,
} from './vendor/nexgeraete'

// APP: where the app mounts the module's browser routes (`browser_router`; '/api', or its own prefix such as
// '/api/devices' where the app's older browser routes stay under /api), its name and its link scheme. Every card gets
// it as `base`.
const BASE = '/api/v1'
const APP = 'nexpaper'
const SCHEME = 'nexpaper'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Call = { path: string; method: string; body: unknown }

let root: Root
let box: HTMLDivElement
let calls: Call[]
let devices: Device[]
let hasApp: boolean
let pairingState: PairingState['state']
let pairings: number
let kinds: Record<string, PushKind[]>
let operatorView: AccountDevices
let redirect: string
let refuse: { method: string; path: string; detail: Record<string, unknown> } | null
/** An answer of another shape for every GET (a test double of the app answering `[]`). */
let oddAnswer: unknown

function device(id: number, extra: Partial<Device> = {}): Device {
  return {
    id,
    name: `Device ${id}`,
    kind: 'ios',
    model: 'iPhone 15',
    system: 'iOS 26.1',
    app_version: '1.0.2',
    via: 'qr',
    created_at: '2026-11-01T09:00:00+00:00',
    last_seen_at: '2026-11-24T09:00:00+00:00',
    push: true,
    ...extra,
  }
}

function kindsOf(on: boolean): PushKind[] {
  return [
    { id: 'changed', title: 'Änderungen in geteilten Notizen', hint: 'Wenn jemand eine geteilte Notiz ändert.', on, operator_only: false },
    { id: 'update', title: `Neue Version von ${APP}`, hint: 'Einmal je Version.', on, operator_only: true },
  ]
}

const request: DeviceRequest = async <T,>(path: string, init: { method?: string; body?: unknown } = {}) => {
  const method = init.method ?? 'GET'
  calls.push({ path, method, body: init.body })
  if (refuse && refuse.method === method && refuse.path === path) {
    const { detail } = refuse
    refuse = null
    throw Object.assign(new Error('refused'), { detail })
  }
  if (oddAnswer !== undefined && method === 'GET') return oddAnswer as T
  const kindsMatch = path.match(new RegExp(`^${BASE}/app-devices/([^/]+)/push-kinds$`))
  if (kindsMatch) {
    const id = decodeURIComponent(kindsMatch[1]!)
    if (method === 'PUT') {
      const changes = init.body as Record<string, boolean>
      kinds[id] = kinds[id]!.map((kind) => (kind.id in changes ? { ...kind, on: changes[kind.id]! } : kind))
    }
    return { kinds: kinds[id] } as T
  }
  const deviceMatch = path.match(new RegExp(`^${BASE}/app-devices/([^/]+)$`))
  if (deviceMatch) {
    const id = decodeURIComponent(deviceMatch[1]!)
    if (method === 'DELETE') {
      devices = devices.filter((found) => String(found.id) !== id)
      return undefined as T
    }
    devices = devices.map((found) => (String(found.id) === id ? { ...found, ...(init.body as object) } : found))
    return devices.find((found) => String(found.id) === id) as T
  }
  if (path === `${BASE}/app-devices` && method === 'DELETE') {
    const removed = devices.length
    devices = []
    return { removed } as T
  }
  if (path === `${BASE}/app-devices`) return { devices, max: 30, app_store_url: 'https://apps.apple.com/app/id000000', has_app: hasApp } as T
  if (path === `${BASE}/app-pairing` && method === 'POST') {
    pairings += 1
    return {
      id: `pairing-${pairings}`,
      secret: 'S'.repeat(43),
      code: 'K7MQ-R4TX',
      link: `${SCHEME}://connect?server=https%3A%2F%2Fnotes.example.com&pairing=pairing-${pairings}&secret=x`,
      address: 'https://notes.example.com',
      expires_at: new Date(Date.now() + 600_000).toISOString(),
      qr_svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>',
      app_store_url: 'https://apps.apple.com/app/id000000',
    } as T
  }
  if (path.startsWith(`${BASE}/app-pairing/`)) {
    if (method === 'DELETE') return undefined as T
    if (pairingState === 'used' && !devices.some((found) => found.id === 9)) devices = [device(9, { name: 'iPhone 16 Pro', model: 'iPhone 16 Pro', push: false }), ...devices]
    return { state: pairingState, device: pairingState === 'used' ? devices.find((found) => found.id === 9)! : null } as T
  }
  if (path === `${BASE}/app-connect` && method === 'POST') return { redirect } as T
  if (path === `${BASE}/server/accounts/7/devices`) {
    if (method === 'DELETE') {
      const removed = operatorView.count
      operatorView = { count: 0, devices: [] }
      return { removed } as T
    }
    return operatorView as T
  }
  throw new Error(`unexpected ${method} ${path}`)
}

function show(node: ReactNode, language = 'de'): void {
  act(() => root.render(<NexuiLanguage language={language}>{node}</NexuiLanguage>))
}

async function settle(): Promise<void> {
  await act(async () => await new Promise((resolve) => setTimeout(resolve, 0)))
}

/** With fake timers: let `ms` pass and every promise settle. */
async function pass(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

function click(element: Element | null): void {
  expect(element).not.toBeNull()
  act(() => (element as HTMLElement).click())
}

function type(input: HTMLInputElement, value: string): void {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const find = <T extends Element = HTMLElement>(selector: string) => document.querySelector<T>(selector)
const all = (selector: string) => Array.from(document.querySelectorAll<HTMLElement>(selector))
const button = (testId: string) => find<HTMLButtonElement>(`[data-testid="${testId}"]`)
const made = (method: string, path: string) => calls.filter((call) => call.method === method && call.path === path)

beforeEach(() => {
  calls = []
  refuse = null
  oddAnswer = undefined
  hasApp = true
  pairingState = 'waiting'
  pairings = 0
  redirect = `${SCHEME}://connected?code=abc&state=state-1234`
  devices = [
    device(1, { name: 'Kims iPhone' }),
    device(2, { name: 'iPad Air', kind: 'ipados', model: 'iPad', via: 'icloud', push: false, last_seen_at: '2026-11-23T20:40:00+00:00' }),
    device(3, { name: 'MacBook Air', kind: 'mac', model: 'Mac', app_version: '1.0.1', push: false, last_seen_at: null }),
  ]
  kinds = { '1': kindsOf(true), '2': kindsOf(false), '3': [] }
  operatorView = {
    count: 2,
    devices: [
      { kind: 'ios', model: 'iPhone 15', last_seen_at: '2026-11-24T08:12:00+00:00' },
      { kind: 'ipados', model: 'iPad', last_seen_at: '2026-11-20T08:12:00+00:00' },
    ],
  }
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  document.body.innerHTML = ''
  vi.useRealTimers()
})

describe('the words of the module', () => {
  it("have the same keys in German, English and French, and the plan's words in German", () => {
    const shape = (value: unknown): unknown =>
      typeof value === 'object' && value ? Object.fromEntries(Object.entries(value).map(([name, inner]) => [name, shape(inner)])) : typeof value
    expect(shape(DEVICE_TEXTS.en)).toEqual(shape(DEVICE_TEXTS.de))
    expect(shape(DEVICE_TEXTS.fr)).toEqual(shape(DEVICE_TEXTS.de))
    expect(DEVICE_TEXTS.de.devices.title).toBe('Geräte')
    expect(DEVICE_TEXTS.de.devices.connect).toBe('iPhone oder iPad verbinden')
    expect(DEVICE_TEXTS.de.devices.rename).toBe('Umbenennen')
    expect(DEVICE_TEXTS.de.devices.disconnect).toBe('Trennen')
    expect(DEVICE_TEXTS.de.devices.disconnectAll).toBe('Alle Geräte trennen')
    expect(DEVICE_TEXTS.de.devices.none).toBe('Noch kein Gerät verbunden.')
    expect(DEVICE_TEXTS.de.pair.valid).toBe('Gilt noch {time} Minuten, für ein Gerät.')
    expect(DEVICE_TEXTS.de.push.title).toBe('Mitteilungen auf deinen Geräten')
    expect(DEVICE_TEXTS.de.account.privacy).toBe('Du siehst nur Zahl, Art und wann zuletzt; nie, was auf den Geräten liegt.')
  })
})

describe('the card Geräte', () => {
  it('lists every device with its symbol, line, badge and small buttons', async () => {
    show(<DevicesCard request={request} base={BASE} app={APP} />)
    await settle()
    const card = find('[data-card="devices"]')!
    expect(card.textContent).toContain(`Die ${APP}-App auf iPhone, iPad und Mac.`)
    expect(find('[data-testid="devices-box"]')!.textContent).toContain('3 Geräte')
    const rows = all('[data-testid="device-row"]')
    expect(rows.map((row) => row.querySelector('[data-testid="device-name"]')!.textContent)).toEqual(['Kims iPhone', 'iPad Air', 'MacBook Air'])
    const lines = all('[data-testid="device-line"]').map((line) => line.textContent)
    expect(lines[0]).toMatch(/^iPhone 15 · App 1\.0\.2 · zuletzt 24\.11\.2026, \d\d:\d\d$/)
    expect(lines[1]).toContain('iPad · App 1.0.2 · über iCloud übernommen · zuletzt')
    expect(lines[2]).toBe('Mac · App 1.0.1 · noch nicht gemeldet')
    expect(all('[data-testid="device-push"]').map((badge) => [badge.textContent, badge.dataset.tone])).toEqual([
      ['Mitteilungen an', 'on'],
      ['Mitteilungen aus', 'off'],
      ['Mitteilungen aus', 'off'],
    ])
    const rename = all('[data-testid="device-rename"]')[0]!
    expect([rename.dataset.kind, rename.dataset.size, rename.dataset.icon, rename.textContent]).toEqual(['secondary', 'sm', 'Pencil', 'Umbenennen'])
    const disconnect = all('[data-testid="device-disconnect"]')[0]!
    expect([disconnect.dataset.kind, disconnect.dataset.size, disconnect.dataset.icon, disconnect.textContent]).toEqual(['danger', 'sm', 'Unplug', 'Trennen'])
    expect(disconnect.getAttribute('aria-label')).toBe('Kims iPhone trennen')
    expect([button('devices-connect')!.dataset.kind, button('devices-connect')!.textContent]).toEqual(['primary', 'iPhone oder iPad verbinden'])
    expect([button('devices-disconnect-all')!.dataset.kind, button('devices-disconnect-all')!.textContent]).toEqual(['danger', 'Alle Geräte trennen'])
  })

  it('says so without devices, offers "Alle Geräte trennen" only from two on, and shows nothing without an iPhone app', async () => {
    devices = []
    show(<DevicesCard request={request} base={BASE} app={APP} />)
    await settle()
    expect(find('[data-testid="devices-none"]')!.textContent).toBe('Noch kein Gerät verbunden.')
    expect(button('devices-disconnect-all')).toBeNull()
    expect(button('devices-connect')).not.toBeNull()
    act(() => root.unmount())
    root = createRoot(box)
    devices = [device(1)]
    show(<DevicesCard request={request} base={BASE} app={APP} />)
    await settle()
    expect(all('[data-testid="device-row"]')).toHaveLength(1)
    expect(button('devices-disconnect-all')).toBeNull()
    act(() => root.unmount())
    root = createRoot(box)
    hasApp = false
    show(<DevicesCard request={request} base={BASE} app={APP} />)
    await settle()
    expect(find('[data-card="devices"]')).toBeNull()
  })

  it('renames a device, and says what is wrong with a name', async () => {
    show(<DevicesCard request={request} base={BASE} app={APP} />)
    await settle()
    click(all('[data-testid="device-rename"]')[1]!)
    const dialog = find('[data-testid="device-rename-dialog"]')!
    expect(dialog.textContent).toContain('Gerät umbenennen')
    expect(dialog.textContent).toContain('Seit iOS 16')
    const field = find<HTMLInputElement>('[data-testid="device-rename-name"]')!
    expect(field.value).toBe('iPad Air')
    type(field, 'x')
    refuse = { method: 'PATCH', path: `${BASE}/app-devices/2`, detail: { code: 'name_invalid', message: 'bad' } }
    click(button('device-rename-save'))
    await settle()
    expect(find('[data-testid="device-rename-dialog"]')!.textContent).toContain('Der Name darf nicht leer sein')
    type(field, 'Kims iPad')
    click(button('device-rename-save'))
    await settle()
    expect(made('PATCH', `${BASE}/app-devices/2`).at(-1)!.body).toEqual({ name: 'Kims iPad' })
    expect(find('[data-testid="device-rename-dialog"]')).toBeNull()
    expect(all('[data-testid="device-name"]').map((name) => name.textContent)).toContain('Kims iPad')
  })

  it('disconnects one device only after the question', async () => {
    show(<DevicesCard request={request} base={BASE} app={APP} />)
    await settle()
    click(all('[data-testid="device-disconnect"]')[0]!)
    const dialog = find('[data-testid="device-disconnect-dialog"]')!
    expect(dialog.textContent).toContain('„Kims iPhone“ trennen?')
    expect(dialog.textContent).toContain('sofort keinen Zugriff mehr')
    click(Array.from(dialog.querySelectorAll('button')).find((found) => found.textContent === 'Abbrechen')!)
    expect(made('DELETE', `${BASE}/app-devices/1`)).toHaveLength(0)
    click(all('[data-testid="device-disconnect"]')[0]!)
    const confirm = find('[data-testid="device-disconnect-dialog"] button[type="submit"]')!
    expect([confirm.dataset.kind, confirm.dataset.icon]).toEqual(['danger', 'Unplug'])
    click(confirm)
    await settle()
    expect(made('DELETE', `${BASE}/app-devices/1`)).toHaveLength(1)
    expect(all('[data-testid="device-name"]').map((name) => name.textContent)).toEqual(['iPad Air', 'MacBook Air'])
  })

  it('disconnects all devices after the question', async () => {
    show(<DevicesCard request={request} base={BASE} app={APP} />)
    await settle()
    click(button('devices-disconnect-all'))
    const dialog = find('[data-testid="devices-disconnect-all-dialog"]')!
    expect(dialog.textContent).toContain('Alle 3 Geräte trennen?')
    expect(dialog.textContent).toContain('Browser und API-Schlüssel bleiben.')
    click(dialog.querySelector('button[type="submit"]'))
    await settle()
    expect(made('DELETE', `${BASE}/app-devices`)).toHaveLength(1)
    expect(find('[data-testid="devices-none"]')).not.toBeNull()
  })

  it('writes the line in English', async () => {
    show(<DevicesCard request={request} base={BASE} app={APP} />, 'en')
    await settle()
    expect(all('[data-testid="device-line"]')[0]!.textContent).toMatch(/^iPhone 15 · App 1\.0\.2 · last 24\/11\/2026, \d\d:\d\d$/)
    expect(button('devices-connect')!.textContent).toBe('Connect iPhone or iPad')
  })
})

describe('the pairing window', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-27T12:00:00Z'))
  })

  async function open(operator = false): Promise<void> {
    show(<DevicesCard request={request} base={BASE} app={APP} operator={operator} serverHref="/settings/server-connections" />)
    await pass(0)
    click(button('devices-connect'))
    await pass(0)
  }

  it('shows the QR picture, the steps, the time left, the App Store and the code to type in, and asks every two seconds', async () => {
    await open()
    expect(made('POST', `${BASE}/app-pairing`)).toEqual([{ path: `${BASE}/app-pairing`, method: 'POST', body: { address: window.location.origin } }])
    const dialog = find('[data-testid="pair-dialog"]')!
    expect(dialog.textContent).toContain('iPhone oder iPad verbinden')
    expect(find<HTMLImageElement>('[data-testid="pair-qr"]')!.getAttribute('src')).toMatch(/^data:image\/svg\+xml;charset=utf-8,/)
    expect(dialog.querySelector('svg rect')).toBeNull()
    expect(all('[data-testid="pair-steps"] li')).toHaveLength(3)
    expect(find('[data-testid="pair-valid"]')!.textContent).toBe('Gilt noch 10:00 Minuten, für ein Gerät.')
    expect(find<HTMLAnchorElement>('[data-testid="pair-store"]')!.getAttribute('href')).toBe('https://apps.apple.com/app/id000000')
    expect(find('[data-testid="pair-store"]')!.textContent).toBe(`${APP} im App Store`)
    expect(find('[data-testid="pair-address"]')!.textContent).toContain('notes.example.com')
    expect(find('[data-testid="pair-code"]')!.textContent).toContain('K7MQ-R4TX')
    await pass(2000)
    expect(find('[data-testid="pair-valid"]')!.textContent).toBe('Gilt noch 9:58 Minuten, für ein Gerät.')
    expect(made('GET', `${BASE}/app-pairing/pairing-1`)).toHaveLength(1)
    await pass(2000)
    expect(made('GET', `${BASE}/app-pairing/pairing-1`)).toHaveLength(2)
  })

  it('says "<device> ist verbunden" once a device took the code; "Fertig" shows it in the list, marked new', async () => {
    await open()
    pairingState = 'used'
    await pass(2000)
    const dialog = find('[data-testid="pair-dialog"]')!
    expect(dialog.textContent).toContain('iPhone 16 Pro ist verbunden')
    expect(dialog.textContent).toContain('Es steht jetzt in deiner Geräteliste.')
    click(button('pair-done'))
    await pass(0)
    expect(find('[data-testid="pair-dialog"]')).toBeNull()
    expect(made('DELETE', `${BASE}/app-pairing/pairing-1`)).toHaveLength(0)
    const first = all('[data-testid="device-row"]')[0]!
    expect(first.querySelector('[data-testid="device-name"]')!.textContent).toBe('iPhone 16 Pro')
    expect(first.querySelector('[data-testid="device-new"]')!.textContent).toBe('neu')
  })

  it('says when the code ran out and shows a new one', async () => {
    await open()
    pairingState = 'expired'
    await pass(2000)
    expect(find('[data-testid="pair-expired"]')!.textContent).toBe('Der Code ist abgelaufen.')
    expect(find('[data-testid="pair-qr"]')).toBeNull()
    expect(find('[data-testid="pair-code-box"]')).toBeNull()
    pairingState = 'waiting'
    click(button('pair-renew'))
    await pass(0)
    expect(made('POST', `${BASE}/app-pairing`)).toHaveLength(2)
    expect(find('[data-testid="pair-qr"]')).not.toBeNull()
    expect(find('[data-testid="pair-body"]')!.dataset.state).toBe('waiting')
  })

  it('runs out by the clock too, when the server is not asked in time', async () => {
    await open()
    await act(async () => {
      vi.setSystemTime(new Date('2026-11-27T12:10:01Z'))
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(find('[data-testid="pair-expired"]')).not.toBeNull()
  })

  it('withdraws the code on "Abbrechen" and stops asking', async () => {
    await open()
    click(button('pair-cancel'))
    await pass(0)
    expect(find('[data-testid="pair-dialog"]')).toBeNull()
    expect(made('DELETE', `${BASE}/app-pairing/pairing-1`)).toHaveLength(1)
    await pass(6000)
    expect(made('GET', `${BASE}/app-pairing/pairing-1`)).toHaveLength(0)
  })

  it('says why no code came', async () => {
    refuse = { method: 'POST', path: `${BASE}/app-pairing`, detail: { code: 'too_many_pairings', message: 'x' } }
    await open()
    expect(find('[data-testid="pair-problem"]')!.textContent).toContain('zu viele Codes offen')
    expect(find('[data-testid="pair-operator-hint"]')).toBeNull()
    refuse = { method: 'POST', path: `${BASE}/app-pairing`, detail: { code: 'app_pairing_disabled', message: 'x' } }
    click(button('pair-cancel'))
    click(button('devices-connect'))
    await pass(0)
    expect(find('[data-testid="pair-problem"]')!.textContent).toBe('Der Betreiber lässt gerade keine neuen Geräte zu.')
  })

  it('tells an operator where the app and new devices are switched on', async () => {
    refuse = { method: 'POST', path: `${BASE}/app-pairing`, detail: { code: 'app_disabled', message: 'x' } }
    await open(true)
    expect(find('[data-testid="pair-operator-hint"]')!.textContent).toContain('Einschalten kannst du das unter Server › Verbindungen.')
    expect(find<HTMLAnchorElement>('[data-testid="pair-to-server"]')!.getAttribute('href')).toBe('/settings/server-connections')
  })
})

describe('the card Mitteilungen auf deinen Geräten', () => {
  it('shows each device with its kinds, marks those only operators get, and keeps a tick at once', async () => {
    show(<DevicePushCard request={request} base={BASE} app={APP} />)
    await settle()
    expect(find('[data-card="devices-push"]')!.textContent).toContain('Mitteilungen auf deinen Geräten')
    const boxes = all('[data-testid="devices-push-device"]')
    expect(boxes.map((found) => found.querySelector('h3')!.textContent)).toEqual(['Kims iPhone · iPhone 15', 'iPad Air · iPad', 'MacBook Air · Mac'])
    expect(all('[data-testid="devices-push-state"]').map((badge) => badge.textContent)).toEqual(['Mitteilungen erlaubt', 'Keine Mitteilungen angemeldet', 'Keine Mitteilungen angemeldet'])
    expect(boxes[1]!.textContent).toContain(`nicht für Mitteilungen von ${APP} angemeldet`)
    expect(boxes[0]!.textContent).toContain(`In ${APP} auf dem Gerät wählst du sie erst mit einer kommenden App-Version.`)
    expect(boxes[0]!.textContent).not.toContain('Einstellungen › Mitteilungen')
    expect(boxes[0]!.querySelectorAll('input[type="checkbox"]')).toHaveLength(2)
    expect(boxes[0]!.querySelector('[data-testid="devices-push-operator"]')!.textContent).toBe('nur Betreiber')
    expect(boxes[2]!.textContent).toContain('noch keine Mitteilungen zum Auswählen')
    const tick = find<HTMLInputElement>('[data-testid="devices-push-1-changed"]')!
    expect(tick.checked).toBe(true)
    click(tick)
    await settle()
    expect(made('PUT', `${BASE}/app-devices/1/push-kinds`).at(-1)!.body).toEqual({ changed: false })
    expect(find<HTMLInputElement>('[data-testid="devices-push-1-changed"]')!.checked).toBe(false)
    expect(boxes[0]!.querySelector('[data-testid="devices-push-saved"]')!.textContent).toBe('Gespeichert.')
  })

  it('points to the app\'s own ticks only where the app on the device shows them', async () => {
    devices = devices.map((found) => (found.id === 1 ? { ...found, chooses_kinds: true } : found))
    show(<DevicePushCard request={request} base={BASE} app={APP} />)
    await settle()
    const boxes = all('[data-testid="devices-push-device"]')
    expect(boxes[0]!.textContent).toContain('Die App zeigt dieselben Haken unter Einstellungen › Mitteilungen.')
    expect(find('[data-card="devices-push"]')!.textContent).toContain('Jedes Gerät hat seine eigene Auswahl.')
  })

  it('shows an answer of another shape as a problem', async () => {
    oddAnswer = []
    show(<DevicePushCard request={request} base={BASE} app={APP} />)
    await settle()
    expect(find('[data-testid="devices-push-problem"]')!.textContent).toBe('Das hat nicht geklappt. Versuche es noch einmal.')
  })

  it('without devices says where to connect one', async () => {
    devices = []
    show(<DevicePushCard request={request} base={BASE} app={APP} connectionsHref="/settings/connections" />)
    await settle()
    expect(find('[data-testid="devices-push-none"]')!.textContent).toContain('Mein Konto › Verbindungen')
    expect(find<HTMLAnchorElement>('[data-testid="devices-push-connections"]')!.getAttribute('href')).toBe('/settings/connections')
  })
})

describe('the row "iPhone und iPad" of NotifyWays', () => {
  it('counts the devices and those with notifications', async () => {
    const listing = { devices, max: 30, app_store_url: null, has_app: true }
    show(<NotifyWays devices={devicesWay(listing, DEVICE_TEXTS.de, '/settings/connections')} />)
    expect(find('[data-testid="notify-devices-box"]')!.textContent).toContain('3 Geräte verbunden, Mitteilungen auf 1 erlaubt.')
    expect(devicesWay({ ...listing, devices: [] }, DEVICE_TEXTS.de)!.note).toContain('Noch kein Gerät verbunden')
    expect(devicesWay({ ...listing, has_app: false }, DEVICE_TEXTS.de)).toBeUndefined()
  })
})

describe("the operator's part in Konten › Verwalten", () => {
  it('shows count, kinds and last contact, never more, and disconnects after the question', async () => {
    show(<AccountDevicesPart request={request} base={BASE} accountId={7} name="Mila Example" />)
    await settle()
    expect(find('[data-testid="account-devices-line"]')!.textContent).toBe('2 Geräte: iPhone, iPad')
    expect(find('[data-testid="account-devices-sub"]')!.textContent).toMatch(/^zuletzt 24\.11\.2026, \d\d:\d\d$/)
    expect(find('[data-testid="account-devices-privacy"]')!.textContent).toBe('Du siehst nur Zahl, Art und wann zuletzt; nie, was auf den Geräten liegt.')
    const drop = button('account-devices-disconnect')!
    expect([drop.dataset.kind, drop.dataset.size, drop.textContent]).toEqual(['danger', 'sm', 'Geräte trennen'])
    click(drop)
    expect(find('[data-testid="account-devices-dialog"]')!.textContent).toContain('Geräte von Mila Example trennen?')
    click(find('[data-testid="account-devices-dialog"] button[type="submit"]'))
    await settle()
    expect(made('DELETE', `${BASE}/server/accounts/7/devices`)).toHaveLength(1)
    expect(find('[data-testid="account-devices-line"]')!.textContent).toBe('Kein Gerät verbunden')
    expect(find('[data-testid="account-devices-sub"]')!.textContent).toBe('Mila Example kann jederzeit neu verbinden.')
  })

  it('shows an answer of another shape as a problem and never falls over', async () => {
    oddAnswer = []
    show(<AccountDevicesPart request={request} base={BASE} accountId={7} name="Mila Example" />)
    await settle()
    expect(find('[data-testid="account-devices-problem"]')!.textContent).toBe('Das hat nicht geklappt. Versuche es noch einmal.')
    expect(find('[data-testid="account-devices-line"]')).toBeNull()
    expect(find('[data-testid="account-devices-privacy"]')).not.toBeNull()
    oddAnswer = { count: 1 }
    show(<DevicesCard request={request} base={BASE} app={APP} />)
    await settle()
    expect(find('[data-testid="devices-problem"]')!.textContent).toBe('Das hat nicht geklappt. Versuche es noch einmal.')
  })

  it('says the devices rest while the account is blocked', async () => {
    show(<AccountDevicesPart request={request} base={BASE} accountId={7} name="Mila Example" blocked />)
    await settle()
    expect(find('[data-testid="account-devices-sub"]')!.textContent).toBe('ruhen, solange das Konto gesperrt ist')
  })
})

describe('the page /app-connect', () => {
  const account = { name: 'Kim Example', login: 'kim' }
  const challenge = 'c'.repeat(43)

  it('asks first, then hands the code to the app (new form with state and challenge)', async () => {
    const went: string[] = []
    show(<AppConnectPage request={request} base={BASE} app={APP} scheme={SCHEME} account={account} search={`?state=state-1234&challenge=${challenge}`} go={(url) => went.push(url)} />)
    const page = find('[data-testid="app-connect"]')!
    expect(page.textContent).toContain(`${APP}-App mit deinem Konto verbinden?`)
    expect(find('[data-testid="app-connect-name"]')!.textContent).toContain('Kim Example')
    expect(find('[data-testid="app-connect-login"]')!.textContent).toContain('kim')
    expect(made('POST', `${BASE}/app-connect`)).toHaveLength(0)
    expect(button('app-connect-confirm')!.dataset.kind).toBe('primary')
    click(button('app-connect-confirm'))
    await settle()
    expect(made('POST', `${BASE}/app-connect`)[0]!.body).toEqual({ state: 'state-1234', challenge })
    expect(went).toEqual([redirect])
    expect(find('[data-testid="app-connect"]')!.dataset.state).toBe('done')
  })

  it('tells the app on "Abbrechen"', () => {
    const went: string[] = []
    show(<AppConnectPage request={request} base={BASE} app={APP} scheme={SCHEME} account={account} search="?state=state-1234" go={(url) => went.push(url)} />)
    click(button('app-connect-cancel'))
    expect(went).toEqual([`${SCHEME}://connected?error=cancelled&state=state-1234`])
    expect(made('POST', `${BASE}/app-connect`)).toHaveLength(0)
  })

  it('takes the old form with the device name, and never leads elsewhere than to the app', async () => {
    const went: string[] = []
    redirect = 'https://elsewhere.example.com/'
    show(<AppConnectPage request={request} base={BASE} app={APP} scheme={SCHEME} account={account} search="?device=Kims%20iPhone" go={(url) => went.push(url)} />)
    expect(find('[data-testid="app-connect"]')!.textContent).toContain('„Kims iPhone“ mit deinem Konto verbinden?')
    click(button('app-connect-confirm'))
    await settle()
    expect(made('POST', `${BASE}/app-connect`)[0]!.body).toEqual({ device: 'Kims iPhone' })
    expect(went).toEqual([])
    expect(find('[data-testid="app-connect-problem"]')).not.toBeNull()
  })

  it('shows the sign-in of the app while nobody is signed in, and says so for a page opened by hand', () => {
    show(<AppConnectPage request={request} base={BASE} app={APP} scheme={SCHEME} account={null} search="?state=state-1234" signIn={<p data-testid="sign-in">sign in</p>} />)
    expect(find('[data-testid="sign-in"]')).not.toBeNull()
    act(() => root.unmount())
    root = createRoot(box)
    show(<AppConnectPage request={request} base={BASE} app={APP} scheme={SCHEME} account={account} search="" />)
    expect(find('[data-testid="app-connect-invalid"]')!.textContent).toContain('Starte das Verbinden in der App.')
  })
})
