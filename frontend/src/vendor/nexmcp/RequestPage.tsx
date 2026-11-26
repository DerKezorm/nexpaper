/**
 * The page of one request (the app's route, e.g. `/settings/connections/requests/:id`): program, tool, what it wants,
 * when it was asked and runs out, its state, the arguments as JSON in fixed-width letters, the answer once it ran.
 * While it waits: "Erlauben" (primary) and "Ablehnen" (danger). A dangerous request asks a second time
 * (`ConfirmDialog`) and only then sends `confirm: true`; the server refuses it without.
 *
 * Copied unchanged into frontend/src/vendor/nexmcp/ by bauplaene/mcp/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Badge, Button, Buttons, Card, ConfirmDialog, Facts, Notice, useNexuiTexts, type BadgeTone, type Fact } from '../nexui'
import {
  MCP_BASE,
  MCP_BUTTONS,
  decideRequest,
  defaultWhen,
  fillMcp,
  refusalCode,
  refusalText,
  toolLabel,
  useMcpTexts,
  type McpRequest,
  type McpWords,
  type RequestStatus,
  type ToolRequest,
  type WhenFormat,
} from './mcp'

export type RequestPageProps = {
  request: McpRequest
  /** The request's `id` (from the app's route). */
  id: number | string
  base?: string
  words?: McpWords
  language?: string
  when?: WhenFormat
  /** After "Erlauben" or "Ablehnen", with the request as the server keeps it. */
  onDecided?: (decided: ToolRequest) => void
  testId?: string
}

const TONES: Record<RequestStatus, BadgeTone> = { waiting: 'warn', running: 'accent', done: 'on', failed: 'danger', declined: 'off', expired: 'off' }

function Block({ title, children, testId }: { title: string; children: ReactNode; testId: string }) {
  return (
    <section className="flex min-w-0 flex-col gap-1" data-testid={testId}>
      <h3 className="m-0 text-xs leading-4 font-semibold tracking-normal text-[var(--nexui-text-muted)]">{title}</h3>
      <pre className="m-0 max-h-80 overflow-auto rounded-[12px] border border-solid border-[var(--nexui-line)] px-3 py-2 font-mono text-xs leading-4 whitespace-pre-wrap text-[var(--nexui-text)] [overflow-wrap:anywhere]">
        {children}
      </pre>
    </section>
  )
}

const shown = (value: unknown) => (typeof value === 'string' ? value : JSON.stringify(value, null, 2))

export function RequestPage({ request, id, base = MCP_BASE, words, language, when = defaultWhen, onDecided, testId = 'request-page' }: RequestPageProps) {
  const { texts, code } = useMcpTexts(language)
  const kit = useNexuiTexts()
  const [entry, setEntry] = useState<ToolRequest | null>(null)
  const [problem, setProblem] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [asking, setAsking] = useState(false)
  const [round, setRound] = useState(0)

  const load = useCallback(() => request<ToolRequest>(`${base}/requests/${encodeURIComponent(String(id))}`), [request, base, id])
  useEffect(() => {
    load().then(setEntry, (failure: unknown) => setProblem(refusalText(texts, failure)))
  }, [load, round, texts])

  const decide = async (answer: 'approve' | 'decline', confirmed = false) => {
    if (!entry) return
    setBusy(true)
    setProblem(undefined)
    try {
      const decided = await decideRequest(request, base, entry, answer, confirmed)
      setEntry(decided)
      setAsking(false)
      onDecided?.(decided)
    } catch (failure) {
      setAsking(false)
      setProblem(refusalText(texts, failure))
      // Decided or run out meanwhile: show how it stands now.
      if (refusalCode(failure) === 'request_decided' || refusalCode(failure) === 'request_expired') setRound((value) => value + 1)
    } finally {
      setBusy(false)
    }
  }

  const program = entry?.key_name ?? texts.request.unknownProgram
  const tool = entry ? toolLabel(texts, words, entry.tool) : ''
  const facts: Fact[] = entry
    ? [
        { label: texts.request.program, value: program, testId: 'request-fact-program' },
        { label: texts.request.tool, value: tool, testId: 'request-fact-tool' },
        ...(entry.summary ? [{ label: texts.request.summary, value: entry.summary, testId: 'request-fact-summary' }] : []),
        { label: texts.request.created, value: when(entry.created_at, code), testId: 'request-fact-created' },
        { label: texts.request.expires, value: when(entry.expires_at, code), testId: 'request-fact-expires' },
        {
          label: texts.request.status,
          value: (
            <Badge tone={TONES[entry.status]} testId="request-status">
              {texts.status[entry.status]}
            </Badge>
          ),
          testId: 'request-fact-status',
        },
        ...(entry.decided_at
          ? [
              {
                label: texts.request.decided,
                value: entry.decided_by ? fillMcp(texts.request.decidedBy, { when: when(entry.decided_at, code), name: entry.decided_by }) : when(entry.decided_at, code),
                testId: 'request-fact-decided',
              },
            ]
          : []),
      ]
    : []

  return (
    <Card id="mcp-request" icon="ShieldCheck" title={fillMcp(texts.request.title, { program })} subtitle={entry?.status === 'waiting' ? texts.request.exactly : undefined} testId={testId}>
      {!entry && !problem && <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]">{texts.request.loading}</p>}
      {problem && (
        <Notice tone="danger" testId="request-problem">
          {problem}
        </Notice>
      )}
      {entry && entry.dangerous && entry.status === 'waiting' && (
        <Notice tone="warn" testId="request-dangerous-note">
          {texts.request.dangerousText}
        </Notice>
      )}
      {entry && <Facts items={facts} label={fillMcp(texts.request.title, { program })} testId="request-facts" />}
      {entry && (
        <Block title={texts.request.arguments} testId="request-arguments">
          {Object.keys(entry.arguments).length ? JSON.stringify(entry.arguments, null, 2) : texts.requests.noArguments}
        </Block>
      )}
      {entry && entry.result !== null && entry.result !== undefined && (
        <Block title={texts.request.result} testId="request-result">
          {shown(entry.result)}
        </Block>
      )}
      {entry?.status === 'waiting' && (
        <Buttons>
          <Button
            kind={MCP_BUTTONS.approve.kind}
            icon={MCP_BUTTONS.approve.icon}
            busy={busy && !asking}
            disabled={busy}
            onClick={() => (entry.dangerous ? setAsking(true) : void decide('approve'))}
            testId="request-approve"
          >
            {texts.request.approve}
          </Button>
          <Button kind={MCP_BUTTONS.decline.kind} icon={MCP_BUTTONS.decline.icon} disabled={busy} onClick={() => void decide('decline')} testId="request-decline">
            {texts.request.decline}
          </Button>
        </Buttons>
      )}
      {asking && entry && (
        <ConfirmDialog
          title={fillMcp(texts.request.confirmTitle, { tool })}
          text={fillMcp(texts.request.confirmText, { program })}
          confirm={{ label: texts.request.confirm, kind: MCP_BUTTONS.confirmApprove.kind, icon: MCP_BUTTONS.confirmApprove.icon }}
          cancel={texts.request.cancel}
          closeLabel={kit.close}
          busy={busy}
          onCancel={() => setAsking(false)}
          onConfirm={() => void decide('approve', true)}
          testId="request-confirm-dialog"
        />
      )}
    </Card>
  )
}
