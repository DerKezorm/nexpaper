/**
 * Server › Log: the card "Log" (ScrollText) as nexnotes has it, built only from the ui kit. Above the table the bar: the
 * levels as a `Segment` (All, INFO, WARNING, ERROR; a level shows the higher ones too, said in its hint), the search,
 * the level of detail (a deep one for an hour), "Refresh" and "Download" (secondary) and "Clear log" (danger, asks first). Below a
 * `Table` of time, level, source, request and account, message (a card per line on a phone), newest first, older ones
 * page by page. The number of a request is a small button that shows only that request (no text link as a button).
 *
 * The app hands over how it calls its server (`request`), where the routes are (`base`), its word for what it keeps
 * (`things`, "Notizen") and, if it has them, its own ways to write a moment. The words come with the module (de, en,
 * fr), in the language the kit uses (`NexuiLanguage`, else the page's) unless `language` says otherwise.
 *
 * Copied unchanged into frontend/src/vendor/nexlog/ by bauplaene/log/tools/sync.py; changed only there.
 */
import { Search } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { Badge, Button, Buttons, Card, ConfirmDialog, Field, NEXUI_TEXTS, Notice, Segment, SelectField, Table, languageOf, useNexuiTexts } from '../nexui'
import {
  DEEP_MODES,
  LEVEL_FILTERS,
  LOG_COLUMNS,
  LOG_COLUMN_WIDTHS,
  LOG_PAGE,
  LOG_TEXTS,
  SEARCH_DELAY,
  fillLog,
  levelTone,
  logQuery,
  modeChange,
  type LevelFilter,
  type LogColumn,
  type LogLine,
  type LogMode,
  type LogRequest,
  type LogTexts,
} from './log'

/** The module's words in the kit's language (or the one given). */
function useLogTexts(language?: string): LogTexts {
  const kit = useNexuiTexts()
  if (language) return LOG_TEXTS[languageOf(language)]
  const code = (Object.keys(NEXUI_TEXTS) as (keyof typeof NEXUI_TEXTS)[]).find((key) => NEXUI_TEXTS[key] === kit) ?? 'en'
  return LOG_TEXTS[code]
}

function defaultWhen(line: LogLine, language: string): string {
  if (!line.at) return line.time
  const moment = new Date(line.at)
  return Number.isNaN(moment.getTime()) ? line.time : moment.toLocaleString(language, { dateStyle: 'short', timeStyle: 'medium' })
}

function defaultClock(iso: string, language: string): string {
  const moment = new Date(iso)
  return Number.isNaN(moment.getTime()) ? iso : moment.toLocaleTimeString(language, { hour: '2-digit', minute: '2-digit' })
}

export type LogCardProps = {
  /** The app's client (its headers, its errors). */
  request: LogRequest
  /** Where the routes are mounted: `/api/logs` (nexpaper `/api/v1/logs`). */
  base?: string
  /** The address of the download, if the app needs another (a base path in front). */
  downloadHref?: string
  /** The app's word for what it keeps ("Notizen", "Kalender"; "notes"). */
  things: string
  /** Since E34: the same after "von" in the hint ("Kalendern"); default `things`. */
  thingsDative?: string
  /** `de`, `en` or `fr`; default the kit's. */
  language?: string
  /** How a line's time is written (the app's own, in the account's zone); default the browser's. */
  when?: (line: LogLine, language: string) => string
  /** How the end of a deep level is written ("14:05"); default the browser's. */
  clock?: (iso: string, language: string) => string
  testId?: string
}

export function LogCard({
  request,
  base = '/api/logs',
  downloadHref,
  things,
  thingsDative = things,
  language,
  when = defaultWhen,
  clock = defaultClock,
  testId = 'log-card',
}: LogCardProps) {
  const texts = useLogTexts(language)
  const kit = useNexuiTexts()
  const shownIn = language ?? (Object.keys(LOG_TEXTS) as (keyof typeof LOG_TEXTS)[]).find((key) => LOG_TEXTS[key] === texts) ?? 'en'
  const [lines, setLines] = useState<LogLine[] | null>(null)
  const [more, setMore] = useState(false)
  const [level, setLevel] = useState<LevelFilter>('')
  const [words, setWords] = useState('')
  const [mode, setMode] = useState<LogMode | null>(null)
  const [clearing, setClearing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(false)
  /** Counts "Refresh": a new round loads the newest lines and the level again. */
  const [round, setRound] = useState(0)

  const page = useCallback((offset: number) => request<LogLine[]>(base, { query: logQuery(level, words, offset) }), [request, base, level, words])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      page(0).then(
        (found) => {
          setLines(found)
          setMore(found.length === LOG_PAGE)
        },
        () => setProblem(true),
      )
    }, SEARCH_DELAY)
    return () => window.clearTimeout(timer)
  }, [page, round])

  useEffect(() => {
    request<LogMode>(`${base}/level`).then(setMode, () => setProblem(true))
  }, [request, base, round])

  const older = () =>
    void page(lines?.length ?? 0).then(
      (found) => {
        setLines([...(lines ?? []), ...found])
        setMore(found.length === LOG_PAGE)
      },
      () => setProblem(true),
    )

  const changeMode = (value: string) => {
    setProblem(false)
    request<LogMode>(`${base}/level`, { method: 'PUT', body: modeChange(value) }).then(setMode, () => setProblem(true))
  }

  const clear = async () => {
    setBusy(true)
    try {
      await request(base, { method: 'DELETE' })
      setClearing(false)
      setLines([])
      setMore(false)
    } catch {
      setProblem(true)
      setClearing(false)
    } finally {
      setBusy(false)
    }
  }

  const cell = (line: LogLine, column: LogColumn) => {
    switch (column) {
      case 'time':
        return <span className="whitespace-nowrap text-[var(--nexui-text-muted)]">{when(line, shownIn)}</span>
      case 'level':
        return (
          <Badge tone={levelTone(line.level)} testId="log-level">
            {line.level}
          </Badge>
        )
      case 'source':
        return (
          <span className="block truncate text-[var(--nexui-text-muted)]" title={line.logger}>
            {line.logger}
          </span>
        )
      case 'request':
        return (
          <span className="flex flex-col items-end gap-0.5 @min-[640px]:items-start">
            {line.request_id ? (
              <Button kind="secondary" size="sm" icon={Search} title={texts.requestHint} aria-label={`${texts.requestHint}: ${line.request_id}`} onClick={() => setWords(line.request_id ?? '')} testId="log-request">
                <span className="font-mono">{line.request_id}</span>
              </Button>
            ) : (
              <span className="text-[var(--nexui-text-muted)]">–</span>
            )}
            {line.user && <span className="truncate text-[var(--nexui-text-muted)]">{line.user}</span>}
          </span>
        )
      case 'message':
        return <span className="block whitespace-pre-wrap [overflow-wrap:anywhere]">{line.message}</span>
    }
  }

  const modeHints = mode?.fixed_by_env
    ? [fillLog(texts.fixed, { variable: mode.variable ?? '' })]
    : mode?.until && DEEP_MODES.includes(mode.mode)
      ? [fillLog(texts.until, { time: clock(mode.until, shownIn) })]
      : []

  return (
    <Card id="log" icon="ScrollText" title={texts.title} subtitle={fillLog(texts.hint, { things, thingsDative })} testId={testId}>
      <div className="flex flex-col gap-3" data-testid="log-bar">
        <Segment<LevelFilter>
          label={texts.level}
          hideLabel
          hints={[texts.levelHint]}
          value={level}
          onChange={setLevel}
          options={LEVEL_FILTERS.map((value) => ({ value, label: value || texts.all, testId: `log-level-${value || 'all'}` }))}
          testId="log-levels"
        />
        <div className="grid gap-3 @min-[640px]:grid-cols-2">
          <Field
            label={texts.search}
            type="search"
            value={words}
            placeholder={texts.searchPlaceholder}
            onChange={(event) => setWords(event.target.value)}
            data-testid="log-search"
          />
          {mode && (
            <SelectField
              label={texts.detail}
              value={mode.mode}
              disabled={mode.fixed_by_env}
              hints={modeHints}
              options={mode.modes.map((value) => ({ value, label: (texts.modes as Record<string, string>)[value] ?? value }))}
              onChange={(event) => changeMode(event.target.value)}
              data-testid="log-mode"
            />
          )}
        </div>
        <Buttons>
          <Button
            kind="secondary"
            icon="RefreshCw"
            onClick={() => {
              setProblem(false)
              setRound((value) => value + 1)
            }}
            testId="log-refresh"
          >
            {texts.refresh}
          </Button>
          <Button kind="secondary" icon="Download" href={downloadHref ?? `${base}/download`} testId="log-download">
            {texts.download}
          </Button>
          <Button kind="danger" icon="Trash2" onClick={() => setClearing(true)} testId="log-clear">
            {texts.clear}
          </Button>
        </Buttons>
      </div>
      {problem && (
        <Notice tone="danger" testId="log-problem">
          {texts.failed}
        </Notice>
      )}
      {lines && (
        <Table<LogLine, LogColumn>
          label={texts.title}
          columns={LOG_COLUMNS.map((key) => ({ key, label: texts.columns[key], width: LOG_COLUMN_WIDTHS[key] }))}
          rows={lines}
          cell={cell}
          rowProps={(line) => ({ 'data-level': line.level, 'data-testid': 'log-row' })}
          empty={texts.empty}
          testId="log-table"
        />
      )}
      {more && (
        <Buttons>
          <Button kind="secondary" icon="ChevronDown" onClick={older} testId="log-more">
            {texts.more}
          </Button>
        </Buttons>
      )}
      {clearing && (
        <ConfirmDialog
          title={texts.clear}
          text={texts.clearText}
          confirm={{ label: texts.clear, kind: 'danger', icon: 'Trash2' }}
          cancel={texts.cancel}
          closeLabel={kit.close}
          busy={busy}
          onCancel={() => setClearing(false)}
          onConfirm={() => void clear()}
          testId="log-clear-dialog"
        />
      )}
    </Card>
  )
}
