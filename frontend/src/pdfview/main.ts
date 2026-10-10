/**
 * The PDF frame: pdf.js draws the pages here, with their text (to select, copy and find), the pictures of the pages
 * and the PDF's own contents on the left. The frame has no origin of its own and may fetch nothing (its policy says
 * `connect-src 'none'`): the PDF and every file pdf.js asks for come from the page by message (`lib/pdfFrame.ts`).
 * Messages count only from the page that holds the frame; links of the PDF go to the page, which opens web addresses
 * in a tab of their own.
 */
import 'pdfjs-dist/web/pdf_viewer.css'
import './pdfview.css'

import * as pdfjs from 'pdfjs-dist'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import workerSource from 'pdfjs-dist/build/pdf.worker.min.mjs?raw'
import { EventBus, PDFFindController, PDFLinkService, PDFViewer } from 'pdfjs-dist/web/pdf_viewer.mjs'

import { classicWorker, DATA_FOLDERS, fromParent, plainName, type Colours, type DataKind, type FrameTexts, type FromFrame, type ToFrame } from '../lib/pdfFrame'

const box = document.getElementById('box') as HTMLDivElement
const viewerDiv = document.getElementById('viewer') as HTMLDivElement
const side = document.getElementById('side') as HTMLElement
const tabs = document.getElementById('tabs') as HTMLDivElement
const thumbs = document.getElementById('thumbs') as HTMLDivElement
const outlineBox = document.getElementById('outline') as HTMLDivElement
const said = document.getElementById('said') as HTMLParagraphElement

function tell(message: FromFrame): void {
  // The page's origin is not known here (this frame has none); what is said is only about the PDF on show.
  window.parent.postMessage(message, '*')
}

const workerUrl = URL.createObjectURL(new Blob([classicWorker(workerSource)], { type: 'text/javascript' }))
pdfjs.GlobalWorkerOptions.workerPort = new Worker(workerUrl)

// Files pdf.js asks for (character maps, the 14 standard fonts, decoders) come from the page, by name only.
let nextAsk = 1
const waiting = new Map<number, (bytes: ArrayBuffer | null) => void>()

class FromPage {
  constructor(_options: unknown) {}

  async fetch({ kind, filename }: { kind: DataKind; filename: string }): Promise<Uint8Array> {
    if (!(kind in DATA_FOLDERS) || !plainName(filename)) throw new Error('not asked for')
    const id = nextAsk++
    const bytes = await new Promise<ArrayBuffer | null>((resolve) => {
      waiting.set(id, resolve)
      tell({ type: 'data', id, kind, name: filename })
    })
    if (!bytes) throw new Error('not there')
    return new Uint8Array(bytes)
  }
}

// pdf.js would fetch its words from the server; the frame shows almost none of its own, and fetches nothing.
const quiet = {
  getLanguage: () => document.documentElement.lang || 'en',
  getDirection: () => 'ltr',
  get: async (_ids: unknown, _args: unknown, fallback?: string) => fallback ?? '',
  translate: async () => {},
  translateOnce: async () => {},
  pause: () => {},
  resume: () => {},
  destroy: async () => {},
}

const eventBus = new EventBus()
const linkService = new PDFLinkService({ eventBus })
const findController = new PDFFindController({ eventBus, linkService })
const viewer = new PDFViewer({
  container: box,
  viewer: viewerDiv,
  eventBus,
  linkService,
  findController,
  // Forms are shown as they are filled, never filled in here; nothing the PDF says runs as a script.
  annotationMode: pdfjs.AnnotationMode.ENABLE,
  l10n: quiet as never,
  removePageBorders: false,
})
linkService.setViewer(viewer)

let texts: FrameTexts | null = null
let documentShown: PDFDocumentProxy | null = null
let compact = false
let firstPage = 1

eventBus.on('pagesinit', () => {
  viewer.currentScaleValue = compact ? 'page-width' : 'page-width'
  if (firstPage > 1) viewer.currentPageNumber = Math.min(firstPage, viewer.pagesCount)
})
eventBus.on('pagechanging', (event: { pageNumber: number }) => {
  tell({ type: 'page', page: event.pageNumber })
  markThumb(event.pageNumber)
})
eventBus.on('scalechanging', (event: { scale: number }) => tell({ type: 'scale', percent: Math.round(event.scale * 100) }))
const found = (event: { matchesCount?: { current: number; total: number } }) => {
  const count = event.matchesCount ?? { current: 0, total: 0 }
  tell({ type: 'found', current: count.current, total: count.total })
}
eventBus.on('updatefindmatchescount', found)
eventBus.on('updatefindcontrolstate', found)

// A link of the PDF: inside it, pdf.js follows it; to the web, the page decides (this frame may open nothing).
box.addEventListener('click', (event) => {
  const link = (event.target as HTMLElement).closest('a')
  if (!link) {
    if (!window.getSelection()?.toString()) tell({ type: 'click' })
    return
  }
  const href = link.getAttribute('href') ?? ''
  if (href && !href.startsWith('#')) {
    event.preventDefault()
    event.stopPropagation()
    tell({ type: 'link', href: link.href })
  }
}, true)

function paint(colours: Colours): void {
  const root = document.documentElement.style
  root.setProperty('--ground', colours.ground)
  root.setProperty('--panel', colours.panel)
  root.setProperty('--text', colours.text)
  root.setProperty('--muted', colours.muted)
  root.setProperty('--accent', colours.accent)
  root.setProperty('--line', colours.line)
}

// --- The pictures of the pages and the contents ---------------------------------------------------------------------

const THUMB_WIDTH = 116
let thumbsDrawn = new Set<number>()
const watcher = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue
    const page = Number((entry.target as HTMLElement).dataset.page)
    if (!thumbsDrawn.has(page)) {
      thumbsDrawn.add(page)
      void drawThumb(page, entry.target as HTMLElement)
    }
  }
}, { root: thumbs, rootMargin: '300px' })

async function drawThumb(number: number, holder: HTMLElement): Promise<void> {
  if (!documentShown) return
  const page = await documentShown.getPage(number)
  const base = page.getViewport({ scale: 1 })
  const scale = THUMB_WIDTH / base.width
  const viewport = page.getViewport({ scale: scale * window.devicePixelRatio })
  const canvas = holder.querySelector('canvas') as HTMLCanvasElement
  canvas.width = Math.floor(viewport.width)
  canvas.height = Math.floor(viewport.height)
  canvas.style.height = `${Math.floor(base.height * scale)}px`
  await page.render({ canvas, viewport }).promise
}

function markThumb(page: number): void {
  for (const each of thumbs.querySelectorAll<HTMLElement>('[data-page]')) {
    const on = Number(each.dataset.page) === page
    each.classList.toggle('on', on)
    if (on) each.setAttribute('aria-current', 'page')
    else each.removeAttribute('aria-current')
  }
  const current = thumbs.querySelector<HTMLElement>(`[data-page="${page}"]`)
  if (current && !side.hidden) current.scrollIntoView({ block: 'nearest' })
}

function buildThumbs(count: number): void {
  thumbs.replaceChildren()
  thumbsDrawn = new Set()
  for (let number = 1; number <= count; number++) {
    const item = document.createElement('button')
    item.type = 'button'
    item.className = 'thumb'
    item.dataset.page = String(number)
    item.setAttribute('aria-label', (texts?.page ?? 'Page {{page}}').replace('{{page}}', String(number)))
    const canvas = document.createElement('canvas')
    canvas.style.width = `${THUMB_WIDTH}px`
    canvas.style.height = `${Math.round(THUMB_WIDTH * 1.414)}px`
    const label = document.createElement('span')
    label.textContent = String(number)
    item.append(canvas, label)
    item.addEventListener('click', () => (viewer.currentPageNumber = number))
    thumbs.append(item)
    watcher.observe(item)
  }
}

type OutlineItem = { title: string; dest: unknown; items: OutlineItem[] }

function buildOutline(items: OutlineItem[] | null): void {
  outlineBox.replaceChildren()
  if (!items || items.length === 0) {
    const none = document.createElement('p')
    none.className = 'none'
    none.textContent = texts?.noContents ?? ''
    outlineBox.append(none)
    return
  }
  const add = (list: OutlineItem[], depth: number) => {
    for (const item of list.slice(0, 500)) {
      const line = document.createElement('button')
      line.type = 'button'
      line.className = 'line'
      line.style.paddingLeft = `${8 + depth * 12}px`
      line.textContent = item.title
      line.addEventListener('click', () => void linkService.goToDestination(item.dest as never))
      outlineBox.append(line)
      if (depth < 4) add(item.items ?? [], depth + 1)
    }
  }
  add(items, 0)
}

function buildTabs(): void {
  tabs.replaceChildren()
  for (const [key, label] of [['pages', texts?.pages ?? 'Pages'], ['contents', texts?.contents ?? 'Contents']] as const) {
    const tab = document.createElement('button')
    tab.type = 'button'
    tab.setAttribute('role', 'tab')
    tab.dataset.tab = key
    tab.textContent = label
    tab.setAttribute('aria-selected', String(key === 'pages'))
    tab.addEventListener('click', () => {
      for (const each of tabs.querySelectorAll('[role="tab"]')) each.setAttribute('aria-selected', String(each === tab))
      thumbs.hidden = key !== 'pages'
      outlineBox.hidden = key !== 'contents'
    })
    tabs.append(tab)
  }
}

// --- What the page says ----------------------------------------------------------------------------------------------

async function open(message: Extract<ToFrame, { type: 'open' }>): Promise<void> {
  texts = message.texts
  compact = message.compact
  firstPage = message.page
  document.body.classList.toggle('compact', compact)
  paint(message.colours)
  side.hidden = !message.sidebar || compact
  buildTabs()
  try {
    const task = pdfjs.getDocument({
      data: new Uint8Array(message.data),
      isEvalSupported: false,
      enableXfa: false,
      // Not the system's fonts: pdf.js would name the standard fonts by an address (`page:/...`) in a FontFace, which the
      // frame's policy refuses; without them it asks for their bytes like any other file (FromPage).
      useSystemFonts: false,
      useWorkerFetch: false,
      // Only a name to hand to FromPage; pdf.js wants them to end in a slash.
      cMapUrl: 'page:/', cMapPacked: true, standardFontDataUrl: 'page:/', wasmUrl: 'page:/',
      BinaryDataFactory: FromPage,
    } as never)
    task.onPassword = () => {
      void task.destroy()
      show(texts?.password ?? '')
      tell({ type: 'failed', reason: 'password' })
    }
    const pdf = await task.promise
    documentShown = pdf
    viewer.setDocument(pdf)
    linkService.setDocument(pdf, null)
    tell({ type: 'loaded', pages: pdf.numPages })
    buildThumbs(pdf.numPages)
    markThumb(firstPage)
    buildOutline((await pdf.getOutline()) as OutlineItem[] | null)
  } catch {
    if (said.hidden) {
      show(texts?.broken ?? '')
      tell({ type: 'failed', reason: 'broken' })
    }
  }
}

function show(text: string): void {
  said.textContent = text
  said.hidden = false
  box.hidden = true
}

window.addEventListener('message', (event: MessageEvent<ToFrame>) => {
  if (!fromParent(event, window.parent)) return
  const message = event.data
  if (!message || typeof message !== 'object') return
  switch (message.type) {
    case 'open':
      if (!documentShown && message.data instanceof ArrayBuffer) void open(message)
      break
    case 'go':
      if (Number.isInteger(message.page) && message.page >= 1) viewer.currentPageNumber = Math.min(message.page, viewer.pagesCount)
      break
    case 'zoom':
      if (message.to === 'in') viewer.increaseScale()
      else if (message.to === 'out') viewer.decreaseScale()
      else viewer.currentScaleValue = 'page-width'
      break
    case 'find':
      eventBus.dispatch('find', {
        source: null, type: message.again ? 'again' : '', query: String(message.query).slice(0, 500),
        caseSensitive: false, entireWord: false, highlightAll: true, findPrevious: !!message.previous, matchDiacritics: false,
      })
      break
    case 'sidebar':
      side.hidden = !message.show || compact
      break
    case 'colours':
      paint(message.colours)
      break
    case 'data': {
      const resolve = waiting.get(message.id)
      if (resolve) {
        waiting.delete(message.id)
        resolve(message.bytes instanceof ArrayBuffer ? message.bytes : null)
      }
      break
    }
  }
})

window.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
    event.preventDefault()
    tell({ type: 'findKey' })
  }
})

tell({ type: 'ready' })
