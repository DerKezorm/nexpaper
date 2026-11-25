/**
 * The operator's part of the settings, laid out card by card as nexnotes' (`pages/settings/ServerCards.tsx` and
 * `AccountsTab.tsx` there): accounts and invitations, the API keys of all accounts, mail, storage and backups,
 * languages and the log. Sign-in (password, public address, second factor, providers, authentik) is in
 * ``SignInCards.tsx``. Everything here is the
 * server's; it applies to all. The operator manages accounts and does not read the documents in them.
 */
import { AlertTriangle, Download, FileText, Globe, HardDrive, Info, KeyRound, Mail, RotateCcw, ShieldCheck, Trash2, Upload } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, api, apiKeysApi, passwordHeader, type AddressQuestion, type AnyApiKey } from '../../api/client'
import { useConfirm } from '../../components/useConfirm'
import { byName, forgetAddedLanguages, templateFile } from '../../i18n'
import { iso } from '../../lib/say'
import { useAuth } from '../../state/auth'
import { SpaceBlock, type StorageInfo } from './FilesCards'
import { Button, Card, Confirm, Feedback, Input, saveAsFile, Select, useAction } from './ui'

export type ServerSettings = {
  public_url: string
  password_login: boolean
  two_factor_required: boolean
  backup_schedule: 'off' | 'daily' | 'weekly'
  backup_keep: number
  smtp_host: string
  smtp_port: number
  smtp_security: 'starttls' | 'tls' | 'none'
  smtp_user: string
  smtp_password_set: boolean
  smtp_from: string
  /** The name system mail goes out under (the shared post module); empty: "nexpaper". */
  smtp_sender_name?: string
  /** The shared account module's switch: passkeys may be added and used (on from the start). */
  passkeys_allowed?: boolean
  api_keys_allowed: boolean
  update_check: boolean
  links_allowed: boolean
  link_max_days: number
  upload_max_mb: number
  upload_max_pages: number
  upload_max_megapixels: number
  upload_open_count: number
  upload_open_mb: number
  process_timeout_seconds: number
  process_memory_mb: number
  cache_max_mb: number
  /** U1: upload requests, off from the start. */
  upload_requests_allowed?: boolean
}

type Change = Partial<ServerSettings> & { smtp_password?: string; current_password?: string; confirm_address?: boolean }
type Server = ReturnType<typeof useServerSettings>

// eslint-disable-next-line react-refresh/only-export-components
export function useServerSettings() {
  const [settings, setSettings] = useState<ServerSettings | null>(null)
  const action = useAction()
  const reload = useCallback(async () => {
    const fresh = await api<ServerSettings>('/api/v1/settings')
    setSettings(fresh)
    return fresh
  }, [])
  useEffect(() => {
    reload().catch(() => undefined)
  }, [reload])
  /** Straight to the server, without the switch moving first (a change asked with the operator's password). */
  const saveNow = async (change: Change) => setSettings(await api<ServerSettings>('/api/v1/settings', { method: 'PUT', body: change }))
  /**
   * The public address. While the authentik button registered the old one, or a provider entered by hand is on, the
   * server asks first (409 `public_url_change`, nothing saved): the question comes back for the page to ask
   *; with `confirm` it is saved. Null: saved, or refused for another reason (shown by `problem`).
   */
  const saveAddress = async (public_url: string, confirm = false): Promise<AddressQuestion | null> => {
    let question: AddressQuestion | null = null
    await action.run(async () => {
      try {
        setSettings(await api<ServerSettings>('/api/v1/settings', { method: 'PUT', body: { public_url, confirm_address: confirm } }))
      } catch (error) {
        if (!(error instanceof ApiError) || error.code !== 'public_url_change') throw error
        question = { count: Number(error.values.count ?? 0), address: String(error.values.address ?? ''), hand: Number(error.values.hand ?? 0) }
      }
    })
    return question
  }
  /** The switch moves at once; the server's answer confirms it, a refusal puts it back. */
  const save = async (change: Change, done?: string) => {
    const before = settings
    if (settings) setSettings({ ...settings, ...change })
    const ok = await action.run(async () => setSettings(await api<ServerSettings>('/api/v1/settings', { method: 'PUT', body: change })), done)
    if (!ok) setSettings(before)
  }
  return { settings, save, saveNow, saveAddress, reload, setSettings, ...action }
}

/** What the interface offers programs: the description and how a device or a key signs in. */
export function InterfaceCard() {
  const { t } = useTranslation()
  const rows: [string, string, string][] = [
    [t('server.interface.docs'), '/api/v1/docs', t('server.interface.docsText')],
    [t('server.interface.schema'), '/api/v1/openapi.json', t('server.interface.schemaText')],
    [t('server.interface.pair'), 'POST /api/v1/devices/pair', t('server.interface.pairText')],
    [t('server.interface.auth'), 'Authorization: Bearer …', t('server.interface.authText')],
  ]
  return (
    <Card id="interface" icon={FileText} title={t('server.interface.title')} text={t('server.interface.text')}>
      <ul className="space-y-2 text-sm">
        {rows.map(([name, code, text]) => (
          <li key={name} className="rounded-xl border border-line bg-sheet-2/50 px-4 py-3">
            <span className="font-semibold">{name}</span>{' '}
            {code.startsWith('/') ? (
              <a href={code} target="_blank" rel="noreferrer" className="ml-1 rounded bg-sheet px-1.5 py-0.5 font-mono text-xs text-accent hover:underline">
                {code}
              </a>
            ) : (
              <code className="ml-1 rounded bg-sheet px-1.5 py-0.5 font-mono text-xs text-accent">{code}</code>
            )}
            <span className="block text-xs text-muted">{text}</span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted">{t('server.interface.limits')}</p>
    </Card>
  )
}

/** "API-Schlüssel aller Konten", as nexnotes' card of all tokens: every key there is, whose it is, what it is called,
 * what it may and when it was used; blocked for good on request (every way out needs a latch). Never the key itself.
 * The switch that allows keys at all is under General, "Funktionen für alle Konten". */
export function AllApiKeysCard() {
  const { t, i18n } = useTranslation()
  const { busy, problem, run } = useAction()
  const [keys, setKeys] = useState<AnyApiKey[] | null>(null)
  const [blocking, setBlocking] = useState<AnyApiKey | null>(null)
  const load = useCallback(() => {
    apiKeysApi.every().then(setKeys, () => setKeys(null))
  }, [])
  useEffect(load, [load])
  const lang = i18n.language
  const describe = (key: AnyApiKey) =>
    [
      key.scope === 'upload' ? t('phone.keys.uploadOne') : t('apiKeys.readOnlyOne'),
      key.expires_at ? t('apiKeys.runsOut', { day: new Date(key.expires_at).toLocaleDateString(lang) }) : t('apiKeys.never'),
      key.last_used_at ? t('apiKeys.used', { when: new Date(key.last_used_at).toLocaleString(lang, { dateStyle: 'short', timeStyle: 'short' }) }) : t('apiKeys.unused'),
    ].join(' · ')
  return (
    <Card id="all-api-keys" icon={KeyRound} title={t('server.apiKeys.title')} text={t('server.apiKeys.text')}>
      {keys && keys.length === 0 && (
        <p className="text-sm text-muted" data-testid="admin-api-keys-none">
          {t('server.apiKeys.none')}
        </p>
      )}
      {keys && keys.length > 0 && (
        <ul className="flex flex-col" data-testid="admin-api-keys">
          {keys.map((key) => (
            <li key={key.id} className="flex items-center gap-3 border-b border-line py-2.5 last:border-0">
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate text-sm">
                  <span className="text-muted">{key.account}</span> · {key.name} <code className="font-mono text-xs text-muted">{key.prefix}…</code>
                </span>
                <span className="text-xs text-muted">{describe(key)}</span>
              </span>
              {key.blocked ? (
                <span className="text-xs text-bad">{t('server.apiKeys.blocked')}</span>
              ) : (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setBlocking(key)}
                  aria-label={t('server.apiKeys.blockNamed', { name: key.name, account: key.account })}
                  className="text-[13px] text-bad hover:underline disabled:opacity-50"
                >
                  {t('server.apiKeys.block')}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted">{t('server.apiKeys.offHint')}</p>
      <p className="text-sm">
        <Link to="/settings/connections" className="font-semibold text-accent underline decoration-accent/40 underline-offset-4">
          {t('server.apiKeys.own')}
        </Link>
      </p>
      <Feedback problem={problem} />
      {blocking && (
        <Confirm
          title={t('server.apiKeys.blockTitle', { name: blocking.name, account: blocking.account })}
          text={t('server.apiKeys.blockText')}
          confirm={t('server.apiKeys.block')}
          danger
          onCancel={() => setBlocking(null)}
          onConfirm={async () => {
            await run(async () => {
              await apiKeysApi.block(blocking.id)
              load()
            })
            setBlocking(null)
          }}
        />
      )}
    </Card>
  )
}

export function MailCard({ server }: { server: Server }) {
  const { t } = useTranslation()
  const s = server.settings
  const [draft, setDraft] = useState<Change>({})
  const [to, setTo] = useState('')
  const test = useAction()
  if (!s) return null
  const value = { ...s, ...draft }
  return (
    <Card id="mail" icon={Mail} title={t('server.mail')} text={t('server.mailHint')}>
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault()
          test.clear()
          void server.save(draft, t('settings.saved')).then(() => setDraft({}))
        }}
      >
        <Input label={t('server.smtpHost')} value={value.smtp_host} onChange={(smtp_host) => setDraft({ ...draft, smtp_host })} placeholder="smtp.example.com" />
        <Input label={t('server.smtpPort')} type="number" value={String(value.smtp_port)} onChange={(port) => setDraft({ ...draft, smtp_port: Number(port) })} />
        <Select
          label={t('server.smtpSecurity')}
          value={value.smtp_security}
          onChange={(smtp_security) => setDraft({ ...draft, smtp_security })}
          options={[
            { value: 'starttls', label: 'STARTTLS' },
            { value: 'tls', label: 'TLS' },
            { value: 'none', label: t('server.none') },
          ]}
        />
        <Input label={t('server.smtpUser')} value={value.smtp_user} onChange={(smtp_user) => setDraft({ ...draft, smtp_user })} />
        <Input label={t('auth.password')} type="password" autoComplete="new-password" value={draft.smtp_password ?? ''} onChange={(smtp_password) => setDraft({ ...draft, smtp_password })} placeholder={s.smtp_password_set ? t('server.secretKept') : ''} />
        <Input label={t('server.smtpFrom')} value={value.smtp_from} onChange={(smtp_from) => setDraft({ ...draft, smtp_from })} placeholder="paper@example.com" />
        <Input label={t('mail.senderName')} hint={t('mail.senderNameHint')} value={value.smtp_sender_name ?? ''} onChange={(smtp_sender_name) => setDraft({ ...draft, smtp_sender_name })} maxLength={80} />
        <div className="sm:col-span-2">
          <Button type="submit" primary busy={server.busy}>
            {t('common.save')}
          </Button>
        </div>
      </form>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          server.clear()
          void test.run(() => api('/api/v1/settings/mail-test', { method: 'POST', body: { to } }), t('server.mailSent'))
        }}
      >
        <Input label={t('server.mailTest')} value={to} onChange={setTo} placeholder="jule@example.com" className="min-w-60 flex-1" />
        <Button type="submit" busy={test.busy} disabled={!to.trim()}>
          {t('server.send')}
        </Button>
      </form>
      {/* One line for both, as in nexnotes: what the test said, else what saving said. */}
      <Feedback problem={test.problem ?? server.problem} done={test.done ?? server.done} values={test.problem ? test.values : server.values} />
    </Card>
  )
}

type Backup = { name: string; size: number; created: string; kind: string; note: string; accounts: number; version: string; uploaded?: boolean; documents?: number }
type Brief = {
  usable: boolean
  too_new: boolean
  accounts: number
  documents: number
  missing_documents: number
  changed_documents: number
  not_compared: number
  newer_documents: number
  rebuilds_index: boolean
  /** Devices, keys and links that were valid in the backup and are revoked, blocked or gone on this server now: a
   * restore brings them back to life. */
  revived_devices?: number
  revived_keys?: number
  revived_links?: number
  /** Further documents (N2) a restore puts back on a link: on one that comes back, or taken out of one since. */
  revived_link_documents?: number
  /** Kept PDF passwords the backup holds that are deleted here now: a restore brings them back (a number only). */
  revived_pdf_passwords?: number
  /** Upload requests (U1) a restore would open again. */
  revived_upload_requests?: number
  created: string
}

/** What a restore would do, line by line: the documents the backup knows, which files are missing or changed on the disk,
 * which documents of today would go, and that the search is built anew. */
function PreviewLines({ brief }: { brief: Brief }) {
  const { t } = useTranslation()
  const lines: string[] = []
  if (brief.documents > 0) {
    lines.push(t('server.restorePreview.documents', { count: brief.documents }))
    if (brief.missing_documents === 0 && brief.changed_documents === 0) lines.push(t('server.restorePreview.allThere'))
    if (brief.missing_documents > 0) lines.push(t('server.restorePreview.missing', { count: brief.missing_documents }))
    if (brief.changed_documents > 0) lines.push(t('server.restorePreview.changed', { count: brief.changed_documents }))
    if (brief.not_compared > 0) lines.push(t('server.restorePreview.notCompared', { count: brief.not_compared }))
  }
  if (brief.newer_documents > 0) lines.push(t('server.restorePreview.newer', { count: brief.newer_documents }))
  if (brief.revived_devices) lines.push(t('server.restorePreview.revivedDevices', { count: brief.revived_devices }))
  if (brief.revived_keys) lines.push(t('server.restorePreview.revivedKeys', { count: brief.revived_keys }))
  if (brief.revived_links) lines.push(t('server.restorePreview.revivedLinks', { count: brief.revived_links }))
  if (brief.revived_link_documents) lines.push(t('linkRelated.revived', { count: brief.revived_link_documents }))
  if (brief.revived_pdf_passwords) lines.push(t('server.restorePreview.revivedPdfPasswords', { count: brief.revived_pdf_passwords }))
  if (brief.revived_upload_requests) lines.push(t('uploadRequest.revived', { count: brief.revived_upload_requests }))
  if (brief.rebuilds_index) lines.push(t('server.restorePreview.index'))
  return (
    <ul className="mt-2 space-y-1 text-xs" data-testid="restore-preview">
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  )
}

/**
 * "Speicher und Sicherung", as nexnotes' card "Speicher und Backups": on top what nexpaper takes on its disk (when the
 * area hands it in), then that the documents themselves are not in a backup, the last backup, one row with the schedule,
 * how many to keep, "Sicherung hochladen" and "Jetzt sichern", and the list of backups with their small buttons.
 */
export function BackupsCard({ server, space = null }: { server: Server; space?: StorageInfo | null }) {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [list, setList] = useState<Backup[]>([])
  const [brief, setBrief] = useState<(Brief & { name: string }) | null>(null)
  const [asking, setAsking] = useState<{ kind: 'restore' | 'download' | 'delete' | 'upload'; name: string; file?: File; brief?: Brief } | null>(null)
  const picker = useRef<HTMLInputElement>(null)
  const [keep, setKeep] = useState<string | null>(null)
  const [restarting, setRestarting] = useState(false)
  const [uploaded, setUploaded] = useState(false)
  const action = useAction()
  const load = useCallback(() => {
    api<Backup[]>('/api/v1/backups').then(setList, () => undefined)
  }, [])
  useEffect(load, [load])
  const s = server.settings
  if (!s) return null
  const lang = i18n.language
  const size = (bytes: number) => (bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`)
  const moment = (value: string) => new Date(value).toLocaleString(lang)
  const forBackup = (entry: Backup, verb: string) => t('server.forBackup', { name: moment(entry.created), action: verb })
  // The server lists the newest first.
  const last = list[0]
  const small = 'h-3.5 w-3.5'
  return (
    <Card id="backups" icon={HardDrive} title={t('server.storageBackups')} text={t('server.backupsHint')}>
      {space && <SpaceBlock info={space} />}
      <div className="flex items-start gap-3 rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm" data-testid="backup-without-documents">
        <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
        <span>
          <span className="font-semibold">{t('server.backupNoDocuments')}</span>
          <span className="block text-xs text-ink-2">{t('server.backupNoDocumentsText')}</span>
        </span>
      </div>
      <p className="text-sm text-ink-2" data-testid="last-backup">
        {last ? t('server.lastBackup', { time: moment(last.created) }) : t('server.noBackups')}
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <Select
          label={t('server.schedule')}
          value={s.backup_schedule}
          onChange={(backup_schedule) => void server.save({ backup_schedule })}
          options={[
            { value: 'off', label: t('server.off') },
            { value: 'daily', label: t('server.daily') },
            { value: 'weekly', label: t('server.weekly') },
          ]}
          className="w-44"
        />
        <form
          className="flex items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            void server.save({ backup_keep: Math.max(1, Math.min(365, Number(keep ?? s.backup_keep) || 7)) }, t('settings.saved'))
          }}
        >
          <Input label={t('server.keep')} type="number" min={1} max={365} value={keep ?? String(s.backup_keep)} onChange={setKeep} className="w-28" />
          <Button type="submit" busy={server.busy}>
            {t('common.save')}
          </Button>
        </form>
        <span className="ml-auto flex flex-wrap gap-2">
          <input
            ref={picker}
            type="file"
            accept=".zip,application/zip"
            className="hidden"
            aria-label={t('server.uploadBackup')}
            onChange={(event) => {
              const file = event.target.files?.[0]
              event.target.value = ''
              if (file) setAsking({ kind: 'upload', name: file.name, file })
            }}
          />
          <Button onClick={() => picker.current?.click()}>
            <Upload size={16} aria-hidden />
            {t('server.uploadBackup')}
          </Button>
          <Button
            primary
            busy={action.busy}
            onClick={() =>
              void action.run(async () => {
                await api('/api/v1/backups', { method: 'POST', body: { note: '' } })
                load()
              }, t('server.backupMade'))
            }
          >
            {t('server.backupNow')}
          </Button>
        </span>
      </div>
      <Feedback problem={server.problem} done={server.done} />
      {/* Without backups the line above says so once; an empty list would say it a second time. */}
      {list.length > 0 && (
        <ul className="divide-y divide-line rounded-[12px] border border-line text-sm" data-testid="backup-list">
          {list.map((entry) => (
            <li key={entry.name} className="flex flex-wrap items-center gap-2 px-4 py-2.5">
              <span className="min-w-0 flex-1">
                <span className="block">{moment(entry.created)}</span>
                <span className="block text-xs text-muted">
                  {entry.uploaded ? t('server.uploaded') : t(`server.kinds.${entry.kind}`)} · {t('server.countAccounts', { count: entry.accounts })}
                  {entry.documents ? `, ${t('server.countDocuments', { count: entry.documents })}` : ''} · {size(entry.size)} · {entry.version}
                </span>
              </span>
              <span className="flex flex-wrap gap-1.5">
                <Button small label={forBackup(entry, t('server.check'))} onClick={() => void action.run(async () => setBrief({ ...(await api<Brief>(`/api/v1/backups/${entry.name}/check`, { method: 'POST' })), name: entry.name }))}>
                  <ShieldCheck className={small} aria-hidden />
                  {t('server.check')}
                </Button>
                <Button small label={forBackup(entry, t('server.download'))} onClick={() => setAsking({ kind: 'download', name: entry.name })}>
                  <Download className={small} aria-hidden />
                  {t('server.download')}
                </Button>
                <Button
                  small
                  label={forBackup(entry, t('server.restore'))}
                  onClick={() =>
                    // The trial run first: the dialog that asks for the password tells what the restore would do.
                    void action.run(async () => {
                      const found = await api<Brief>(`/api/v1/backups/${entry.name}/check`, { method: 'POST' })
                      if (found.usable) setAsking({ kind: 'restore', name: entry.name, brief: found })
                      else setBrief({ ...found, name: entry.name })
                    })
                  }
                >
                  <RotateCcw className={small} aria-hidden />
                  {t('server.restore')}
                </Button>
                <Button small danger label={forBackup(entry, t('server.deleteBackup'))} onClick={() => setAsking({ kind: 'delete', name: entry.name })}>
                  <Trash2 className={small} aria-hidden />
                  {t('server.deleteBackup')}
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {brief && (
        <div className={'rounded-xl border px-4 py-3 text-sm ' + (brief.usable ? 'border-accent/40 bg-accent-soft/50' : 'border-bad/40 bg-bad/10 text-bad')} data-testid="trial-run">
          {brief.usable
            ? t('server.checkOk', { accounts: t('server.countAccounts', { count: brief.accounts }) })
            : brief.too_new
              ? t('server.checkNewer')
              : t('server.checkBad')}
          {brief.usable && <PreviewLines brief={brief} />}
        </div>
      )}
      <p className="text-xs text-muted">{t('server.sizeNote')}</p>
      {uploaded && <p className="rounded-xl border border-accent/40 bg-accent-soft/50 px-4 py-3 text-sm">{t('server.uploadedHint')}</p>}
      {restarting && <p className="rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-warn">{t('server.restarting')}</p>}
      <Feedback problem={action.problem} done={action.done} />
      {asking && (
        <Confirm
          title={t(`server.confirm.backup_${asking.kind}.title`)}
          text={
            asking.kind === 'restore' && asking.brief ? (
              <>
                {t('server.confirm.backup_restore.text')}
                <PreviewLines brief={asking.brief} />
              </>
            ) : (
              t(`server.confirm.backup_${asking.kind}.text`)
            )
          }
          confirm={t(`server.confirm.backup_${asking.kind}.button`)}
          danger={asking.kind !== 'download'}
          password={me?.sign_in === 'password'}
          onCancel={() => setAsking(null)}
          onConfirm={async (password) => {
            if (asking.kind === 'download') {
              const blob = await api<Blob>(`/api/v1/backups/${asking.name}/download`, { method: 'POST', body: { password }, blob: true })
              saveAsFile(asking.name, blob)
            }
            if (asking.kind === 'delete') {
              await api(`/api/v1/backups/${asking.name}`, { method: 'DELETE', body: { password } })
              load()
            }
            if (asking.kind === 'upload' && asking.file) {
              await api('/api/v1/backups/upload', { method: 'POST', raw: asking.file, headers: { 'X-Nexpaper-Password': passwordHeader(password) } })
              load()
              setUploaded(true)
            }
            if (asking.kind === 'restore') {
              await api(`/api/v1/backups/${asking.name}/restore`, { method: 'POST', body: { password } })
              setRestarting(true)
              window.setTimeout(() => window.location.reload(), 8000)
            }
            setAsking(null)
          }}
        />
      )}
    </Card>
  )
}

type Locale = { code: string; name: string; keys: number }

export function LanguagesCard() {
  const { t } = useTranslation()
  const [list, setList] = useState<Locale[]>([])
  const [code, setCode] = useState('')
  const file = useRef<HTMLInputElement>(null)
  const action = useAction()
  const { ask, dialog } = useConfirm()
  const load = useCallback(() => {
    api<Locale[]>('/api/v1/locales').then((rows) => setList(rows.sort(byName)), () => undefined)
  }, [])
  useEffect(load, [load])
  const chip = 'flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold'
  return (
    <Card id="languages" icon={Globe} title={t('server.languages')} text={t('server.languagesHint')}>
      <div className="flex flex-wrap gap-2">
        <span className={chip + ' border-line text-ink-2'}>Deutsch · {t('server.builtIn')}</span>
        <span className={chip + ' border-line text-ink-2'}>English · {t('server.builtIn')}</span>
        {list.map((entry) => (
          <span key={entry.code} className={chip + ' border-accent/40 text-ink'}>
            {entry.name} ({entry.code}) · {t('server.texts', { count: entry.keys })}
            <button
              type="button"
              aria-label={t('server.removeLanguage', { name: entry.name })}
              className="text-muted hover:text-bad"
              onClick={() =>
                ask({
                  title: t('confirm.locale.title'),
                  text: t('confirm.locale.text', { name: iso(entry.name) }),
                  confirm: t('confirm.locale.confirm'),
                  run: async () => {
                    await api(`/api/v1/locales/${entry.code}`, { method: 'DELETE' })
                    forgetAddedLanguages()
                    load()
                  },
                })
              }
            >
              <Trash2 size={12} />
            </button>
          </span>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Button onClick={() => saveAsFile('nexpaper-language-template.json', templateFile())}>
          <Download size={16} />
          {t('server.template')}
        </Button>
        <Input label={t('server.languageCode')} value={code} onChange={(value) => setCode(value.trim())} placeholder="es" className="w-28" />
        <Button disabled={!code} busy={action.busy} onClick={() => file.current?.click()}>
          <Upload size={16} />
          {t('server.upload')}
        </Button>
        <input
          ref={file}
          type="file"
          accept="application/json,.json"
          aria-label={t('server.upload')}
          className="hidden"
          onChange={(e) => {
            const chosen = e.target.files?.[0]
            e.target.value = ''
            if (!chosen) return
            void action.run(async () => {
              await api(`/api/v1/locales/${encodeURIComponent(code)}`, { method: 'PUT', raw: chosen })
              forgetAddedLanguages()
              load()
            }, t('server.languageAdded'))
          }}
        />
      </div>
      <Feedback problem={action.problem} done={action.done} />
      {dialog}
    </Card>
  )
}

type LogLine = { time: string; level: string; logger: string; message: string; request_id?: string | null; user?: string | null }
type LogMode = { mode: string; until: string | null; fixed_by_env: boolean; modes: string[] }

const LOG_LEVELS = ['', 'INFO', 'WARNING', 'ERROR'] as const
/** The newest lines shown; the server gives no older ones page by page, so there is no "load older". */
const LOG_LINES = 300
const TONE: Record<string, string> = { DEBUG: 'text-muted', INFO: 'text-muted', WARNING: 'font-semibold text-warn', ERROR: 'font-semibold text-bad', CRITICAL: 'font-semibold text-bad' }

/**
 * "Log", laid out as nexnotes' card: one bar with chips for the level (a level shows the higher ones too), a search in
 * the text, the level of detail, download and clear (asks first); below a table of time, level, source, request and
 * account, message, and on a phone a card per line instead (no table, no sideways scrolling). The newest come first.
 */
export function LogCard() {
  const { t } = useTranslation()
  const [lines, setLines] = useState<LogLine[] | null>(null)
  const [level, setLevel] = useState('')
  const [words, setWords] = useState('')
  const [mode, setMode] = useState<LogMode | null>(null)
  const [clearing, setClearing] = useState(false)
  const action = useAction()
  const load = useCallback(() => {
    api<LogLine[]>('/api/v1/logs', { query: { level: level || undefined, search: words.trim() || undefined, limit: LOG_LINES } }).then(setLines, () => undefined)
  }, [level, words])
  useEffect(() => {
    const timer = window.setTimeout(load, 250)
    return () => window.clearTimeout(timer)
  }, [load])
  useEffect(() => {
    api<LogMode>('/api/v1/logs/level').then(setMode, () => undefined)
  }, [])
  const request = (line: LogLine) =>
    line.request_id ? (
      <button type="button" onClick={() => setWords(line.request_id ?? '')} title={t('server.logRequestHint')} className="font-mono text-accent hover:underline">
        {line.request_id}
      </button>
    ) : (
      <span className="text-muted">–</span>
    )
  const td = 'border-b border-line/60 px-3 py-1.5 align-top'
  return (
    <Card id="log" icon={Info} title={t('server.log')} text={t('server.logHint')}>
      <div className="flex flex-wrap items-center gap-2" data-testid="log-bar">
        <div role="radiogroup" aria-label={t('server.level')} className="flex flex-wrap gap-1.5">
          {LOG_LEVELS.map((value) => (
            <button
              key={value || 'all'}
              type="button"
              role="radio"
              aria-checked={level === value}
              onClick={() => setLevel(value)}
              className={'rounded-full border px-3 py-1 text-[13px] font-medium ' + (level === value ? 'chosen border-accent/50' : 'border-line text-muted hover:text-ink')}
              data-testid={`log-level-${value || 'all'}`}
            >
              {value || t('server.logAll')}
            </button>
          ))}
        </div>
        <input
          type="search"
          value={words}
          onChange={(event) => setWords(event.target.value)}
          placeholder={t('server.logSearch')}
          aria-label={t('server.logSearch')}
          className="input h-9 min-w-40 flex-1"
          data-testid="log-search"
        />
        {mode && (
          <label className="flex items-center gap-2 text-[13px] text-muted">
            {t('server.detail')}
            <select
              className="input h-9 w-auto px-2"
              value={mode.mode}
              disabled={mode.fixed_by_env}
              data-testid="log-mode"
              onChange={(e) => void action.run(async () => setMode(await api<LogMode>('/api/v1/logs/level', { method: 'PUT', body: { mode: e.target.value, minutes: e.target.value === 'detailed' || e.target.value === 'trace' ? 60 : 0 } })))}
            >
              {mode.modes.map((value) => (
                <option key={value} value={value}>
                  {t(`server.levels.${value}`)}
                </option>
              ))}
            </select>
          </label>
        )}
        <a href="/api/v1/logs/download" className="btn btn-ghost h-9">
          <Download size={16} aria-hidden />
          {t('server.download')}
        </a>
        <Button danger className="h-9" onClick={() => setClearing(true)}>
          <Trash2 size={16} aria-hidden />
          {t('server.logClear')}
        </Button>
      </div>
      <p className="-mt-1 text-xs text-muted">{t('server.logLevelHint')}</p>
      {mode?.until && <p className="text-xs text-muted">{t('server.logUntil', { time: new Date(mode.until).toLocaleTimeString() })}</p>}
      <Feedback problem={action.problem} done={action.done} />
      {lines?.length === 0 && <p className="rounded-[12px] border border-dashed border-line px-6 py-10 text-center text-sm text-muted">{t('server.logEmpty')}</p>}
      {lines && lines.length > 0 && (
        <>
          <div className="hidden overflow-hidden rounded-[12px] border border-line md:block">
            <table className="w-full table-fixed border-separate border-spacing-0 text-left text-xs" data-testid="log-table" role="log">
              <colgroup>
                <col className="w-[9.5rem]" />
                <col className="w-[5.5rem]" />
                <col className="w-[9rem]" />
                <col className="w-[9rem]" />
                <col />
              </colgroup>
              <thead className="text-muted">
                <tr>
                  {(['logTime', 'level', 'logSource', 'logRequest', 'logMessage'] as const).map((key) => (
                    <th key={key} className="border-b border-line px-3 py-2 font-medium">
                      {t(`server.${key}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {lines.map((line, index) => (
                  <tr key={index} data-testid="log-row" data-level={line.level}>
                    <td className={td + ' whitespace-nowrap text-muted'}>{line.time}</td>
                    <td className={td + ' ' + (TONE[line.level] ?? '')} data-testid="log-level">
                      {line.level}
                    </td>
                    <td className={td + ' truncate text-muted'} title={line.logger}>
                      {line.logger}
                    </td>
                    <td className={td}>
                      <span className="flex flex-col">
                        {request(line)}
                        {line.user && <span className="truncate text-muted">{line.user}</span>}
                      </span>
                    </td>
                    <td className={td + ' break-words whitespace-pre-wrap text-ink-2'}>{line.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="flex flex-col gap-2 md:hidden" data-testid="log-cards" role="log">
            {lines.map((line, index) => (
              <li key={index} className="rounded-[10px] border border-line px-3 py-2 text-xs" data-testid="log-card">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className={TONE[line.level] ?? ''}>{line.level}</span>
                  <span className="text-muted">{line.time}</span>
                  <span className="min-w-0 truncate text-muted">{line.logger}</span>
                </div>
                <p className="mt-1 break-words whitespace-pre-wrap text-ink-2">{line.message}</p>
                {(line.request_id || line.user) && (
                  <div className="mt-1 flex flex-wrap gap-2">
                    {line.request_id && request(line)}
                    {line.user && <span className="text-muted">{line.user}</span>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {clearing && (
        <Confirm
          title={t('server.logClear')}
          text={t('server.logClearText')}
          confirm={t('server.logClear')}
          danger
          onCancel={() => setClearing(false)}
          onConfirm={async () => {
            await api('/api/v1/logs', { method: 'DELETE' })
            setClearing(false)
            setLines([])
          }}
        />
      )}
    </Card>
  )
}
