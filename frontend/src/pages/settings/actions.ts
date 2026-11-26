/**
 * What the cards of the settings share besides their looks (those come from the ui kit): running a change and
 * remembering whether it worked (`Outcome` shows it), and handing a file to the browser.
 */
import { useCallback, useState } from 'react'

import { ApiError } from '../../api/client'

/** Runs a change, remembers whether it worked; the card shows it with `Outcome`. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  /** What the server said along with the problem (a limit, a number), for the sentence. */
  const [values, setValues] = useState<Record<string, unknown>>({})
  const run = useCallback(async (work: () => Promise<unknown>, success?: string): Promise<boolean> => {
    setBusy(true)
    setProblem(null)
    setValues({})
    setDone(null)
    try {
      await work()
      if (success) setDone(success)
      return true
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
      setValues(error instanceof ApiError ? error.values : {})
      return false
    } finally {
      setBusy(false)
    }
  }, [])
  const clear = useCallback(() => {
    setProblem(null)
    setDone(null)
  }, [])
  return { busy, problem, values, done, run, clear }
}

export function saveAsFile(name: string, data: Blob) {
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
