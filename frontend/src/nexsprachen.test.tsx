// Vorlage nexsprachen 1.0.0
// @vitest-environment jsdom
/**
 * The card "Sprachen" of the module in the app and its i18n helper: built from the ui kit (Card, Chip, Button, Field
 * action), the module's words in German, English and French, the built-in languages in the line and as chips, the
 * operator's files with removing, the template, uploading by code; the operator's languages in the menus, ordered by
 * name, what a file leaves out from English, nothing reaching the prototype. Copied once by
 * bauplaene/sprachen/tools/sync.py to `frontend/src/nexsprachen.test.tsx`; then the app's file. Fill in the places
 * marked APP. Needs react-dom, both in every app.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NexuiLanguage } from './vendor/nexui'
import { LanguagesCard } from './vendor/nexsprachen/LanguagesCard'
import { ownLanguages } from './vendor/nexsprachen/languages'
import { SPRACHEN_TEXTS, hintOf, mergeTexts, type Fetcher, type LanguageEntry, type Texts } from './vendor/nexsprachen/sprachen'

// APP: where the app mounts the routes, its name, the languages it ships (as AppConfig.built_in, in its order) and
// how the line of the card names them in German.
const BASE = '/api/v1/locales'
const APP = 'nexpaper'
const BUILT_IN = [
  { code: 'de', name: 'Deutsch' },
  { code: 'en', name: 'English' },
  { code: 'fr', name: 'Français' },
]
const LINE = 'Deutsch, Englisch und Französisch sind eingebaut.'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Call = { path: string; method: string; body: unknown }

let root: Root
let box: HTMLDivElement
let calls: Call[]
let files: Record<string, { name: string; texts: Texts }>
let refuse: { status: number; body: unknown } | null

function entries(): LanguageEntry[] {
  const own = (code: string) => files[code]
  return [
    ...BUILT_IN.map((entry) => ({ code: entry.code, name: entry.name, keys: own(entry.code) ? 1 : 0, built_in: true, own: Boolean(own(entry.code)) })),
    ...Object.entries(files)
      .filter(([code]) => !BUILT_IN.some((entry) => entry.code === code))
      .map(([code, file]) => ({ code, name: file.name, keys: Object.keys(file.texts).length, built_in: false, own: true })),
  ]
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const fetcher: Fetcher = async (path, init) => {
  calls.push({ path, method: init.method ?? 'GET', body: init.body })
  if (refuse) return json(refuse.body, refuse.status)
  const code = decodeURIComponent(path.slice(BASE.length + 1))
  if (path === BASE) return json(entries())
  if (path === `${BASE}/template`) return new Response('{"_meta": {"name": "x"}}', { status: 200 })
  if (init.method === 'PUT') {
    files[code] = { name: 'Nederlands', texts: { a: 'b' } }
    return json({ code, name: 'Nederlands', keys: 1 })
  }
  if (init.method === 'DELETE') {
    delete files[code]
    return new Response(null, { status: 204 })
  }
  return files[code] ? json(files[code].texts) : json({ detail: { code: 'not_found', message: 'Not found.' } }, 404)
}

async function show(language = 'de', props: Partial<Parameters<typeof LanguagesCard>[0]> = {}): Promise<void> {
  await act(async () =>
    root.render(
      <NexuiLanguage language={language}>
        <LanguagesCard fetcher={fetcher} base={BASE} app={APP} {...props} />
      </NexuiLanguage>,
    ),
  )
  await settle()
}

async function settle(): Promise<void> {
  await act(async () => await new Promise((resolve) => setTimeout(resolve, 0)))
}

const find = <T extends Element = HTMLElement>(selector: string) => box.querySelector<T>(selector)!
const card = () => find('[data-card="languages"]')

async function choose(file: File): Promise<void> {
  const input = find<HTMLInputElement>('[data-testid="language-upload-file"]')
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  await act(async () => {
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await settle()
}

function type(input: HTMLInputElement, value: string): void {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  calls = []
  files = { nl: { name: 'Nederlands', texts: { common: { close: 'Sluiten' } } } }
  refuse = null
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  vi.restoreAllMocks()
})

describe('the card "Sprachen"', () => {
  it('is the card of the plan: Globe, its title, a line naming the built-in languages', async () => {
    await show()
    expect(card().querySelector('h2')?.textContent).toBe('Sprachen')
    expect(card().textContent).toContain(LINE)
    expect(card().textContent).toContain('fehlende Texte fallen auf Englisch zurück')
    expect(calls[0]).toEqual({ path: BASE, method: 'GET', body: undefined })
  })

  it('shows each built-in language as a chip without removing, each file of the operator with it', async () => {
    await show()
    for (const entry of BUILT_IN) {
      const chip = find(`[data-testid="language-built-in-${entry.code}"]`)
      expect(chip.textContent).toBe(`${entry.name} · eingebaut`)
      expect(chip.querySelector('button')).toBeNull()
    }
    const own = find('[data-testid="language-nl"]')
    expect(own.textContent).toBe('Nederlands (nl) · ein Text')
    expect(own.querySelector('button')?.getAttribute('aria-label')).toBe('Nederlands entfernen')
  })

  it('removes a file of the operator and tells the app', async () => {
    const changed = vi.fn()
    await show('de', { onChange: changed })
    await act(async () => find<HTMLButtonElement>('[data-testid="language-nl"] button').click())
    await settle()
    expect(calls.some((call) => call.method === 'DELETE' && call.path === `${BASE}/nl`)).toBe(true)
    expect(box.querySelector('[data-testid="language-nl"]')).toBeNull()
    expect(changed).toHaveBeenCalledTimes(1)
  })

  it('has "Vorlage herunterladen" as a secondary button with Download, made from the app texts when given', async () => {
    const made = vi.fn<(blob: Blob) => string>(() => 'blob:template')
    Object.assign(URL, { createObjectURL: made, revokeObjectURL: vi.fn() })
    await show('de', { template: { common: { close: 'Close' } } })
    const button = find<HTMLButtonElement>('[data-testid="language-template"]')
    expect([button.dataset.kind, button.dataset.icon, button.textContent]).toEqual(['secondary', 'Download', 'Vorlage herunterladen'])
    await act(async () => button.click())
    await settle()
    const written = JSON.parse(await made.mock.calls[0]![0].text())
    expect(written).toEqual({ _meta: { name: 'Name of the language in itself, for example Nederlands' }, common: { close: 'Close' } })
    expect(calls.some((call) => call.path === `${BASE}/template`)).toBe(false)
  })

  it('fetches the template from the server when the app gives no texts', async () => {
    Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:template'), revokeObjectURL: vi.fn() })
    await show()
    await act(async () => find<HTMLButtonElement>('[data-testid="language-template"]').click())
    await settle()
    expect(calls.some((call) => call.path === `${BASE}/template`)).toBe(true)
  })

  it('uploads by language code with the button of the field, only for a code', async () => {
    const changed = vi.fn()
    await show('de', { onChange: changed })
    const field = find('[data-part="field-action"]')
    const upload = find('[data-testid="language-upload"]')
    expect(field.contains(upload)).toBe(true)
    expect([upload.dataset.kind, upload.dataset.icon, upload.textContent]).toEqual(['secondary', 'Upload', 'Sprache hochladen'])
    expect(card().querySelector('label')?.textContent).toBe('Sprachcode')
    const code = find<HTMLInputElement>('[data-testid="language-code"]')
    for (const wrong of ['', 'NL', 'nl_NL', 'nederlands']) {
      type(code, wrong)
      expect(find<HTMLInputElement>('[data-testid="language-upload-file"]').disabled).toBe(true)
    }
    type(code, 'pt-BR')
    expect(find<HTMLInputElement>('[data-testid="language-upload-file"]').disabled).toBe(false)
    await choose(new File(['{"a": "b"}'], 'pt.json', { type: 'application/json' }))
    const put = calls.find((call) => call.method === 'PUT')!
    expect(put.path).toBe(`${BASE}/pt-BR`)
    expect(put.body).toBeInstanceOf(File)
    expect(find('[data-testid="languages-done"]').textContent).toBe(SPRACHEN_TEXTS.de.added)
    expect(changed).toHaveBeenCalledTimes(1)
  })

  it('says why a file is refused, in the words of the module, nexnotes form and nexmail form alike', async () => {
    await show()
    type(find<HTMLInputElement>('[data-testid="language-code"]'), 'nl')
    refuse = { status: 422, body: { detail: { code: 'locale_unusable', message: 'x', reason: 'not_json' } } }
    await choose(new File(['no json'], 'nl.json'))
    expect(find('[data-testid="languages-problem"]').textContent).toBe('Diese Sprachdatei geht nicht: kein gültiges JSON.')
    refuse = { status: 413, body: { detail: 'too_large', werte: { max_kb: 512 } } }
    await choose(new File(['{}'], 'nl.json'))
    expect(find('[data-testid="languages-problem"]').textContent).toBe('Die Datei ist größer als erlaubt (512 KB).')
  })

  it('names one built-in language in the singular', () => {
    const english: LanguageEntry = { code: 'en', name: 'English', keys: 0, built_in: true, own: false }
    expect(hintOf(SPRACHEN_TEXTS.de, [english], 'de')).toMatch(/^Englisch ist eingebaut\. /)
    expect(hintOf(SPRACHEN_TEXTS.en, [english], 'en')).toMatch(/^English is built in\. /)
  })

  it('speaks English and French as well', async () => {
    await show('en')
    expect(card().querySelector('h2')?.textContent).toBe('Languages')
    // APP (nexpaper): the template names German and English here; nexpaper ships French as well.
    expect(card().textContent).toContain('German, English, and French are built in.')
    act(() => root.unmount())
    root = createRoot(box)
    await show('fr')
    expect(card().querySelector('h2')?.textContent).toBe('Langues')
    expect(find('[data-testid="language-upload"]').textContent).toBe('Envoyer la langue')
  })
})

describe('the operator languages in the app i18n', () => {
  it('offers the built-in and the added languages by name, and the added ones only once', async () => {
    files.af = { name: 'Afrikaans', texts: { a: 'b' } }
    const options = await ownLanguages({ base: BASE, fetcher }).options(BUILT_IN)
    const expected = [...BUILT_IN, { code: 'af', name: 'Afrikaans' }, { code: 'nl', name: 'Nederlands' }].sort((a, b) => a.name.localeCompare(b.name))
    expect(options.map((option) => option.code)).toEqual(expected.map((entry) => entry.code))
    expect(options.filter((option) => option.added).map((option) => option.code).sort()).toEqual(['af', 'nl'])
  })

  it('asks for the list once and fetches texts only of a file the operator added', async () => {
    const languages = ownLanguages({ base: BASE, fetcher })
    expect(await languages.texts('nl')).toEqual({ common: { close: 'Sluiten' } })
    expect(await languages.texts(BUILT_IN[0]!.code)).toBeNull()
    expect(await languages.texts('NL')).toBeNull()
    expect(calls.filter((call) => call.path === BASE)).toHaveLength(1)
    expect(calls.map((call) => call.path)).toEqual([BASE, `${BASE}/nl`])
    languages.forget()
    await languages.list()
    expect(calls.filter((call) => call.path === BASE)).toHaveLength(2)
  })

  it('lays a file over the built-in texts and an added language over English', async () => {
    files[BUILT_IN[0]!.code] = { name: BUILT_IN[0]!.name, texts: { common: { close: 'Zu' } } }
    const languages = ownLanguages({ base: BASE, fetcher })
    const shipped: Texts = { common: { close: 'Schließen', save: 'Sichern' } }
    const english: Texts = { common: { close: 'Close', save: 'Save' }, nav: { notes: 'Notes' } }
    expect(await languages.merged(BUILT_IN[0]!.code, shipped, english)).toEqual({ common: { close: 'Zu', save: 'Sichern' } })
    expect(await languages.merged('nl', null, english)).toEqual({ common: { close: 'Sluiten', save: 'Save' }, nav: { notes: 'Notes' } })
    expect(await languages.merged('xx', null, english)).toBeNull()
  })

  it('works on when the server does not answer: the built-in languages only', async () => {
    const down: Fetcher = async () => {
      throw new Error('down')
    }
    const languages = ownLanguages({ base: BASE, fetcher: down })
    expect((await languages.options(BUILT_IN)).map((option) => option.added)).toEqual(BUILT_IN.map(() => false))
    expect(await languages.knows('nl', BUILT_IN)).toBe(false)
    expect(await languages.knows(BUILT_IN[0]!.code, BUILT_IN)).toBe(true)
  })

  it('never lets a file reach the prototype of the page', () => {
    const hostile = JSON.parse('{"__proto__": {"polluted": "yes"}, "constructor": {"prototype": {"polluted": "yes"}}, "a": "b"}') as Texts
    const merged = mergeTexts({ a: 'x', c: 'd' }, hostile)
    expect(merged).toEqual({ a: 'b', c: 'd' })
    expect(({} as Record<string, unknown>).polluted).toBeUndefined()
  })
})
