// The service worker of nexpaper: Web Push, and the files other apps share.
//
// It shows what the server sends (a notice of a new sign-in, a test) and opens nexpaper where a tap leads.
//
// Its fetch handler answers one request only: the form Android's share menu sends to /teilen (the share target of the
// manifest). Everything else passes untouched: it never stands between the page and the server, so it keeps no pages of
// documents and no answers of the API. The shared files stay on the phone, in the cache "nexpaper-share", and the page
// /teilen?share=<id> uploads them through the API once the person says so (src/lib/shared.ts). The server itself never
// takes such a form: it carries the cookie and no header of nexpaper's own, so any site could send one.

const SHARE_CACHE = 'nexpaper-share'
/** What one share may hold: files, and bytes in all. */
const SHARE_FILES = 20
const SHARE_BYTES = 512 * 1024 * 1024
/** A share nobody picked up goes after a quarter of an hour (the page sweeps too, src/lib/shared.ts). */
const SHARE_MINUTES = 15

self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

/**
 * Only a path of nexpaper itself, never another site. A browser drops tabs and line breaks from an address before it
 * reads it ("/" tab "//evil.example.org" becomes "//evil.example.org"), so control characters and backslashes are
 * refused outright, and what is left must still be of this origin once the browser has read it.
 */
function ownPath(value, fallback) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || /[\u0000-\u001f\u007f\\]/.test(value)) return fallback
  try {
    const target = new URL(value, self.location.origin)
    return target.origin === self.location.origin ? target.pathname + target.search + target.hash : fallback
  } catch {
    return fallback
  }
}

function shareId() {
  const bytes = new Uint8Array(16)
  self.crypto.getRandomValues(bytes)
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

async function takeShared(request) {
  const back = (path) => Response.redirect(new URL(path, self.location.origin).href, 303)
  try {
    const form = await request.formData()
    const files = form.getAll('files').filter((item) => item && typeof item === 'object' && typeof item.size === 'number')
    const cache = await self.caches.open(SHARE_CACHE)
    const now = Date.now()
    for (const old of await cache.keys()) {
      const at = Number(new URL(old.url).searchParams.get('at'))
      if (!at || now - at > SHARE_MINUTES * 60 * 1000) await cache.delete(old)
    }
    const id = shareId()
    let total = 0
    let count = 0
    for (const file of files.slice(0, SHARE_FILES)) {
      total += file.size
      if (total > SHARE_BYTES) break
      const headers = { 'Content-Type': file.type || 'application/octet-stream', 'X-Name': encodeURIComponent(String(file.name || 'shared').slice(0, 200)) }
      await cache.put(new URL(`/teilen/${id}/${count}?at=${now}`, self.location.origin).href, new Response(file, { headers }))
      count += 1
    }
    return back(count ? `/teilen?share=${id}` : '/teilen?missed=1')
  } catch {
    return back('/teilen?missed=1')
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'POST') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin || url.pathname !== '/teilen') return
  event.respondWith(takeShared(request))
})

function onPhone() {
  return /Android|iPhone|iPad|iPod|Mobile/i.test(self.navigator.userAgent)
}

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = {}
  }
  const title = typeof data.title === 'string' && data.title ? data.title.slice(0, 80) : 'nexpaper'
  const body = typeof data.body === 'string' ? data.body.slice(0, 600) : ''
  const phone = ownPath(data.url, '/')
  const desk = ownPath(data.desk, phone)
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      // PNG, not SVG: Android and Windows draw no SVG in a notification. The badge is read as a mask, white on clear.
      icon: '/icon-192.png',
      badge: '/badge-96.png',
      tag: typeof data.tag === 'string' ? data.tag.slice(0, 40) : undefined,
      data: { url: onPhone() ? phone : desk },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL(ownPath(event.notification.data && event.notification.data.url, '/'), self.location.origin)
  event.waitUntil(
    (async () => {
      const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of open) {
        if (new URL(client.url).origin !== self.location.origin) continue
        try {
          await client.focus()
          await client.navigate(target.href)
          return
        } catch {
          // A window this worker does not control cannot be led elsewhere: a new one instead.
          break
        }
      }
      await self.clients.openWindow(target.href)
    })(),
  )
})
