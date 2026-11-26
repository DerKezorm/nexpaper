/**
 * One waiting request in the app's bell, compact: program (with the mark "Gefährlich"), tool, what it wants, when it
 * runs out, then "Erlauben" (secondary `sm`) and "Ablehnen" (danger `sm`); a dangerous one gets "Ansehen" in place of
 * "Erlauben" (allowed only on its own page, after a second question). The app lists the requests (its notifications or
 * `GET <base>/requests?status=waiting`) and hears each decision through `onDecided`.
 *
 * Copied unchanged into frontend/src/vendor/nexmcp/ by bauplaene/mcp/tools/sync.py; changed only there.
 */
import { useState } from 'react'

import { MCP_BASE, decideRequest, defaultWhen, refusalText, useMcpTexts, type McpRequest, type McpWords, type ToolRequest, type WhenFormat } from './mcp'
import { DangerBadge, RequestButtons, RequestDetails, RequestProgram } from './parts'

export type RequestBellRowProps = {
  request: McpRequest
  entry: ToolRequest
  base?: string
  words?: McpWords
  language?: string
  when?: WhenFormat
  /** The address of the request's own page: "Ansehen" is then a link. */
  viewHref?: (entry: ToolRequest) => string
  /** Or the app opens that page itself. */
  onView?: (entry: ToolRequest) => void
  /** The request as the server keeps it after "Erlauben" or "Ablehnen". */
  onDecided?: (decided: ToolRequest) => void
  testId?: string
}

export function RequestBellRow({ request, entry, base = MCP_BASE, words, language, when = defaultWhen, viewHref, onView, onDecided, testId = 'request-bell-row' }: RequestBellRowProps) {
  const { texts, code } = useMcpTexts(language)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string>()

  const decide = async (answer: 'approve' | 'decline') => {
    setBusy(true)
    setProblem(undefined)
    try {
      const decided = await decideRequest(request, base, entry, answer)
      onDecided?.(decided)
    } catch (failure) {
      setProblem(refusalText(texts, failure))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-2 py-2 tracking-normal" data-testid={testId} data-request={String(entry.id)}>
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-sm leading-5 font-medium text-[var(--nexui-text)]">
          <RequestProgram entry={entry} texts={texts} />
          {entry.dangerous && <DangerBadge texts={texts} />}
        </span>
        <span className="block text-xs leading-4 text-[var(--nexui-text-muted)] [overflow-wrap:anywhere]">
          <RequestDetails entry={entry} texts={texts} code={code} words={words} when={when} />
        </span>
      </div>
      {problem && (
        <span role="alert" className="block text-xs leading-4 text-[var(--nexui-danger)]" data-testid="request-bell-problem">
          {problem}
        </span>
      )}
      {entry.status === 'waiting' && (
        <RequestButtons
          entry={entry}
          texts={texts}
          busy={busy}
          viewHref={viewHref}
          onView={onView}
          onApprove={() => void decide('approve')}
          onDecline={() => void decide('decline')}
        />
      )}
    </div>
  )
}
