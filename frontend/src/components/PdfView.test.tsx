/**
 * The frame pdf.js draws in: a sandbox for scripts only (no origin of its own: no cookie, no API), messages counted only
 * from that very frame, links of a PDF opened only when they are the web or mail and then without telling the page
 * where they came from; and inside the frame, messages counted only from the page that holds it.
 */
import { act } from 'react'

import mainSource from '../pdfview/main.ts?raw'
import { fromParent } from '../lib/pdfFrame'
import { Page } from '../test/harness'
import { idle } from '../test/wait'
import { PdfView } from './PdfView'

const page = new Page()
let fetched = vi.fn()

beforeEach(() => {
  fetched = vi.fn(async () => new Response(new Uint8Array([37, 80, 68, 70]), { status: 200 }))
  vi.stubGlobal('fetch', fetched)
})
afterEach(() => {
  page.close()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function show(): Promise<HTMLIFrameElement> {
  await page.show(<PdfView url="/api/v1/documents/7/versions/1/archive" page={1} title="Steuerbescheid" />)
  return page.box.querySelector<HTMLIFrameElement>('iframe')!
}

function say(source: MessageEventSource | null, data: unknown): Promise<void> {
  return act(async () => {
    window.dispatchEvent(new MessageEvent('message', { data, source }))
  })
}

describe('the PDF frame', () => {
  it('is a sandbox for scripts and nothing else: no origin of its own, no forms, no popups', async () => {
    const frame = await show()
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts')
    expect(frame.getAttribute('src')).toBe('/pdfview.html')
  })

  it('opens a link of the PDF only from that frame, only to the web or mail, and without a way back', async () => {
    const opened = vi.spyOn(window, 'open').mockImplementation(() => null)
    const frame = await show()
    await say(window, { type: 'link', href: 'https://example.com/a' })
    await say(null, { type: 'link', href: 'https://example.com/b' })
    expect(opened).not.toHaveBeenCalled()
    await say(frame.contentWindow, { type: 'link', href: 'javascript:alert(1)' })
    await say(frame.contentWindow, { type: 'link', href: 'file:///etc/passwd' })
    expect(opened).not.toHaveBeenCalled()
    await say(frame.contentWindow, { type: 'link', href: 'https://example.com/c' })
    expect(opened).toHaveBeenCalledTimes(1)
    expect(opened).toHaveBeenCalledWith('https://example.com/c', '_blank', 'noopener,noreferrer')
  })

  it('fetches nothing for a message of another window', async () => {
    const frame = await show()
    await idle()
    const asked = fetched.mock.calls.length
    await say(window, { type: 'data', id: 1, kind: 'cMapUrl', name: 'Adobe-Japan1-0.bcmap' })
    await idle()
    expect(fetched.mock.calls.length).toBe(asked)
    await say(frame.contentWindow, { type: 'data', id: 2, kind: 'cMapUrl', name: '../../api/v1/auth/me' })
    await idle()
    expect(fetched.mock.calls.length).toBe(asked)
    await say(frame.contentWindow, { type: 'data', id: 3, kind: 'cMapUrl', name: 'Adobe-Japan1-0.bcmap' })
    await idle()
    expect(fetched.mock.calls.at(-1)![0]).toBe('/pdfjs/cmaps/Adobe-Japan1-0.bcmap')
  })
})

describe('inside the frame', () => {
  it('counts only messages of the page that holds it', () => {
    const parent = {} as Window
    expect(fromParent({ source: parent }, parent)).toBe(true)
    expect(fromParent({ source: {} as Window }, parent)).toBe(false)
    expect(fromParent({ source: null }, parent)).toBe(false)
    expect(fromParent({ source: null }, null)).toBe(false)
  })

  it('asks that before it reads any message', () => {
    const listener = mainSource.slice(mainSource.indexOf("window.addEventListener('message'"))
    expect(listener.split('\n')[1].trim()).toBe('if (!fromParent(event, window.parent)) return')
  })
})
