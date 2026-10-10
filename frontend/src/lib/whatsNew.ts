/**
 * "What's new", as in nexlore: one written text per version, in `i18n/whatsnew/<language>.json`, keyed by
 * the version (`"0.2.0"`). Loaded only when needed: an account reads it once after an update.
 *
 * An entry has four fields: `lead`, `sections` (each with `title`, `where`, `body`), `smallTitle` and `small`. An entry
 * of another shape is left out, never shown half; `whatsNew.test.ts` makes sure none ships like that. Bug-fix
 * versions need no entry: without one there is no banner.
 */
import { useEffect, useState } from 'react'

export type WhatsNewSection = { title: string; where: string; body: string }
export type WhatsNewEntry = { lead: string; sections: WhatsNewSection[]; smallTitle: string; small: string[] }
type Entries = Record<string, WhatsNewEntry>

const FILES: Record<'en' | 'de', () => Promise<{ default: Record<string, unknown> }>> = {
  en: () => import('../i18n/whatsnew/en.json'),
  de: () => import('../i18n/whatsnew/de.json'),
}

function isText(value: unknown): value is string {
  return typeof value === 'string' && value.trim() !== ''
}

export function isEntry(value: unknown): value is WhatsNewEntry {
  if (!value || typeof value !== 'object') return false
  const entry = value as Partial<WhatsNewEntry>
  return (
    isText(entry.lead) &&
    Array.isArray(entry.sections) &&
    entry.sections.length > 0 &&
    entry.sections.every((part) => !!part && isText(part.title) && isText(part.where) && isText(part.body)) &&
    typeof entry.smallTitle === 'string' &&
    Array.isArray(entry.small) &&
    entry.small.every(isText)
  )
}

/** German texts for German, English for every other language (an added language has no own texts here). */
export function fileFor(language: string): 'en' | 'de' {
  return language.split('-')[0] === 'de' ? 'de' : 'en'
}

const loaded = new Map<'en' | 'de', Promise<Entries>>()

export function entriesFor(language: string): Promise<Entries> {
  const file = fileFor(language)
  let entries = loaded.get(file)
  if (!entries) {
    entries = FILES[file]().then(
      ({ default: all }) => Object.fromEntries(Object.entries(all).filter((pair): pair is [string, WhatsNewEntry] => isEntry(pair[1]))),
      () => ({}),
    )
    loaded.set(file, entries)
  }
  return entries
}

/** The entry of a version in the language of the page; `ready` only once the file is there (not "no entry"). */
export function useWhatsNew(version: string | undefined, language: string, wanted = true): { entry: WhatsNewEntry | null; ready: boolean } {
  const [state, setState] = useState<{ key: string; entry: WhatsNewEntry | null } | null>(null)
  const key = `${fileFor(language)}:${version ?? ''}`
  useEffect(() => {
    if (!wanted || !version) return
    let alive = true
    void entriesFor(language).then((entries) => {
      if (alive) setState({ key, entry: entries[version] ?? null })
    })
    return () => {
      alive = false
    }
  }, [key, language, version, wanted])
  const ready = state?.key === key
  return { entry: ready ? state.entry : null, ready }
}
