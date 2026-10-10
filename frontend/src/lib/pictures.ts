/**
 * Pictures of pages, fetched by the page itself instead of an `<img>` that asks on its own: the server draws at most two
 * pages at a time for one person or one link and answers the rest at once with `503` and `Retry-After` (it keeps no
 * request waiting). A plain `<img>` cannot read that header; here every picture waits in one queue, at most two are
 * asked for at the same moment, and a busy answer is asked again after the time the server named. A picture that was
 * fetched stays in memory for this tab (its address names the version, so it never changes), the oldest ones go.
 */

/** As many as the server draws for one person at once (`services/pages.py`, `PER_PRINCIPAL`). */
export const AT_ONCE = 2
const TRIES = 8
/** The longest wait between two tries, whatever the server says. */
const LONGEST_WAIT_MS = 30_000
/** While a document is still being read (`409 not_ready`), its pictures are asked for again this often. */
const NOT_READY_WAIT_MS = 4_000
/** Pictures kept in memory; beyond that the oldest are let go. */
const KEPT = 300

export class PictureError extends Error {
  constructor(public readonly status: number) {
    super(`picture ${status}`)
  }
}

/** How long to wait after a busy answer: what `Retry-After` says (seconds), else `fallback`; never under half a second. */
export function retryAfterMs(header: string | null, fallback: number): number {
  const seconds = header === null || header.trim() === '' ? NaN : Number(header)
  const wanted = Number.isFinite(seconds) && seconds >= 0 ? seconds * 1000 : fallback
  return Math.min(LONGEST_WAIT_MS, Math.max(500, wanted))
}

/** The clock of the queue, to be replaced in a test. */
export const timing = {
  sleep: (ms: number, signal?: AbortSignal) =>
    new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, ms)
      signal?.addEventListener('abort', () => {
        clearTimeout(timer)
        reject(new DOMException('aborted', 'AbortError'))
      })
    }),
}

type Waiting = { start: () => void }
let running = 0
const queue: Waiting[] = []
const kept = new Map<string, string>()

function turn(): Promise<() => void> {
  return new Promise((resolve) => {
    const start = () => {
      running += 1
      let done = false
      resolve(() => {
        if (done) return
        done = true
        running -= 1
        queue.shift()?.start()
      })
    }
    if (running < AT_ONCE) start()
    else queue.push({ start })
  })
}

function keep(url: string, objectUrl: string): void {
  kept.set(url, objectUrl)
  while (kept.size > KEPT) {
    const [oldest, made] = kept.entries().next().value as [string, string]
    kept.delete(oldest)
    if (made !== oldest) URL.revokeObjectURL?.(made)
  }
}

/** A picture already fetched in this tab, or nothing. */
export function keptPicture(url: string): string | null {
  return kept.get(url) ?? null
}

/** The picture at `url` as an address the page can show (an object URL), fetched in turn with the others. */
export async function loadPicture(url: string, signal?: AbortSignal): Promise<string> {
  const known = kept.get(url)
  if (known) return known
  for (let attempt = 1; ; attempt++) {
    const done = await turn()
    let wait: number
    try {
      if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
      const response = await fetch(url, { credentials: 'same-origin', signal }).catch((error: unknown) => {
        if (signal?.aborted || (error instanceof DOMException && error.name === 'AbortError')) throw error
        return null // the network: tried again, a little later each time
      })
      if (response?.ok) {
        const blob = await response.blob()
        const made = typeof URL.createObjectURL === 'function' ? URL.createObjectURL(blob) : url
        keep(url, made)
        return made
      }
      const status = response?.status ?? 0
      const busy = status === 503 || status === 429
      if ((response && !busy && status !== 409) || attempt >= TRIES) throw new PictureError(status)
      wait = !response ? retryAfterMs(null, 1000 * attempt) : busy ? retryAfterMs(response.headers.get('Retry-After'), 1500 * attempt) : NOT_READY_WAIT_MS
    } finally {
      done()
    }
    await timing.sleep(wait, signal)
  }
}

/** Forget what was fetched (signing out; and in tests who waits too). */
export function forgetPictures(): void {
  for (const [url, made] of kept) if (made !== url) URL.revokeObjectURL?.(made)
  kept.clear()
  queue.length = 0
  running = 0
}
