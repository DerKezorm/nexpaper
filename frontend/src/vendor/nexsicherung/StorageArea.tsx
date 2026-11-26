/**
 * The area "Speicher und Sicherung" of every nex app (plan "Einstellungen", Server): the card "Speicher" (HardDrive)
 * and the card "Sicherung" (History), the same in every app, then the app's own cards (`children`: nexdiary
 * "Verschlüsselung", nexpaper "So liegen die Dateien auf der Platte", "Dateien prüfen").
 *
 * Only from the kit nexui (1.1.0): `Card`, `Segment`, `Field` with `action`, `Button` (`sm` in the rows), `Box` for the
 * result of a check, `ConfirmDialog` with the password. What the app gives: its name, its word for its things, the
 * sentence of what a backup holds, the calls (`makeSicherungApi`), whether the operator has a password, and its own
 * words for its parts, its counts and the findings of its check.
 *
 * Copied unchanged into frontend/src/vendor/nexsicherung/ by bauplaene/sicherung/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Badge, Box, Button, Card, CheckboxRow, ConfirmDialog, Field, Notice, Row, Rows, Segment, SelectField, type Confirm } from '../nexui'
import {
  bytes,
  errorText,
  fill,
  fillWhen,
  initialAnswers,
  partName,
  shares,
  useSicherungTexts,
  when as defaultWhen,
  type Backups,
  type Brief,
  type Entry,
  type Every,
  type Language,
  type Overview,
  type RestoreAnswers,
  type RestoreOption,
  type SicherungApi,
  type SicherungTexts,
} from './sicherung'
import { blockedWords, type BlockedTexts } from './storage'

export type StorageAreaProps = {
  /** The app's name ("nexnotes"). */
  app: string
  /** The app's word for what it keeps, for the warning on a share ("Notizen", "Mails"). */
  things: string
  /** The app's sentence: what a backup holds and what not (the line under "Sicherung"). */
  holds: string
  api: SicherungApi
  /** The operator signs in with a password (`me.sign_in === 'password'`): the dialogs ask for it. */
  password: boolean
  /** The app's words for its own parts of the storage ("Seitenbilder"); the module's for the rest. */
  partLabel?: (key: string) => string | undefined
  /** The line of an entry's counts ("12 Notizen, 3 Dateien") from its facts; nothing without it. */
  facts?: (entry: Entry) => string | null
  /** The app's findings in the result of a check (what comes, changes, goes; the titles of the asker's own). */
  details?: (brief: Brief) => ReactNode
  /** After a restore with a restart: the app's way to wait (default: reload the page after 8 s). */
  onRestarting?: () => void
  /** Language of numbers and dates (de, en, fr). */
  language: Language
  /** Since E34: how the app writes a moment (its clock and zone, "heute 3:00 AM"), as LogCard's `clock`; every time of
   * the card goes through it: "Zuletzt: …", the list, the result of a check, the failure lines. Default: day and time
   * in the browser's zone (`when`). */
  when?: (iso: string, language: Language) => string
  /** Since E37: the app's own words for its own codes that block a restore (nexdiary `backup_other_master_key`), code →
   * sentence per language (`{ backup_other_master_key: { de: '…', en: '…' } }`); in the result of a check and when a
   * restore is refused, before the server's `blocked_text` and the module's words. Without it all stays as before. */
  blockedText?: BlockedTexts
  /** Since E38: the app's own questions in the dialog "Wiederherstellen", in its words (nexmail: whether the public
   * address of the archive applies); the answers go to the server as `options` and on to the app's hook. */
  restoreOptions?: readonly RestoreOption[]
  children?: ReactNode
}

/** The code of a refusal, if it has one. */
function codeOf(error: unknown): string | null {
  const given = error && typeof error === 'object' && 'code' in error ? (error as { code: unknown }).code : null
  return typeof given === 'string' ? given : null
}

export function StorageArea(props: StorageAreaProps) {
  return (
    <>
      <StorageCard {...props} />
      <BackupCard {...props} />
      {props.children}
    </>
  )
}

/** Card "Speicher": what the app takes, by part, the bar, what is free, a share. */
export function StorageCard({ app, things, api, partLabel, language }: Pick<StorageAreaProps, 'app' | 'things' | 'api' | 'partLabel' | 'language'>) {
  const texts = useSicherungTexts()
  const [overview, setOverview] = useState<Overview | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  useEffect(() => {
    api.overview().then(setOverview, (error: unknown) => setProblem(errorText(texts, error, app)))
  }, [api, app, texts])
  const t = texts.storage
  return (
    <Card id="storage" icon="HardDrive" title={t.title}>
      {problem && <Notice tone="danger">{problem}</Notice>}
      {overview && <StorageBody overview={overview} app={app} things={things} texts={texts} partLabel={partLabel} language={language} />}
    </Card>
  )
}

function StorageBody({ overview, app, things, texts, partLabel, language }: { overview: Overview; app: string; things: string; texts: SicherungTexts; partLabel?: (key: string) => string | undefined; language: Language }) {
  const t = texts.storage
  const { own, other } = shares(overview)
  const parts = overview.parts.filter((part) => !part.within)
  const within = overview.parts.filter((part) => part.within)
  const elsewhere = overview.network.filter((key) => key !== 'data')
  return (
    <div className="flex flex-col gap-1.5" data-testid="storage-overview">
      <div className="flex flex-wrap justify-between gap-2 text-sm">
        <span className="text-[var(--nexui-text-muted)]">{fill(t.uses, { app })}</span>
        <span className="text-[var(--nexui-text)]" data-testid="storage-used">
          {bytes(overview.used, language)}
        </span>
      </div>
      <p className="m-0 text-xs text-[var(--nexui-text-muted)]" data-testid="storage-parts">
        {parts.map((part) => fill(t.part, { name: partName(texts, part.key, partLabel), size: bytes(part.bytes, language) })).join(' · ')}
        {within.length > 0 && ` (${within.map((part) => fill(t.within, { name: partName(texts, part.key, partLabel), size: bytes(part.bytes, language) })).join(', ')})`}
      </p>
      <div
        className="flex h-2 overflow-hidden rounded-full bg-[var(--nexui-line)]"
        role="img"
        aria-label={fill(t.bar, { app, own: bytes(overview.used, language), used: bytes(overview.disk_used, language), total: bytes(overview.total, language) })}
        data-nearly-full={overview.nearly_full || undefined}
      >
        <div className="h-full bg-[var(--nexui-accent)]" style={{ width: `${own}%`, minWidth: overview.used > 0 ? 3 : 0 }} />
        <div className="h-full" style={{ width: `${other}%`, background: overview.nearly_full ? 'var(--nexui-warn)' : 'var(--nexui-text-muted)', opacity: overview.nearly_full ? 1 : 0.35 }} />
      </div>
      <p className={`m-0 text-xs ${overview.nearly_full ? 'text-[var(--nexui-warn)]' : 'text-[var(--nexui-text-muted)]'}`} data-testid="storage-free">
        {fill(t.free, { free: bytes(overview.free, language), total: bytes(overview.total, language) })}
      </p>
      {!overview.complete && <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t.partial}</p>}
      {overview.network.includes('data') && (
        <Notice tone="warn" testId="storage-network">
          {fill(t.network, { things })}
        </Notice>
      )}
      {elsewhere.length > 0 && (
        <Notice tone="warn" testId="storage-network-places">
          {fill(t.networkPlace, { places: elsewhere.map((key) => (t.places as Record<string, string>)[key] ?? key).join(', ') })}
        </Notice>
      )}
    </div>
  )
}

type Asking =
  | { kind: 'restore' | 'download' | 'delete'; entry: Entry; brief?: Brief }
  | { kind: 'upload'; file: File }
  | { kind: 'check'; entry: Entry }
  | { kind: 'make' }

/** The longest note of a backup (the module's routes refuse more, E63). */
const NOTE_LENGTH = 200

/** Card "Sicherung": the schedule, the last one, failures, "Jetzt sichern", "Sicherung hochladen", the list. */
export function BackupCard({ app, holds, api, password, facts, details, onRestarting, language, when = defaultWhen, blockedText, restoreOptions }: StorageAreaProps) {
  const texts = useSicherungTexts()
  const refusal = (error: unknown) => blockedWords(blockedText, codeOf(error), language) ?? errorText(texts, error, app)
  const t = texts.backup
  const [state, setState] = useState<Backups | null>(null)
  const [time, setTime] = useState<string | null>(null)
  const [keep, setKeep] = useState<string | null>(null)
  const [brief, setBrief] = useState<Brief | null>(null)
  const [asking, setAsking] = useState<Asking | null>(null)
  const [typed, setTyped] = useState('')
  const [archiveTyped, setArchiveTyped] = useState('')
  const [answers, setAnswers] = useState<RestoreAnswers>(() => initialAnswers(restoreOptions))
  const [againTyped, setAgainTyped] = useState('')
  const [note, setNote] = useState('')
  const [dialogProblem, setDialogProblem] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [restarting, setRestarting] = useState<'restart' | 'now' | null>(null)

  const load = useCallback(() => {
    api.backups().then(setState, (error: unknown) => setProblem(errorText(texts, error, app)))
  }, [api, app, texts])
  useEffect(load, [load])

  const run = async (label: string, work: () => Promise<void>, success?: string) => {
    setBusy(label)
    setProblem(null)
    setDone(null)
    try {
      await work()
      if (success) setDone(success)
    } catch (error) {
      setProblem(refusal(error))
    } finally {
      setBusy(null)
    }
  }

  if (!state) {
    return (
      <Card id="backups" icon="History" title={t.title} subtitle={holds}>
        {problem && <Notice tone="danger">{problem}</Notice>}
      </Card>
    )
  }

  const schedule = state.schedule
  const saveSchedule = (every: Every, at: string, count: number) =>
    run('schedule', async () => {
      const saved = await api.saveSchedule({ every, time: at, keep: count })
      setState({ ...state, schedule: saved })
      setTime(null)
      setKeep(null)
      load()
    }, t.saved)

  /** A time of the card in the app's words; none for an empty one (E64). */
  const at = (iso: string) => (iso ? when(iso, language) : '')
  const forBackup = (entry: Entry, action: string) => fillWhen(t.forBackup, at(entry.created), { action })
  const open = (next: Asking) => {
    setTyped('')
    setArchiveTyped('')
    setAgainTyped('')
    setNote('')
    setAnswers(initialAnswers(restoreOptions))
    setDialogProblem(null)
    setAsking(next)
  }

  const checkEntry = (entry: Entry, archivePassword?: string) =>
    run(`check:${entry.name}`, async () => {
      setBrief(await api.check(entry.name, archivePassword))
    })

  const confirmAsked = async () => {
    if (!asking) return
    setBusy('dialog')
    setDialogProblem(null)
    const archive = archiveTyped || undefined
    try {
      if (asking.kind === 'make') {
        // "Jetzt sichern" with the note of the window (E63); blanks alone are no note.
        await api.make(note.trim())
        setDone(t.made)
        load()
      } else if (asking.kind === 'check') {
        setBrief(await api.check(asking.entry.name, archive))
      } else if (asking.kind === 'download') {
        const blob = await api.download(asking.entry.name, typed, state.download_password ? archiveTyped : undefined)
        const link = document.createElement('a')
        link.href = URL.createObjectURL(blob)
        link.download = asking.entry.name
        link.click()
        URL.revokeObjectURL(link.href)
      } else if (asking.kind === 'delete') {
        await api.remove(asking.entry.name, typed)
        if (brief?.name === asking.entry.name) setBrief(null)
        load()
      } else if (asking.kind === 'upload') {
        await api.upload(asking.file, typed)
        setDone(t.uploadedHint)
        load()
      } else if (asking.kind === 'restore') {
        const result = restoreOptions?.length ? await api.restore(asking.entry.name, typed, archive, answers) : await api.restore(asking.entry.name, typed, archive)
        if (result.restarting) {
          setRestarting('restart')
          if (onRestarting) onRestarting()
          else window.setTimeout(() => window.location.reload(), 8000)
        } else {
          setRestarting('now')
        }
      }
      setAsking(null)
    } catch (error) {
      setDialogProblem(refusal(error))
    } finally {
      setBusy(null)
    }
  }

  const confirmOf = (kind: Asking['kind']): Confirm => {
    const words = t.confirm[kind]
    const icon = { restore: 'RotateCcw', download: 'Download', delete: 'Trash2', upload: 'Upload', check: 'ShieldCheck', make: 'Archive' }[kind] as Confirm['icon']
    // What removes or replaces something is danger (plan: kinds of buttons); fetching, bringing in, checking primary.
    return { label: words.button, kind: kind === 'delete' || kind === 'restore' ? 'danger' : 'primary', icon }
  }
  const askText = (kind: Asking['kind']) => {
    if (kind === 'restore') return fill(state.restore === 'now' ? t.confirm.restore.textNow : t.confirm.restore.text, { app })
    if (kind === 'check' || kind === 'make') return undefined
    return fill(t.confirm[kind].text, { app })
  }
  const needsArchivePassword = asking !== null && (asking.kind === 'restore' || asking.kind === 'check') && asking.entry.locked
  const needsPassword = password && asking !== null && asking.kind !== 'check' && asking.kind !== 'make'
  // nexmail: a download is encrypted with a password of its own, at least 8 characters, typed twice.
  const needsFilePassword = asking !== null && asking.kind === 'download' && state.download_password
  const filePasswordOk = archiveTyped.length >= 8 && archiveTyped === againTyped

  const last = state.last
  const failure = state.failure
  const reason = failure ? ((t.reasons as Record<string, string>)[failure.reason] ?? failure.reason) : ''

  return (
    <Card id="backups" icon="History" title={t.title} subtitle={holds}>
      <Segment<Every>
        label={t.schedule}
        value={schedule.every}
        onChange={(every) => void saveSchedule(every, time ?? schedule.time, schedule.keep)}
        disabled={busy === 'schedule'}
        testId="backup-schedule"
        options={[
          { value: 'off', label: t.every.off, testId: 'backup-every-off' },
          { value: 'daily', label: t.every.daily, testId: 'backup-every-daily' },
          { value: 'weekly', label: t.every.weekly, testId: 'backup-every-weekly' },
          { value: 'monthly', label: t.every.monthly, testId: 'backup-every-monthly' },
        ]}
      />
      <form
        className="grid gap-3 sm:grid-cols-[10rem_1fr]"
        onSubmit={(event) => {
          event.preventDefault()
          void saveSchedule(schedule.every, time ?? schedule.time, Math.round(Number(keep ?? schedule.keep)))
        }}
      >
        <Field label={t.time} type="time" value={time ?? schedule.time} onChange={(event) => setTime(event.target.value)} hints={[fill(schedule.every === 'monthly' ? t.timeHintMonthly : t.timeHint, { zone: state.zone })]} disabled={schedule.every === 'off'} />
        <Field
          label={t.keep}
          type="number"
          min={1}
          max={365}
          value={keep ?? String(schedule.keep)}
          onChange={(event) => setKeep(event.target.value)}
          hints={[t.keepHint]}
          action={
            <Button type="submit" kind="secondary" icon="Check" busy={busy === 'schedule'}>
              {t.save}
            </Button>
          }
        />
      </form>
      <p className="m-0 text-sm text-[var(--nexui-text-muted)]" data-testid="backup-last">
        {state.running ? t.running : last ? fillWhen(t.last, at(last.created), { size: bytes(last.size, language) }) : t.never}
      </p>
      {failure && (
        <Notice tone="danger" testId="backup-failure">
          {fillWhen(t.failed, at(failure.at), { reason })}
        </Notice>
      )}
      {state.restore_failure && (
        <Notice tone="danger" testId="restore-failure">
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span>{fillWhen(t.restoreFailed, at(state.restore_failure.at), { app })}</span>
            <Button size="sm" kind="secondary" icon="Check" onClick={() => void run('dismiss', async () => { await api.dismissFailed(); load() })}>
              {t.restoreFailedSeen}
            </Button>
          </span>
        </Notice>
      )}
      <div className="flex flex-wrap gap-2">
        <Button kind="primary" icon="Archive" busy={state.running} onClick={() => open({ kind: 'make' })} testId="backup-now">
          {t.now}
        </Button>
        <Button kind="secondary" icon="Upload" accept=".zip,application/zip" onFile={(file) => open({ kind: 'upload', file })} testId="backup-upload">
          {t.upload}
        </Button>
      </div>
      {problem && <Notice tone="danger">{problem}</Notice>}
      {done && <Notice tone="ok">{done}</Notice>}
      {restarting && <Notice tone="warn" testId="backup-restarting">{restarting === 'restart' ? fill(t.restarting, { app }) : t.restoredNow}</Notice>}
      {state.backups.length > 0 && (
        <Rows label={t.list} testId="backup-list">
          {state.backups.map((entry) => {
            const counts = entry.readable ? facts?.(entry) : null
            const sub = [entry.readable ? (entry.uploaded ? t.uploaded : t.kinds[entry.kind]) : t.unreadable, entry.note, counts, bytes(entry.size, language), entry.version].filter(Boolean).join(' · ')
            return (
              <Row
                key={entry.name}
                icon="Archive"
                name={when(entry.created, language)}
                sub={sub}
                badge={entry.locked ? <Badge tone="off">{t.locked}</Badge> : undefined}
                testId={`backup-${entry.name}`}
                action={
                  <span className="flex flex-wrap gap-1.5">
                    {entry.readable && (
                      <Button size="sm" kind="secondary" icon="ShieldCheck" aria-label={forBackup(entry, t.check)} busy={busy === `check:${entry.name}`} onClick={() => (entry.locked ? open({ kind: 'check', entry }) : void checkEntry(entry))}>
                        {t.check}
                      </Button>
                    )}
                    <Button size="sm" kind="secondary" icon="Download" aria-label={forBackup(entry, t.download)} onClick={() => open({ kind: 'download', entry })}>
                      {t.download}
                    </Button>
                    {entry.readable && (
                      <Button
                        size="sm"
                        kind="secondary"
                        icon="RotateCcw"
                        aria-label={forBackup(entry, t.restore)}
                        busy={busy === `restore:${entry.name}`}
                        onClick={() =>
                          entry.locked
                            ? open({ kind: 'restore', entry })
                            : void run(`restore:${entry.name}`, async () => {
                                // First the trial run: what comes, what changes, what goes; then the question.
                                const checked = await api.check(entry.name)
                                setBrief(checked)
                                if (checked.usable) open({ kind: 'restore', entry, brief: checked })
                              })
                        }
                      >
                        {t.restore}
                      </Button>
                    )}
                    <Button size="sm" kind="danger" icon="Trash2" aria-label={forBackup(entry, t.delete)} onClick={() => open({ kind: 'delete', entry })}>
                      {t.delete}
                    </Button>
                  </span>
                }
              />
            )
          })}
        </Rows>
      )}
      {brief && <BriefBox brief={brief} app={app} texts={texts} details={details} language={language} when={when} blockedText={blockedText} />}
      {asking && (
        <ConfirmDialog
          title={t.confirm[asking.kind].title}
          text={askText(asking.kind)}
          confirm={confirmOf(asking.kind)}
          cancel={t.cancel}
          closeLabel={t.close}
          busy={busy === 'dialog'}
          error={dialogProblem}
          confirmDisabled={(needsPassword && !typed) || (needsArchivePassword && !archiveTyped) || (needsFilePassword && !filePasswordOk)}
          onCancel={() => setAsking(null)}
          onConfirm={() => void confirmAsked()}
          testId={`backup-confirm-${asking.kind}`}
        >
          {asking.kind === 'make' && (
            <Field label={t.note} maxLength={NOTE_LENGTH} autoComplete="off" value={note} onChange={(event) => setNote(event.target.value)} hints={[t.noteHint]} data-testid="backup-note" />
          )}
          {asking.kind === 'restore' && asking.brief && details && <div className="text-sm">{details(asking.brief)}</div>}
          {asking.kind === 'restore' &&
            (restoreOptions ?? []).map((question) =>
              question.choices ? (
                <SelectField
                  key={question.key}
                  label={question.label}
                  hints={question.hint ? [question.hint] : undefined}
                  value={String(answers[question.key] ?? '')}
                  onChange={(event) => setAnswers({ ...answers, [question.key]: event.target.value })}
                  options={question.choices}
                  data-testid={`restore-option-${question.key}`}
                />
              ) : (
                <CheckboxRow
                  key={question.key}
                  label={question.label}
                  hint={question.hint}
                  checked={answers[question.key] === true}
                  onChange={(checked) => setAnswers({ ...answers, [question.key]: checked })}
                  testId={`restore-option-${question.key}`}
                />
              ),
            )}
          {needsArchivePassword && <Field label={t.archivePassword} type="password" autoComplete="off" value={archiveTyped} onChange={(event) => setArchiveTyped(event.target.value)} hints={[t.archivePasswordHint]} />}
          {needsFilePassword && (
            <>
              <Field label={t.downloadPassword} type="password" autoComplete="new-password" minLength={8} value={archiveTyped} onChange={(event) => setArchiveTyped(event.target.value)} hints={[t.downloadPasswordHint]} />
              <Field
                label={t.downloadPasswordAgain}
                type="password"
                autoComplete="new-password"
                value={againTyped}
                onChange={(event) => setAgainTyped(event.target.value)}
                error={againTyped && againTyped !== archiveTyped ? t.downloadPasswordMismatch : undefined}
              />
            </>
          )}
          {needsPassword && <Field label={t.password} type="password" autoComplete="current-password" value={typed} onChange={(event) => setTyped(event.target.value)} />}
        </ConfirmDialog>
      )}
    </Card>
  )
}

/** The result of a check, as a box: whole or not, too new, blocked, damaged members, the app's findings. */
export function BriefBox({
  brief,
  app,
  texts,
  details,
  language,
  when = defaultWhen,
  blockedText,
}: {
  brief: Brief
  app: string
  texts: SicherungTexts
  details?: (brief: Brief) => ReactNode
  language: Language
  when?: (iso: string, language: Language) => string
  blockedText?: BlockedTexts
}) {
  const t = texts.backup
  let line: string
  if (brief.too_new) line = fill(t.checkNewer, { app, version: brief.version })
  else if (brief.blocked) line = blockedWords(blockedText, brief.blocked, language) ?? (brief.blocked_text || errorText(texts, { code: brief.blocked }, app))
  else line = brief.usable ? t.checkOk : t.checkBad
  return (
    <Box
      title={fillWhen(t.brief, brief.created ? when(brief.created, language) : '')}
      badge={<Badge tone={brief.usable ? 'on' : 'danger'}>{brief.usable ? t.briefOk : t.briefBad}</Badge>}
      testId="backup-brief"
    >
      <p className="m-0 text-sm text-[var(--nexui-text)]">{line}</p>
      {brief.damaged.length > 0 && <p className="m-0 text-xs text-[var(--nexui-danger)]">{fill(t.checkDamaged, { names: brief.damaged.join(', ') })}</p>}
      {brief.usable && details?.(brief)}
    </Box>
  )
}
