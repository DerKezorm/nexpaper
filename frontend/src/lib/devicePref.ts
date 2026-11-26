/**
 * A choice kept in this browser only (which points of "Ready for the internet?" are open): read once, written at
 * every change. Without storage (a private window) it holds until the page is left.
 */
import { useCallback, useState } from 'react'

export function useDevicePref<T>(key: string, read: (raw: string | null) => T): [T, (raw: string) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      return read(localStorage.getItem(`nexpaper.${key}`))
    } catch {
      return read(null)
    }
  })
  const write = useCallback(
    (raw: string) => {
      try {
        localStorage.setItem(`nexpaper.${key}`, raw)
      } catch {
        // Then the choice only holds for this page.
      }
      setValue(read(raw))
    },
    [key, read],
  )
  return [value, write]
}
