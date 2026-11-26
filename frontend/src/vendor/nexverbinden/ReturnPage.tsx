/**
 * The page at the app's route `/connect/return`: the browser is back from the partner's consent page with `code`,
 * `state` and `iss` (or `error`). It finishes the connection once (`POST <base>/return`) and goes on to the cards; a
 * refusal stands as a `Notice` with the way back.
 *
 * Copied unchanged into frontend/src/vendor/nexverbinden/ by bauplaene/verbinden/tools/sync.py; changed only there.
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import { AuthCard, Button, Notice } from '../nexui'
import { CONNECTIONS_PAGE, VERBINDEN_BASE, VERBINDEN_BUTTONS, refusalText, useVerbindenTexts, type PartnerView, type VerbindenRequest } from './verbinden'

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
  const declined = values.error === 'access_denied'
  const [problem, setProblem] = useState<string | undefined>(declined ? texts.return.declined : undefined)
  const sent = useRef(false)

  useEffect(() => {
    if (declined || sent.current) return
    sent.current = true
    request<PartnerView>(`${base}/return`, { method: 'POST', body: { code: values.code ?? '', state: values.state ?? '', iss: values.iss ?? '' } }).then(
      (view) => navigate(`${done}#${encodeURIComponent(view.partner)}`),
      (failure: unknown) => setProblem(refusalText(texts, failure, app)),
    )
  }, [request, base, values, declined, navigate, done, texts, app])

  return (
    <div className="flex w-full justify-center" data-testid={testId}>
      <AuthCard title={problem ? texts.return.failed : texts.return.working}>
        {problem && (
          <>
            <Notice tone={declined ? 'warn' : 'danger'} testId="return-problem">
              {problem}
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
