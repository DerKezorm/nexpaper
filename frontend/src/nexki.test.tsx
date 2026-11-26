// Vorlage nexki 0.1.0
// @vitest-environment jsdom
/**
 * The parts of the module in the app: Server › KI-Anbieter (cards "KI-Dienst", "Wer KI nutzen darf", "Grenzen") and
 * Mein Konto › KI (cards "KI", "Eigener Zugang", "Was ging hinaus"), built from the ui kit, the module's words in
 * German, English and French. What each part shows and what it sends: only what changed, the key never shown, a host of
 * the own network never named, a refusal in words. Copied once by bauplaene/ki/tools/sync.py to
 * `frontend/src/nexki.test.tsx`; then the app's file. Fill in the places marked APP. Needs react-dom (in every app).
 */
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { NexuiLanguage } from './vendor/nexui'
import { AiAccountArea, AiProviderArea, KI_TEXTS, type AiEvent, type AiOperatorView, type AiRequest, type AiState } from './vendor/nexki'

// APP: the app's name as the texts show it, and where it mounts the module's routes.
const APP = 'nexpaper'
const SERVER = '/api/v1/server/ai'
const ME = '/api/v1/me/ai'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Call = { path: string; method: string; body: unknown }

let root: Root
let box: HTMLDivElement
let calls: Call[]
let view: AiOperatorView
let state: AiState
let events: AiEvent[]
let refuse: Record<string, unknown> | null

function freshView(): AiOperatorView {
  return {
    enabled: true,
    mode: 'shared',
    modes: ['shared', 'own'],
    api: 'openai',
    url: 'https://ai.example.com/v1/',
    model: 'plain',
    key_set: true,
    complete: true,
    hosts: [],
    per_minute: 20,
    per_day: 0,
    server_day: 0,
    used_today: 3,
    messages_url: 'https://api.example.com/v1/',
  }
}

function freshState(): AiState {
  return { available: true, reason: null, enabled: true, allowed: true, mine: true, mode: 'shared', api: 'openai', model: 'plain', local: false, to: 'ai.example.com' }
}

const request: AiRequest = async <T,>(path: string, init: { method?: string; body?: unknown } = {}) => {
  const method = init.method ?? 'GET'
  calls.push({ path, method, body: init.body })
  if (refuse && method !== 'GET') {
    const detail = refuse
    refuse = null
    throw Object.assign(new Error('refused'), { detail })
  }
  if (path === SERVER && method === 'PUT') {
    view = { ...view, ...(init.body as Partial<AiOperatorView>) }
    return view as T
  }
  if (path === SERVER) return view as T
  if (path === `${SERVER}/models`) return [{ id: 'plain', name: '' }, { id: 'large', name: 'Large' }] as T
  if (path === `${SERVER}/probe`) return { seconds: 1.2, local: false } as T
  if (path === ME && method === 'PUT') {
    state = { ...state, ...(init.body as Partial<AiState>) }
    return state as T
  }
  if (path === ME) return state as T
  if (path === `${ME}/events` && method === 'DELETE') {
    events = []
    return { cleared: 1 } as T
  }
  if (path === `${ME}/events`) return events as T
  throw new Error(`unexpected ${method} ${path}`)
}

function show(node: ReactNode, language = 'de'): void {
  act(() => root.render(<NexuiLanguage language={language}>{node}</NexuiLanguage>))
}

async function settle(): Promise<void> {
  await act(async () => await new Promise((resolve) => setTimeout(resolve, 0)))
}

function click(element: Element | null | undefined): void {
  expect(element).toBeTruthy()
  act(() => (element as HTMLElement).click())
}

function type(element: Element | null | undefined, value: string): void {
  const input = element as HTMLInputElement
  expect(input).toBeTruthy()
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  act(() => {
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const find = (id: string) => box.querySelector(`[data-testid="${id}"]`)

beforeEach(() => {
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  calls = []
  view = freshView()
  state = freshState()
  events = []
  refuse = null
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
})

describe('Server › KI-Anbieter', () => {
  it('shows three cards in their order, the key never, and today', async () => {
    show(<AiProviderArea request={request} app={APP} base={SERVER} />)
    await settle()
    const cards = [...box.querySelectorAll('[data-card]')].map((card) => card.getAttribute('data-card'))
    expect(cards).toEqual(['ai-service', 'ai-who', 'ai-limits'])
    const key = find('ki-operator-service-key') as HTMLInputElement
    expect(key.value).toBe('')
    expect(key.placeholder).toBe(KI_TEXTS.de.service.keyKept)
    expect(find('ki-operator-today')?.textContent).toContain('3')
  })

  it('sends only what changed, and the main switch alone', async () => {
    show(<AiProviderArea request={request} app={APP} base={SERVER} />)
    await settle()
    type(find('ki-operator-service-model'), 'large')
    click(find('ki-operator-service-save'))
    await settle()
    expect(calls.filter((call) => call.method === 'PUT').map((call) => call.body)).toEqual([{ model: 'large' }])
    click(find('ki-operator-enabled'))
    await settle()
    expect(calls.filter((call) => call.method === 'PUT').at(-1)?.body).toEqual({ enabled: false })
  })

  it('a tile fills in address and interface; the models are loaded with what is typed', async () => {
    show(<AiProviderArea request={request} app={APP} base={SERVER} />)
    await settle()
    click(find('ki-operator-service-tile-ollama'))
    expect((find('ki-operator-service-url') as HTMLInputElement).value).toBe('http://ollama:11434/v1/')
    click(find('ki-operator-service-load'))
    await settle()
    expect(calls.at(-1)).toEqual({ path: `${SERVER}/models`, method: 'POST', body: { api: 'openai', url: 'http://ollama:11434/v1/' } })
    expect(find('ki-operator-service-models')?.textContent).toContain('Large')
  })

  it('in the way "own" the service card goes and the hosts come', async () => {
    view = { ...freshView(), mode: 'own' }
    show(<AiProviderArea request={request} app={APP} base={SERVER} />)
    await settle()
    expect(find('ki-card-service')).toBeNull()
    type(find('ki-operator-hosts'), 'ollama.example.com:11434, gpu.example.com')
    click(find('ki-operator-hosts-save'))
    await settle()
    expect(calls.at(-1)?.body).toEqual({ hosts: ['ollama.example.com:11434', 'gpu.example.com'] })
  })

  it('a refusal shows in words, with the service own words', async () => {
    show(<AiProviderArea request={request} app={APP} base={SERVER} />, 'en')
    await settle()
    refuse = { code: 'ai_service_failed', answered: 500, said: 'broke down' }
    click(find('ki-operator-probe'))
    await settle()
    const text = find('ki-operator-probe-result')?.textContent ?? ''
    expect(text).toContain(KI_TEXTS.en.errors.ai_service_failed)
    expect(text).toContain('broke down')
  })
})

describe('Mein Konto › KI', () => {
  it('says where the text goes and never a host of the own network', async () => {
    show(<AiAccountArea request={request} app={APP} base={ME} />)
    await settle()
    expect(find('ki-me-where')?.textContent).toContain('ai.example.com')
    act(() => root.unmount())
    root = createRoot(box)
    state = { ...freshState(), local: true, to: '' }
    show(<AiAccountArea request={request} app={APP} base={ME} />)
    await settle()
    expect(find('ki-me-where')?.textContent).toContain(KI_TEXTS.de.me.toLocal)
  })

  it('switches the AI off for me and names the reason', async () => {
    show(<AiAccountArea request={request} app={APP} base={ME} />)
    await settle()
    state = { ...state, available: false, reason: 'ai_switched_off' }
    click(find('ki-me-mine'))
    await settle()
    expect(calls.at(-1)).toEqual({ path: ME, method: 'PUT', body: { mine: false } })
    expect(find('ki-me-state')?.textContent).toContain(KI_TEXTS.de.errors.ai_switched_off)
  })

  it('the own access only in the way "own"', async () => {
    show(<AiAccountArea request={request} app={APP} base={ME} />)
    await settle()
    expect(find('ki-card-own')).toBeNull()
    act(() => root.unmount())
    root = createRoot(box)
    state = { ...freshState(), mode: 'own', own: null }
    show(<AiAccountArea request={request} app={APP} base={ME} />)
    await settle()
    expect(find('ki-card-own')).toBeTruthy()
  })

  it('what went out: a manual task opens word for word, an automatic one has no content, the list clears', async () => {
    events = [
      { id: 2, at: '2026-11-26T09:00:00+00:00', task: 'rewrite', to: 'local', model: 'plain', manual: true, chars: 12, outcome: 'ok', sent: { system: 'Rules', user: 'Hello there' } },
      { id: 1, at: '2026-11-26T08:00:00+00:00', task: 'propose', to: 'ai.example.com', model: 'plain', manual: false, chars: 40, outcome: 'ai_timeout', sent: null },
    ]
    show(<AiAccountArea request={request} app={APP} base={ME} tasks={{ rewrite: 'Umformulieren' }} />)
    await settle()
    const table = find('ki-me-events')?.textContent ?? ''
    expect(table).toContain('Umformulieren')
    expect(table).toContain(KI_TEXTS.de.events.automatic)
    expect(table).toContain(KI_TEXTS.de.events.failed)
    expect(table).not.toContain('{seconds}')
    click(find('ki-me-event-show'))
    expect(document.body.textContent).toContain('Hello there')
    click(document.querySelector('[data-testid="ki-me-event"] button'))
    click(find('ki-me-events-clear'))
    const confirm = [...document.querySelectorAll('button')].find((button) => button.textContent?.includes(KI_TEXTS.de.events.clear) && !button.closest('[data-card]'))
    click(confirm)
    await settle()
    expect(calls.at(-1)).toEqual({ path: `${ME}/events`, method: 'DELETE', body: undefined })
  })
})
