/** A page's way to ask "really?" (``ConfirmDialog``): ``ask`` opens the dialog with what to say and what to do, ``dialog``
 * is put in the page once. */
import { useCallback, useRef, useState } from 'react'

import { ConfirmDialog, type ConfirmOptions } from './ConfirmDialog'

export type { ConfirmOptions }

export function useConfirm() {
  const [options, setOptions] = useState<ConfirmOptions | null>(null)
  // What is asked now: a request that asks the next question itself (a sender that documents still use) keeps the dialog.
  const asked = useRef<ConfirmOptions | null>(null)
  // Every question is a dialog of its own (a fresh button that has not been pressed).
  const count = useRef(0)
  const [number, setNumber] = useState(0)
  const ask = useCallback((next: ConfirmOptions) => {
    asked.current = next
    count.current += 1
    setNumber(count.current)
    setOptions(next)
  }, [])
  const dialog = options ? (
    <ConfirmDialog
      key={number}
      title={options.title}
      text={options.text}
      confirm={options.confirm}
      danger={options.danger ?? true}
      password={options.password}
      onCancel={() => {
        asked.current = null
        setOptions(null)
      }}
      onConfirm={async (password) => {
        await options.run(password)
        if (asked.current === options) {
          asked.current = null
          setOptions(null)
        }
      }}
    />
  ) : null
  return { ask, dialog }
}
