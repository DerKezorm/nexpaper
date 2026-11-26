/**
 * Server › Import: taking documents over from Paperless-ngx. Address and token, "connect and
 * look" (what Paperless holds, how it is translated, who is who, where it goes), then the run with its progress. The server connects to Paperless, the run is a job in the background that goes on
 * after a stop, and a second run takes only what is new. The token goes to the server once and never comes back.
 */
import { ArrowRight, Inbox } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, paperlessApi, type PaperlessCheck, type PaperlessRun, type PaperlessSettings, type PaperlessSkipped, type PaperlessSort, type PaperlessWhere } from '../../api/client'
import { useAsk } from './useAsk'
import { errorText } from '../../lib/errors'
import { Button, Card, CheckboxRow, Field, Notice, Segment, SelectField } from '../../vendor/nexui'

const POLL_MS = 2000

/** The sentence for a code of this card: its own words, else the app's. */
function useImportText() {
  const { t, i18n } = useTranslation()
  return useCallback(
    (code: string) => {
      const own = `paperless.errors.${code}`
      return i18n.exists(own) ? t(own) : errorText(code)
    },
    [t, i18n],
  )
}

function codeOf(error: unknown): string {
  return error instanceof ApiError ? error.code : 'internal_error'
}

type Stage = 'form' | 'check' | 'run'

function sameAddress(a: string, b: string): boolean {
  const plain = (value: string) => value.trim().replace(/\/+$/, '').replace(/\/api$/, '').toLowerCase()
  return plain(a) === plain(b)
}

export function ImportCard() {
  const { t } = useTranslation()
  const say = useImportText()
  const [settings, setSettings] = useState<PaperlessSettings | null>(null)
  const [stage, setStage] = useState<Stage>('form')
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')
  const [own, setOwn] = useState(false)
  const [found, setFound] = useState<PaperlessCheck | null>(null)
  const [people, setPeople] = useState<Record<string, number>>({})
  const [where, setWhere] = useState<PaperlessWhere>('owner')
  const [vault, setVault] = useState<number | null>(null)
  const [sort, setSort] = useState<PaperlessSort>('paperless')
  const [busy, setBusy] = useState(false)
  const { ask, dialog } = useAsk()
  const [problem, setProblem] = useState<string | null>(null)

  const take = useCallback((next: PaperlessSettings) => {
    setSettings(next)
    setUrl((before) => before || next.url)
    setOwn(next.private)
    if (next.run.state !== 'idle') setStage((before) => (before === 'form' ? 'run' : before))
  }, [])

  useEffect(() => {
    paperlessApi.read().then(take, (error: unknown) => setProblem(codeOf(error)))
  }, [take])

  // The server keeps the token for the address it was given with: a changed address needs it again.
  const kept = Boolean(settings?.token_set && sameAddress(url, settings.url))
  const running = settings?.run.state === 'queued' || settings?.run.state === 'running'
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => {
      paperlessApi.read().then(setSettings, () => undefined)
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [running])

  const act = async (work: () => Promise<void>) => {
    setBusy(true)
    setProblem(null)
    try {
      await work()
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      setBusy(false)
    }
  }

  const connect = () =>
    act(async () => {
      const change: { url: string; private: boolean; token?: string } = { url: url.trim(), private: own }
      if (token.trim()) change.token = token.trim()
      const saved = await paperlessApi.save(change)
      setSettings(saved)
      setToken('')
      const looked = await paperlessApi.check()
      setFound(looked)
      setPeople(Object.fromEntries(looked.owners.map((owner) => [String(owner.paperless_id), owner.user_id])))
      const firstShared = looked.vaults.find((v) => !v.own) ?? looked.vaults[0]
      setVault(saved.vault_id ?? firstShared?.id ?? null)
      // A vault for each storage path only where Paperless has paths in use.
      setWhere(saved.where === 'storage' && !looked.storage_paths?.length ? 'owner' : saved.where)
      setSort(saved.sort ?? 'paperless')
      setStage('check')
    })

  const start = () =>
    act(async () => {
      if (!found) return
      const next = await paperlessApi.start({
        where,
        vault_id: where === 'vault' ? vault : null,
        sort,
        people: found.owners.map((owner) => ({ paperless_id: owner.paperless_id, user_id: people[String(owner.paperless_id)] ?? owner.user_id })),
      })
      setSettings(next)
      setStage('run')
    })

  return (
    <Card id="paperless" icon={Inbox} title={t('paperless.title')} subtitle={t('paperless.text')}>
      {stage === 'form' && (
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            void connect()
          }}
        >
          <Field label={t('paperless.url')} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="http://paperless:8000" />
          <Field label={t('paperless.token')} type="password" value={token} onChange={(event) => setToken(event.target.value)} hints={[kept ? t('paperless.tokenKept') : t('paperless.tokenHint')]} />
          <div className="sm:col-span-2">
            <CheckboxRow label={t('paperless.private')} hint={t('paperless.privateHint')} checked={own} onChange={setOwn} />
          </div>
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button kind="primary" icon="Plug" type="submit" busy={busy} disabled={!url.trim() || (!token.trim() && !kept)}>
              {t('paperless.connect')}
            </Button>
            {settings?.token_set && (
              <Button
                kind="danger"
                icon="Trash2"
                onClick={() =>
                  ask({
                    title: t('confirm.paperless.title'),
                    text: t('confirm.paperless.text'),
                    confirm: t('confirm.paperless.confirm'),
                    run: async () => {
                      setSettings(await paperlessApi.forget())
                      setUrl('')
                    },
                  })
                }
                disabled={busy}
              >
                {t('paperless.forget')}
              </Button>
            )}
          </div>
        </form>
      )}
      {stage === 'check' && found && (
        <CheckView
          found={found}
          people={people}
          setPeople={setPeople}
          where={where}
          setWhere={setWhere}
          vault={vault}
          setVault={setVault}
          sort={sort}
          setSort={setSort}
          busy={busy}
          onStart={() => void start()}
          onBack={() => setStage('form')}
        />
      )}
      {stage === 'run' && settings && (
        <RunView
          run={settings.run}
          busy={busy}
          onStop={() => void act(async () => setSettings(await paperlessApi.stop()))}
          onResume={() => void act(async () => setSettings(await paperlessApi.resume()))}
          onAgain={() => {
            setFound(null)
            setStage('form')
          }}
        />
      )}
      {problem && <Notice tone="danger">{say(problem)}</Notice>}
      {dialog}
    </Card>
  )
}

function CheckView({
  found,
  people,
  setPeople,
  where,
  setWhere,
  vault,
  setVault,
  sort,
  setSort,
  busy,
  onStart,
  onBack,
}: {
  found: PaperlessCheck
  people: Record<string, number>
  setPeople: (next: Record<string, number>) => void
  where: PaperlessWhere
  setWhere: (next: PaperlessWhere) => void
  vault: number | null
  setVault: (next: number) => void
  sort: PaperlessSort
  setSort: (next: PaperlessSort) => void
  busy: boolean
  onStart: () => void
  onBack: () => void
}) {
  const { t, i18n } = useTranslation()
  const number = (n: number) => n.toLocaleString(i18n.language)
  const chosen = found.vaults.find((v) => v.id === vault)
  const vaultName = (v: { name: string; own: boolean }) => (v.own ? t('paperless.myVault') : v.name)
  const left = Math.max(0, found.documents - found.already)
  const paths = found.storage_paths ?? []
  const inbox = Math.min(found.inbox_documents ?? 0, found.documents)
  const personName = (id: number) => {
    const person = found.people.find((p) => p.id === id)
    return person ? person.display_name || person.name : ''
  }
  return (
    <div className="space-y-4 text-sm">
      <div className="grid gap-3 sm:grid-cols-4">
        {(
          [
            [found.documents, t('paperless.stats.documents')],
            [found.tags, t('paperless.stats.tags')],
            [found.correspondents, t('paperless.stats.correspondents')],
            [found.document_types, t('paperless.stats.types')],
          ] as const
        ).map(([value, label]) => (
          <div key={label} className="rounded-[12px] border border-solid border-[var(--nexui-line)] px-4 py-3">
            <p className="text-2xl font-semibold">{number(value)}</p>
            <p className="text-xs text-[var(--nexui-text-muted)]">{label}</p>
          </div>
        ))}
      </div>
      {found.version && <p className="text-xs text-[var(--nexui-text-muted)]">{t('paperless.version', { version: found.version })}</p>}
      <div>
        <p className="font-semibold">{t('paperless.howTitle')}</p>
        <ul className="mt-1 space-y-0.5 text-[var(--nexui-text-muted)]">
          <li>{t('paperless.how1')}</li>
          <li>{t('paperless.how2')}</li>
          <li>{t('paperless.how3')}</li>
          <li>{t('paperless.how4')}</li>
        </ul>
        {found.new_kinds.length > 0 && <p className="mt-1 text-xs text-[var(--nexui-text-muted)]">{t('paperless.newKinds', { names: found.new_kinds.join(', ') })}</p>}
      </div>
      <div>
        <p className="font-semibold">{t('paperless.ownersTitle')}</p>
        {found.users_hidden && <p className="text-xs text-[var(--nexui-text-muted)]">{t('paperless.usersHidden')}</p>}
        <ul className="mt-2 space-y-1.5">
          {found.owners.map((owner) => {
            const key = String(owner.paperless_id)
            const name = owner.paperless_id === null ? t('paperless.noOwner') : owner.name || t('paperless.unknownOwner', { id: owner.paperless_id })
            return (
              <li key={key} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="w-24 truncate font-mono text-xs" title={name}>
                  {name}
                </span>
                <ArrowRight size={14} className="text-[var(--nexui-text-muted)]" aria-hidden />
                <div className="w-48">
                  <SelectField
                    label={t('paperless.personFor', { name })}
                    value={String(people[key] ?? owner.user_id)}
                    onChange={(event) => setPeople({ ...people, [key]: Number(event.target.value) })}
                    options={found.people.map((person) => ({ value: String(person.id), label: person.display_name || person.name }))}
                  />
                </div>
                {owner.paperless_id !== null && !owner.matched && (
                  <span className="text-xs text-[var(--nexui-text-muted)]">{t('paperless.noMatch', { name: personName(people[key] ?? owner.user_id) })}</span>
                )}
              </li>
            )
          })}
        </ul>
      </div>
      <div>
        <p className="font-semibold">{t('paperless.where')}</p>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <Segment
            value={where}
            onChange={setWhere}
            hideLabel
            label={t('paperless.where')}
            options={[
              { value: 'owner', label: t('paperless.whereOwner') },
              { value: 'vault', label: t('paperless.whereVault', { name: chosen ? vaultName(chosen) : '…' }) },
              ...(paths.length > 0 ? [{ value: 'storage' as const, label: t('paperless.whereStorage') }] : []),
            ]}
          />
          {where === 'vault' && found.vaults.length > 1 && (
            <div className="w-56">
              <SelectField
                label={t('paperless.vault')}
                value={String(vault ?? '')}
                onChange={(event) => setVault(Number(event.target.value))}
                options={found.vaults.map((v) => ({ value: String(v.id), label: vaultName(v) }))}
              />
            </div>
          )}
        </div>
        <p className="mt-1 text-xs text-[var(--nexui-text-muted)]">
          {where === 'owner' ? t('paperless.whereOwnerHint') : where === 'vault' ? t('paperless.whereVaultHint') : t('paperless.whereStorageHint')}
        </p>
        {where === 'storage' && (
          <ul className="mt-2 flex flex-wrap gap-1.5" aria-label={t('paperless.storagePaths')} data-testid="storage-paths">
            {paths.map((path) => (
              <li key={path.name} className="rounded-[9px] border border-solid border-[var(--nexui-line)] px-2.5 py-1 text-xs">
                <span className="font-semibold">{path.name}</span> · {number(path.documents)} · <span className="text-[var(--nexui-text-muted)]">{path.exists ? t('paperless.storageExists') : t('paperless.storageNew')}</span>
              </li>
            ))}
            {(found.without_storage_path ?? 0) > 0 && (
              <li className="rounded-full border border-line px-2.5 py-1 text-xs text-[var(--nexui-text-muted)]">{t('paperless.storageNone', { n: number(found.without_storage_path ?? 0) })}</li>
            )}
          </ul>
        )}
        <p className="mt-1 text-xs text-[var(--nexui-text-muted)]">{t('paperless.whereHint')}</p>
      </div>
      <div>
        <p className="font-semibold">{t('paperless.sortTitle')}</p>
        <div className="mt-2">
          <Segment
            value={sort}
            onChange={setSort}
            hideLabel
            label={t('paperless.sortTitle')}
            options={[
              { value: 'paperless', label: t('paperless.sortPaperless') },
              { value: 'inbox', label: t('paperless.sortInbox') },
            ]}
          />
        </div>
        <p className="mt-1 text-xs text-[var(--nexui-text-muted)]">
          {sort === 'paperless'
            ? t('paperless.sortPaperlessHint', { inbox: number(inbox), total: number(found.documents), filed: number(found.documents - inbox) })
            : t('paperless.sortInboxHint', { total: number(found.documents) })}
        </p>
      </div>
      {found.already > 0 && <p className="text-xs text-[var(--nexui-text-muted)]">{t('paperless.already', { n: number(found.already) })}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        <Button kind="secondary" icon="ArrowLeft" onClick={onBack}>
          {t('paperless.back')}
        </Button>
        <Button kind="primary" icon="Download" onClick={onStart} busy={busy} disabled={left === 0 || (where === 'vault' && vault === null)}>
          {t('paperless.go', { n: number(left) })}
        </Button>
      </div>
    </div>
  )
}

function RunView({ run, busy, onStop, onResume, onAgain }: { run: PaperlessRun; busy: boolean; onStop: () => void; onResume: () => void; onAgain: () => void }) {
  const { t, i18n } = useTranslation()
  const say = useImportText()
  const number = (n: number) => n.toLocaleString(i18n.language)
  // The bar counts what was looked at: taken in the accent colour, skipped set apart in a second one. When the run is
  // done it is full, however the numbers fall.
  const finished = run.state === 'done'
  const share = (n: number) => (run.total > 0 ? Math.min(100, (n / run.total) * 100) : 0)
  const takenShare = finished && run.skipped === 0 ? 100 : share(run.done)
  const skippedShare = finished ? Math.max(0, 100 - takenShare) : Math.min(share(run.skipped), 100 - takenShare)
  const progress = finished ? 100 : Math.min(100, Math.round(takenShare + skippedShare))
  const values = { n: number(run.done), total: number(run.total) }
  let sentence: string
  if (run.state === 'done') sentence = run.skipped > 0 ? t('paperless.doneSkipped', { n: number(run.done), skipped: number(run.skipped) }) : t('paperless.done', values)
  else if (run.state === 'paused') sentence = t('paperless.paused', values)
  else if (run.state === 'failed') sentence = t('paperless.failed', { ...values, why: say(run.error || 'failed') })
  else if (run.state === 'queued') sentence = t('paperless.queued', values)
  else sentence = t('paperless.running', values)
  const listed = run.skipped > 0 && run.state !== 'queued' && run.state !== 'running'
  return (
    <div className="space-y-3 text-sm">
      <div className="flex h-3 overflow-hidden rounded-full bg-[var(--nexui-line)]" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
        <div className="h-full bg-[var(--nexui-accent)] transition-all" style={{ width: `${takenShare}%` }} />
        {skippedShare > 0 && <div data-testid="skipped-part" className="h-full bg-[var(--nexui-text-muted)] opacity-60 transition-all" style={{ width: `${skippedShare}%` }} />}
      </div>
      <p className="text-[var(--nexui-text-muted)]" aria-live="polite">
        {sentence}
      </p>
      {run.stop && (run.state === 'running' || run.state === 'queued') && <p className="text-xs text-[var(--nexui-text-muted)]">{t('paperless.stopping')}</p>}
      {listed && <SkippedList key={`${run.state}-${run.skipped}-${run.finished_at ?? ''}`} />}
      {run.state === 'done' && <p className="text-xs text-[var(--nexui-text-muted)]">{t('paperless.again')}</p>}
      <div className="flex flex-wrap gap-2">
        {(run.state === 'running' || run.state === 'queued') && !run.stop && (
          <Button kind="danger" icon="Ban" onClick={onStop} busy={busy}>
            {t('paperless.stop')}
          </Button>
        )}
        {(run.state === 'paused' || run.state === 'failed') && (
          <Button kind="primary" icon="RotateCcw" onClick={onResume} busy={busy}>
            {t('paperless.resume')}
          </Button>
        )}
        {(run.state === 'done' || run.state === 'paused' || run.state === 'failed') && (
          <Button kind="secondary" icon="RefreshCw" onClick={onAgain} disabled={busy}>
            {run.state === 'done' ? t('paperless.runAgain') : t('paperless.other')}
          </Button>
        )}
      </div>
    </div>
  )
}

/** The documents that were not taken: the number in Paperless and why, in plain words (no title, nothing of Paperless). */
function SkippedList() {
  const { t, i18n } = useTranslation()
  const [found, setFound] = useState<PaperlessSkipped | null>(null)
  useEffect(() => {
    let alive = true
    paperlessApi.skipped().then(
      (next) => alive && setFound(next),
      () => undefined,
    )
    return () => {
      alive = false
    }
  }, [])
  if (!found || found.items.length === 0) return null
  const reason = (code: string) => (i18n.exists(`paperless.reasons.${code}`) ? t(`paperless.reasons.${code}`) : t('paperless.reasons.other'))
  return (
    <div>
      <p className="flex items-center gap-2 font-semibold">
        <span className="inline-block h-2.5 w-2.5 rounded-full bg-[var(--nexui-text-muted)] opacity-60" aria-hidden />
        {t('paperless.skippedTitle')}
      </p>
      <ul className="mt-1 space-y-0.5 text-[var(--nexui-text-muted)]" aria-label={t('paperless.skippedTitle')}>
        {found.items.map((item) => (
          <li key={item.paperless_id}>
            <span className="font-mono text-xs">{t('paperless.skippedNumber', { id: item.paperless_id })}</span>
            {': '}
            {reason(item.reason)}
          </li>
        ))}
      </ul>
      {found.more > 0 && <p className="mt-1 text-xs text-[var(--nexui-text-muted)]">{t('paperless.skippedMore', { n: found.more.toLocaleString(i18n.language) })}</p>}
    </div>
  )
}
