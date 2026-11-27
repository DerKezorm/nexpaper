// nexwasneu in the browser: what the routes answer and the calls to them. The texts come from the server (W3), in the
// language the page asks for, English where a version has none in it (W4); sections for operators reach operators only
// (W8). Banner and window are the kit's (`WhatsNewBanner`, `WhatsNewDialog`, ui 1.2.0); WhatsNew.tsx binds them.
//
// Copied unchanged into frontend/src/vendor/nexwasneu/ by bauplaene/wasneu/tools/sync.py; changed only there.

import type { WhatsNewEntry, WhatsNewVersion } from '../nexui'

/** One version's text as the server gives it: the entry, its version and the language it is in. */
export type WhatsNewItem = WhatsNewEntry & { version: string; language: string }

/** `GET <base>`: the running version, what this account read, its unread texts (the newest first, at most five; `more`
 * when there were more), the text for "About" and whether there are earlier ones. */
export type WhatsNewAnswer = {
  version: string
  seen: string
  unread: WhatsNewItem[]
  more: boolean
  current: WhatsNewItem | null
  earlier: boolean
}

/** `GET <base>/history`: every text up to the running version, the newest first. */
export type WhatsNewHistory = { version: string; entries: WhatsNewItem[] }

export const BASE = '/api/whats-new'

/** The app's way to the server: `fetch` with what the app adds (cookies, a base path, its own headers). */
export type Fetcher = (path: string, init: RequestInit) => Promise<Response>

export const plainFetch: Fetcher = (path, init) => fetch(path, { credentials: 'same-origin', ...init })

export type WhatsNewApi = {
  state(language?: string): Promise<WhatsNewAnswer>
  history(language?: string): Promise<WhatsNewHistory>
  seen(): Promise<{ seen: string }>
}

// --- The form of an answer (W25) ------------------------------------------------------------------------------------
// What comes back is checked before the page uses it: an answer of another form (an old server, a test double, the
// page of a proxy) is no answer and shows nothing; a text of another form is left out, never shown half. Nothing
// throws into the app. Fields the page does not know are ignored, so a newer server stays readable.

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const isText = (value: unknown): value is string => typeof value === 'string'

function isLink(value: unknown): boolean {
  if (value === undefined || value === null) return true
  if (!isRecord(value)) return false
  const { label, href } = value
  return isText(label) && isText(href)
}

function isSection(value: unknown): boolean {
  if (!isRecord(value)) return false
  const { title, where, body, link, operator } = value
  return isText(title) && isText(where) && isText(body) && isLink(link) && (operator === undefined || typeof operator === 'boolean')
}

/** Whether a value is one version's text in the form the page shows. */
export function isItem(value: unknown): value is WhatsNewItem {
  if (!isRecord(value)) return false
  const { version, language, lead, sections, smallTitle, small } = value
  return (
    isText(version) &&
    isText(language) &&
    isText(lead) &&
    isText(smallTitle) &&
    Array.isArray(small) &&
    small.every(isText) &&
    Array.isArray(sections) &&
    sections.every(isSection)
  )
}

const items = (value: unknown[]): WhatsNewItem[] => value.filter(isItem)

/** `GET <base>` as the page may use it, or null for an answer of another form. */
export function readAnswer(value: unknown): WhatsNewAnswer | null {
  if (!isRecord(value)) return null
  const { version, seen, unread, more, current, earlier } = value
  if (!isText(version) || !Array.isArray(unread)) return null
  return {
    version,
    seen: isText(seen) ? seen : '',
    unread: items(unread),
    more: more === true,
    current: isItem(current) ? current : null,
    earlier: earlier === true,
  }
}

/** `GET <base>/history` as the page may use it, or null for an answer of another form. */
export function readHistory(value: unknown): WhatsNewHistory | null {
  if (!isRecord(value)) return null
  const { version, entries } = value
  if (!isText(version) || !Array.isArray(entries)) return null
  return { version, entries: items(entries) }
}

function shaped<T>(found: T | null): T {
  if (found === null) throw new Error('an answer of another form')
  return found
}

/** The calls to the module's routes under `base` (where the app mounted `api.router`). An answer of another form
 * rejects like a failed call (W25). */
export function makeWhatsNewApi(fetcher: Fetcher = plainFetch, base: string = BASE): WhatsNewApi {
  const call = async (path: string, init: RequestInit): Promise<unknown> => {
    const response = await fetcher(base + path, init)
    if (!response.ok) throw new Error(String(response.status))
    return (await response.json()) as unknown
  }
  const json = { Accept: 'application/json' }
  const asked = (language?: string) => (language ? `?language=${encodeURIComponent(language)}` : '')
  return {
    state: async (language) => shaped(readAnswer(await call(asked(language), { method: 'GET', headers: json }))),
    history: async (language) => shaped(readHistory(await call(`/history${asked(language)}`, { method: 'GET', headers: json }))),
    seen: async () => readSeen(await call('/seen', { method: 'POST', headers: json })),
  }
}

function readSeen(value: unknown): { seen: string } {
  if (!isRecord(value)) return { seen: '' }
  const { seen } = value
  return { seen: isText(seen) ? seen : '' }
}

/** The server's texts as the kit's window takes them; a link leaves only to https (the server checks it too). */
export function asVersions(items: readonly WhatsNewItem[]): WhatsNewVersion[] {
  return items.map(({ version, lead, sections, smallTitle, small }) => ({
    version,
    entry: {
      lead,
      smallTitle,
      small,
      sections: sections.map((part) => ({
        ...part,
        link: part.link && part.link.href.startsWith('https://') ? part.link : null,
      })),
    },
  }))
}
