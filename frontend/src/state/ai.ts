/**
 * What the signed-in person may know about the AI, loaded once per page that shows it. Loading it never reaches the
 * service: the server answers from its settings. Only a press of "Write it up" sends notes (`aiApi.formulate`).
 */
import { useEffect, useState } from 'react'

import { aiApi, type AiState } from '../api/client'

export function useAiState(): AiState | null {
  const [state, setState] = useState<AiState | null>(null)
  useEffect(() => {
    let alive = true
    aiApi.state().then(
      (found) => alive && setState(found),
      () => alive && setState(null),
    )
    return () => {
      alive = false
    }
  }, [])
  return state
}
