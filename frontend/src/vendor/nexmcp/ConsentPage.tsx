/**
 * "Programm verbinden", the page at the app's route `/oauth/authorize`: a program (an AI tool) asks to work as the
 * signed-in account. The page shows its name (which it gives itself), where the browser goes back to (the host stands
 * out), the level (`Segment`, the lowest chosen at first), the areas (all, or some ticked one by one; the app's word for
 * them), the extras (`CheckboxRow`, off at first), then "Erlauben" (primary) and "Ablehnen" (secondary). Either way the
 * browser goes to the address the server answers, the program's own, which the server checked. Where the operator lets
 * the account use no AI, only "Ablehnen" is left. A refusal of the server stands as a `Notice` in the module's words.
 *
 * Copied unchanged into frontend/src/vendor/nexmcp/ by bauplaene/mcp/tools/sync.py; changed only there.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { AuthCard, Button, Buttons, Checkbox, CheckboxRow, Facts, Notice, Segment } from '../nexui'
import {
  CONSENT_PARAMS,
  MCP_BUTTONS,
  OAUTH_BASE,
  extraLabel,
  fillMcp,
  levelLabel,
  refusalText,
  useMcpTexts,
  type ConsentInfo,
  type McpRequest,
  type McpWords,
} from './mcp'

export type ConsentPageProps = {
  request: McpRequest
  oauthBase?: string
  /** The query of the page (`?client_id=…`); without, `window.location.search`. */
  search?: string
  /** The app's word for its areas above the choice ("Ordner", "Bereiche", "Kalender"). */
  areaWord?: string
  words?: McpWords
  language?: string
  /** Sends the browser on (default `window.location.assign`; a test passes its own). */
  navigate?: (url: string) => void
  testId?: string
}

/** A sentence with `{host}`, the host standing out. */
function withHost(text: string, host: string): ReactNode {
  const [before, ...after] = text.split('{host}')
  return (
    <>
      {before}
      {after.length > 0 && <strong data-testid="consent-host">{host}</strong>}
      {after.join(host)}
    </>
  )
}

/** The return address with its host standing out. */
function ReturnTo({ uri, host }: { uri: string; host: string }) {
  const at = host ? uri.indexOf(host) : -1
  if (at < 0) return <span className="font-mono text-xs">{uri}</span>
  return (
    <span className="font-mono text-xs" data-testid="consent-return">
      {uri.slice(0, at)}
      <strong className="text-sm">{host}</strong>
      {uri.slice(at + host.length)}
    </span>
  )
}

export function ConsentPage({ request, oauthBase = OAUTH_BASE, search, areaWord, words, language, navigate = (url) => window.location.assign(url), testId = 'mcp-consent' }: ConsentPageProps) {
  const { texts } = useMcpTexts(language)
  const asked = search ?? window.location.search
  const params = useMemo(() => {
    const found = new URLSearchParams(asked)
    return Object.fromEntries(CONSENT_PARAMS.flatMap((name) => (found.get(name) ? [[name, found.get(name) as string]] : []))) as Record<string, string>
  }, [asked])
  const complete = Boolean(params.client_id && params.redirect_uri)
  const [info, setInfo] = useState<ConsentInfo | null>(null)
  const [problem, setProblem] = useState<string | undefined>(complete ? undefined : texts.consent.broken)
  const [sendProblem, setSendProblem] = useState<string>()
  const [level, setLevel] = useState('')
  const [allAreas, setAllAreas] = useState(true)
  const [areas, setAreas] = useState<string[]>([])
  const [extras, setExtras] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!complete) return
    request<ConsentInfo>(`${oauthBase}/authorize?${new URLSearchParams(params).toString()}`).then(
      (found) => {
        setInfo(found)
        setLevel(found.levels[0] ?? found.level)
        setExtras(Object.fromEntries(found.extras.map((name) => [name, false])))
      },
      (failure: unknown) => setProblem(refusalText(texts, failure)),
    )
  }, [request, oauthBase, params, complete, texts])

  const answer = async (allow: boolean) => {
    if (!info || busy) return
    setBusy(true)
    setSendProblem(undefined)
    try {
      const chosen = info.areas.filter((area) => areas.includes(String(area.id))).map((area) => area.id)
      const body = { ...params, allow, level, areas: allAreas || info.areas.length === 0 ? null : chosen, options: extras }
      const { redirect } = await request<{ redirect: string }>(`${oauthBase}/authorize`, { method: 'POST', body })
      navigate(redirect)
    } catch (failure) {
      setSendProblem(refusalText(texts, failure))
      setBusy(false)
    }
  }

  if (problem || !info) {
    return (
      <div className="flex w-full justify-center" data-testid={testId}>
        <AuthCard title={problem ? texts.consent.failed : texts.consent.loading}>
          {problem && (
            <Notice tone="danger" testId="consent-problem">
              {problem}
            </Notice>
          )}
        </AuthCard>
      </div>
    )
  }

  const program = info.client.name
  const noneChosen = !allAreas && info.areas.length > 0 && areas.length === 0
  return (
    <div className="flex w-full justify-center" data-testid={testId}>
      <AuthCard wide title={fillMcp(texts.consent.title, { program, app: info.app })} subtitle={withHost(texts.consent.text, info.redirect_host)}>
        <Facts items={[{ label: texts.consent.returnTo, value: <ReturnTo uri={info.redirect_uri} host={info.redirect_host} />, testId: 'consent-return-to' }]} />
        <p className="m-0 text-xs leading-4 tracking-normal text-[var(--nexui-text-muted)]" data-testid="consent-unverified">
          {fillMcp(texts.consent.unverified, { app: info.app })}
        </p>
        {!info.ai_allowed && (
          <Notice tone="warn" testId="consent-ai-off">
            {texts.consent.aiOff}
          </Notice>
        )}
        {info.ai_allowed && (
          <>
            <Segment<string>
              label={texts.consent.level}
              hints={words?.levelHints?.[level] ? [words.levelHints[level]] : []}
              value={level}
              onChange={setLevel}
              options={info.levels.map((value) => ({ value, label: levelLabel(texts, words, value), testId: `consent-level-${value}` }))}
              testId="consent-level"
            />
            {info.areas.length > 0 && (
              <div className="flex flex-col gap-2" data-testid="consent-areas">
                <Segment<'all' | 'some'>
                  label={areaWord ?? texts.consent.areas}
                  value={allAreas ? 'all' : 'some'}
                  onChange={(value) => setAllAreas(value === 'all')}
                  options={[
                    { value: 'all', label: texts.consent.areasAll, testId: 'consent-areas-all' },
                    { value: 'some', label: texts.consent.areasSome, testId: 'consent-areas-some' },
                  ]}
                  hints={noneChosen ? [texts.consent.areasNone] : []}
                />
                {!allAreas &&
                  info.areas.map((area) => (
                    <Checkbox
                      key={String(area.id)}
                      label={area.name}
                      checked={areas.includes(String(area.id))}
                      onChange={(on) => setAreas(on ? [...areas, String(area.id)] : areas.filter((found) => found !== String(area.id)))}
                      testId={`consent-area-${area.id}`}
                    />
                  ))}
              </div>
            )}
            {info.extras.map((name) => (
              <CheckboxRow
                key={name}
                label={extraLabel(words, name)}
                hint={words?.extraHints?.[name]}
                checked={extras[name] ?? false}
                onChange={(on) => setExtras({ ...extras, [name]: on })}
                testId={`consent-extra-${name}`}
              />
            ))}
            <p className="m-0 text-xs leading-4 tracking-normal text-[var(--nexui-text-muted)]">{texts.consent.after}</p>
          </>
        )}
        {sendProblem && (
          <Notice tone="danger" testId="consent-send-problem">
            {sendProblem}
          </Notice>
        )}
        <Buttons end>
          <Button kind={MCP_BUTTONS.refuse.kind} icon={MCP_BUTTONS.refuse.icon} disabled={busy} onClick={() => void answer(false)} testId="consent-refuse">
            {texts.consent.refuse}
          </Button>
          {info.ai_allowed && (
            <Button kind={MCP_BUTTONS.allow.kind} icon={MCP_BUTTONS.allow.icon} busy={busy} disabled={noneChosen || !level} onClick={() => void answer(true)} testId="consent-allow">
              {texts.consent.allow}
            </Button>
          )}
        </Buttons>
      </AuthCard>
    </div>
  )
}
