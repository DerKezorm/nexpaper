/**
 * Server › KI-Anbieter, the same in every app with AI (E10): three cards from the ui kit.
 *
 * 1. "KI-Dienst" (Sparkles): the operator's service for all (`ServiceFields`), "Verbindung prüfen"; shown while the
 *    way is "Einer für alle".
 * 2. "Wer KI nutzen darf" (ShieldCheck): the main switch "KI auf diesem Server erlaubt" (K3), the way (K2), the hosts in
 *    the own network accounts may use for their own service (K4), the sentence where "KI erlaubt" per account lives.
 * 3. "Grenzen" (Gauge): per person and minute, per person and day, on the server per day, today's count.
 *
 * The app may put its own cards after them (`children`: nexpaper "Eigene Anweisungen", nexmail "Eingegangene Post").
 * Copied unchanged into frontend/src/vendor/nexki/ by bauplaene/ki/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Badge, Button, Card, CheckboxRow, Field, Notice, Segment } from '../nexui'
import { KI_SERVER_BASE, fillKi, refusalText, useKiTexts, type AiMode, type AiModel, type AiOperatorView, type AiRequest } from './ki'
import { ServiceFields, type ServiceChange } from './ServiceFields'

export type AiProviderAreaProps = {
  request: AiRequest
  app: string
  base?: string
  language?: string
  children?: ReactNode
}

type Change = Partial<Omit<AiOperatorView, 'key_set' | 'complete' | 'used_today' | 'modes' | 'messages_url'>> & { key?: string }

export function AiProviderArea({ request, app, base = KI_SERVER_BASE, language, children }: AiProviderAreaProps) {
  const { texts } = useKiTexts(language)
  const [view, setView] = useState<AiOperatorView | null>(null)
  const [problem, setProblem] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [probe, setProbe] = useState<{ tone: 'ok' | 'danger'; text: string }>()
  const [hosts, setHosts] = useState('')
  const [limits, setLimits] = useState({ per_minute: '', per_day: '', server_day: '' })

  const show = useCallback((found: AiOperatorView) => {
    setView(found)
    setHosts(found.hosts.join(', '))
    setLimits({ per_minute: String(found.per_minute), per_day: String(found.per_day), server_day: String(found.server_day) })
  }, [])

  useEffect(() => {
    request<AiOperatorView>(base).then(show, (failure: unknown) => setProblem(refusalText(texts, failure, app)))
  }, [request, base, show, texts, app])

  const change = async (body: Change) => {
    setBusy(true)
    setProblem(undefined)
    try {
      show(await request<AiOperatorView>(base, { method: 'PUT', body }))
    } catch (failure) {
      setProblem(refusalText(texts, failure, app))
      throw failure
    } finally {
      setBusy(false)
    }
  }
  const quietly = (body: Change) => change(body).catch(() => undefined)

  const check = async () => {
    setProbe(undefined)
    setBusy(true)
    try {
      const found = await request<{ seconds: number }>(`${base}/probe`, { method: 'POST' })
      setProbe({ tone: 'ok', text: fillKi(texts.service.probeOk, { seconds: found.seconds }) })
    } catch (failure) {
      setProbe({ tone: 'danger', text: refusalText(texts, failure, app) })
    } finally {
      setBusy(false)
    }
  }

  const loadModels = (typed: { api: string; url: string; key?: string }) => request<AiModel[]>(`${base}/models`, { method: 'POST', body: typed })

  if (!view) {
    return problem ? (
      <Notice tone="danger" testId="ki-operator-problem">
        {problem}
      </Notice>
    ) : null
  }
  return (
    <div className="flex flex-col gap-6" data-testid="ki-operator">
      {problem && (
        <Notice tone="danger" testId="ki-operator-problem">
          {problem}
        </Notice>
      )}
      {view.mode === 'shared' && (
        <Card id="ai-service" icon="Sparkles" title={texts.service.title} subtitle={fillKi(texts.service.text, { app })} testId="ki-card-service">
          <ServiceFields
            key={`${view.api}|${view.url}|${view.model}|${String(view.key_set)}`}
            texts={texts}
            app={app}
            value={view}
            loadModels={loadModels}
            onSave={(body: ServiceChange) => change(body)}
            busy={busy}
            more={
              view.complete && (
                <Button kind="secondary" icon="Plug" busy={busy} onClick={() => void check()} testId="ki-operator-probe">
                  {texts.service.probe}
                </Button>
              )
            }
            testId="ki-operator-service"
          />
          {probe && (
            <Notice tone={probe.tone} testId="ki-operator-probe-result">
              {probe.text}
            </Notice>
          )}
        </Card>
      )}
      <Card id="ai-who" icon="ShieldCheck" title={texts.who.title} subtitle={texts.who.text} testId="ki-card-who">
        <div className="flex flex-col gap-4">
          <CheckboxRow
            label={texts.who.enabled}
            hint={texts.who.enabledHint}
            checked={view.enabled}
            disabled={busy}
            onChange={(on) => void quietly({ enabled: on })}
            testId="ki-operator-enabled"
          />
          {view.modes.length > 1 && (
            <Segment<AiMode>
              label={texts.who.mode}
              hints={[texts.who.modeHint]}
              value={view.mode}
              onChange={(mode) => void quietly({ mode })}
              options={[
                { value: 'shared', label: texts.who.shared, icon: 'Users' },
                { value: 'own', label: texts.who.own, icon: 'KeyRound' },
              ]}
              disabled={busy}
              testId="ki-operator-mode"
            />
          )}
          {view.mode === 'own' && (
            <Field
              label={texts.who.hosts}
              hints={[texts.who.hostsHint]}
              value={hosts}
              onChange={(event) => setHosts(event.target.value)}
              mono
              data-testid="ki-operator-hosts"
              action={
                <Button kind="secondary" icon="Check" busy={busy} onClick={() => void quietly({ hosts: hosts.split(',').map((one) => one.trim()).filter(Boolean) })} testId="ki-operator-hosts-save">
                  {texts.who.save}
                </Button>
              }
            />
          )}
          <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{texts.who.perAccount}</p>
        </div>
      </Card>
      <Card id="ai-limits" icon="Gauge" title={texts.limits.title} subtitle={texts.limits.text} testId="ki-card-limits">
        <div className="flex flex-col gap-4">
          {(['per_minute', 'per_day', 'server_day'] as const).map((name) => (
            <Field
              key={name}
              label={texts.limits[name === 'per_minute' ? 'perMinute' : name === 'per_day' ? 'perDay' : 'serverDay']}
              hints={name === 'per_minute' ? [] : [texts.limits.none]}
              type="number"
              min={name === 'per_minute' ? 1 : 0}
              value={limits[name]}
              onChange={(event) => setLimits({ ...limits, [name]: event.target.value })}
              data-testid={`ki-operator-${name}`}
              action={
                <Button kind="secondary" icon="Check" busy={busy} onClick={() => void quietly({ [name]: Number(limits[name]) })} testId={`ki-operator-${name}-save`}>
                  {texts.limits.save}
                </Button>
              }
            />
          ))}
          <div>
            <Badge tone="off" testId="ki-operator-today">
              {fillKi(texts.limits.today, { count: view.used_today })}
            </Badge>
          </div>
        </div>
      </Card>
      {children}
    </div>
  )
}
