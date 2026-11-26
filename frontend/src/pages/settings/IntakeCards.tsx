/**
 * Inputs: Server › Inputs (the intake folder and the mailbox for documents, for the operator) and My
 * account, Upload (the addresses a person forwards from, the own subfolder). The folder must be a place nexpaper may take files from, the
 * mailbox is tried with the server, and an address counts once the link mailed to it was opened.
 */
import { AtSign, FolderInput, Mail } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, intakeApi, type IntakeChange, type IntakeSettings, type MyIntake } from '../../api/client'
import { ago } from '../../lib/ago'
import { errorText } from '../../lib/errors'
import { iso } from '../../lib/say'
import { Button, Card, CheckboxRow, CopyRow, Field, Notice, Row, Rows, Segment, SelectField } from '../../vendor/nexui'
import { useAsk } from './useAsk'

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
      {problem ? <Notice tone="danger">{say(problem)}</Notice> : <Notice tone="ok">{done}</Notice>}
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

/** Server › Inputs: both cards. */
export function IntakeCards() {
  const intake = useIntakeSettings()
  if (!intake.settings) return null
  return (
    <>
      <FolderCard intake={intake} settings={intake.settings} />
      <MailboxCard intake={intake} settings={intake.settings} />
    </>
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
    <Card id="intake-folder" icon={FolderInput} title={t('intake.folder.title')} subtitle={t('intake.folder.text')}>
      <CheckboxRow label={t('intake.folder.watch')} checked={folder.on} onChange={(folder_on) => void run({ folder_on }, null)} />
      {folder.on && (
        <>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void run({ folder_path: path.trim() }, t('intake.folder.saved'))
            }}
          >
            <Field
              label={t('intake.folder.path')}
              value={path}
              onChange={(event) => setPath(event.target.value)}
              hints={[t('intake.folder.pathHint')]}
              action={
                <Button kind="secondary" icon="Check" type="submit" busy={busy} disabled={!changed}>
                  {t('intake.folder.save')}
                </Button>
              }
            />
          </form>
          <ul className="m-0 flex list-none flex-col gap-1 rounded-[9px] bg-[var(--nexui-field)] px-4 py-3 font-mono text-xs">
            {folder.people.map((person) => (
              <li key={person.name}>
                {shown}/{person.name}/ <span className="text-[var(--nexui-text-muted)]">{t('intake.folder.to', { name: person.display_name })}</span>
                {person.problem === 'folder_readonly' && <span className="ml-2 font-sans font-semibold text-[var(--nexui-danger)]">{t('intake.folder.personReadonly')}</span>}
              </li>
            ))}
            <li>
              {shown}/ <span className="text-[var(--nexui-text-muted)]">{t('intake.folder.toOperator')}</span>
            </li>
          </ul>
          <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t('intake.folder.quiet')}</p>
          <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t('intake.folder.aside')}</p>
        </>
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
      const texts = got.texts ? ' ' + t('mailText.lastTexts', { count: got.texts }) : ''
      setDone(t(got.more ? 'intake.mail.fetchedMore' : 'intake.mail.fetched', { mails: got.mails, files: got.files }) + texts)
      intake.setSettings(await intakeApi.settings())
    } catch (error) {
      setProblem(codeOf(error))
    } finally {
      setBusy(null)
    }
  }

  const last = mail.last
  /** The server whose verdict counts for the text of a mail: the trusted one, else the domain of the mailbox. */
  const judge = mail.auth_server || mail.address.split('@')[1] || ''
  return (
    <Card id="intake-mail" icon={Mail} title={t('intake.mail.title')} subtitle={t('intake.mail.text', { local })}>
      <CheckboxRow label={t('intake.mail.fetch')} hint={t('intake.mail.fetchHint')} checked={mail.on} onChange={(mail_on) => void flip({ mail_on })} />
      {mail.on && (
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            void saveAndTry()
          }}
        >
          <Field label={t('intake.mail.host')} value={draft.host} onChange={(event) => set({ host: event.target.value })} placeholder="imap.example.com" hints={[t('intake.mail.hostHint', { port: draft.port, security: securityName })]} />
          <Field label={t('intake.mail.address')} value={draft.address} onChange={(event) => set({ address: event.target.value })} placeholder="paper@example.com" />
          <Field label={t('intake.mail.user')} value={draft.user} onChange={(event) => set({ user: event.target.value })} />
          <Field label={t('intake.mail.password')} type="password" autoComplete="new-password" value={draft.password} onChange={(event) => set({ password: event.target.value })} placeholder={mail.password_set ? t('intake.mail.passwordKept') : ''} />
          <Field label={t('intake.mail.port')} type="number" value={draft.port} onChange={(event) => set({ port: event.target.value })} min={1} max={65535} />
          <SelectField
            label={t('intake.mail.security')}
            value={draft.security}
            onChange={(event) => set({ security: event.target.value as MailDraft['security'] })}
            options={[
              { value: 'tls', label: t('intake.mail.tls') },
              { value: 'starttls', label: t('intake.mail.starttls') },
              { value: 'none', label: t('intake.mail.none') },
            ]}
          />
          <div className="sm:col-span-2">
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
            <CheckboxRow label={t('intake.mail.private')} hint={t('intake.mail.privateHint')} checked={mail.private} onChange={(mail_private) => void flip({ mail_private })} />
          </div>
          <div className="sm:col-span-2">
            <Field label={t('intake.mail.authServer')} value={draft.authServer} onChange={(event) => set({ authServer: event.target.value })} placeholder={draft.address.split('@')[1] || 'example.com'} hints={[t('intake.mail.authServerHint')]} />
          </div>
          <div className="sm:col-span-2">
            <CheckboxRow label={t('intake.mail.dropUnknown')} hint={t('intake.mail.dropUnknownHint')} checked={mail.drop_unknown} onChange={(mail_drop_unknown) => void flip({ mail_drop_unknown })} />
          </div>
          <div className="flex flex-col gap-2 sm:col-span-2">
            <CheckboxRow label={t('mailText.toggle')} hint={t('mailText.hint')} checked={mail.text === true} onChange={(mail_text) => void flip({ mail_text })} />
            {mail.text === true && (
              <p className="m-0 text-xs text-[var(--nexui-text-muted)]" data-testid="mail-text-judge">
                {judge ? t('mailText.judge', { server: judge }) : t('mailText.noJudge')}
              </p>
            )}
          </div>
          <p className="m-0 text-xs text-[var(--nexui-text-muted)] sm:col-span-2">{t('intake.mail.taken')}</p>
          <p className="m-0 text-xs text-[var(--nexui-text-muted)] sm:col-span-2">{t('intake.mail.whole')}</p>
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button kind="primary" icon="Check" type="submit" busy={busy === 'save'} disabled={busy !== null}>
              {t('intake.mail.saveTry')}
            </Button>
            <Button kind="secondary" icon="Download" onClick={() => void fetchNow()} busy={busy === 'fetch'} disabled={busy !== null || !mail.password_set}>
              {t('intake.mail.now')}
            </Button>
          </div>
          {last.at && (
            <p className="m-0 text-xs text-[var(--nexui-text-muted)] sm:col-span-2" data-testid="mail-last">
              {last.ok
                ? t('intake.mail.lastOk', { when: ago(last.at, i18n.language, t('me.justNow')), mails: last.mails, files: last.files })
                : t('intake.mail.lastFailed', { when: ago(last.at, i18n.language, t('me.justNow')), reason: say(last.code) })}
              {(last.skipped ?? 0) > 0 && ' ' + t('intake.mail.lastSkipped', { count: last.skipped })}
              {(last.flagged ?? 0) > 0 && ' ' + t('intake.mail.lastFlagged', { count: last.flagged })}
              {(last.deferred ?? 0) > 0 && ' ' + t('intake.mail.lastDeferred', { count: last.deferred })}
              {last.ok && (last.texts ?? 0) > 0 && ' ' + t('mailText.lastTexts', { count: last.texts })}
            </p>
          )}
        </form>
      )}
      <Said problem={problem} done={done} />
    </Card>
  )
}

// --- My account › Upload -------------------------------------------------------------------------------------------

/** My account › Upload: "Per Mail" (the addresses forwarded from) and the own subfolder, when the operator set them up. */
export function MyIntakeCards() {
  const { t } = useTranslation()
  const [mine, setMine] = useState<MyIntake | null>(null)
  const [address, setAddress] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { ask, dialog } = useAsk()
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
        <Card id="my-intake-mail" icon={AtSign} title={t('intake.mine.mailTitle')} subtitle={t('intake.mine.mailText', { address: mine.mail_address })}>
          {(mine.account_address || mine.senders.length > 0) && (
            <Rows label={t('intake.mine.mailTitle')} testId="my-senders">
              {mine.account_address && <Row icon={AtSign} name={mine.account_address} detail={t('intake.mine.accountAddress')} />}
              {mine.senders.map((sender) => (
                <Row
                  key={sender.id}
                  icon={AtSign}
                  name={sender.address}
                  badge={!sender.confirmed ? <span className="text-xs text-[var(--nexui-text-muted)]">{t('intake.mine.waiting')}</span> : undefined}
                  action={
                    <Button kind="danger" size="sm" icon="Trash2" onClick={() => remove(sender.id, sender.address)} aria-label={`${t('intake.mine.remove')}: ${sender.address}`}>
                      {t('intake.mine.remove')}
                    </Button>
                  }
                />
              ))}
            </Rows>
          )}
          {mine.can_confirm ? (
            <form
              onSubmit={(event) => {
                event.preventDefault()
                void add()
              }}
            >
              <Field
                label={t('intake.mine.add')}
                value={address}
                onChange={(event) => setAddress(event.target.value)}
                placeholder="name@example.com"
                hints={[t('intake.mine.addHint')]}
                action={
                  <Button kind="secondary" icon="Plus" type="submit" busy={busy} disabled={!address.includes('@')}>
                    {t('intake.mine.addButton')}
                  </Button>
                }
              />
            </form>
          ) : (
            <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t('intake.mine.noMailServer')}</p>
          )}
          <Said problem={problem} done={done} />
          {mine.plus_address && (
            <p className="m-0 text-sm">
              {t('intake.mine.plus')} <span className="font-mono">{mine.plus_address}</span>
            </p>
          )}
          <Former mine={mine} kind="@" />
        </Card>
      )}
      {mine.folder_on && mine.folder && (
        <Card id="my-intake-folder" icon={FolderInput} title={t('intake.mine.folderTitle')} subtitle={t('intake.mine.folderText')}>
          <CopyRow label={t('intake.mine.folderTitle')} value={mine.folder} testId="my-folder" />
          <Former mine={mine} kind="/" />
        </Card>
      )}
      {dialog}
    </>
  )
}


/** After a rename: the plus addresses (``@``) or subfolders (``/``) of the former names, which still reach the account. */
function Former({ mine, kind }: { mine: MyIntake; kind: '@' | '/' }) {
  const { t } = useTranslation()
  const shown = (mine.former ?? []).filter((entry) => (kind === '@' ? entry.includes('@') : entry.endsWith('/')))
  if (shown.length === 0) return null
  return (
    <p className="m-0 text-xs text-[var(--nexui-text-muted)]" data-testid={kind === '@' ? 'former-plus' : 'former-folder'}>
      {t('intake.mine.former', { list: shown.join(', ') })}
    </p>
  )
}
