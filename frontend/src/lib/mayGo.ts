/** The documents that may go ("Darf weg", `GET /api/v1/keeping`), for the section `components/MayGo.tsx`. */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, keepingApi, type DocumentInfo } from '../api/client'
import { useConfirm } from '../components/useConfirm'
import { inboxChanged, useSay } from './say'

/** How many are fetched at once (the most the server gives and takes in one go). */
const MOST = 500

/** How many documents may go (the number of the archive's chip and hint), and how many nexpaper put in the trash by
 * itself lately (`away`, the note that leads to the trash), asked for with one document; again after `reload`. 0 while
 * it is unknown. */
export function useMayGoCount(): { total: number; away: number; reload: () => void } {
  const [total, setTotal] = useState(0)
  const [away, setAway] = useState(0)
  const [again, setAgain] = useState(0)
  useEffect(() => {
    let alive = true
    keepingApi.mayGo({ limit: 1 }).then(
      (answer) => {
        if (!alive) return
        setTotal(typeof answer.total === 'number' ? answer.total : 0)
        setAway(typeof answer.auto_trashed === 'number' ? answer.auto_trashed : 0)
      },
      () => undefined,
    )
    return () => {
      alive = false
    }
  }, [again])
  const reload = useCallback(() => setAgain((n) => n + 1), [])
  return { total, away, reload }
}

export type MayGoState = { items: DocumentInfo[]; total: number; problem: string | null; reload: () => void }

/** The documents that may go, fetched once and again after `reload`. `vaultId`: only those of one vault. `enabled`
 * false: nothing is fetched (a page that has them from another call). */
export function useMayGo(vaultId?: number, enabled = true): MayGoState {
  const [items, setItems] = useState<DocumentInfo[]>([])
  const [total, setTotal] = useState(0)
  const [problem, setProblem] = useState<string | null>(null)
  const [again, setAgain] = useState(0)
  useEffect(() => {
    if (!enabled) return
    let alive = true
    keepingApi.mayGo({ vault_id: vaultId, limit: MOST }).then(
      (answer) => {
        if (!alive) return
        setItems(Array.isArray(answer.items) ? answer.items : [])
        setTotal(typeof answer.total === 'number' ? answer.total : 0)
        setProblem(null)
      },
      (error: unknown) => alive && setProblem(error instanceof ApiError ? error.code : 'internal_error'),
    )
    return () => {
      alive = false
    }
  }, [vaultId, again, enabled])
  const reload = useCallback(() => setAgain((n) => n + 1), [])
  return { items, total, problem, reload }
}

/**
 * Asks, then puts documents in the trash, each checked on its own by the server, and says how it went. The question
 * names the number and that the trash holds them for 30 days (rule 13: nothing is put away without a "really?").
 * `trash(ids)` opens the question, `dialog` is put in the page once. Used by the section on the deadlines page and by
 * the archive's filter "Darf weg".
 */
export function useTrashMany(onDone: () => void) {
  const { t, i18n } = useTranslation()
  const say = useSay()
  const { ask, dialog } = useConfirm()
  const n = (value: number) => value.toLocaleString(i18n.language)
  const trash = (ids: number[]) => {
    if (!ids.length) return
    ask({
      title: t('keeping.askTitle', { count: ids.length, n: n(ids.length) }),
      text: t('keeping.askText', { count: ids.length }),
      confirm: t('keeping.toTrash'),
      danger: false,
      run: async () => {
        const done = await keepingApi.trashMany(ids)
        inboxChanged()
        onDone()
        const gone = done.trashed.length
        const notice = t('keeping.done', { count: gone, n: n(gone) })
        say(done.failed.length ? `${notice} ${t('keeping.failed', { count: done.failed.length, n: n(done.failed.length) })}` : notice, undefined, {
          to: '/papierkorb',
          label: t('docs.inbox.trashLink'),
        })
      },
    })
  }
  return { trash, dialog }
}
