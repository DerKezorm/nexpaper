/**
 * Every language choice of the family lists the languages by their names: Deutsch, English, Français, and
 * a language the operator added in its place among them, not simply at the end.
 */

import { BUILT_IN, own } from './index'

function serve(list: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(list), { status: 200, headers: { 'Content-Type': 'application/json' } })),
  )
  own.forget()
}

afterEach(() => {
  vi.unstubAllGlobals()
  own.forget()
})

describe('the language choice', () => {
  it('lists the shipped languages by name', async () => {
    serve([])
    expect((await own.options(BUILT_IN)).map((option) => option.name)).toEqual(['Deutsch', 'English', 'Français'])
  })

  it('puts an added language in its place, not at the end', async () => {
    serve([
      { code: 'de', name: 'Deutsch', keys: 0, built_in: true, own: false },
      { code: 'en', name: 'English', keys: 0, built_in: true, own: false },
      { code: 'fr', name: 'Français', keys: 0, built_in: true, own: false },
      { code: 'it', name: 'Italiano', keys: 1, built_in: false, own: true },
      { code: 'af', name: 'Afrikaans', keys: 1, built_in: false, own: true },
      { code: 'es', name: 'Español', keys: 1, built_in: false, own: true },
    ])
    const options = await own.options(BUILT_IN)
    expect(options.map((option) => option.name)).toEqual(['Afrikaans', 'Deutsch', 'English', 'Español', 'Français', 'Italiano'])
    expect(options.filter((option) => option.added).map((option) => option.code)).toEqual(['af', 'es', 'it'])
  })

  it('reads a list in the form of before too (no built_in, no own): every entry is an added language', async () => {
    serve([
      { code: 'it', name: 'Italiano', keys: 1 },
      { code: 'es', name: 'Español', keys: 1 },
    ])
    const options = await own.options(BUILT_IN)
    expect(options.map((option) => option.name)).toEqual(['Deutsch', 'English', 'Español', 'Français', 'Italiano'])
    expect(options.filter((option) => option.added).map((option) => option.code)).toEqual(['es', 'it'])
  })
})
