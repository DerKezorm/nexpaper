// @vitest-environment jsdom
/**
 * Server › Allgemein › "Sprachen" in nexpaper (module sprachen 1.0.0, E51): the module's card under `/api/v1/locales`,
 * the line naming nexpaper's three built-in languages (E48), its changes naming this tab (`X-Nexpaper-Client`, the
 * server refuses changes without), the menus asking again afterwards (`own.forget`), the template made on the page
 * from nexpaper's English texts; the profile's menu with the operator's languages in their place by name.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import i18n, { BUILT_IN, own, TEMPLATE } from '../../i18n'
import { NexuiLanguage } from '../../vendor/nexui'
import { LanguagesCard } from './ServerCards'

let root: Root
let box: HTMLDivElement
let calls: { path: string; method: string; client: string | null }[]

const LIST = [
  { code: 'de', name: 'Deutsch', keys: 0, built_in: true, own: false },
  { code: 'en', name: 'English', keys: 0, built_in: true, own: false },
  { code: 'fr', name: 'Français', keys: 0, built_in: true, own: false },
  { code: 'nl', name: 'Nederlands', keys: 12, built_in: false, own: true },
]

beforeEach(async () => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  await i18n.changeLanguage('de')
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, init: RequestInit = {}) => {
      calls.push({ path, method: init.method ?? 'GET', client: new Headers(init.headers).get('X-Nexpaper-Client') })
      if ((init.method ?? 'GET') === 'DELETE') return new Response(null, { status: 204 })
      return new Response(JSON.stringify(LIST), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  own.forget()
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
})

afterEach(async () => {
  act(() => root.unmount())
  box.remove()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  own.forget()
  await i18n.changeLanguage('en')
})

describe('the card "Sprachen" of nexpaper', () => {
  it('is the module card under /api/v1/locales, removes with the tab named and lets the menus ask again', async () => {
    const forget = vi.spyOn(own, 'forget')
    await act(async () => root.render(<NexuiLanguage language="de"><LanguagesCard /></NexuiLanguage>))
    await act(async () => undefined)
    const card = box.querySelector<HTMLElement>('[data-card="languages"]')!
    expect(card.textContent).toContain('Deutsch, Englisch und Französisch sind eingebaut.')
    expect([...card.querySelectorAll('[data-testid^="language-built-in-"]')].map((chip) => chip.textContent)).toEqual([
      'Deutsch · eingebaut',
      'English · eingebaut',
      'Français · eingebaut',
    ])
    expect(box.querySelector('[data-testid="language-nl"]')?.textContent).toContain('Nederlands (nl) · 12 Texte')
    expect(card.querySelector('[data-testid="language-upload"]')?.getAttribute('data-icon')).toBe('Upload')
    expect(calls[0]).toMatchObject({ path: '/api/v1/locales', method: 'GET' })
    await act(async () => box.querySelector<HTMLButtonElement>('[aria-label="Nederlands entfernen"]')!.click())
    await act(async () => undefined)
    // Since sprachen 1.0.1 the cross asks first: nothing goes before "Sprache entfernen" in the window.
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    const dialog = document.querySelector<HTMLElement>('[data-testid="language-remove-dialog"]')!
    const confirm = [...dialog.querySelectorAll('button')].find((button) => button.textContent?.trim() === 'Sprache entfernen')!
    await act(async () => confirm.click())
    await act(async () => undefined)
    const removed = calls.find((call) => call.method === 'DELETE')!
    expect(removed.path).toBe('/api/v1/locales/nl')
    expect(removed.client).toMatch(/^tab-/)
    expect(forget).toHaveBeenCalled()
  })

  it('hands out nexpaper English texts as the template', () => {
    expect(TEMPLATE).toMatchObject({ app: { archive: 'Archive', inbox: 'Inbox' } })
    expect(JSON.stringify(TEMPLATE)).not.toContain('Einstellungen')
  })
})

describe('the language menu of the profile', () => {
  it('offers the built-in languages and every added one, by name, an added file over French only once', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify([...LIST.slice(0, 2), { ...LIST[2]!, keys: 3, own: true }, LIST[3]]), { status: 200 })),
    )
    own.forget()
    const options = await own.options(BUILT_IN)
    expect(options.map((option) => option.code)).toEqual(['de', 'en', 'fr', 'nl'])
    expect(options.filter((option) => option.added).map((option) => option.code)).toEqual(['nl'])
  })
})
