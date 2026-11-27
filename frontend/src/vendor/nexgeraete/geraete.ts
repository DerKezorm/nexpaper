// nexgeraete in the browser: what the server answers, the buttons, the symbols and the words of the cards. The cards
// themselves are DevicesCard.tsx (with PairDialog.tsx and RenameDialog.tsx), DevicePushCard.tsx, AccountDevicesPart.tsx
// and the page AppConnectPage.tsx (built from the ui kit). Copied unchanged into frontend/src/vendor/nexgeraete/ by
// bauplaene/geraete/tools/sync.py; changed only there.

import { formatMoment, type IconName } from '../nexui'

import de from './geraete.de.json'
import en from './geraete.en.json'
import fr from './geraete.fr.json'

/** `ios` (iPhone), `ipados` (iPad), `mac` (the app on a Mac). An older app may send something else. */
export type DeviceKind = 'ios' | 'ipados' | 'mac'

/** How a device came: `qr`, `code` (typed in), `browser` (signed in on `/app-connect`), `icloud` (taken over from
 * another device of the account); an older way of the app stays as it is stored. */
export type DeviceWay = 'qr' | 'code' | 'browser' | 'icloud'

/** One device as `GET /api/app-devices` lists it: never its key, never its hash. */
export type Device = {
  id: number | string
  name: string
  kind: string
  /** "iPhone 16 Pro"; `null` from an app that does not say it yet. */
  model: string | null
  /** "iOS 26.1". */
  system: string | null
  /** "1.0.2". */
  app_version: string | null
  via: string | null
  created_at: string | null
  last_seen_at: string | null
  /** The device is signed up for notifications (iOS lets the app show them). */
  push: boolean
  /** Since 0.1.1: the app on the device named the kinds it understands (a version that shows the same ticks under
   * Settings › Notifications); false for the published apps. Missing from an older server. */
  chooses_kinds?: boolean
  /** Only in the app's own list (`/api/app/1/devices`): the device that asks. */
  this?: boolean
}

/** `GET /api/app-devices`. */
export type DeviceListing = {
  devices: Device[]
  /** How many devices an account may connect. */
  max: number
  app_store_url: string | null
  /** False: the app has no iPhone app yet (nexdiary, nexfolk); no page shows the cards. */
  has_app: boolean
}

/** `POST /api/app-pairing` (201, answered with `no-store`). */
export type Pairing = {
  id: string
  secret: string
  /** "K7MQ-R4TX", to type in without a camera. */
  code: string
  /** `<scheme>://connect?…`, what the QR code holds. */
  link: string
  /** The server's address the app keeps ("https://notes.example.com"). */
  address: string
  expires_at: string
  /** The QR code as SVG markup; shown as a picture, never put into the page. */
  qr_svg: string
  app_store_url: string | null
}

/** `GET /api/app-pairing/{id}`. */
export type PairingState = { state: 'waiting' | 'used' | 'expired'; device: Device | null }

/** One kind of notification of a device (`GET /api/app-devices/{id}/push-kinds`), in the account's language. */
export type PushKind = { id: string; title: string; hint: string | null; on: boolean; operator_only: boolean }

export type PushKinds = { kinds: PushKind[] }

/** A device as the operator sees it (`GET /api/server/accounts/{id}/devices`): kind, model and last contact only. */
export type OperatorDevice = { kind: string; model: string | null; last_seen_at: string | null }

export type AccountDevices = { count: number; devices: OperatorDevice[] }

/** The app's way to call its server (its own client with its headers), as for the other modules. A refusal throws;
 * the cards read its code with `refusalCode`. */
export type DeviceRequest = <T>(
  path: string,
  init?: { method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'; query?: Record<string, string | number | undefined>; body?: unknown },
) => Promise<T>

/** An answer of another shape than the module's (a test double, a route of the app's that answers in its old form). The
 * parts show it as "did not work" (`refusalText`), they never fall over. */
export class UnexpectedAnswer extends Error {
  constructor(what: string) {
    super(`nexgeraete: unexpected answer for ${what}`)
    this.name = 'UnexpectedAnswer'
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isDevice(value: unknown): value is Device {
  return isRecord(value) && (typeof value.id === 'number' || typeof value.id === 'string') && typeof value.name === 'string'
}

/** `GET <base>/app-devices`, checked. */
export function asListing(found: unknown): DeviceListing {
  if (!isRecord(found) || !Array.isArray(found.devices) || !found.devices.every(isDevice)) throw new UnexpectedAnswer('app-devices')
  return { ...found, has_app: found.has_app !== false } as DeviceListing
}

/** `GET <base>/server/accounts/{id}/devices`, checked. */
export function asAccountDevices(found: unknown): AccountDevices {
  if (!isRecord(found) || typeof found.count !== 'number' || !Array.isArray(found.devices) || !found.devices.every(isRecord)) throw new UnexpectedAnswer('account devices')
  return found as AccountDevices
}

/** `GET`/`PUT <base>/app-devices/{id}/push-kinds`, checked. */
export function asPushKinds(found: unknown): PushKinds {
  if (!isRecord(found) || !Array.isArray(found.kinds) || !found.kinds.every((kind) => isRecord(kind) && typeof kind.id === 'string')) throw new UnexpectedAnswer('push-kinds')
  return found as PushKinds
}

/** `POST <base>/app-pairing`, checked. */
export function asPairing(found: unknown): Pairing {
  if (!isRecord(found) || typeof found.id !== 'string' || typeof found.link !== 'string' || typeof found.code !== 'string') throw new UnexpectedAnswer('app-pairing')
  return found as Pairing
}

/** `GET <base>/app-pairing/{id}`, checked. */
export function asPairingState(found: unknown): PairingState {
  if (!isRecord(found) || typeof found.state !== 'string' || (found.device != null && !isDevice(found.device))) throw new UnexpectedAnswer('app-pairing state')
  return found as PairingState
}

/** `PATCH <base>/app-devices/{id}`, checked. */
export function asDevice(found: unknown): Device {
  if (!isDevice(found)) throw new UnexpectedAnswer('app-device')
  return found
}

/** Where the module's browser routes are mounted. */
export const DEVICES_BASE = '/api'

/** How often the pairing window asks whether the code was used. */
export const POLL_MS = 2000

/** Longest name of a device. */
export const NAME_MAX = 80

/** Kind and symbol of every button (the rules of the ui kit: what ends or removes is `danger`, at most one primary per
 * box). */
export const BUTTONS = {
  connect: { kind: 'primary', icon: 'Smartphone' },
  rename: { kind: 'secondary', icon: 'Pencil' },
  disconnect: { kind: 'danger', icon: 'Unplug' },
  disconnectAll: { kind: 'danger', icon: 'Unplug' },
  save: { kind: 'primary', icon: 'Check' },
  done: { kind: 'primary', icon: 'Check' },
  cancel: { kind: 'secondary', icon: 'X' },
  renew: { kind: 'secondary', icon: 'RefreshCw' },
  store: { kind: 'secondary', icon: 'ExternalLink' },
  confirm: { kind: 'primary', icon: 'Link' },
  again: { kind: 'secondary', icon: 'RotateCcw' },
} as const

/** The symbol of a device in a row. The kit has no tablet or laptop, so an iPad shows the phone too. */
export const KIND_ICONS: Record<DeviceKind, IconName> = { ios: 'Smartphone', ipados: 'Smartphone', mac: 'Monitor' }

export function kindIcon(kind: string): IconName {
  return KIND_ICONS[kind as DeviceKind] ?? 'Smartphone'
}

export type DeviceTexts = typeof de
export const DEVICE_TEXTS: Record<'de' | 'en' | 'fr', DeviceTexts> = { de, en, fr }

/** Fills `{app}`, `{name}`, `{count}`, `{when}` … */
export function fillDevices(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key] ?? '') : whole))
}

/** How a moment is written; the app may give its own (nextime: the account's zone). */
export type WhenFormat = (iso: string, language: string) => string

/** E65: "heute, 14:05", "gestern, 21:40", "12.11.2026, 09:12". */
export function defaultWhen(iso: string, language: string): string {
  return formatMoment(iso, language)
}

/** "iPhone", "iPad", "Mac". */
export function kindLabel(texts: DeviceTexts, kind: string): string {
  return (texts.kinds as Record<string, string>)[kind] ?? texts.kinds.ios
}

/** "1 Gerät", "3 Geräte". */
export function countText(texts: DeviceTexts, count: number): string {
  return fillDevices(count === 1 ? texts.devices.one : texts.devices.many, { count })
}

/** The line under a device's name: "iPhone 15 · App 1.0.2 · zuletzt heute, 14:05", with "über iCloud übernommen" for
 * a device taken over from another one. */
export function deviceLine(device: Device, texts: DeviceTexts, language: string, when: WhenFormat = defaultWhen): string {
  return [
    device.model || kindLabel(texts, device.kind),
    device.app_version ? fillDevices(texts.devices.app, { version: device.app_version }) : null,
    device.via === 'icloud' ? texts.devices.icloud : null,
    device.last_seen_at ? fillDevices(texts.devices.lastSeen, { when: when(device.last_seen_at, language) }) : texts.devices.neverSeen,
  ]
    .filter((part): part is string => Boolean(part))
    .join(' · ')
}

/** "iPhone, iPad": the kinds of the devices, each once, in the order they come. */
export function kindsText(texts: DeviceTexts, devices: readonly { kind: string }[]): string {
  return [...new Set(devices.map((device) => kindLabel(texts, device.kind)))].join(', ')
}

/** The latest contact of any of the devices, or null. */
export function lastContact(devices: readonly { last_seen_at: string | null }[]): string | null {
  return devices.reduce<string | null>((latest, device) => {
    if (!device.last_seen_at) return latest
    return latest === null || Date.parse(device.last_seen_at) > Date.parse(latest) ? device.last_seen_at : latest
  }, null)
}

/** What is left of a code: "9:41" (minutes and seconds), "0:00" once it ran out. */
export function remaining(expiresAt: string, now: number): string {
  const seconds = Math.max(0, Math.ceil((Date.parse(expiresAt) - now) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** The QR code as a picture: an image, never markup put into the page. */
export function qrSource(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

/** "notes.example.com" from "https://notes.example.com"; what is no address stays as it came. */
export function hostOf(address: string): string {
  try {
    return new URL(address).host || address
  } catch {
    return address
  }
}

/** What the app sends along to `/app-connect`: 8 to 128 characters of base64url. */
export function validState(state: string | null): state is string {
  return state !== null && /^[A-Za-z0-9_-]{8,128}$/.test(state)
}

/** Where "Abbrechen" on `/app-connect` leads: back to the app, which hears that the person said no. */
export function cancelLink(scheme: string, state: string): string {
  return `${scheme}://connected?error=cancelled&state=${encodeURIComponent(state)}`
}

/** What `/app-connect` was opened with: the new form (`state`, `challenge`), the old one of nextasks and nexlore
 * (`device`), or nothing usable. */
export type ConnectAsk = { form: 'state'; state: string; challenge: string | null } | { form: 'device'; device: string } | { form: 'invalid' }

export function connectAsk(search: string): ConnectAsk {
  const params = new URLSearchParams(search)
  const state = params.get('state')
  if (state !== null) {
    const challenge = params.get('challenge')
    if (!validState(state) || (challenge !== null && !/^[A-Za-z0-9_-]{43,128}$/.test(challenge))) return { form: 'invalid' }
    return { form: 'state', state, challenge }
  }
  const device = params.get('device')
  if (device !== null) return { form: 'device', device: device.slice(0, NAME_MAX) }
  return { form: 'invalid' }
}

/** The row "iPhone und iPad" of `NotifyWays` (`devices`): the count and how many may show notifications. `undefined`
 * while the app has no iPhone app (the row is left out). */
export function devicesWay(listing: DeviceListing, texts: DeviceTexts, href?: string): { href?: string; note: string } | undefined {
  if (!listing.has_app) return undefined
  const count = listing.devices.length
  if (count === 0) return { href, note: texts.way.none }
  return { href, note: fillDevices(texts.way.some, { devices: countText(texts, count), push: listing.devices.filter((device) => device.push).length }) }
}

/** The code of a refused request: the module's `{code}` in FastAPI's `detail`, or on the error itself. */
export function refusalCode(error: unknown): { code?: string; max?: number } {
  const found = error as { code?: unknown; max?: unknown; detail?: unknown; body?: unknown } | null
  const inner = (found?.detail ?? (found?.body as { detail?: unknown } | undefined)?.detail ?? found) as { code?: unknown; max?: unknown } | null
  return { code: typeof inner?.code === 'string' ? inner.code : undefined, max: typeof inner?.max === 'number' ? inner.max : undefined }
}

/** The words of a refusal of the module (`too_many_pairings`, `app_disabled`, `name_invalid` …). */
export function refusalText(texts: DeviceTexts, error: unknown): string {
  const { code, max } = refusalCode(error)
  const known = code ? (texts.errors as Record<string, string>)[code] : undefined
  return known ? fillDevices(known, { max: max ?? '' }) : texts.failed
}
