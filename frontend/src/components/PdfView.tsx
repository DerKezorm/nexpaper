/**
 * A PDF with pdf.js, as in nexlore: the pages are drawn in a frame of their own (`/pdfview.html`: no origin, no network,
 * its own policy from the server), the page fetches the PDF with the person's session and hands the bytes over, and the
 * few files pdf.js asks for (character maps, fonts, decoders) by name only. A PDF can carry code (fonts, forms); what
 * pdf.js does with it stays in the frame, away from the session and the API. The text can be selected and found there.
 *
 * `page` turns the view to a page; `onPage` says which page is in view; `onLoaded` says how many pages there are (until
 * then the document page shows the picture of the page from the server, which is quicker).
 */
import { Minus, Plus, Scan, Search, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { DATA_FOLDERS, openable, plainName, type Colours, type FromFrame, type ToFrame } from '../lib/pdfFrame'

function colours(): Colours {
  const style = getComputedStyle(document.documentElement)
  const take = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    ground: take('--sheet-2', '#f1ebe1'),
    panel: take('--sheet', '#fffdf9'),
    text: take('--ink', '#2e2720'),
    muted: take('--muted', '#7f7264'),
    accent: take('--accent', '#9a6a3a'),
    line: take('--line', '#e4dacb'),
  }
}

type Props = {
  /** Where the PDF is fetched from (with the session). */
  url: string
  page: number
  onPage?: (page: number) => void
  onLoaded?: (pages: number) => void
  onFailed?: (reason: 'password' | 'broken' | 'load') => void
  /** A click on a page (no link, no text chosen). */
  onClick?: () => void
  title: string
}

export function PdfView({ url, page, onPage, onLoaded, onFailed, onClick, title }: Props) {
  const { t } = useTranslation()
  const frame = useRef<HTMLIFrameElement>(null)
  const bytes = useRef<Promise<ArrayBuffer> | null>(null)
  const [pages, setPages] = useState(0)
  const [percent, setPercent] = useState(0)
  const [finding, setFinding] = useState(false)
  const [query, setQuery] = useState('')
  const [found, setFound] = useState({ current: 0, total: 0 })
  const shownPage = useRef(page)
  const callbacks = useRef({ onPage, onLoaded, onFailed, onClick })
  callbacks.current = { onPage, onLoaded, onFailed, onClick }

  const say = useCallback((message: ToFrame, transfer: Transferable[] = []) => {
    // The frame has no origin of its own, so no other target than "*" reaches it; only this frame is spoken to.
    frame.current?.contentWindow?.postMessage(message, '*', transfer)
  }, [])

  useEffect(() => {
    setPages(0)
    bytes.current = fetch(url, { credentials: 'same-origin' }).then((response) => {
      if (!response.ok) throw new Error(String(response.status))
      return response.arrayBuffer()
    })
    bytes.current.catch(() => callbacks.current.onFailed?.('load'))
  }, [url])

  useEffect(() => {
    const listen = (event: MessageEvent<FromFrame>) => {
      if (!frame.current || event.source !== frame.current.contentWindow) return
      const message = event.data
      if (!message || typeof message !== 'object') return
      switch (message.type) {
        case 'ready':
          void bytes.current?.then(
            (data) => {
              const copy = data.slice(0)
              say(
                {
                  type: 'open', data: copy, page: shownPage.current, colours: colours(), sidebar: false, compact: true,
                  texts: { pages: t('docs.pdf.pages'), contents: t('docs.pdf.contents'), noContents: t('docs.pdf.noContents'), password: t('docs.pdf.password'), broken: t('docs.pdf.broken'), page: t('docs.pdf.page') },
                },
                [copy],
              )
            },
            () => undefined,
          )
          break
        case 'click':
          callbacks.current.onClick?.()
          break
        case 'loaded':
          setPages(message.pages)
          callbacks.current.onLoaded?.(message.pages)
          break
        case 'page':
          shownPage.current = message.page
          callbacks.current.onPage?.(message.page)
          break
        case 'scale':
          setPercent(message.percent)
          break
        case 'found':
          setFound({ current: message.current, total: message.total })
          break
        case 'link':
          if (openable(message.href)) window.open(message.href, '_blank', 'noopener,noreferrer')
          break
        case 'failed':
          callbacks.current.onFailed?.(message.reason)
          break
        case 'findKey':
          setFinding(true)
          break
        case 'data': {
          const folder = DATA_FOLDERS[message.kind]
          if (!folder || !plainName(message.name)) {
            say({ type: 'data', id: message.id, bytes: null })
            break
          }
          fetch(`/pdfjs/${folder}/${message.name}`).then(
            async (response) => {
              const data = response.ok ? await response.arrayBuffer() : null
              say({ type: 'data', id: message.id, bytes: data }, data ? [data] : [])
            },
            () => say({ type: 'data', id: message.id, bytes: null }),
          )
          break
        }
      }
    }
    window.addEventListener('message', listen)
    return () => window.removeEventListener('message', listen)
  }, [say, t, url])

  // A page asked for from outside (a picture of a page clicked): the frame turns to it.
  useEffect(() => {
    if (pages > 0 && page !== shownPage.current) {
      shownPage.current = page
      say({ type: 'go', page })
    }
  }, [page, pages, say])

  // Light or dark changed: the frame follows.
  useEffect(() => {
    const watcher = new MutationObserver(() => say({ type: 'colours', colours: colours() }))
    watcher.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => watcher.disconnect()
  }, [say])

  const find = (previous: boolean, again: boolean) => query.trim() && say({ type: 'find', query: query.trim(), previous, again })
  const tool = 'inline-grid h-8 w-8 place-items-center rounded-full text-ink-2 hover:bg-sheet-2 disabled:opacity-40'
  const ready = pages > 0
  return (
    <div className="relative h-full w-full" data-testid="pdf-view" data-pages={pages}>
      <iframe ref={frame} key={url} src="/pdfview.html" sandbox="allow-scripts" title={t('docs.pdf.frame', { title })} className="absolute inset-0 h-full w-full rounded-[3px] border-0" data-testid="pdf-frame" />
      <div className="absolute top-2 right-2 flex items-center gap-0.5 rounded-full border border-line bg-sheet/95 p-0.5 shadow-soft" role="toolbar" aria-label={t('docs.pdf.tools')}>
        {finding ? (
          <>
            <Search size={14} className="ml-2 text-muted" aria-hidden />
            <input
              autoFocus
              value={query}
              aria-label={t('docs.pdf.find')}
              placeholder={t('docs.pdf.find')}
              onChange={(event) => {
                setQuery(event.target.value)
                if (event.target.value.trim()) say({ type: 'find', query: event.target.value.trim(), previous: false, again: false })
                else setFound({ current: 0, total: 0 })
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') find(event.shiftKey, true)
                if (event.key === 'Escape') setFinding(false)
              }}
              className="h-7 w-32 bg-transparent px-1 text-sm outline-none"
            />
            <span className="px-1 text-xs text-muted tabular-nums" role="status">
              {query.trim() ? t('docs.pdf.found', { current: found.current, total: found.total }) : ''}
            </span>
            <button type="button" className={tool} onClick={() => setFinding(false)} aria-label={t('common.close')}>
              <X size={14} aria-hidden />
            </button>
          </>
        ) : (
          <>
            <button type="button" className={tool} onClick={() => say({ type: 'zoom', to: 'out' })} disabled={!ready} aria-label={t('docs.pdf.zoomOut')} title={t('docs.pdf.zoomOut')}>
              <Minus size={14} aria-hidden />
            </button>
            <span className="w-10 text-center text-xs text-muted tabular-nums">{percent ? `${percent} %` : ''}</span>
            <button type="button" className={tool} onClick={() => say({ type: 'zoom', to: 'in' })} disabled={!ready} aria-label={t('docs.pdf.zoomIn')} title={t('docs.pdf.zoomIn')}>
              <Plus size={14} aria-hidden />
            </button>
            <button type="button" className={tool} onClick={() => say({ type: 'zoom', to: 'width' })} disabled={!ready} aria-label={t('docs.pdf.fit')} title={t('docs.pdf.fit')}>
              <Scan size={14} aria-hidden />
            </button>
            <button type="button" className={tool} onClick={() => setFinding(true)} disabled={!ready} aria-label={t('docs.pdf.find')} title={t('docs.pdf.find')}>
              <Search size={14} aria-hidden />
            </button>
          </>
        )}
      </div>
    </div>
  )
}
