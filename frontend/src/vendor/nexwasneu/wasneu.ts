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

/** The calls to the module's routes under `base` (where the app mounted `api.router`). */
export function makeWhatsNewApi(fetcher: Fetcher = plainFetch, base: string = BASE): WhatsNewApi {
  const call = async <T,>(path: string, init: RequestInit): Promise<T> => {
    const response = await fetcher(base + path, init)
    if (!response.ok) throw new Error(String(response.status))
    return (await response.json()) as T
  }
  const json = { Accept: 'application/json' }
  const asked = (language?: string) => (language ? `?language=${encodeURIComponent(language)}` : '')
  return {
    state: (language) => call<WhatsNewAnswer>(asked(language), { method: 'GET', headers: json }),
    history: (language) => call<WhatsNewHistory>(`/history${asked(language)}`, { method: 'GET', headers: json }),
    seen: () => call<{ seen: string }>('/seen', { method: 'POST', headers: json }),
  }
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
