/**
 * Server › Sign-in (plan "Einstellungen", Anmeldung), the whole page from the shared modules: konten's `SignInPage`
 * (the emergency hammer's notice, "Bereit fürs Internet?" with nexpaper's own points: the server's secrets, the
 * backups, the upload requests; the card "Anmeldung") with the module oidc's `SignInProviders` after it
 * ("Anmeldeanbieter", "authentik in einem Schritt"). nexpaper hands over its words, its server's answers and how it
 * calls it; order, wording, kinds and sizes come from the modules. Before: nexpaper's own `ReadinessCards.tsx` and
 * `SignInCards.tsx`.
 *
 * The switches go to `/api/v1/server/sign-in` (the module's rules: the password sign-in off only with an active
 * provider, the second factor for everybody on only with an own one, off only with the password); the public address
 * keeps its own way (`PUT /api/v1/settings`, the question when authentik knows the old one). Which points of "Bereit
 * fürs Internet?" are open stays per device (`fold.ready`).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ApiError, oidcApi, signInApi, type SignInSettingsView } from '../../api/client'
import { APP_NAME } from '../../i18n'
import { useDevicePref } from '../../lib/devicePref'
import { errorText } from '../../lib/errors'
import type { Readiness } from '../../vendor/nexkonten/konten'
import { SignInPage, type AddressQuestion } from '../../vendor/nexkonten/SignInPage'
import { SignInProviders, type ErrorOf, type OidcAdminCalls, type OidcProviderForm, type OidcProviderRow } from '../../vendor/nexoidc/SignInProviders'

/** How the provider cards call nexpaper's routes (the module oidc's under `/api/v1`). */
const CALLS: OidcAdminCalls = {
  providers: () => oidcApi.providers() as unknown as Promise<OidcProviderRow[]>,
  add: (form: OidcProviderForm) => oidcApi.addProvider(form),
  save: (id, form: OidcProviderForm) => oidcApi.saveProvider(Number(id), form),
  remove: (id) => oidcApi.removeProvider(Number(id)),
  impact: (id, issuer) => oidcApi.providerImpact(Number(id), issuer ?? ''),
  order: (ids) => oidcApi.orderProviders(ids.map(Number)),
  authentik: (url, token, confirm, publicUrl) => oidcApi.authentik(url, token, confirm, publicUrl),
  authentikAddress: () => oidcApi.address(),
  authentikSaveAddress: (publicUrl, confirm) => oidcApi.saveAddress(publicUrl, confirm),
}

/** A refusal as the module oidc reads it: the server's code and the values of the answer. */
// eslint-disable-next-line react-refresh/only-export-components
export const errorOf: ErrorOf = (error) => (error instanceof ApiError ? { code: error.code, values: error.values } : null)

/** A refusal in nexpaper's words (its codes, with their values). */
const problemText = (error: unknown) => (error instanceof ApiError ? errorText(error.code, error.values) : errorText('internal_error'))

const readOpen = (raw: string | null): Record<string, boolean> => {
  try {
    const value = raw ? (JSON.parse(raw) as unknown) : {}
    return value && typeof value === 'object' ? (value as Record<string, boolean>) : {}
  } catch {
    return {}
  }
}

export function SignInArea() {
  const { t } = useTranslation()
  const [view, setView] = useState<SignInSettingsView | null>(null)
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [opened, setOpened] = useDevicePref('fold.ready', readOpen)
  const load = useCallback(async () => {
    const [found, ready] = await Promise.all([signInApi.read(), signInApi.readiness().catch(() => null)])
    setView(found)
    setReadiness(ready)
  }, [])
  useEffect(() => {
    void load().catch(() => undefined)
  }, [load])
  const translate = useMemo(() => (key: string, values?: Record<string, unknown>) => t(key, values), [t])
  if (!view) return null

  const saveAddress = async (url: string, confirm: boolean): Promise<AddressQuestion | null> => {
    try {
      await api('/api/v1/settings', { method: 'PUT', body: { public_url: url, confirm_address: confirm } })
    } catch (error) {
      if (error instanceof ApiError && error.code === 'public_url_change') {
        return { count: Number(error.values.count ?? 0), hand: Number(error.values.hand ?? 0), address: String(error.values.address ?? '') }
      }
      throw error
    }
    await load()
    return null
  }

  return (
    <SignInPage
      t={translate}
      app={APP_NAME}
      view={view}
      readiness={readiness}
      publicUrl={view.public_url}
      operatorHasPassword={view.operator_has_password}
      onChange={async (change, password) => {
        setView(await signInApi.save(change, password ?? ''))
        setReadiness(await signInApi.readiness().catch(() => null))
      }}
      onSaveAddress={saveAddress}
      errorText={problemText}
      saved={t('settings.saved')}
      open={opened}
      onOpenChange={(key, open) => setOpened(JSON.stringify({ ...opened, [key]: open }))}
      providers={<SignInProviders t={translate} app={APP_NAME} apiPrefix="/api/v1" calls={CALLS} errorOf={errorOf} publicUrl={view.public_url_effective || view.public_url} onAddress={load} />}
    />
  )
}
