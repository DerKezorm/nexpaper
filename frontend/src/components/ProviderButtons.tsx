/**
 * The sign-in providers as buttons, in the order of the operator's list, with the line "or" above them: on the sign-in
 * page "Sign in with …", on the invitation page "Continue with …" (the invitation travels along to the provider).
 * Words from the shared sign-in module (`oidc.login.*`, `oidc.invite.button`), the same in every nex app.
 */
import { useTranslation } from 'react-i18next'

import { providerStart, type ProviderButton } from '../api/client'

export function OrLine() {
  const { t } = useTranslation()
  return (
    <div className="my-5 flex items-center gap-3 text-xs text-muted">
      <span className="h-px flex-1 bg-line" />
      {t('oidc.login.or')}
      <span className="h-px flex-1 bg-line" />
    </div>
  )
}

const OUTLINE = 'flex h-11 w-full items-center justify-center gap-2 rounded-full border border-line text-sm font-semibold hover:bg-sheet-2'

export function ProviderButtons({
  providers,
  invite,
  next,
}: {
  providers: ProviderButton[]
  /** The invitation's key: the buttons say "Continue with" and take it along. */
  invite?: string
  /** The page the sign-in is for (an app's request to be paired, say): it goes along to the provider and back. */
  next?: string
}) {
  const { t } = useTranslation()
  if (providers.length === 0) return null
  return (
    <div className="space-y-2.5" data-testid="provider-buttons">
      {providers.map((provider) => (
        <button key={provider.slug} type="button" onClick={() => window.location.assign(providerStart(provider.slug, { invite, next }))} className={OUTLINE}>
          {invite ? t('oidc.invite.button', { name: provider.label }) : t('oidc.login.button', { name: provider.label })}
        </button>
      ))}
    </div>
  )
}
