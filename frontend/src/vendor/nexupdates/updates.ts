// nexupdates in the browser: what the routes answer, the calls to them, the module's words, and what the kit's
// `AboutPage` takes (its card "Aktualisierungen" with the badge "Version x ist erschienen"). An operator sees the state
// and may switch and ask; a member sees neither the card nor the state, only the own version (U2, U15; `showUpdates`
// of ui 1.1.1). The setup's box is UpdateSetupRow.tsx.
//
// Copied unchanged into frontend/src/vendor/nexupdates/ by bauplaene/updates/tools/sync.py; changed only there.

import { useCallback, useEffect, useMemo, useState } from 'react'

import { NEXUI_TEXTS, fill, languageOf, useNexuiTexts, type AboutUpdates } from '../nexui'

import de from './updates.de.json'
import en from './updates.en.json'
import fr from './updates.fr.json'

/** `GET <base>`: version, licence and where the app comes from. */
export type AboutInfo = { version: string; license: string; repo_url: string; releases_url: string; project_url: string }

/** `GET <base>/updates` and the other routes: the switch and what the last question found. */
export type UpdatesAnswer = {
  update_check: boolean
  checked: boolean
  latest: string | null
  newer: boolean
  checked_at: string | null
  release_url: string | null
  /** The state is not this account's to see (a member, U21): every other field is then empty. */
  hidden: boolean
}

export const BASE = '/api/about'
/** GitHub's address for the question; an app with `<APP>_UPDATE_URL` names its own. */
export const GITHUB = 'https://api.github.com'

/** The app's way to the server: `fetch` with what the app adds (cookies, a base path, its own headers). */
export type Fetcher = (path: string, init: RequestInit) => Promise<Response>

export const plainFetch: Fetcher = (path, init) => fetch(path, { credentials: 'same-origin', ...init })

export type UpdatesApi = {
  about(): Promise<AboutInfo>
  state(): Promise<UpdatesAnswer>
  check(): Promise<UpdatesAnswer>
  switch(on: boolean): Promise<UpdatesAnswer>
}

/** The calls to the module's routes under `base` (where the app mounted `api.router`). */
export function makeUpdatesApi(fetcher: Fetcher = plainFetch, base: string = BASE): UpdatesApi {
  const call = async <T,>(path: string, init: RequestInit): Promise<T> => {
    const response = await fetcher(base + path, init)
    if (!response.ok) throw new Error(String(response.status))
    return (await response.json()) as T
  }
  const json = { 'Content-Type': 'application/json', Accept: 'application/json' }
  return {
    about: () => call<AboutInfo>('', { method: 'GET', headers: json }),
    state: () => call<UpdatesAnswer>('/updates', { method: 'GET', headers: json }),
    check: () => call<UpdatesAnswer>('/updates/check', { method: 'POST', headers: json }),
    switch: (on) => call<UpdatesAnswer>('/updates', { method: 'PUT', headers: json, body: JSON.stringify({ update_check: on }) }),
  }
}

/** Only a tag of the fixed form is shown and linked (as the server keeps it). */
const TAG = /^v?\d{1,6}\.\d{1,6}\.\d{1,6}$/

/** What the kit's card shows: the operator's state; a member gets none (U15), nor does an answer the server marks
 * `hidden` (U21). `when` writes a moment in the reader's
 * words ("heute, 09:12"). */
export function aboutUpdates(answer: UpdatesAnswer | null, operator: boolean, when: (iso: string) => string): AboutUpdates | null {
  if (!answer || !operator || answer.hidden) return null
  const latest = answer.latest && TAG.test(answer.latest) ? answer.latest : null
  return {
    checkDaily: answer.update_check,
    checked: answer.checked,
    latest,
    newer: Boolean(latest) && answer.newer,
    checkedAt: answer.checked_at ? when(answer.checked_at) : null,
    releaseUrl: latest ? answer.release_url : null,
  }
}

// --- Words ------------------------------------------------------------------------------------------------------------

export type UpdatesTexts = typeof de
export const UPDATES_TEXTS: Record<'de' | 'en' | 'fr', UpdatesTexts> = { de, en, fr }

/** The module's words in the kit's language (`NexuiLanguage`, else `<html lang>`) or in the one given. */
export function useUpdatesTexts(language?: string): UpdatesTexts {
  const kit = useNexuiTexts()
  if (language) return UPDATES_TEXTS[languageOf(language)]
  return kit === NEXUI_TEXTS.de ? UPDATES_TEXTS.de : kit === NEXUI_TEXTS.fr ? UPDATES_TEXTS.fr : UPDATES_TEXTS.en
}

/** The host of an address ("api.github.com"), for the sentences; the address itself where it is none. */
export function hostOf(url: string): string {
  try {
    return new URL(url).host || url
  } catch {
    return url
  }
}

/** The card's sentence on what goes out: exactly the one address, and the app's other calls by itself (nextime: the
 * check of the internet connection), never "the only call" where it is not. */
export function whatGoesOut(texts: UpdatesTexts, app: string, url: string = GITHUB, others: readonly string[] = []): string {
  const first = fill(texts.whatGoesOut, { host: hostOf(url), app })
  const then = others.length ? fill(texts.otherCalls, { app, others: others.join(', ') }) : fill(texts.noOtherCalls, { app })
  return `${first} ${then}`
}

export type UseUpdates = {
  about: AboutInfo | null
  updates: AboutUpdates | null
  /** For `AboutPage showUpdates` (ui ≥ 1.1.1): the card only for an operator (U15), and not when the server says the
   * state is hidden from this account (U21). */
  showUpdates: boolean
  onDaily: (on: boolean) => void
  onCheck: () => void
  checking: boolean
  problem: string | null
}

/** Everything the kit's `AboutPage` needs for the card "Aktualisierungen": load, switch, ask now, all the operator's.
 * A member's page asks only for the about facts (its own version); the state is never fetched for it (U15). */
export function useUpdates({
  fetcher = plainFetch,
  base = BASE,
  operator,
  when,
  language,
}: {
  fetcher?: Fetcher
  base?: string
  operator: boolean
  when: (iso: string) => string
  language?: string
}): UseUpdates {
  const texts = useUpdatesTexts(language)
  const api = useMemo(() => makeUpdatesApi(fetcher, base), [fetcher, base])
  const [about, setAbout] = useState<AboutInfo | null>(null)
  const [answer, setAnswer] = useState<UpdatesAnswer | null>(null)
  const [checking, setChecking] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const load = useCallback(() => {
    api.about().then(setAbout, () => setProblem(texts.failed))
    // A side matter: when it does not come, the card simply shows no state. A member's page never asks.
    if (operator) api.state().then(setAnswer, () => setAnswer(null))
  }, [api, texts, operator])
  useEffect(load, [load])

  const onCheck = () => {
    setChecking(true)
    api
      .check()
      .then((found) => {
        setAnswer(found)
        setProblem(null)
      }, () => setProblem(texts.failed))
      .finally(() => setChecking(false))
  }
  const onDaily = (on: boolean) => {
    if (answer) setAnswer({ ...answer, update_check: on })
    api.switch(on).then(setAnswer, () => {
      setProblem(texts.failed)
      load()
    })
  }
  return { about, updates: aboutUpdates(answer, operator, when), showUpdates: operator && !answer?.hidden, onDaily, onCheck, checking, problem }
}
