// "What's new" in the app, the same everywhere: the banner after an update with its window, under the app's head, for
// every signed-in account. Only from the kit (ui 1.2.0: `WhatsNewBanner`, `WhatsNewDialog`); the row on "About" is
// `useAboutWhatsNew` (useWhatsNew.tsx).
//
// Putting away does not wait for the server (W5, as nexmail): the banner goes at once and the note follows; when it
// fails, the banner comes back at the next load, the harmless mistake.
//
// Copied unchanged into frontend/src/vendor/nexwasneu/ by bauplaene/wasneu/tools/sync.py; changed only there.

import { useMemo, useState } from 'react'

import { WhatsNewBanner, WhatsNewDialog } from '../nexui'

import { useAnswer, useEarlier, type WhatsNewProps } from './useWhatsNew'
import { asVersions, BASE, makeWhatsNewApi, plainFetch } from './wasneu'

/**
 * The banner after an update and its window. Stands as long as the account has texts it has not read or put away;
 * "Was ist neu?" opens them (the newest first), "Verstanden", closing the window and the button beside the banner put
 * them away for this account on every device. With more unread versions than the window shows, "Frühere Versionen"
 * loads them all. `onSeen` runs after the server took the note (an app that keeps `whats_new_seen` in its own state
 * reloads it there).
 */
export function WhatsNewAfterUpdate({ app, logo, fetcher = plainFetch, base = BASE, language, onSeen }: WhatsNewProps & { onSeen?: () => void }) {
  const answer = useAnswer(fetcher, base, language)
  const api = useMemo(() => makeWhatsNewApi(fetcher, base), [fetcher, base])
  const earlier = useEarlier(fetcher, base, language)
  const [gone, setGone] = useState(false)
  const [open, setOpen] = useState(false)
  if (!answer || answer.unread.length === 0 || gone) return null

  const putAway = () => {
    setOpen(false)
    setGone(true)
    api.seen().then(
      () => onSeen?.(),
      () => undefined,
    )
  }
  return (
    <>
      <WhatsNewBanner app={app} version={answer.version} onShow={() => setOpen(true)} onPutAway={putAway} />
      {open && (
        <WhatsNewDialog
          app={app}
          version={answer.version}
          entries={asVersions(earlier.entries ?? answer.unread)}
          title={earlier.entries ? 'all' : 'since'}
          logo={logo}
          onClose={putAway}
          onEarlier={answer.more && !earlier.entries ? earlier.load : undefined}
          earlierBusy={earlier.busy}
        />
      )}
    </>
  )
}

