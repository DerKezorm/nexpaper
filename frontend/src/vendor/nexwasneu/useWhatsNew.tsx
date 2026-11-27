// The hooks of "What's new": the answer of the server, the history on demand, and the row on "About"
// (`useAboutWhatsNew`, W7, W18). Reading the text on "About" does not count as putting it away. A file without
// components, so that the app's fast refresh keeps working (react-refresh/only-export-components).
//
// Copied unchanged into frontend/src/vendor/nexwasneu/ by bauplaene/wasneu/tools/sync.py; changed only there.

import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { WhatsNewDialog } from '../nexui'

import { asVersions, BASE, makeWhatsNewApi, plainFetch, type Fetcher, type WhatsNewAnswer, type WhatsNewItem } from './wasneu'

export type WhatsNewProps = {
  /** The app's name ("nexlore"). */
  app: string
  /** The address of the app's logo, beside the first text. */
  logo?: string
  fetcher?: Fetcher
  /** Where the app mounted the routes (nexpaper `/api/v1/whats-new`). */
  base?: string
  /** The page's language; the texts come in it, else in its base language, else in English. */
  language?: string
}

/** The answer of `GET <base>` for this language; null until it is there (and when it fails: nothing to show). */
export function useAnswer(fetcher: Fetcher, base: string, language: string | undefined): WhatsNewAnswer | null {
  const api = useMemo(() => makeWhatsNewApi(fetcher, base), [fetcher, base])
  const key = `${base}|${language ?? ''}`
  const [found, setFound] = useState<{ key: string; answer: WhatsNewAnswer | null } | null>(null)
  useEffect(() => {
    let alive = true
    api.state(language).then(
      (answer) => alive && setFound({ key, answer }),
      () => alive && setFound({ key, answer: null }),
    )
    return () => {
      alive = false
    }
  }, [api, key, language])
  return found?.key === key ? found.answer : null
}

/** The history, loaded on a click on "Frühere Versionen"; without one text of the right form the window keeps what it
 * shows (W25). */
export function useEarlier(fetcher: Fetcher, base: string, language: string | undefined) {
  const api = useMemo(() => makeWhatsNewApi(fetcher, base), [fetcher, base])
  const [entries, setEntries] = useState<WhatsNewItem[] | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => {
    setBusy(true)
    api
      .history(language)
      .then((found) => setEntries(found.entries.length > 0 ? found.entries : null), () => setEntries(null))
      .finally(() => setBusy(false))
  }
  return { entries, busy, load, reset: () => setEntries(null) }
}

export type AboutWhatsNew = {
  /** For the kit's `AboutPage`: `whatsNewVersion` and `onWhatsNew`, or nothing while there is no text. */
  about: { whatsNewVersion?: string; onWhatsNew?: () => void }
  /** The window, to put beside the `AboutPage`. */
  window: ReactNode
}

/** The row "Was ist neu" on "About": the newest text up to the running version (after a fix without its own text the
 * one before, W7), with "Frühere Versionen" for the history (W18). Reading here puts nothing away. */
export function useAboutWhatsNew({ app, logo, fetcher = plainFetch, base = BASE, language }: WhatsNewProps): AboutWhatsNew {
  const answer = useAnswer(fetcher, base, language)
  const earlier = useEarlier(fetcher, base, language)
  const [open, setOpen] = useState(false)
  const current = answer?.current ?? null
  if (!answer || !current) return { about: {}, window: null }
  const close = () => {
    setOpen(false)
    earlier.reset()
  }
  return {
    about: { whatsNewVersion: current.version, onWhatsNew: () => setOpen(true) },
    window: open ? (
      <WhatsNewDialog
        app={app}
        version={answer.version}
        entries={asVersions(earlier.entries ?? [current])}
        title="all"
        logo={logo}
        onClose={close}
        onEarlier={answer.earlier && !earlier.entries ? earlier.load : undefined}
        earlierBusy={earlier.busy}
      />
    ) : null,
  }
}
