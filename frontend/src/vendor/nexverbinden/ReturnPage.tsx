/**
 * The page at the app's route `/connect/return`: the browser is back from the partner's consent page with `code`,
 * `state` and `iss` (or `error`). It finishes the connection once (`POST <base>/return`) and goes on to the cards.
 *
 * Since 0.1.8 (B6, V47): a refusal goes on to the cards too, also a no or an error mark the other app sent back; the
 * card of the partner shows it (carried in `sessionStorage`, `carryProblem`), so every failure of connecting stands in
 * the card where "Verbinden" was clicked. Only where it cannot be carried does the page say it itself, in the middle of
 * the page, with the way back.
 *
 * Copied unchanged into frontend/src/vendor/nexverbinden/ by bauplaene/verbinden/tools/sync.py; changed only there.
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import { AuthCard, Button, Notice } from '../nexui'
import {
  CONNECTIONS_PAGE,
  PAGE_FRAME,
  VERBINDEN_BASE,
  VERBINDEN_BUTTONS,
  carryProblem,
  refusalCode,
  refusalPartner,
  refusalText,
  useVerbindenTexts,
  type PartnerView,
  type VerbindenRequest,
} from './verbinden'

export type ReturnPageProps = {
  app: string
  request: VerbindenRequest
  base?: string
  search?: string
  /** Where the cards are (default `/settings/connections`). */
  done?: string
  language?: string
  navigate?: (url: string) => void
  testId?: string
}

export function ReturnPage({ app, request, base = VERBINDEN_BASE, search, done = CONNECTIONS_PAGE, language, navigate = (url) => window.location.assign(url), testId = 'connect-return' }: ReturnPageProps) {
  const { texts } = useVerbindenTexts(language)
  const asked = search ?? window.location.search
  const values = useMemo(() => Object.fromEntries(new URLSearchParams(asked).entries()), [asked])
  const [problem, setProblem] = useState<{ text: string; declined: boolean }>()
  const sent = useRef(false)

  useEffect(() => {
    if (sent.current) return
    sent.current = true
    const body = values.error ? { error: values.error, state: values.state ?? '' } : { code: values.code ?? '', state: values.state ?? '', iss: values.iss ?? '' }
    request<PartnerView>(`${base}/return`, { method: 'POST', body }).then(
      (view) => navigate(`${done}#${encodeURIComponent(view.partner)}`),
      (failure: unknown) => {
        const code = refusalCode(failure) ?? (values.error === 'access_denied' ? 'declined' : 'consent_failed')
        const partner = refusalPartner(failure) ?? null
        if (carryProblem({ partner, code })) navigate(partner ? `${done}#${encodeURIComponent(partner)}` : done)
        else setProblem({ text: refusalText(texts, failure, app), declined: code === 'declined' })
      },
    )
  }, [request, base, values, navigate, done, texts, app])

  return (
    <div className={PAGE_FRAME} data-testid={testId}>
      <AuthCard title={problem ? texts.return.failed : texts.return.working}>
        {problem && (
          <>
            <Notice tone={problem.declined ? 'warn' : 'danger'} testId="return-problem">
              {problem.text}
            </Notice>
            <div>
              <Button kind={VERBINDEN_BUTTONS.back.kind} icon={VERBINDEN_BUTTONS.back.icon} onClick={() => navigate(done)} testId="return-back">
                {texts.buttons.back}
              </Button>
            </div>
          </>
        )}
      </AuthCard>
    </div>
  )
}
