/**
 * "Gemerkt" in the side bar against a stand-in of the server: the entries with their numbers, the hint for a vault the
 * person does not see, the menu (rename, up, down, delete), and that deleting asks first (rule 13).
 */
import { act } from 'react'

import type { SavedSearch } from '../api/client'
import { changeLanguage } from '../i18n'
import { forgetSaved } from '../lib/saved'
import { Page, Server, plain } from '../test/harness'
import { idle } from '../test/wait'
import { SavedNav } from './SavedNav'

const server = new Server()
const page = new Page()

const entry = (id: number, name: string, query: string, extra: Partial<SavedSearch> = {}): SavedSearch => ({
  id, name, query, position: id - 1, count: 12, state: 'ok', deadlines_off: false, ...extra,
})
const LIST = 'GET /api/v1/saved-searches'
const entries = () => [
  entry(1, 'Stromrechnungen', 'kind=3&q=strom'),
  entry(2, 'Haushalt alt', 'vault=9', { count: null, state: 'no_access' }),
  entry(3, 'Offene Fristen', 'deadline=open', { count: 1234, deadlines_off: true }),
]

beforeEach(async () => {
  forgetSaved()
  await changeLanguage('de', false)
  server.answers = { [LIST]: entries() }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

const rows = () => [...page.box.querySelectorAll<HTMLElement>('[data-testid="saved-entry"]')]

describe('Gemerkt in the side bar', () => {
  it('lists the entries with their numbers and leads to the archive', async () => {
    await page.show(<SavedNav />, '/eingang')
    expect(plain(page.box.textContent)).toContain('Gemerkt')
    expect(rows().map((row) => plain(row.querySelector('a')?.textContent))).toEqual(['Stromrechnungen12', 'Haushalt alt', 'Offene Fristen1.234'])
    expect(rows()[0].querySelector('a')?.getAttribute('href')).toBe('/?kind=3&q=strom')
    // A vault the person cannot see: a hint instead of a number, and not an error.
    expect(rows()[1].querySelector('[data-testid="saved-hint"]')?.getAttribute('aria-label')).toBe('Den Tresor dieser Suche siehst du nicht.')
    expect(rows()[2].querySelector('a')?.getAttribute('title')).toContain('Fristen sind für dich ausgeschaltet')
  })

  it('marks the entry of the search that is open', async () => {
    await page.show(<SavedNav />, '/?q=strom&kind=3&page=2')
    expect(rows()[0].querySelector('a')?.getAttribute('aria-current')).toBe('page')
    expect(rows()[1].querySelector('a')?.getAttribute('aria-current')).toBeNull()
  })

  it('shows nothing without entries', async () => {
    server.answers[LIST] = []
    await page.show(<SavedNav />, '/')
    expect(page.box.querySelector('[data-testid="saved-nav"]')).toBeNull()
  })

  it('moves up and down through the menu, the first not up and the last not down', async () => {
    server.answers['POST /api/v1/saved-searches/2/up'] = [entries()[1], entries()[0], entries()[2]]
    await page.show(<SavedNav />, '/eingang')
    await page.click(page.button('Mehr zu Stromrechnungen'))
    expect(page.button('Nach oben')?.disabled).toBe(true)
    await page.click(page.button('Mehr zu Stromrechnungen'))
    await page.click(page.button('Mehr zu Haushalt alt'))
    await page.click(page.button('Nach oben'))
    expect(server.changes()).toEqual(['POST /api/v1/saved-searches/2/up'])
    expect(rows().map((row) => plain(row.querySelector('bdi')?.textContent))).toEqual(['Haushalt alt', 'Stromrechnungen', 'Offene Fristen'])
    await page.click(page.button('Mehr zu Offene Fristen'))
    expect(page.button('Nach unten')?.disabled).toBe(true)
  })

  it('renames in place', async () => {
    server.answers['PATCH /api/v1/saved-searches/1'] = entry(1, 'Strom', 'kind=3&q=strom')
    await page.show(<SavedNav />, '/eingang')
    await page.click(page.button('Mehr zu Stromrechnungen'))
    await page.click(page.button('Umbenennen'))
    const field = page.box.querySelector<HTMLInputElement>('input[aria-label="Neuer Name"]')!
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
      set.call(field, 'Strom')
      field.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => field.form!.requestSubmit())
    await idle()
    expect(server.called('PATCH', '/api/v1/saved-searches/1')?.body).toEqual({ name: 'Strom' })
  })

  it('asks before it deletes, and sends nothing without a yes', async () => {
    server.answers['DELETE /api/v1/saved-searches/1'] = 204
    await page.show(<SavedNav />, '/eingang')
    await page.click(page.button('Mehr zu Stromrechnungen'))
    await page.click(page.button('Löschen'))
    expect(page.text).toContain('Gemerkte Suche löschen?')
    expect(page.text).toContain('„Stromrechnungen“ verschwindet aus deiner Seitenleiste. Die Dokumente bleiben, wie sie sind.')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Abbrechen'))
    expect(server.changes()).toEqual([])
    await page.click(page.button('Mehr zu Stromrechnungen'))
    await page.click(page.button('Löschen'))
    const yes = [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')].find((b) => b.textContent?.trim() === 'Löschen')
    await page.click(yes)
    expect(server.changes()).toEqual(['DELETE /api/v1/saved-searches/1'])
  })
})
