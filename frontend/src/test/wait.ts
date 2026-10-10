/**
 * Waiting in tests, by events and never by a guess of how long something takes.
 *
 * - `idle()`: until every request of the fake API has been answered and the page has had its turns to react (a new
 *   request started by the answer is waited for too).
 * - `until(check)`: until `check` returns something truthy (a lookup in the page, say); gives that value.
 * - `eventually(check)`: until `check` stops throwing (a block of `expect`).
 * - `flush()`: one turn of the event loop inside `act`, for the rare place where nothing is awaited but a click has
 *   to reach its handler.
 *
 * `setup.ts` counts the requests (every stub of `fetch` goes through it) and can hold each answer back by
 * `TEST_API_DELAY_MS`, so that the suite can be run against a slow server.
 */
import { act } from 'react'

const state = { started: 0, open: 0, test: 0 }

/** Called before each test: requests a test left open (a held answer, say) are not the next test's business. */
export function newTest(): void {
  state.test += 1
  state.started = 0
  state.open = 0
}

/** The most a wait may take before the test says what it waited for. */
const LIMIT_MS = 10_000

type FetchLike = (...args: never[]) => unknown

function delayMs(): number {
  const raw = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env?.TEST_API_DELAY_MS
  const value = Number(raw ?? 0)
  return Number.isFinite(value) && value > 0 ? value : 0
}

/** A stub of `fetch` that is counted while a call is open and, with `TEST_API_DELAY_MS`, answers late. */
export function tracked<T extends FetchLike>(stub: T): T {
  const wrapped = async (...args: Parameters<T>) => {
    const mine = state.test
    state.started += 1
    state.open += 1
    try {
      const wait = delayMs()
      if (wait) {
        await new Promise((resolve) => setTimeout(resolve, wait))
        // The test is over by now (the stub was taken away): the request dies like one of a page that was closed,
        // instead of changing the stand-in server of the next test.
        if (globalThis.fetch !== (wrapped as unknown)) throw new TypeError('Failed to fetch')
      }
      return await (stub as unknown as (...inner: Parameters<T>) => unknown)(...args)
    } finally {
      if (mine === state.test) state.open -= 1
    }
  }
  return wrapped as unknown as T
}

export async function flush(): Promise<void> {
  await act(async () => new Promise((resolve) => setTimeout(resolve, 0)))
}

export async function idle(): Promise<void> {
  const end = Date.now() + LIMIT_MS
  let quiet = 0
  let seen = -1
  while (quiet < 3) {
    if (Date.now() > end) throw new Error(`idle: ${state.open} request(s) of the fake API still open after ${LIMIT_MS} ms`)
    await flush()
    if (state.open === 0 && state.started === seen) quiet += 1
    else quiet = 0
    seen = state.started
  }
}

export async function until<T>(check: () => T | null | undefined | false, what = 'the condition'): Promise<T> {
  const end = Date.now() + LIMIT_MS
  let last: unknown
  for (;;) {
    try {
      const found = check()
      if (found) return found
      last = undefined
    } catch (error) {
      last = error
    }
    if (Date.now() > end) throw new Error(`Gave up waiting for ${what} after ${LIMIT_MS} ms${last instanceof Error ? `: ${last.message}` : ''}`)
    await flush()
  }
}

export async function eventually(check: () => void, what = 'the expectations'): Promise<void> {
  await until(() => {
    check()
    return true
  }, what)
}
