/**
 * The box "Wartende Rückfragen", in the place `children` of schluessel's `ToolsCard`: per waiting request a row with the
 * program, the tool (the app's word), what it wants and when it runs out, then "Ablehnen" (secondary `sm`, X) on the
 * left and "Erlauben" (primary `sm`, Check) on the right (MCP 20, since 1.1.2). A dangerous request is allowed only on
 * its own page after a second question, so its row has "Ansehen" (a link with `viewHref`, or `onView`) in place of
 * "Erlauben". Nothing waiting: "Nichts wartet."
 *
 * Copied unchanged into frontend/src/vendor/nexmcp/ by bauplaene/mcp/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState } from 'react'

import { Box, Notice, Row, Rows } from '../nexui'
import { MCP_BASE, decideRequest, defaultWhen, refusalCode, refusalText, useMcpTexts, type McpRequest, type McpWords, type ToolRequest, type WhenFormat } from './mcp'
import { DangerBadge, RequestButtons, RequestDetails, RequestProgram } from './parts'

export type PendingRequestsProps = {
  request: McpRequest
  base?: string
  words?: McpWords
  language?: string
  when?: WhenFormat
  /** The address of a request's own page (`RequestPage`): "Ansehen" is then a link. */
  viewHref?: (entry: ToolRequest) => string
  /** Or the app opens that page itself. */
  onView?: (entry: ToolRequest) => void
  /** After every decision (the app counts its bell anew). */
  onChanged?: (decided: ToolRequest) => void
  testId?: string
}

export function PendingRequests({ request, base = MCP_BASE, words, language, when = defaultWhen, viewHref, onView, onChanged, testId = 'pending-requests' }: PendingRequestsProps) {
  const { texts, code } = useMcpTexts(language)
  const [waiting, setWaiting] = useState<ToolRequest[] | null>(null)
  const [problem, setProblem] = useState<string>()
  const [busy, setBusy] = useState<number | string | null>(null)
  const [round, setRound] = useState(0)

  const load = useCallback(() => request<ToolRequest[]>(`${base}/requests?status=waiting`), [request, base])
  useEffect(() => {
    load().then(
      (found) => setWaiting(found.filter((entry) => entry.status === 'waiting')),
      (failure: unknown) => setProblem(refusalText(texts, failure)),
    )
  }, [load, round, texts])

  const decide = async (entry: ToolRequest, answer: 'approve' | 'decline') => {
    setBusy(entry.id)
    setProblem(undefined)
    try {
      const decided = await decideRequest(request, base, entry, answer)
      onChanged?.(decided)
    } catch (failure) {
      setProblem(refusalText(texts, failure))
      if (refusalCode(failure) === undefined) return
    } finally {
      setBusy(null)
    }
    setRound((value) => value + 1)
  }

  return (
    <Box title={texts.requests.title} hint={texts.requests.hint} testId={testId}>
      {problem && (
        <Notice tone="danger" testId="pending-requests-problem">
          {problem}
        </Notice>
      )}
      {waiting && waiting.length === 0 && (
        <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]" data-testid="pending-requests-none">
          {texts.requests.none}
        </p>
      )}
      {waiting && waiting.length > 0 && (
        <Rows label={texts.requests.list} testId="pending-requests-list">
          {waiting.map((entry) => (
            <Row
              key={String(entry.id)}
              name={<RequestProgram entry={entry} texts={texts} />}
              badge={entry.dangerous ? <DangerBadge texts={texts} /> : undefined}
              sub={<RequestDetails entry={entry} texts={texts} code={code} words={words} when={when} />}
              action={
                <RequestButtons
                  entry={entry}
                  texts={texts}
                  busy={busy !== null}
                  viewHref={viewHref}
                  onView={onView}
                  onApprove={() => void decide(entry, 'approve')}
                  onDecline={() => void decide(entry, 'decline')}
                />
              }
              testId="pending-request"
            />
          ))}
        </Rows>
      )}
    </Box>
  )
}
