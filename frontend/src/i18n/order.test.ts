/**
 * Every language choice of the family lists the languages by their names (decided 06.10.2026): Deutsch, English, and
 * a language the operator added in its place among them, not simply at the end.
 */

import { forgetAddedLanguages, languageOptions } from './index'

function serve(list: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(list), { status: 200, headers: { 'Content-Type': 'application/json' } })),
  )
  forgetAddedLanguages()
}

afterEach(() => {
  vi.unstubAllGlobals()
  forgetAddedLanguages()
})

describe('the language choice', () => {
  it('lists the shipped languages by name', async () => {
    serve([])
    expect((await languageOptions()).map((option) => option.name)).toEqual(['Deutsch', 'English'])
  })

  it('puts an added language in its place, not at the end', async () => {
    serve([
      { code: 'fr', name: 'Français', keys: 1 },
      { code: 'af', name: 'Afrikaans', keys: 1 },
      { code: 'es', name: 'Español', keys: 1 },
    ])
    const options = await languageOptions()
    expect(options.map((option) => option.name)).toEqual(['Afrikaans', 'Deutsch', 'English', 'Español', 'Français'])
    expect(options.filter((option) => option.added).map((option) => option.code)).toEqual(['af', 'es', 'fr'])
  })
})
