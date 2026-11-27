// Vorlage nexwasneu 0.1.1
// @vitest-environment jsdom
/**
 * "What's new" in the app: after an update the banner stands under the head; "Was ist neu?" shows the texts since the
 * account's version, the newest first, "Verstanden" and the button beside the banner put them away (once, without
 * waiting for the server); more versions than the window shows come with "Frühere Versionen". On "About" the row opens
 * the newest text and the earlier ones, and puts nothing away (W5 to W7, W18, W19). The page asks in its language.
 * Copied once by bauplaene/wasneu/tools/sync.py to `frontend/src/nexwasneu.test.tsx`; then the app's file. Fill in the
 * places marked APP.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AboutPage, NexuiLanguage } from './vendor/nexui'
import { WhatsNewAfterUpdate } from './vendor/nexwasneu/WhatsNew'
import { useAboutWhatsNew } from './vendor/nexwasneu/useWhatsNew'
import type { Fetcher, WhatsNewAnswer, WhatsNewItem } from './vendor/nexwasneu/wasneu'

// APP: where the app mounts the routes (nexpaper '/api/v1/whats-new') and its name.
const BASE = '/api/v1/whats-new'
const APP = 'nexpaper'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root
let box: HTMLDivElement
let calls: { path: string; method: string }[]
let answer: WhatsNewAnswer
let failing: boolean
let raw: string | null
let rawHistory: string | null

const item = (version: string, operator = false): WhatsNewItem => ({
  version,
  language: 'de',
  lead: `Neu in ${version}.`,
  sections: [
    { title: `Teil ${version}`, where: 'Einstellungen › Über', body: `Text ${version}.`, link: null, operator: false },
    ...(operator ? [{ title: `Betrieb ${version}`, where: 'Server', body: 'Nichts zu tun.', link: null, operator: true }] : []),
  ],
  smallTitle: 'Außerdem',
  small: [`Klein ${version}`],
})
const HISTORY = ['1.4.0', '1.3.0', '1.2.0', '1.1.0', '1.0.0', '0.9.0', '0.8.0'].map((version) => item(version))

const fetcher: Fetcher = async (path, init) => {
  const method = init.method ?? 'GET'
  calls.push({ path, method })
  if (failing) return new Response('{}', { status: 500 })
  if (method === 'POST' && path === `${BASE}/seen`) {
    answer = { ...answer, seen: answer.version, unread: [] }
    return new Response(JSON.stringify({ seen: answer.version }), { status: 200 })
  }
  if (path.startsWith(`${BASE}/history`)) return new Response(rawHistory ?? JSON.stringify({ version: answer.version, entries: HISTORY }), { status: 200 })
  if (path.startsWith(BASE)) return new Response(raw ?? JSON.stringify(answer), { status: 200 })
  return new Response('{}', { status: 404 })
}

function About() {
  const news = useAboutWhatsNew({ app: APP, logo: '/logo.svg', fetcher, base: BASE, language: 'de' })
  return (
    <>
      <AboutPage
        app={APP}
        logo="/logo.svg"
        tagline="tagline"
        version={answer.version}
        licence={{ name: 'AGPL-3.0', href: 'https://www.gnu.org/licenses/agpl-3.0.html' }}
        source="https://github.com/example/nexapp"
        showUpdates={false}
        builtWith={[]}
        {...news.about}
      />
      {news.window}
    </>
  )
}

async function settle(): Promise<void> {
  await act(async () => await new Promise((resolve) => setTimeout(resolve, 0)))
}

async function shell(language = 'de'): Promise<void> {
  await act(async () =>
    root.render(
      <NexuiLanguage language={language}>
        <WhatsNewAfterUpdate app={APP} logo="/logo.svg" fetcher={fetcher} base={BASE} language={language} />
      </NexuiLanguage>,
    ),
  )
  await settle()
}

async function about(): Promise<void> {
  await act(async () => root.render(<NexuiLanguage language="de"><About /></NexuiLanguage>))
  await settle()
}

async function fresh(): Promise<void> {
  act(() => root.unmount())
  root = createRoot(box)
}

// Answers of another form (W25): an old server, a test double, the page of a proxy. Nothing to show, nothing thrown.
const OTHER_FORMS = [
  '[]',
  '{}',
  'null',
  '"1.4.0"',
  '<!doctype html><title>nexapp</title>',
  JSON.stringify({ version: '1.4.0', unread: 'all' }),
  JSON.stringify({ version: 140, unread: [] }),
  JSON.stringify({ version: '1.4.0', seen: '1.2.0', unread: [{ version: '1.4.0' }, 7, null, []], more: false, current: { version: '1.4.0' }, earlier: true }),
]

async function click(element: Element | null | undefined): Promise<void> {
  expect(element).toBeTruthy()
  await act(async () => (element as HTMLElement).click())
  await settle()
}

const banner = () => document.querySelector('[data-testid="whats-new-banner"]')
const win = () => document.querySelector<HTMLElement>('[data-testid="whats-new-window"]')
const button = (inside: Element | null, name: string) =>
  Array.from(inside?.querySelectorAll('button') ?? []).find((found) => found.textContent?.trim() === name || found.getAttribute('aria-label') === name)
const seenCalls = () => calls.filter((call) => call.method === 'POST')

beforeEach(() => {
  calls = []
  failing = false
  raw = null
  rawHistory = null
  answer = { version: '1.4.0', seen: '1.2.0', unread: [item('1.4.0', true), item('1.3.0')], more: false, current: item('1.4.0', true), earlier: true }
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
})

describe("what's new after an update", () => {
  it('shows the banner, opens the texts since the version read and puts them away once', async () => {
    await shell()
    expect(calls[0]).toEqual({ path: `${BASE}?language=de`, method: 'GET' })
    expect(banner()?.textContent).toContain(`${APP} 1.4.0 ist da.`)
    await click(button(banner(), 'Was ist neu?'))
    const shown = win()!
    expect(shown.getAttribute('role')).toBe('dialog')
    expect(shown.getAttribute('aria-label') ?? shown.textContent).toContain(`Neu in ${APP} seit deinem letzten Besuch`)
    expect(Array.from(shown.querySelectorAll<HTMLElement>('section[data-version]')).map((part) => part.dataset.version)).toEqual(['1.4.0', '1.3.0'])
    expect(shown.querySelector('[data-operator="true"]')?.textContent).toContain('Für Betreiber')
    expect(button(shown, 'Frühere Versionen')).toBeUndefined()
    expect(seenCalls()).toHaveLength(0)
    await click(button(shown, 'Verstanden'))
    expect(win()).toBeNull()
    expect(banner()).toBeNull()
    expect(seenCalls()).toEqual([{ path: `${BASE}/seen`, method: 'POST' }])
  })

  it('goes with the button beside it, without opening anything', async () => {
    await shell()
    await click(button(banner(), 'Ausblenden'))
    expect(banner()).toBeNull()
    expect(win()).toBeNull()
    expect(seenCalls()).toHaveLength(1)
  })

  it('goes at once even when the server does not take the note', async () => {
    await shell()
    failing = true
    await click(button(banner(), 'Ausblenden'))
    expect(banner()).toBeNull()
  })

  it('stands not while nothing is unread, nor when the server does not answer', async () => {
    answer = { ...answer, seen: '1.4.0', unread: [] }
    await shell()
    expect(banner()).toBeNull()
    failing = true
    await shell('en')
    expect(banner()).toBeNull()
  })

  it('a single text has the title of its version; more than the window shows come with the earlier versions', async () => {
    answer = { ...answer, unread: [item('1.4.0')] }
    await shell()
    await click(button(banner(), 'Was ist neu?'))
    expect(win()?.textContent).toContain(`Neu in ${APP} 1.4.0`)
    act(() => root.unmount())
    root = createRoot(box)
    answer = { ...answer, unread: HISTORY.slice(0, 5), more: true }
    await shell()
    await click(button(banner(), 'Was ist neu?'))
    await click(button(win(), 'Frühere Versionen'))
    expect(calls.some((call) => call.path === `${BASE}/history?language=de`)).toBe(true)
    expect(win()?.querySelectorAll('section[data-version]')).toHaveLength(HISTORY.length)
    expect(win()?.textContent).toContain(`Was ist neu in ${APP}`)
  })

  it('shows nothing and does not fail when the answer has another form', async () => {
    for (const body of OTHER_FORMS) {
      await fresh()
      raw = body
      await shell()
      expect(banner(), body).toBeNull()
    }
  })

  it('leaves out a text of another form and shows the others', async () => {
    const broken = { ...item('1.3.0'), sections: [{ title: 'Teil', where: 'Über', body: 'Text', link: 'https://example.com' }] }
    raw = JSON.stringify({ ...answer, unread: [item('1.4.0'), broken, { ...item('1.2.0'), small: 'Klein' }, item('1.1.0')] })
    await shell()
    await click(button(banner(), 'Was ist neu?'))
    expect(Array.from(win()?.querySelectorAll<HTMLElement>('section[data-version]') ?? []).map((part) => part.dataset.version)).toEqual(['1.4.0', '1.1.0'])
  })

  it('speaks the language of the page', async () => {
    await shell('en')
    expect(calls[0]?.path).toBe(`${BASE}?language=en`)
    expect(banner()?.textContent).toContain(`${APP} 1.4.0 is here.`)
  })
})

describe("what's new on About", () => {
  it('opens the newest text and the earlier versions, and puts nothing away', async () => {
    await about()
    await click(document.querySelector('[data-testid="about-whats-new"]'))
    expect(win()?.textContent).toContain(`Neu in ${APP} 1.4.0`)
    await click(button(win(), 'Frühere Versionen'))
    expect(win()?.querySelectorAll('section[data-version]')).toHaveLength(HISTORY.length)
    await click(button(win(), 'Verstanden'))
    expect(win()).toBeNull()
    expect(seenCalls()).toHaveLength(0)
  })

  it('names the version of the text after a fix without its own', async () => {
    answer = { ...answer, version: '1.4.1', unread: [] }
    await about()
    expect(document.querySelector('[data-testid="about-whats-new"]')?.textContent).toBe(`Neu in ${APP} 1.4.0`)
  })

  it('has no row and does not fail when the answer has another form', async () => {
    for (const body of OTHER_FORMS) {
      await fresh()
      raw = body
      await about()
      expect(document.querySelector('[data-testid="about-whats-new"]'), body).toBeNull()
    }
  })

  it('keeps the newest text when the history has another form', async () => {
    for (const body of ['[]', '{}', JSON.stringify({ version: '1.4.0', entries: [7, { version: '1.3.0' }] })]) {
      await fresh()
      rawHistory = body
      await about()
      await click(document.querySelector('[data-testid="about-whats-new"]'))
      await click(button(win(), 'Frühere Versionen'))
      expect(win()?.textContent, body).toContain('Text 1.4.0.')
    }
  })

  it('has no row while there is no text at all', async () => {
    answer = { ...answer, unread: [], current: null, earlier: false }
    await about()
    expect(document.querySelector('[data-testid="about-whats-new"]')).toBeNull()
  })
})
