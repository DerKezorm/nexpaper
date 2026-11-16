/**
 * Wide screens (issue #7): from this width (in CSS pixels, after the scaling of the system and the zoom of the browser)
 * the archive shows a document beside its list, and the pages that stand next to a list use the whole width. A laptop
 * at 150 % (2304 px → 1536) stays below it and keeps the pages as they were.
 */
import { useEffect, useState } from 'react'

export const SPLIT_FROM = 1600
const QUERY = `(min-width: ${SPLIT_FROM}px)`

function matches(): boolean {
  try {
    return window.matchMedia(QUERY).matches
  } catch {
    return window.innerWidth >= SPLIT_FROM
  }
}

/** Whether the window is wide enough for a document beside a list; follows resizing and zooming. */
export function useWide(): boolean {
  const [wide, setWide] = useState(matches)
  useEffect(() => {
    let query: MediaQueryList
    try {
      query = window.matchMedia(QUERY)
    } catch {
      return
    }
    const follow = () => setWide(query.matches)
    follow()
    query.addEventListener?.('change', follow)
    return () => query.removeEventListener?.('change', follow)
  }, [])
  return wide
}
