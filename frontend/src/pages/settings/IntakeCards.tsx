/**
 * Inputs: Settings, Inputs (the intake folder and the mailbox for documents, for the operator) and My
 * account, Upload (the addresses a person forwards from, the own subfolder). The folder must be a place nexpaper may take files from, the
 * mailbox is tried with the server, and an address counts once the link mailed to it was opened.
 */
import { AtSign, FolderInput, Mail, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, intakeApi, type IntakeChange, type IntakeSettings, type MyIntake } from '../../api/client'
import { useConfirm } from '../../components/useConfirm'
import { ago } from '../../lib/ago'
import { errorText } from '../../lib/errors'
import { iso } from '../../lib/say'
import { Button, Card, Input, Segment, Select, Toggle } from './ui'

/** The sentence for a code of these cards: their own words, else the app's. */
// eslint-disable-next-line react-refresh/only-export-components
export function useIntakeText() {
  const { t, i18n } = useTranslation()
  return useCallback(
    (code: string) => {
      const own = `intake.errors.${code}`
      return i18n.exists(own) ? t(own) : errorText(code)
    },
    [t, i18n],
  )
}

function codeOf(error: unknown): string {
  return error instanceof ApiError ? error.code : 'internal_error'
}

/** One line under a card: what went wrong, or what came of it. */
function Said({ problem, done }: { problem: string | null; done: string | null }) {
  const say = useIntakeText()
  if (!problem && !done) return null
  return (
    <div aria-live="polite">
      {problem && (
        <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {say(problem)}
        </p>
      )}
      {done && (
        <p role="status" className="text-sm font-semibold text-accent">
          ✓ {done}
        </p>
      )}
    </div>
  )
}

/** The operator's settings of both cards, saved field by field. */
function useIntakeSettings() {
  const [settings, setSettings] = useState<IntakeSettings | null>(null)
  useEffect(() => {
    intakeApi.settings().then(setSettings, () => undefined)
  }, [])
  const save = async (change: IntakeChange) => {
    const next = await intakeApi.save(change)
    setSettings(next)
    return next
  }
  return { settings, setSettings, save }
}

type Intake = ReturnType<typeof useIntakeSettings>

/** Settings, Inputs: both cards. */
export function IntakeCards() {
  const intake = useIntakeSettings()
  if (!intake.settings) return null
  return (
    <div className="space-y-6">
      <FolderCard intake={intake} settings={intake.settings} />
      <MailboxCard intake={intake} settings={intake.settings} />
    </div>
  )
}

function FolderCard({ intake, settings }: { intake: Intake; settings: IntakeSettings }) {
  const { t } = useTranslation()
  const folder = settings.folder
  const [path, setPath] = useState(folder.path || folder.used)
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async (change: IntakeChange, success: string | null) => {
    setBusy(true)
    setProblem(null)
    setDone(null)
    try {
      const next = await intake.save(change)
      setPath(next.folder.path || next.folder.used)
      setDone(success)
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      setBusy(false)
    }
  }
  const shown = (folder.path || folder.used).replace(/[\\/]+$/, '')
  const changed = path.trim() !== (folder.path || folder.used)
  return (
    <Card icon={FolderInput} title={t('intake.folder.title')} text={t('intake.folder.text')}>
      <Toggle label={t('intake.folder.watch')} checked={folder.on} onChange={(folder_on) => void run({ folder_on }, null)} />
      {folder.on && (
        <div className="mt-4 space-y-3">
          <form
            className="flex flex-wrap items-start gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              void run({ folder_path: path.trim() }, t('intake.folder.saved'))
            }}
          >
            <Input label={t('intake.folder.path')} value={path} onChange={setPath} hint={t('intake.folder.pathHint')} className="min-w-60 flex-1" />
            {changed && (
              <Button type="submit" busy={busy} className="mt-6">
                {t('intake.folder.save')}
              </Button>
            )}
          </form>
          <ul className="space-y-1 rounded-xl bg-sheet-2 px-4 py-3 font-mono text-xs text-ink-2">
            {folder.people.map((person) => (
              <li key={person.name}>
                {shown}/{person.name}/ <span className="text-muted">{t('intake.folder.to', { name: person.display_name })}</span>
                {person.problem === 'folder_readonly' && <span className="ml-2 font-sans font-semibold text-bad">{t('intake.folder.personReadonly')}</span>}
              </li>
            ))}
            <li>
              {shown}/ <span className="text-muted">{t('intake.folder.toOperator')}</span>
            </li>
          </ul>
          <p className="text-xs text-muted">{t('intake.folder.quiet')}</p>
          <p className="text-xs text-muted">{t('intake.folder.aside')}</p>
        </div>
      )}
      <Said problem={problem ?? (folder.on && folder.problem ? folder.problem : null)} done={done} />
    </Card>
  )
}

type MailDraft = { host: string; port: string; security: 'tls' | 'starttls' | 'none'; address: string; user: string; password: string; authServer: string }

function draftOf(mail: IntakeSettings['mail']): MailDraft {
  return { host: mail.host, port: String(mail.port), security: mail.security, address: mail.address, user: mail.user, password: '', authServer: mail.auth_server }
}

function MailboxCard({ intake, settings }: { intake: Intake; settings: IntakeSettings }) {
  const { t, i18n } = useTranslation()
  const say = useIntakeText()
  const mail = settings.mail
  const [draft, setDraft] = useState<MailDraft>(() => draftOf(mail))
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState<'save' | 'fetch' | null>(null)
  const set = (part: Partial<MailDraft>) => setDraft({ ...draft, ...part })
  const local = (mail.address || draft.address || 'paper@').split('@')[0] || 'paper'
  const securityName = t(`intake.mail.${draft.security}`)

  /** One change of a switch: saved at once. */
  const flip = async (change: IntakeChange) => {
    setProblem(null)
    setDone(null)
    try {
      await intake.save(change)
    } catch (error) {
      setProblem(codeOf(error))
    }
  }

  const saveAndTry = async () => {
    setBusy('save')
    setProblem(null)
    setDone(null)
    try {
      const port = Number(draft.port)
      const change: IntakeChange = {
        mail_host: draft.host.trim(),
        mail_port: Number.isInteger(port) && port > 0 && port < 65536 ? port : mail.port,
        mail_security: draft.security,
        mail_address: draft.address.trim(),
        mail_user: draft.user.trim(),
        mail_auth_server: draft.authServer.trim(),
      }
      if (draft.password) change.mail_password = draft.password
      const next = await intake.save(change)
      setDraft(draftOf(next.mail))
      const found = await intakeApi.testMail()
      const instead = found.after !== next.mail.after ? ' ' + t(`intake.mail.instead.${found.after}`) : ''
      setDone(t('intake.mail.tested', { count: found.mails }) + instead)
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      setBusy(null)
    }
  }

  const fetchNow = async () => {
    setBusy('fetch')
    setProblem(null)
    setDone(null)
    try {
      const got = await intakeApi.fetchMail()
      setDone(t(got.more ? 'intake.mail.fetchedMore' : 'intake.mail.fetched', { mails: got.mails, files: got.files }))
      intake.setSettings(await intakeApi.settings())
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      setBusy(null)
    }
  }

  const last = mail.last
  return (
    <Card icon={Mail} title={t('intake.mail.title')} text={t('intake.mail.text', { local })}>
      <Toggle label={t('intake.mail.fetch')} hint={t('intake.mail.fetchHint')} checked={mail.on} onChange={(mail_on) => void flip({ mail_on })} />
      {mail.on && (
        <form
          className="mt-4 grid gap-3 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            void saveAndTry()
          }}
        >
          <Input label={t('intake.mail.host')} value={draft.host} onChange={(host) => set({ host })} placeholder="imap.example.com" hint={t('intake.mail.hostHint', { port: draft.port, security: securityName })} />
          <Input label={t('intake.mail.address')} value={draft.address} onChange={(address) => set({ address })} placeholder="paper@example.com" />
          <Input label={t('intake.mail.user')} value={draft.user} onChange={(user) => set({ user })} />
          <Input label={t('intake.mail.password')} type="password" autoComplete="new-password" value={draft.password} onChange={(password) => set({ password })} placeholder={mail.password_set ? t('intake.mail.passwordKept') : ''} />
          <Input label={t('intake.mail.port')} type="number" value={draft.port} onChange={(port) => set({ port })} min={1} max={65535} />
          <Select
            label={t('intake.mail.security')}
            value={draft.security}
            onChange={(security) => set({ security })}
            options={[
              { value: 'tls', label: t('intake.mail.tls') },
              { value: 'starttls', label: t('intake.mail.starttls') },
              { value: 'none', label: t('intake.mail.none') },
            ]}
          />
          <div className="sm:col-span-2">
            <p className="mb-2 text-sm font-semibold">{t('intake.mail.after')}</p>
            <Segment
              label={t('intake.mail.after')}
              value={mail.after}
              onChange={(mail_after) => void flip({ mail_after })}
              options={[
                { value: 'read', label: t('intake.mail.read') },
                { value: 'move', label: t('intake.mail.move') },
                { value: 'delete', label: t('intake.mail.delete') },
              ]}
            />
          </div>
          <div className="sm:col-span-2">
            <Toggle label={t('intake.mail.private')} hint={t('intake.mail.privateHint')} checked={mail.private} onChange={(mail_private) => void flip({ mail_private })} />
          </div>
          <Input label={t('intake.mail.authServer')} value={draft.authServer} onChange={(authServer) => set({ authServer })} placeholder={(draft.address.split('@')[1] || 'example.com')} hint={t('intake.mail.authServerHint')} className="sm:col-span-2" />
          <div className="sm:col-span-2">
            <Toggle label={t('intake.mail.dropUnknown')} hint={t('intake.mail.dropUnknownHint')} checked={mail.drop_unknown} onChange={(mail_drop_unknown) => void flip({ mail_drop_unknown })} />
          </div>
          <p className="text-xs text-muted sm:col-span-2">{t('intake.mail.taken')}</p>
          <p className="text-xs text-muted sm:col-span-2">{t('intake.mail.whole')}</p>
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button primary type="submit" busy={busy === 'save'} disabled={busy !== null}>
              {t('intake.mail.saveTry')}
            </Button>
            <Button onClick={() => void fetchNow()} busy={busy === 'fetch'} disabled={busy !== null || !mail.password_set}>
              {t('intake.mail.now')}
            </Button>
          </div>
          {last.at && (
            <p className="text-xs text-muted sm:col-span-2" data-testid="mail-last">
              {last.ok
                ? t('intake.mail.lastOk', { when: ago(last.at, i18n.language, t('me.justNow')), mails: last.mails, files: last.files })
                : t('intake.mail.lastFailed', { when: ago(last.at, i18n.language, t('me.justNow')), reason: say(last.code) })}
              {(last.skipped ?? 0) > 0 && ' ' + t('intake.mail.lastSkipped', { count: last.skipped })}
              {(last.flagged ?? 0) > 0 && ' ' + t('intake.mail.lastFlagged', { count: last.flagged })}
              {(last.deferred ?? 0) > 0 && ' ' + t('intake.mail.lastDeferred', { count: last.deferred })}
            </p>
          )}
        </form>
      )}
      <Said problem={problem} done={done} />
    </Card>
  )
}

// --- My account, Upload -------------------------------------------------------------------------------------------

/** My account, Upload: "Per Mail" (the addresses forwarded from) and the own subfolder, when the operator set them up. */
export function MyIntakeCards() {
  const { t } = useTranslation()
  const [mine, setMine] = useState<MyIntake | null>(null)
  const [address, setAddress] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { ask, dialog } = useConfirm()
  const load = useCallback(() => {
    intakeApi.mine().then(setMine, () => undefined)
  }, [])
  useEffect(load, [load])
  if (!mine) return null
  const add = async () => {
    const wanted = address.trim()
    if (!wanted) return
    setBusy(true)
    setProblem(null)
    setDone(null)
    try {
      await intakeApi.addSender(wanted)
      setAddress('')
      setDone(t('intake.mine.sent', { address: wanted }))
      load()
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      setBusy(false)
    }
  }
  /** Takes a forwarding address away, after asking. */
  const remove = (id: number, address: string) =>
    ask({
      title: t('confirm.mailSender.title'),
      text: t('confirm.mailSender.text', { address: iso(address) }),
      confirm: t('confirm.mailSender.confirm'),
      run: async () => {
        setProblem(null)
        setDone(null)
        await intakeApi.removeSender(id)
        load()
      },
    })
  return (
    <>
      {mine.mail_on && mine.mail_address && (
        <Card icon={AtSign} title={t('intake.mine.mailTitle')} text={t('intake.mine.mailText', { address: mine.mail_address })}>
          {(mine.account_address || mine.senders.length > 0) && (
            <ul className="space-y-2">
              {mine.account_address && (
                <li className="flex items-center gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-2.5 text-sm">
                  <AtSign size={16} className="text-accent" aria-hidden />
                  <span className="flex-1 font-semibold">{mine.account_address}</span>
                  <span className="text-xs text-muted">{t('intake.mine.accountAddress')}</span>
                </li>
              )}
              {mine.senders.map((sender) => (
                <li key={sender.id} className="flex items-center gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-2.5 text-sm">
                  <AtSign size={16} className={sender.confirmed ? 'text-accent' : 'text-muted'} aria-hidden />
                  <span className="flex-1 font-semibold">{sender.address}</span>
                  {!sender.confirmed && <span className="text-xs text-muted">{t('intake.mine.waiting')}</span>}
                  <button type="button" onClick={() => remove(sender.id, sender.address)} className="rounded-full p-1 text-muted hover:text-ink" aria-label={`${t('intake.mine.remove')}: ${sender.address}`}>
                    <Trash2 size={14} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {mine.can_confirm ? (
            <form
              className="mt-3 flex flex-wrap items-start gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                void add()
              }}
            >
              <Input label={t('intake.mine.add')} value={address} onChange={setAddress} placeholder="name@example.com" className="min-w-60 flex-1" hint={t('intake.mine.addHint')} />
              <Button type="submit" className="mt-6" busy={busy} disabled={!address.includes('@')}>
                {t('intake.mine.addButton')}
              </Button>
            </form>
          ) : (
            <p className="text-sm text-muted">{t('intake.mine.noMailServer')}</p>
          )}
          <Said problem={problem} done={done} />
          {mine.plus_address && (
            <p className="mt-3 text-sm text-ink-2">
              {t('intake.mine.plus')} <span className="font-mono text-ink">{mine.plus_address}</span>
            </p>
          )}
        </Card>
      )}
      {mine.folder_on && mine.folder && (
        <Card icon={FolderInput} title={t('intake.mine.folderTitle')} text={t('intake.mine.folderText')}>
          <p className="rounded-xl bg-sheet-2 px-4 py-3 font-mono text-sm">{mine.folder}</p>
        </Card>
      )}
      {dialog}
    </>
  )
}
