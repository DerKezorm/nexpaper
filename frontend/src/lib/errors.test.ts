/** A refusal that names a limit says it in the sentence: "at most 20 MB", never a raw placeholder. */
import '../i18n'
import { changeLanguage } from '../i18n'
import { errorText } from './errors'

describe('the sentence for an error', () => {
  it('fills in what the server sent along', async () => {
    await changeLanguage('de', false)
    expect(errorText('avatar_too_large', { max_mb: 20 })).toBe('Das Bild ist zu groß, höchstens 20 MB.')
    await changeLanguage('en', false)
    expect(errorText('too_large', { max_mb: 16 })).toBe('The file is larger than allowed, at most 16 MB.')
  })

  it('falls back to the general sentence for a code it does not know', async () => {
    await changeLanguage('en', false)
    expect(errorText('no_such_code')).toBe(errorText('internal_error'))
  })
})
