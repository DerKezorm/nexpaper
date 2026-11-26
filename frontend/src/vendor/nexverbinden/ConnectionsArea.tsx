/**
 * Every partner app of this app under Mein Konto › Verbindungen, one `ConnectionCard` each, in the order of the module's
 * catalog (Verbindungen 3). It loads `GET <base>/partners` once and keeps each card as the server answers after a
 * change. The app gives the logos, its forms for connecting by hand and its own parts per partner.
 *
 * Copied unchanged into frontend/src/vendor/nexverbinden/ by bauplaene/verbinden/tools/sync.py; changed only there.
 */
import { useEffect, useState, type ReactNode } from 'react'

import { Notice } from '../nexui'
import { ConnectionCard } from './ConnectionCard'
import { VERBINDEN_BASE, refusalText, useVerbindenTexts, type PartnerView, type VerbindenRequest, type WhenFormat } from './verbinden'

export type ConnectionsAreaProps = {
  app: string
  request: VerbindenRequest
  base?: string
  /** Partner -> address of its logo. */
  logos?: Record<string, string>
  /** Partner -> the app's own form for connecting by hand. */
  manual?: Record<string, ReactNode>
  /** The app's own parts in a connected card. */
  extra?: (view: PartnerView) => ReactNode
  areaWord?: string
  language?: string
  when?: WhenFormat
  navigate?: (url: string) => void
  testId?: string
}

export function ConnectionsArea({ app, request, base = VERBINDEN_BASE, logos = {}, manual = {}, extra, areaWord, language, when, navigate, testId = 'connections-area' }: ConnectionsAreaProps) {
  const { texts } = useVerbindenTexts(language)
  const [views, setViews] = useState<PartnerView[] | null>(null)
  const [problem, setProblem] = useState<string>()

  useEffect(() => {
    let live = true
    request<PartnerView[]>(`${base}/partners`).then(
      (found) => {
        if (live) setViews(found)
      },
      (failure: unknown) => {
        if (live) setProblem(refusalText(texts, failure, app))
      },
    )
    return () => {
      live = false
    }
  }, [request, base, texts, app])

  if (problem) {
    return (
      <div data-testid={testId}>
        <Notice tone="danger">{problem}</Notice>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-3" data-testid={testId}>
      {(views ?? []).map((view) => (
        <ConnectionCard
          key={view.partner}
          app={app}
          view={view}
          request={request}
          base={base}
          logo={logos[view.partner]}
          manual={manual[view.partner]}
          areaWord={areaWord}
          language={language}
          when={when}
          navigate={navigate}
          onChange={(changed) => setViews((all) => (all ?? []).map((one) => (one.partner === changed.partner ? changed : one)))}
        >
          {extra?.(view)}
        </ConnectionCard>
      ))}
    </div>
  )
}
