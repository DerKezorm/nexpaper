// @vitest-environment jsdom
/**
 * The card "Log" of the module in the app: built from the ui kit (Segment, Table, Button, ConfirmDialog), the module's
 * words in German, English and French, the filters, the pages, the level of detail and clearing as the plan says.
 * Copied once by bauplaene/log/tools/sync.py to `frontend/src/nexlog.test.tsx`; then the app's file. Fill in the places
 * marked APP. Needs react-dom and @testing-library/dom, both in every app.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { NexuiLanguage } from './vendor/nexui'
import { LogCard } from './vendor/nexlog/LogCard'
import { LOG_TEXTS, type LogLine, type LogMode, type LogRequest } from './vendor/nexlog/log'

// APP: where the app mounts the routes (nexpaper '/api/v1/logs'), and its word for what it keeps (German).
const BASE = '/api/logs'
const THINGS = 'Notizen'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Call = { path: string; method: string; query: Record<string, string | number | undefined>; body: unknown }

let root: Root
let box: HTMLDivElement
let calls: Call[]
let mode: LogMode
let failing: boolean

function line(number: number, level = 'INFO'): LogLine {
  return {
    time: '2026-11-21 09:00:00',
    level,
    logger: 'nexapp.notes',
    message: `line ${number}`,
    request_id: number === 1 ? 'a1b2c3' : null,
    user: number === 1 ? 'anna' : null,
    at: '2026-11-21T09:00:00+00:00',
  }
}

const ALL = [line(1, 'ERROR'), line(2, 'WARNING'), ...Array.from({ length: 248 }, (_, index) => line(index + 3))]

const request: LogRequest = async <T,>(path: string, init: { method?: string; query?: Record<string, string | number | undefined>; body?: unknown } = {}) => {
  calls.push({ path, method: init.method ?? 'GET', query: init.query ?? {}, body: init.body })
  if (failing) throw new Error('down')
  if (path === `${BASE}/level` && init.method === 'PUT') {
    const wanted = (init.body as { mode: string }).mode
    mode = { ...mode, mode: wanted, until: wanted === 'detailed' || wanted === 'trace' ? '2026-11-21T10:00:00+00:00' : null }
    return mode as T
  }
  if (path === `${BASE}/level`) return mode as T
  if (path === BASE && init.method === 'DELETE') return undefined as T
  const offset = Number(init.query?.offset ?? 0)
  return ALL.slice(offset, offset + Number(init.query?.limit)) as T
}

function show(language = 'de'): void {
  act(() =>
    root.render(
      <NexuiLanguage language={language}>
        <LogCard request={request} base={BASE} things={THINGS} />
      </NexuiLanguage>,
    ),
  )
}

async function wait(ms = 320): Promise<void> {
  await act(async () => await new Promise((resolve) => setTimeout(resolve, ms)))
}

function type(input: HTMLInputElement, value: string): void {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const find = <T extends Element = HTMLElement>(selector: string) => box.querySelector<T>(selector)!
const last = (path: string) => calls.filter((call) => call.path === path).at(-1)!

beforeEach(() => {
  calls = []
  failing = false
  mode = { mode: 'normal', until: null, fixed_by_env: false, variable: 'NEXAPP_LOG_LEVEL', modes: ['quiet', 'normal', 'detailed', 'trace'], durations: [30, 60, 120, 480] }
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
})

describe('the card Log', () => {
  it('is the card "Log" with its hint, the levels as a segment, the search, the level of detail and two buttons', async () => {
    show()
    await wait()
    const card = find('[data-card="log"]')
    expect(card.querySelector('h2')!.textContent).toBe('Log')
    expect(card.textContent).toContain(`Nie Inhalte von ${THINGS}, Passwörter oder Schlüssel.`)
    const levels = find('[data-testid="log-levels"]')
    expect(levels.getAttribute('role')).toBe('radiogroup')
    expect([...levels.querySelectorAll('[role="radio"]')].map((item) => item.textContent)).toEqual(['Alle', 'INFO', 'WARNING', 'ERROR'])
    expect(card.textContent).toContain('Ein Filter zeigt immer auch die höheren Stufen')
    expect(find<HTMLInputElement>('[data-testid="log-search"]').placeholder).toBe('Im Text suchen …')
    const download = find('[data-testid="log-download"]')
    expect([download.getAttribute('data-kind'), download.getAttribute('data-icon'), download.getAttribute('href')]).toEqual(['secondary', 'Download', `${BASE}/download`])
    expect(download.textContent).toBe('Herunterladen')
    const refresh = find('[data-testid="log-refresh"]')
    expect([refresh.getAttribute('data-kind'), refresh.getAttribute('data-size'), refresh.getAttribute('data-icon'), refresh.textContent]).toEqual([
      'secondary',
      'md',
      'RefreshCw',
      'Aktualisieren',
    ])
    const buttons = [...find('[data-testid="log-bar"]').querySelectorAll('[data-kind]')].map((button) => button.getAttribute('data-testid'))
    expect(buttons).toEqual(['log-refresh', 'log-download', 'log-clear'])
    const clear = find('[data-testid="log-clear"]')
    expect([clear.getAttribute('data-kind'), clear.getAttribute('data-icon'), clear.textContent]).toEqual(['danger', 'Trash2', 'Protokoll leeren'])
    const detail = find<HTMLSelectElement>('[data-testid="log-mode"]')
    expect([...detail.options].map((option) => option.textContent)).toEqual(['Ruhig', 'Normal', 'Ausführlich (1 Stunde)', 'Alles (1 Stunde)'])
  })

  it('is a table of time, level, source, request and account, message, newest first; WARNING and ERROR stand out', async () => {
    show()
    await wait()
    const table = find('[data-testid="log-table"] table')
    expect([...table.querySelectorAll('th')].map((cell) => cell.textContent)).toEqual(['Zeit', 'Stufe', 'Quelle', 'Anfrage / Konto', 'Meldung'])
    const rows = [...table.querySelectorAll<HTMLElement>('tr[data-testid="log-row"]')]
    expect(rows).toHaveLength(200)
    expect(rows[0]!.dataset.level).toBe('ERROR')
    expect(rows[0]!.textContent).toContain('a1b2c3')
    expect(rows[0]!.textContent).toContain('anna')
    // The level is a Badge: ERROR danger, WARNING warn, INFO and DEBUG off.
    const tone = (row: HTMLElement) => row.querySelector('[data-testid="log-level"]')!.getAttribute('data-tone')
    expect([tone(rows[0]!), tone(rows[1]!), tone(rows[2]!)]).toEqual(['danger', 'warn', 'off'])
    // A phone: the same lines as cards, nothing to scroll sideways.
    expect(box.querySelectorAll('[data-part="table-card"]')).toHaveLength(200)
    expect(box.querySelector('.overflow-x-auto, .overflow-auto')).toBeNull()
  })

  it('filters by level and text, shows one request on a click, loads older lines page by page', async () => {
    show()
    await wait()
    await act(async () => find<HTMLButtonElement>('[data-testid="log-level-WARNING"]').click())
    await wait()
    expect(last(BASE).query.level).toBe('WARNING')
    expect(find('[data-testid="log-level-WARNING"]').getAttribute('aria-checked')).toBe('true')
    const search = find<HTMLInputElement>('[data-testid="log-search"]')
    type(search, 'line 7')
    await wait()
    expect(last(BASE).query.search).toBe('line 7')
    await act(async () => find<HTMLButtonElement>('[data-testid="log-level-all"]').click())
    type(search, '')
    await wait()
    expect(last(BASE).query).toMatchObject({ level: undefined, search: undefined, limit: 200, offset: 0 })
    await act(async () => find<HTMLButtonElement>('[data-testid="log-request"]').click())
    await wait()
    expect(search.value).toBe('a1b2c3')
    expect(last(BASE).query.search).toBe('a1b2c3')
    type(search, '')
    await wait()
    const more = find('[data-testid="log-more"]')
    expect([more.getAttribute('data-kind'), more.textContent]).toEqual(['secondary', 'Ältere laden'])
    await act(async () => (more as HTMLButtonElement).click())
    await wait(20)
    expect(last(BASE).query.offset).toBe(200)
    expect(box.querySelectorAll('tr[data-testid="log-row"]')).toHaveLength(250)
    expect(box.querySelector('[data-testid="log-more"]')).toBeNull()
  })

  it('switches a deep level on for an hour and says when it ends; the environment locks it and is named', async () => {
    show()
    await wait()
    const detail = find<HTMLSelectElement>('[data-testid="log-mode"]')
    await act(async () => {
      detail.value = 'detailed'
      detail.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await wait(20)
    expect(last(`${BASE}/level`)).toMatchObject({ method: 'PUT', body: { mode: 'detailed', minutes: 60 } })
    expect(box.textContent).toMatch(/Um .+ zurück auf normal\./)
    await act(async () => {
      detail.value = 'quiet'
      detail.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await wait(20)
    expect(last(`${BASE}/level`)).toMatchObject({ method: 'PUT', body: { mode: 'quiet', minutes: 0 } })
    expect(box.textContent).not.toContain('zurück auf normal')

    act(() => root.unmount())
    root = createRoot(box)
    mode = { ...mode, mode: 'detailed', fixed_by_env: true }
    show()
    await wait()
    expect(find<HTMLSelectElement>('[data-testid="log-mode"]').disabled).toBe(true)
    expect(box.textContent).toContain('Die Stufe steht in NEXAPP_LOG_LEVEL und lässt sich hier nicht ändern.')
  })

  it('loads the newest lines and the level again on "Refresh", with the filters as they are', async () => {
    show()
    await wait()
    await act(async () => find<HTMLButtonElement>('[data-testid="log-level-ERROR"]').click())
    await wait()
    const before = calls.length
    await act(async () => find<HTMLButtonElement>('[data-testid="log-refresh"]').click())
    await wait()
    const again = calls.slice(before)
    expect(again.filter((call) => call.path === BASE && call.method === 'GET').map((call) => call.query)).toEqual([
      { level: 'ERROR', search: undefined, limit: 200, offset: 0 },
    ])
    expect(again.some((call) => call.path === `${BASE}/level`)).toBe(true)
  })

  it('clears the log only after the question', async () => {
    show()
    await wait()
    await act(async () => find<HTMLButtonElement>('[data-testid="log-clear"]').click())
    const dialog = find('[role="dialog"]')
    expect(dialog.textContent).toContain('Jede Zeile geht. Neue kommen wie bisher.')
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    const confirm = dialog.querySelector<HTMLButtonElement>('button[type="submit"]')!
    expect([confirm.getAttribute('data-kind'), confirm.getAttribute('data-icon'), confirm.textContent]).toEqual(['danger', 'Trash2', 'Protokoll leeren'])
    expect([...dialog.querySelectorAll('button')].map((button) => button.textContent)).toContain('Abbrechen')
    await act(async () => confirm.click())
    await wait(20)
    expect(last(BASE).method).toBe('DELETE')
    expect(box.querySelector('[role="dialog"]')).toBeNull()
    expect(box.textContent).toContain('Nichts im Log.')
  })

  it('says when the server does not answer', async () => {
    failing = true
    show()
    await wait()
    expect(find('[data-testid="log-problem"]').textContent).toBe('Das ging gerade nicht. Gleich noch einmal versuchen.')
  })

  it("speaks English and French in the kit's language", async () => {
    show('en')
    await wait()
    expect(find('[data-card="log"] h2').textContent).toBe('Log')
    expect(find('[data-testid="log-clear"]').textContent).toBe('Clear log')
    act(() => root.unmount())
    root = createRoot(box)
    show('fr')
    await wait()
    expect(find('[data-card="log"] h2').textContent).toBe('Journal')
    expect(find('[data-testid="log-more"]').textContent).toBe('Charger les plus anciennes')
  })
})

describe('the words of the module', () => {
  type Tree = { [key: string]: string | Tree }
  const keys = (tree: Tree, prefix = ''): string[] =>
    Object.entries(tree).flatMap(([name, value]) => (typeof value === 'string' ? [`${prefix}${name}`] : keys(value, `${prefix}${name}.`)))

  it('are there in German, English and French, key for key', () => {
    const german = keys(LOG_TEXTS.de as Tree).sort()
    expect(keys(LOG_TEXTS.en as Tree).sort()).toEqual(german)
    expect(keys(LOG_TEXTS.fr as Tree).sort()).toEqual(german)
  })
})
