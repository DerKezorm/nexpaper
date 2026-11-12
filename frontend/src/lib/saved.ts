/**
 * The person's saved searches ("Gemerkt", `GET /api/v1/saved-searches`): one list for the whole app, so that the side
 * bar and the archive show the same, and a change in one is seen by the other. The server keeps only the known parts of
 * the archive's address (`KEPT`, the page is not one of them) and counts each entry with the search.
 */
import { useCallback, useEffect, useState } from 'react'

import { savedApi, type SavedSearch } from '../api/client'

/** The most saved searches a person keeps (the server says so as well). */
export const SAVED_MAX = 30
/** How long a name may be. */
export const SAVED_NAME_MAX = 60

/** The parts of an archive's address a saved search keeps; the page number is not one of them. */
export const KEPT = ['q', 'vault', 'kind', 'sender', 'tag', 'owner', 'year', 'deadline', 'keep', 'all', 'sort', 'n'] as const

/** The kept parts of an address, sorted: two addresses of the same search give the same text. */
export function keptOf(params: URLSearchParams): string {
  const out = new URLSearchParams()
  for (const key of KEPT) {
    const value = params.get(key)
    if (value) out.set(key, value)
  }
  out.sort()
  return out.toString()
}

/** Whether an entry keeps the search of this address (each read the same way, whatever encoding the server chose). */
export function isSearch(entry: SavedSearch, params: URLSearchParams): boolean {
  const here = keptOf(params)
  return here !== '' && keptOf(new URLSearchParams(entry.query)) === here
}

type Store = { list: SavedSearch[] | null; error: boolean }
let store: Store = { list: null, error: false }
const listeners = new Set<(next: Store) => void>()
let asking: Promise<void> | null = null

function publish(next: Store) {
  store = next
  for (const listener of listeners) listener(next)
}

/** Asks the server again (after a change, or when the archive was opened); one request at a time. */
export function reloadSaved(): Promise<void> {
  if (asking) return asking
  asking = savedApi
    .list()
    .then(
      (list) => publish({ list: Array.isArray(list) ? list : [], error: false }),
      () => publish({ list: store.list ?? [], error: true }),
    )
    .finally(() => {
      asking = null
    })
  return asking
}

/** Puts a list the server answered in place (moving answers the whole list). */
export function setSaved(list: SavedSearch[]): void {
  publish({ list, error: false })
}

/** For the tests: forget what was fetched. */
export function forgetSaved(): void {
  store = { list: null, error: false }
  asking = null
}

/** The saved searches; fetched once for the app, again after `reload`. Empty while they are not known. */
export function useSaved(): { list: SavedSearch[]; known: boolean; reload: () => Promise<void> } {
  const [state, setState] = useState<Store>(store)
  useEffect(() => {
    listeners.add(setState)
    if (store.list === null) void reloadSaved()
    else setState(store)
    return () => {
      listeners.delete(setState)
    }
  }, [])
  const reload = useCallback(() => reloadSaved(), [])
  return { list: state.list ?? [], known: state.list !== null, reload }
}

/** What an entry says about itself when it cannot be counted as it was kept. */
export function savedHint(entry: SavedSearch, t: (key: string) => string): string {
  if (entry.state === 'no_access') return t('saved.noAccess')
  if (entry.state === 'failed') return t('saved.failed')
  if (entry.deadlines_off) return t('saved.deadlinesOff')
  return ''
}
