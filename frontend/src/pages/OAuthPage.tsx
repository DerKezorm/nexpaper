/**
 * An app asks to be paired (OAuth 2 with PKCE, `docs/api.md`): the person is signed in (the route is behind the sign-in,
 * with the second factor or the provider as always), sees which app and what it gets, and allows or refuses. Either
 * way the browser goes back to the app at the address the server checked. An app nexpaper does not know, or an address
 * not in its list, gets nothing back: the page says so and stays.
 */
import { Smartphone } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { ApiError, oauthApi, type OAuthAsk, type OAuthAsked } from '../api/client'
import { LogoMark } from '../components/Logo'
import { errorText } from '../lib/errors'

/** Where the browser goes; a seam for the tests. */
// eslint-disable-next-line react-refresh/only-export-components
export const leave = { to: (address: string) => window.location.assign(address) }

export function OAuthPage() {
  const { t, i18n } = useTranslation()
  const [params] = useSearchParams()
  const ask = useMemo<OAuthAsk>(
    () => ({
      client_id: params.get('client_id') ?? '',
      redirect_uri: params.get('redirect_uri') ?? '',
      response_type: params.get('response_type') ?? '',
      code_challenge: params.get('code_challenge') ?? '',
      code_challenge_method: params.get('code_challenge_method') ?? '',
      state: params.get('state') ?? '',
      device_name: params.get('device_name') ?? '',
    }),
    [params],
  )
  const [asked, setAsked] = useState<OAuthAsked | null>(null)
  const [problem, setProblem] = useState<{ code: string; back: string | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    let alive = true
    oauthApi.check(ask).then(
      (found) => alive && setAsked(found),
      (error) => {
        if (!alive) return
        const back = error instanceof ApiError && typeof error.values.redirect === 'string' ? error.values.redirect : null
        setProblem({ code: error instanceof ApiError ? error.code : 'internal_error', back })
      },
    )
    return () => {
      alive = false
    }
  }, [ask])

  const app = asked ? (i18n.exists(`phone.oauth.clients.${asked.client_id}`) ? t(`phone.oauth.clients.${asked.client_id}`) : asked.client_name) : ''
  const answer = async (allow: boolean) => {
    setBusy(true)
    try {
      const { redirect } = await oauthApi.answer(ask, allow)
      setLeaving(true)
      leave.to(redirect)
    } catch (error) {
      setProblem({ code: error instanceof ApiError ? error.code : 'internal_error', back: null })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col justify-center px-4 py-10">
      <div className="card space-y-4 p-6" data-testid="oauth">
        <div className="flex items-center gap-3">
          <LogoMark size={36} />
          <Smartphone size={22} className="text-accent" aria-hidden />
        </div>
        {problem ? (
          <>
            <h1 className="font-display text-2xl font-semibold">{t('phone.oauth.refused')}</h1>
            <p role="alert" className="text-sm text-bad">
              {errorText(problem.code)}
            </p>
            {problem.back && (
              <button type="button" onClick={() => leave.to(problem.back!)} className="h-10 rounded-full border border-line px-4 text-sm font-semibold text-ink-2">
                {t('phone.oauth.backToApp')}
              </button>
            )}
          </>
        ) : asked ? (
          <>
            <h1 className="font-display text-2xl font-semibold">{t('phone.oauth.title', { app })}</h1>
            <p className="text-sm text-ink-2">{t('phone.oauth.text')}</p>
            <p className="text-sm">{t('phone.oauth.device', { name: asked.device_name })}</p>
            {leaving ? (
              <p role="status" className="text-sm font-semibold text-accent">
                {t('phone.oauth.leaving')}
              </p>
            ) : (
              <div className="flex gap-2 pt-2">
                <button type="button" disabled={busy} onClick={() => void answer(true)} className="h-11 flex-1 rounded-full bg-accent px-5 font-semibold text-accent-ink disabled:opacity-50">
                  {t('phone.oauth.allow')}
                </button>
                <button type="button" disabled={busy} onClick={() => void answer(false)} className="h-11 rounded-full border border-line px-5 font-semibold text-ink-2 disabled:opacity-50">
                  {t('phone.oauth.deny')}
                </button>
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  )
}
