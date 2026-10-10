/**
 * A page of a document as a picture, fetched only when it comes into view (or near it) and through the queue of
 * `lib/pictures.ts`, which honours the server's `Retry-After`. Until it is there, a quiet sheet in the shape of a page
 * stands in. `better` is a sharper picture of the same page (the large one), fetched once the first has arrived and only
 * where the first is too coarse for the place it has on this screen (a phone or a narrow column needs no more); it
 * replaces it when it comes, and when it does not, the first stays. The server draws large pictures only on request,
 * so asking for them where they show nothing better would only make it busy.
 */
import { FileText } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { keptPicture, loadPicture } from '../lib/pictures'

type Props = {
  src: string
  alt: string
  className?: string
  /** Fetched at once, without waiting to be seen (the first page of a document). */
  eager?: boolean
  better?: string
  /** How far outside the view a picture starts to load. */
  margin?: string
}

/** The width the small pictures are drawn at (`services/pages.py`). */
const SMALL_WIDTH = 720

/** Whether the place shows more pixels than the small picture has. */
function sharpWanted(element: HTMLElement | null): boolean {
  const width = element?.getBoundingClientRect().width ?? 0
  return width * (window.devicePixelRatio || 1) > SMALL_WIDTH * 1.1
}

export function PagePicture({ src, alt, className = '', eager = false, better, margin = '600px' }: Props) {
  const holder = useRef<HTMLDivElement>(null)
  const [seen, setSeen] = useState(eager)
  const [shown, setShown] = useState<{ src: string; url: string } | null>(() => {
    const kept = keptPicture(better ?? '') ?? keptPicture(src)
    return kept ? { src, url: kept } : null
  })
  const [failed, setFailed] = useState(false)

  const url = shown && shown.src === src ? shown.url : null

  useEffect(() => {
    if (eager || url) return
    const element = holder.current
    if (!element || typeof IntersectionObserver === 'undefined') {
      setSeen(true)
      return
    }
    // Followed until the picture is there: one scrolled away before its turn gives its place in the queue to those on
    // the screen (a strip of ninety pages), and is asked for again when it comes back.
    const watcher = new IntersectionObserver((entries) => setSeen(entries.some((entry) => entry.isIntersecting)), { rootMargin: margin })
    watcher.observe(element)
    return () => watcher.disconnect()
  }, [eager, url, margin])

  useEffect(() => {
    if (!seen || url) return
    const stop = new AbortController()
    setFailed(false)
    void (async () => {
      try {
        const sharpKept = better ? keptPicture(better) : null
        if (sharpKept) {
          setShown({ src, url: sharpKept })
          return
        }
        setShown({ src, url: await loadPicture(src, stop.signal) })
        if (better && sharpWanted(holder.current)) {
          try {
            const sharp = await loadPicture(better, stop.signal)
            setShown({ src, url: sharp })
          } catch {
            // The small one stays.
          }
        }
      } catch (error) {
        if (!stop.signal.aborted && !(error instanceof DOMException)) setFailed(true)
      }
    })()
    return () => stop.abort()
    // `url` is left out on purpose: once a picture is shown, the sharper one may still be on its way.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seen, src, better])

  return (
    <div ref={holder} className={`relative ${className}`} data-picture={url ? 'shown' : failed ? 'failed' : 'waiting'}>
      {url ? (
        <img src={url} alt={alt} draggable={false} className="block w-full rounded-[3px] bg-white shadow-[0_1px_3px_rgb(0_0_0/0.18)]" />
      ) : (
        <div role="img" aria-label={alt} className={`flex aspect-[210/297] w-full items-center justify-center rounded-[3px] bg-white shadow-[0_1px_3px_rgb(0_0_0/0.18)] ${failed ? '' : 'shimmer'}`}>
          {failed && <FileText size={18} className="text-muted" aria-hidden />}
        </div>
      )}
    </div>
  )
}
