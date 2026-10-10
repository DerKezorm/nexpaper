/**
 * Web Push in this browser, as nexsift's `WebPushSignup` does it: the service worker (`/sw.js`, Web Push only), the
 * permission, the subscription at the browser's push service. What can stand in the way is said before the button:
 * no https, an iPhone outside the home screen app, a browser without push, a permission the person refused.
 */

export type PushReadiness = 'ready' | 'insecure' | 'iphone' | 'unsupported' | 'denied'

/** The browser wants the server key as bytes; nexpaper hands it out as base64url. */
export function keyBytes(text: string): Uint8Array<ArrayBuffer> {
  const padded = (text + '='.repeat((4 - (text.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(padded)
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i)
  return bytes
}

function sameKey(current: ArrayBuffer | null | undefined, wanted: Uint8Array): boolean {
  if (!current) return false
  const have = new Uint8Array(current)
  return have.length === wanted.length && have.every((byte, index) => byte === wanted[index])
}

export function onIphone(): boolean {
  return /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

/** Opened from the home screen, as an app. */
export function installed(): boolean {
  return window.matchMedia?.('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true
}

export function readiness(): PushReadiness {
  if (!window.isSecureContext) return 'insecure'
  if (onIphone() && !installed()) return 'iphone'
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return 'unsupported'
  if (Notification.permission === 'denied') return 'denied'
  return 'ready'
}

/** The subscription this browser holds now, without asking anything; null when there is none or no push at all. */
export async function currentSubscription(): Promise<PushSubscription | null> {
  if (readiness() !== 'ready' && readiness() !== 'denied') return null
  const registration = await navigator.serviceWorker.getRegistration('/')
  return (await registration?.pushManager.getSubscription()) ?? null
}

export type Subscribed = { endpoint: string; p256dh: string; auth: string }

/**
 * Asks for the permission, registers the service worker and subscribes with the server's key. A subscription made
 * with another key (the operator made a new pair) is given up first: the push service would refuse every message.
 * Throws `denied` when the person said no.
 */
export async function subscribe(serverKey: string): Promise<Subscribed> {
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error('denied')
  await navigator.serviceWorker.register('/sw.js', { scope: '/' })
  const registration = await navigator.serviceWorker.ready
  const wanted = keyBytes(serverKey)
  let subscription = await registration.pushManager.getSubscription()
  if (subscription && !sameKey(subscription.options.applicationServerKey, wanted)) {
    await subscription.unsubscribe()
    subscription = null
  }
  subscription ??= await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: wanted })
  const json = subscription.toJSON()
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) throw new Error('incomplete')
  return { endpoint: json.endpoint, p256dh: json.keys.p256dh, auth: json.keys.auth }
}

/** Gives up the subscription of this browser (after its device was removed). */
export async function unsubscribe(): Promise<void> {
  const subscription = await currentSubscription().catch(() => null)
  await subscription?.unsubscribe().catch(() => undefined)
}
