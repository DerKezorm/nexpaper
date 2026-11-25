import i18n from '../i18n'
import { accountErrorKeyOf, ACCOUNT_ERROR_CODES } from '../vendor/nexkonten/konten'
import { oidcErrorKey } from '../vendor/nexoidc/oidc'

/** The codes nexpaper's server answers with in place of the shared account module's (``OLD_CODES`` in
 * ``backend/app/services/konten_store.py``), mapped back to the module's for its sentences. */
export const OLD_ACCOUNT_CODES: Readonly<Record<string, string>> = {
  invalid_account_name: 'username_invalid',
  name_taken: 'username_taken',
  invalid_email: 'email_invalid',
  sign_in_again: 'fresh_sign_in_needed',
}

/** The sentence for a server's error code, in the language of the page; an unknown code gets the general one. */
export function errorText(code: string, values: Record<string, unknown> = {}): string {
  // The fixed codes of sign-in through a provider bring their sentences with the shared module (`oidc.error.*`), the
  // same in every nex app; so do those of accounts (`account.error.*`). They go before nexpaper's own.
  const signIn = oidcErrorKey(code)
  if (signIn) return i18n.t(signIn)
  // The server names the module's own code beside 1.12.0's (`account_code`, konten 0.3.10).
  const accountCode = typeof values.account_code === 'string' ? values.account_code : null
  const moduleCode = accountCode ?? OLD_ACCOUNT_CODES[code] ?? code
  if ((ACCOUNT_ERROR_CODES as readonly string[]).includes(moduleCode)) {
    const key = accountErrorKeyOf({ code, account_code: accountCode }, OLD_ACCOUNT_CODES)
    if (i18n.exists(key)) return i18n.t(key, values)
  }
  const key = `errors.${code}`
  return i18n.exists(key) ? i18n.t(key, values) : i18n.t('errors.internal_error')
}
