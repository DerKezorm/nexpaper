/** The sentences of the page tools for what the server refused (`pagetools.errors.*`), else the general one for the code. */
import { ApiError } from '../api/client'
import i18n from '../i18n'
import { errorText } from './errors'

/** The code of an error from the server (anything else: `failed`). */
export function codeOf(error: unknown): string {
  return error instanceof ApiError ? error.code : 'failed'
}

export function toolText(code: string, values: Record<string, unknown> = {}): string {
  const key = `pagetools.errors.${code}`
  return i18n.exists(key) ? i18n.t(key, values) : errorText(code, values)
}
