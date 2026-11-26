/**
 * Mein Konto › KI, the same in every app with AI (K6, E61): cards from the ui kit.
 *
 * 1. "KI" (Sparkles): "KI für mich" (`CheckboxRow`), the state, where the text goes ("bleibt im eigenen Netz" or the
 *    host on the internet, never a host of the own network), the model; the reason when it does not work.
 * 2. "Eigener Zugang" (KeyRound): only in the way "Jedes Konto selbst", the person's own service (`ServiceFields`).
 * 3. "Was ging hinaus" (ScrollText): the last 14 days as a `Table`; a task the person started opens word for word,
 *    an automatic one is a line without content (K5); "Liste leeren" with a question.
 *
 * The app puts its own cards between 1 and 3 (`children`: nexmail "Eingegangene Post", nexdiary "Morgens selbst
 * schreiben"). Copied unchanged into frontend/src/vendor/nexki/ by bauplaene/ki/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Badge, Button, Buttons, Card, CheckboxRow, ConfirmDialog, Dialog, Facts, Notice, Table } from '../nexui'
import { KI_ME_BASE, defaultWhen, fillKi, refusalText, useKiTexts, type AiEvent, type AiModel, type AiRequest, type AiState, type WhenFormat } from './ki'
import { ServiceFields } from './ServiceFields'

export type AiAccountAreaProps = {
  request: AiRequest
  app: string
  base?: string
  language?: string
  /** The app's words for its tasks (`rewrite` → "Umformulieren"); else the task's name. */
  tasks?: Record<string, string>
  when?: WhenFormat
  children?: ReactNode
}

export function AiAccountArea({ request, app, base = KI_ME_BASE, language, tasks = {}, when = defaultWhen, children }: AiAccountAreaProps) {
  const { texts, code } = useKiTexts(language)
  const [state, setState] = useState<AiState | null>(null)
  const [events, setEvents] = useState<AiEvent[]>([])
  const [problem, setProblem] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [shown, setShown] = useState<AiEvent | null>(null)
  const [clearing, setClearing] = useState(false)

  const loadEvents = useCallback(() => request<AiEvent[]>(`${base}/events`).then(setEvents, () => setEvents([])), [request, base])
  useEffect(() => {
    request<AiState>(base).then(setState, (failure: unknown) => setProblem(refusalText(texts, failure, app)))
    void loadEvents()
  }, [request, base, texts, app, loadEvents])

  const save = async (body: Record<string, unknown>) => {
    setBusy(true)
    setProblem(undefined)
    try {
      setState(await request<AiState>(base, { method: 'PUT', body }))
    } catch (failure) {
      setProblem(refusalText(texts, failure, app))
      throw failure
    } finally {
      setBusy(false)
    }
  }

  const clear = async () => {
    setBusy(true)
    try {
      await request(`${base}/events`, { method: 'DELETE' })
      setEvents([])
      setClearing(false)
    } finally {
      setBusy(false)
    }
  }

  if (!state) {
    return problem ? (
      <Notice tone="danger" testId="ki-me-problem">
        {problem}
      </Notice>
    ) : null
  }
  const where = state.local ? texts.me.toLocal : state.to ? fillKi(texts.me.toHost, { host: state.to }) : ''
  const reason = state.reason ? refusalText(texts, { code: state.reason }, app) : ''
  return (
    <div className="flex flex-col gap-6" data-testid="ki-me">
      <Card id="ai-me" icon="Sparkles" title={texts.me.title} subtitle={fillKi(texts.me.text, { app })} testId="ki-card-me">
        <div className="flex flex-col gap-4">
          <CheckboxRow label={texts.me.mine} hint={texts.me.mineHint} checked={state.mine} disabled={busy} onChange={(on) => void save({ mine: on }).catch(() => undefined)} testId="ki-me-mine" />
          <Facts
            label={texts.me.title}
            items={[
              {
                label: texts.me.state,
                value: <Badge tone={state.available ? 'on' : 'off'}>{state.available ? texts.me.ready : texts.me.notReady}</Badge>,
                note: reason || undefined,
                testId: 'ki-me-state',
              },
              ...(where ? [{ label: texts.me.where, value: where, testId: 'ki-me-where' }] : []),
              ...(state.model ? [{ label: texts.me.model, value: <span className="font-mono">{state.model}</span>, testId: 'ki-me-model' }] : []),
            ]}
          />
          {problem && (
            <Notice tone="danger" testId="ki-me-problem">
              {problem}
            </Notice>
          )}
        </div>
      </Card>
      {state.mode === 'own' && state.allowed && (
        <Card id="ai-own" icon="KeyRound" title={texts.own.title} subtitle={texts.own.text} testId="ki-card-own">
          <ServiceFields
            key={JSON.stringify(state.own ?? null)}
            texts={texts}
            app={app}
            value={state.own ?? { api: 'openai', url: '', model: '', key_set: false }}
            loadModels={(typed) => request<AiModel[]>(`${base}/models`, { method: 'POST', body: typed })}
            onSave={(body) => save(body)}
            busy={busy}
            testId="ki-me-own"
          />
        </Card>
      )}
      {children}
      <Card id="ai-events" icon="ScrollText" title={texts.events.title} subtitle={fillKi(texts.events.text, { app })} testId="ki-card-events">
        <div className="flex flex-col gap-4">
          <Table<AiEvent, 'at' | 'task' | 'to' | 'outcome' | 'show'>
            label={texts.events.table}
            columns={[
              { key: 'at', label: texts.events.at },
              { key: 'task', label: texts.events.task },
              { key: 'to', label: texts.events.to },
              { key: 'outcome', label: texts.events.outcome },
              { key: 'show', label: '' },
            ]}
            rows={events}
            rowKey={(row, index) => String(row.id ?? index)}
            empty={texts.events.empty}
            testId="ki-me-events"
            cell={(row, column) => {
              if (column === 'at') return when(row.at, code)
              if (column === 'task') return tasks[row.task] ?? row.task
              if (column === 'to') return row.to === 'local' ? texts.events.local : row.to
              if (column === 'outcome') {
                if (row.outcome === 'ok') return <Badge tone="on">{texts.events.ok}</Badge>
                return (
                  <span className="flex flex-col items-start gap-1">
                    <Badge tone="warn">{texts.events.failed}</Badge>
                    <span className="text-xs text-[var(--nexui-text-muted)]">{refusalText(texts, { code: row.outcome }, app)}</span>
                  </span>
                )
              }
              return row.sent ? (
                <Button kind="secondary" size="sm" icon="ScrollText" onClick={() => setShown(row)} testId="ki-me-event-show">
                  {texts.events.show}
                </Button>
              ) : (
                <span className="text-sm text-[var(--nexui-text-muted)]">{texts.events.automatic}</span>
              )
            }}
          />
          {events.length > 0 && (
            <Buttons>
              <Button kind="danger" icon="Trash2" onClick={() => setClearing(true)} testId="ki-me-events-clear">
                {texts.events.clear}
              </Button>
            </Buttons>
          )}
        </div>
      </Card>
      {shown?.sent && (
        <Dialog title={tasks[shown.task] ?? shown.task} onClose={() => setShown(null)} closeLabel={texts.events.close} wide testId="ki-me-event">
          <Facts
            items={[
              { label: texts.events.at, value: when(shown.at, code) },
              { label: texts.events.to, value: shown.to === 'local' ? texts.events.local : shown.to },
              { label: texts.me.model, value: shown.model },
            ]}
          />
          <h3 className="mt-4 mb-1 text-sm font-semibold">{texts.events.rules}</h3>
          <pre className="max-h-48 overflow-auto rounded-md bg-[var(--nexui-surface-2,transparent)] p-2 text-xs whitespace-pre-wrap">{shown.sent.system}</pre>
          <h3 className="mt-4 mb-1 text-sm font-semibold">{texts.events.material}</h3>
          <pre className="max-h-96 overflow-auto rounded-md bg-[var(--nexui-surface-2,transparent)] p-2 text-xs whitespace-pre-wrap">{shown.sent.user}</pre>
        </Dialog>
      )}
      {clearing && (
        <ConfirmDialog
          title={texts.events.clearQuestion}
          text={texts.events.clearText}
          confirm={{ label: texts.events.clear, kind: 'danger', icon: 'Trash2' }}
          cancel={texts.events.cancel}
          closeLabel={texts.events.close}
          onConfirm={() => void clear()}
          onCancel={() => setClearing(false)}
          busy={busy}
        />
      )}
    </div>
  )
}
