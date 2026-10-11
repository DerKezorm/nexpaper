import i18n from '../i18n'
import { oidcErrorKey } from '../vendor/nexoidc/oidc'

/** The sentence for a server's error code, in the language of the page; an unknown code gets the general one. */
export function errorText(code: string, values: Record<string, unknown> = {}): string {
  // The fixed codes of sign-in through a provider bring their sentences with the shared module (`oidc.error.*`), the
  // same in every nex app; they go before nexpaper's own.
  const signIn = oidcErrorKey(code)
  if (signIn) return i18n.t(signIn)
  const key = `errors.${code}`
  return i18n.exists(key) ? i18n.t(key, values) : i18n.t('errors.internal_error')
}
