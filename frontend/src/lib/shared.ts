/**
 * Files another app shared with nexpaper (Android's share menu, `share_target` in the manifest). The service worker takes
 * the form on the phone and keeps the files in the cache `nexpaper-share` under `/teilen/<id>/<n>`, then opens
 * `/teilen?share=<id>` (`public/sw.js`). The page reads them from here and uploads them through the API, after the
 * person said so: a page on another site could send a form to `/teilen` just the same, so nothing goes up by itself.
 */

export const SHARE_CACHE = 'nexpaper-share'
const ID = /^[0-9a-f]{16,64}$/

function mine(url: string, id: string): boolean {
  try {
    return new URL(url).pathname.startsWith(`/teilen/${id}/`)
  } catch {
    return false
  }
}

/** The files of one share, in the order they came; none when the id is not one or the cache is gone. */
export async function sharedFiles(id: string): Promise<File[]> {
  if (!ID.test(id) || typeof caches === 'undefined') return []
  try {
    const cache = await caches.open(SHARE_CACHE)
    const keys = (await cache.keys()).filter((request) => mine(request.url, id))
    keys.sort((a, b) => Number(new URL(a.url).pathname.split('/').pop()) - Number(new URL(b.url).pathname.split('/').pop()))
    const files: File[] = []
    for (const key of keys) {
      const response = await cache.match(key)
      if (!response) continue
      const blob = await response.blob()
      let name = 'shared'
      try {
        name = decodeURIComponent(response.headers.get('X-Name') ?? '') || name
      } catch {
        // A name that cannot be read stays "shared".
      }
      files.push(new File([blob], name, { type: blob.type || response.headers.get('Content-Type') || '' }))
    }
    return files
  } catch {
    return []
  }
}

/** How long shared files wait in the browser for the person to say "Upload". */
export const SHARE_MINUTES = 15

/** The share the page at `location` shows (`/teilen?share=<id>`), or none. */
export function openShare(location: { pathname: string; search: string }): string | null {
  if (location.pathname !== '/teilen') return null
  const id = new URLSearchParams(location.search).get('share') ?? ''
  return ID.test(id) ? id : null
}

/**
 * Called as every page starts: every share but the one this page shows goes at once (a page loaded anew, a closed tab
 * or an address typed after sharing leave no files behind), and the one it shows goes too once it is older than
 * `SHARE_MINUTES`.
 */
export async function sweepShared(keep: string | null = null, now: number = Date.now()): Promise<number> {
  if (typeof caches === 'undefined') return 0
  try {
    const cache = await caches.open(SHARE_CACHE)
    let gone = 0
    for (const key of await cache.keys()) {
      const at = Number(new URL(key.url).searchParams.get('at'))
      const shown = keep !== null && mine(key.url, keep)
      if (!shown || !at || now - at > SHARE_MINUTES * 60 * 1000) {
        await cache.delete(key)
        gone += 1
      }
    }
    return gone
  } catch {
    return 0
  }
}

/** The files of one share go from the cache (uploaded, or thrown away). */
export async function dropShared(id: string): Promise<void> {
  if (!ID.test(id) || typeof caches === 'undefined') return
  try {
    const cache = await caches.open(SHARE_CACHE)
    for (const key of await cache.keys()) if (mine(key.url, id)) await cache.delete(key)
  } catch {
    // Nothing to throw away.
  }
}
