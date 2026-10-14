/** The documents that may go ("Darf weg", `GET /api/v1/keeping`), for the section `components/MayGo.tsx`. */
import { useCallback, useEffect, useState } from 'react'

import { ApiError, keepingApi, type DocumentInfo } from '../api/client'

/** How many are fetched at once (the most the server gives and takes in one go). */
const MOST = 500

export type MayGoState = { items: DocumentInfo[]; total: number; problem: string | null; reload: () => void }

/** The documents that may go, fetched once and again after `reload`. `vaultId`: only those of one vault. */
export function useMayGo(vaultId?: number): MayGoState {
  const [items, setItems] = useState<DocumentInfo[]>([])
  const [total, setTotal] = useState(0)
  const [problem, setProblem] = useState<string | null>(null)
  const [again, setAgain] = useState(0)
  useEffect(() => {
    let alive = true
    keepingApi.mayGo({ vault_id: vaultId, limit: MOST }).then(
      (answer) => {
        if (!alive) return
        setItems(Array.isArray(answer.items) ? answer.items : [])
        setTotal(answer.total)
        setProblem(null)
      },
      (error: unknown) => alive && setProblem(error instanceof ApiError ? error.code : 'internal_error'),
    )
    return () => {
      alive = false
    }
  }, [vaultId, again])
  const reload = useCallback(() => setAgain((n) => n + 1), [])
  return { items, total, problem, reload }
}

