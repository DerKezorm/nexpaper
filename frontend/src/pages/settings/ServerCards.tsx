/**
 * The operator's part of the settings, as the mock (and nexlore): accounts and invitations, mail, API keys, backups,
 * languages and the log. Sign-in (password, public address, second factor, providers, authentik) is in
 * ``SignInCards.tsx``. Everything here is the
 * server's; it applies to all. The operator manages accounts and does not read the documents in them.
 */
import { AlertTriangle, Download, FileText, HardDrive, Languages, Mail, MoreHorizontal, Plug, Plus, RotateCcw, ScrollText, ShieldCheck, Trash2, Upload, Users } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { accountsApi, ApiError, api, apiKeysApi, oidcApi, passwordHeader, vaultsApi, type AccountLeaving, type AccountLink, type AddressQuestion, type AnyApiKey, type DocumentsChoice, type Me, type Person } from '../../api/client'
import { Avatar } from '../../components/Avatar'
import { Dialog } from '../../components/Dialog'
import { useConfirm } from '../../components/useConfirm'
import { byName, forgetAddedLanguages, templateFile } from '../../i18n'
import { iso } from '../../lib/say'
import { useAuth } from '../../state/auth'
import { Button, Card, Confirm, CopyLink, Feedback, Input, saveAsFile, Select, SubHead, Toggle, useAction } from './ui'

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
   * (Bauplan 04, card 1); with `confirm` it is saved. Null: saved, or refused for another reason (shown by `problem`).
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

type AccountRow = Me & { locked: boolean; blocked?: boolean; has_password?: boolean; created_at: string; last_seen_at: string | null; ai_allowed: boolean }
type OpenInvite = { id: number; email: string; expires_at: string }
type Asking = 'role' | 'delete' | 'link' | 'reset' | 'signout' | 'block' | 'unblock' | 'unlink'
/** What came of sending a link to set a new password: by mail, or to pass on once. */
type LinkMade = { name: string; sent: boolean; email?: string; link?: string }
const DAYS = ['1', '7', '30'] as const

/** Every account, and the invitations that bring new ones. */
export function AccountsCard() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [list, setList] = useState<AccountRow[]>([])
  const [inviting, setInviting] = useState(false)
  const [invites, setInvites] = useState<OpenInvite[]>([])
  const [menu, setMenu] = useState<number | null>(null)
  const [asking, setAsking] = useState<{ kind: Asking; account: AccountRow; link?: AccountLink } | null>(null)
  const [links, setLinks] = useState<AccountLink[]>([])
  const [made, setMade] = useState<LinkMade | null>(null)
  const { busy, problem, done, run } = useAction()
  const { ask, dialog } = useConfirm()
  const load = useCallback(() => {
    api<AccountRow[]>('/api/v1/accounts').then(setList, () => undefined)
    api<OpenInvite[]>('/api/v1/invites').then(setInvites, () => undefined)
    oidcApi.links().then((found) => setLinks(Array.isArray(found) ? found : []), () => setLinks([]))
  }, [])
  useEffect(load, [load])
  useEffect(() => {
    if (menu === null) return
    const away = (event: MouseEvent) => {
      if (!(event.target as Element).closest('[data-account-actions]')) setMenu(null)
    }
    const escape = (event: KeyboardEvent) => event.key === 'Escape' && setMenu(null)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', escape)
    }
  }, [menu])

  const linksOf = (row: AccountRow) => links.filter((entry) => entry.account_id === row.id)
  const actions = (row: AccountRow): { kind: Asking; label: string; link?: AccountLink }[] => [
    { kind: 'role', label: row.role === 'operator' ? t('server.makeMember') : t('server.makeOperator') },
    ...linksOf(row).map((link) => ({ kind: 'unlink' as const, label: t('server.unlinkProvider', { name: link.label }), link })),
    ...(row.two_factor ? [{ kind: 'reset' as const, label: t('server.resetTwoFactor') }] : []),
    { kind: 'signout', label: t('server.signOutEverywhere') },
    row.blocked ? { kind: 'unblock' as const, label: t('server.unblock') } : { kind: 'block' as const, label: t('server.block') },
    { kind: 'delete', label: t('server.deleteAccount') },
  ]

  return (
    <Card id="accounts" icon={Users} title={t('server.accounts')} text={t('server.accountsHint')}>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {list.map((row) => (
          <li key={row.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
            <Avatar person={row} size={34} />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-semibold">
                {row.display_name || row.name}
                {row.display_name && <span className="ml-1 text-xs font-normal text-muted">{row.name}</span>}
              </span>
              <span className="block text-xs text-muted">
                {t(`me.role.${row.role}`)} · {t(`server.signInBy.${row.sign_in}`)}
                {row.two_factor ? ' · ' + t('server.withTwoFactor') : ''}
                {row.locked ? ' · ' + t('server.locked') : ''}
                {row.blocked ? ' · ' + t('server.blocked') : ''}
              </span>
              {linksOf(row).length > 0 && (
                <span className="mt-1 flex flex-wrap gap-1" data-testid="account-providers">
                  {linksOf(row).map((link) => (
                    <span key={link.provider_id} className="rounded-full border border-line px-2 py-0.5 text-[11px] font-semibold text-ink-2">
                      {link.label}
                    </span>
                  ))}
                </span>
              )}
            </span>
            {row.id !== me?.id && (
              <span className="relative flex items-center gap-1.5" data-account-actions>
                <Button small onClick={() => setAsking({ kind: 'link', account: row })}>
                  {row.has_password === false ? t('server.givePassword') : t('server.newPassword')}
                </Button>
                <button
                  type="button"
                  aria-expanded={menu === row.id}
                  aria-haspopup="true"
                  aria-label={t('server.more', { name: row.name })}
                  onClick={() => setMenu(menu === row.id ? null : row.id)}
                  className="rounded-full p-1.5 text-muted hover:bg-sheet-2 hover:text-ink"
                >
                  <MoreHorizontal size={18} />
                </button>
                {menu === row.id && (
                  <span className="card rise absolute top-full right-0 z-40 mt-1 block w-60 p-1.5">
                    {actions(row).map((entry) => (
                      <button
                        key={entry.kind + (entry.link ? `-${entry.link.provider_id}` : '')}
                        type="button"
                        onClick={() => {
                          setMenu(null)
                          setAsking({ kind: entry.kind, account: row, link: entry.link })
                        }}
                        className={`block w-full rounded-lg px-3 py-2 text-left text-sm font-semibold hover:bg-sheet-2 ${entry.kind === 'delete' || entry.kind === 'block' ? 'text-bad' : 'text-ink-2'}`}
                      >
                        {entry.label}
                      </button>
                    ))}
                  </span>
                )}
              </span>
            )}
            <span className="flex basis-full flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2 sm:pl-[3.1rem]" data-permissions>
              {(['ai_allowed'] as const).map((key) => (
                <label key={key} className="inline-flex items-center gap-1.5 font-semibold">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-[var(--accent)]"
                    checked={row[key]}
                    disabled={busy}
                    aria-label={`${t('server.aiAllowed')}: ${row.display_name || row.name}`}
                    onChange={(event) => {
                      const allowed = event.target.checked
                      setList((rows) => rows.map((item) => (item.id === row.id ? { ...item, [key]: allowed } : item)))
                      void run(async () => {
                        try {
                          await api(`/api/v1/accounts/${row.id}/permissions`, { method: 'PUT', body: { [key]: allowed } })
                        } catch (error) {
                          load()
                          throw error
                        }
                      })
                    }}
                  />
                  {t('server.aiAllowed')}
                </label>
              ))}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted">{t('server.permissionsHint')}</p>
      {invites.length > 0 && (
        <ul className="space-y-2" data-testid="open-invites">
          {invites.map((invite) => (
            <li key={invite.id} className="flex items-center gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-2.5 text-sm">
              <span className="flex-1">
                <span className="font-semibold">{invite.email || t('invite.noEmail')}</span>
                <span className="block text-xs text-muted">{t('invite.until', { when: new Date(invite.expires_at).toLocaleDateString(i18n.language) })}</span>
              </span>
              <Button
                small
                busy={busy}
                onClick={() =>
                  ask({
                    title: t('confirm.invite.title'),
                    text: t('confirm.invite.text'),
                    confirm: t('confirm.invite.confirm'),
                    run: async () => {
                      await api(`/api/v1/invites/${invite.id}`, { method: 'DELETE' })
                      load()
                    },
                  })
                }
              >
                {t('invite.withdraw')}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-2 pt-1">
        <Button primary onClick={() => setInviting(true)}>
          <Plus size={16} /> {t('server.invite')}
        </Button>
      </div>
      {made && (
        <div className="space-y-2 text-sm text-ink-2" role="status">
          {made.sent ? (
            <p>{t('server.linkSent', { name: made.name, email: made.email })}</p>
          ) : (
            <>
              <p>{t('server.linkShown', { name: made.name })}</p>
              {made.link && <CopyLink value={made.link} label={t('server.linkLabel')} />}
            </>
          )}
        </div>
      )}
      <Feedback problem={problem} done={done} />
      {dialog}
      {inviting && (
        <InviteDialog
          onClose={() => {
            setInviting(false)
            load()
          }}
        />
      )}
      {asking?.kind === 'delete' && (
        <DeleteAccount
          account={asking.account}
          password={me?.sign_in === 'password'}
          onCancel={() => setAsking(null)}
          onDeleted={() => {
            setAsking(null)
            load()
          }}
        />
      )}
      {asking && asking.kind !== 'delete' && (
        <Confirm
          title={t(`server.confirm.${asking.kind}.title`, { name: asking.account.name })}
          text={t(asking.kind === 'role' ? (asking.account.role === 'operator' ? 'server.confirm.demote.text' : 'server.confirm.promote.text') : `server.confirm.${asking.kind}.text`, { name: asking.account.name, provider: asking.link?.label ?? '' })}
          confirm={t(`server.confirm.${asking.kind}.button`)}
          danger={asking.kind === 'block'}
          password={me?.sign_in === 'password' && asking.kind !== 'signout'}
          onCancel={() => setAsking(null)}
          onConfirm={async (password) => {
            const id = asking.account.id
            if (asking.kind === 'role') await api(`/api/v1/accounts/${id}/role`, { method: 'PUT', body: { role: asking.account.role === 'operator' ? 'member' : 'operator', current_password: password } })
            if (asking.kind === 'reset') await api(`/api/v1/accounts/${id}/totp/reset`, { method: 'POST', body: { current_password: password } })
            if (asking.kind === 'signout') await api(`/api/v1/accounts/${id}/sign-out`, { method: 'POST' })
            if (asking.kind === 'unblock') await api(`/api/v1/accounts/${id}/unblock`, { method: 'POST', body: { current_password: password } })
            if (asking.kind === 'block') await api(`/api/v1/accounts/${id}/block`, { method: 'POST', body: { current_password: password } })
            if (asking.kind === 'unlink' && asking.link) await oidcApi.unlinkAccount(id, asking.link.provider_id, password)
            if (asking.kind === 'link') {
              // The operator sets no password: the person does, through a link that goes by mail or is shown here once.
              const sent = await api<{ sent: boolean; email?: string; link?: string }>(`/api/v1/accounts/${id}/reset-link`, { method: 'POST', body: { current_password: password } })
              setMade({ name: asking.account.name, ...sent })
            }
            setAsking(null)
            load()
          }}
        />
      )}
    </Card>
  )
}

/**
 * Deleting an account. The dialog says how many documents the person's own vault holds (the trash included) and, when
 * there are some, offers the three ways: to another person (into their own vault, who then owns them), into a shared
 * vault, or away for good. The account's name is typed once more; the server checks it, and the operator's password.
 */
function DeleteAccount({ account, password, onCancel, onDeleted }: { account: AccountRow; password: boolean; onCancel: () => void; onDeleted: () => void }) {
  const { t, i18n } = useTranslation()
  const [leaving, setLeaving] = useState<AccountLeaving | null>(null)
  const [people, setPeople] = useState<Person[]>([])
  const [choice, setChoice] = useState<DocumentsChoice | ''>('')
  const [heir, setHeir] = useState('')
  const [place, setPlace] = useState('')
  const [name, setName] = useState('')
  const [secret, setSecret] = useState('')
  const { busy, problem, values, run } = useAction()
  useEffect(() => {
    let alive = true
    Promise.all([accountsApi.leaving(account.id), vaultsApi.people()]).then(
      ([found, everybody]) => {
        if (!alive) return
        setLeaving(found)
        setPeople(everybody.filter((p) => p.id !== account.id))
      },
      () => undefined,
    )
    return () => {
      alive = false
    }
  }, [account.id])
  const count = leaving?.documents ?? 0
  const ready =
    leaving !== null &&
    leaving.sole_manager_of.length === 0 &&
    name.trim() === account.name &&
    (!password || secret !== '') &&
    (count === 0 || (choice === 'transfer_to_user' && heir !== '') || (choice === 'transfer_to_vault' && place !== '') || choice === 'delete_documents')
  const remove = () =>
    run(async () => {
      await accountsApi.remove(account.id, {
        current_password: secret,
        confirm_name: name.trim(),
        ...(count > 0 && choice ? { documents: choice } : {}),
        ...(count > 0 && choice === 'transfer_to_user' ? { target_user_id: Number(heir) } : {}),
        ...(count > 0 && choice === 'transfer_to_vault' ? { target_vault_id: Number(place) } : {}),
      })
      onDeleted()
    })
  // Said plainly where the operator would see the documents afterwards (allowed, but in the open).
  const youSee = (
    <p role="note" className="mt-2 rounded-lg bg-accent-soft px-2.5 py-1.5 text-xs font-semibold text-ink">
      {t('server.remove.youSee')}
    </p>
  )
  const seesHeir = heir !== '' && (leaving?.heirs_you_see ?? []).includes(Number(heir))
  const seesVault = place !== '' && (leaving?.shared_vaults ?? []).some((v) => String(v.id) === place && v.you_see)
  const way = (value: DocumentsChoice, label: string, hint: string, extra?: ReactNode) => (
    <div className={`rounded-xl border px-3 py-2.5 text-sm ${choice === value ? 'border-accent/50 bg-accent-soft/40' : 'border-line'}`}>
      <label className="flex items-start gap-2.5">
        <input type="radio" name="documents" checked={choice === value} onChange={() => setChoice(value)} className="mt-0.5 h-4 w-4 accent-[var(--accent)]" />
        <span>
          <span className="block font-semibold">{label}</span>
          <span className="block text-xs text-muted">{hint}</span>
        </span>
      </label>
      {choice === value && extra && <div className="mt-2 pl-6">{extra}</div>}
    </div>
  )
  return (
    <Dialog title={t('server.remove.title', { name: account.name })} onClose={onCancel}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (ready) void remove()
        }}
      >
        <p className="text-sm text-ink-2">{t('server.remove.text', { name: account.name })}</p>
        {!leaving && <p className="text-sm text-muted">{t('server.remove.loading')}</p>}
        {leaving && leaving.sole_manager_of.length > 0 && (
          <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
            {t('server.remove.soleManager', { name: account.name, vaults: leaving.sole_manager_of.map((v) => `„${v.name}“`).join(', ') })}
          </p>
        )}
        {leaving && count === 0 && <p className="text-sm text-ink-2">{t('server.remove.none')}</p>}
        {leaving && count > 0 && (
          <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-semibold">{t('server.remove.documents', { count, n: count.toLocaleString(i18n.language) })}</legend>
            {way(
              'transfer_to_user',
              t('server.remove.toPerson'),
              t('server.remove.toPersonHint'),
              people.length > 0 ? (
                <>
                  <Select
                    label={t('server.remove.choosePerson')}
                    value={heir}
                    onChange={setHeir}
                    options={[{ value: '', label: '' }, ...people.map((p) => ({ value: String(p.id), label: p.display_name || p.name }))]}
                  />
                  {seesHeir && youSee}
                </>
              ) : (
                <p className="text-xs text-muted">{t('server.remove.noPerson')}</p>
              ),
            )}
            {way(
              'transfer_to_vault',
              t('server.remove.toVault'),
              t('server.remove.toVaultHint'),
              leaving.shared_vaults.length > 0 ? (
                <>
                  <Select
                    label={t('server.remove.chooseVault')}
                    value={place}
                    onChange={setPlace}
                    options={[{ value: '', label: '' }, ...leaving.shared_vaults.map((v) => ({ value: String(v.id), label: v.name }))]}
                  />
                  {seesVault && youSee}
                </>
              ) : (
                <p className="text-xs text-muted">{t('server.remove.noVault')}</p>
              ),
            )}
            {way('delete_documents', t('server.remove.deleteAll'), t('server.remove.deleteAllHint'))}
          </fieldset>
        )}
        <Input label={t('server.remove.typeName', { name: account.name })} value={name} onChange={setName} autoComplete="off" />
        {password && <Input label={t('settings.ownPassword')} type="password" value={secret} onChange={setSecret} autoComplete="current-password" />}
        <Feedback problem={problem} values={values} />
        <div className="flex justify-end gap-2">
          <Button onClick={onCancel}>{t('common.cancel')}</Button>
          <Button type="submit" busy={busy} danger disabled={!ready}>
            {t('server.remove.button')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

/** "Invite somebody": how long the link holds, to which address it may go, and the link itself, shown once. */
function InviteDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [days, setDays] = useState<(typeof DAYS)[number]>('7')
  const [email, setEmail] = useState('')
  const [send, setSend] = useState(true)
  const [made, setMade] = useState<{ link: string; sent: boolean; email: string } | null>(null)
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('server.invite')} onClose={onClose}>
      {made ? (
        <div className="space-y-3">
          <CopyLink value={made.link} label={t('invite.copy')} />
          <p className="text-sm text-ink-2">{made.sent ? t('invite.sent', { email: made.email }) : t('invite.once')}</p>
          <div className="flex justify-end">
            <Button primary onClick={onClose}>
              {t('common.done')}
            </Button>
          </div>
        </div>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            void run(async () => setMade(await api<{ link: string; sent: boolean; email: string }>('/api/v1/invites', { method: 'POST', body: { days: Number(days), email: email.trim(), send: send && !!email.trim() } })))
          }}
        >
          <p className="text-sm text-ink-2">{t('server.inviteText')}</p>
          <Select label={t('invite.valid')} value={days} options={DAYS.map((value) => ({ value, label: t('invite.days', { count: Number(value) }) }))} onChange={setDays} />
          <Input label={t('invite.email')} value={email} onChange={setEmail} type="email" hint={me?.mail ? undefined : t('invite.noMail')} />
          {me?.mail && email.trim() && <Toggle label={t('invite.send')} checked={send} onChange={setSend} />}
          <Feedback problem={problem} />
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>{t('common.cancel')}</Button>
            <Button type="submit" primary busy={busy}>
              {t('invite.create')}
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  )
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

/** The switch for API keys, and every key there is: who made it, what it is called, when it was used; blocked for good
 * on request (every way out needs a latch). Never the key itself. */
export function ApiKeysCard({ server }: { server: Server }) {
  const { t, i18n } = useTranslation()
  const { busy, problem, run } = useAction()
  const [keys, setKeys] = useState<AnyApiKey[] | null>(null)
  const [blocking, setBlocking] = useState<AnyApiKey | null>(null)
  const load = useCallback(() => {
    apiKeysApi.every().then(setKeys, () => setKeys(null))
  }, [])
  useEffect(load, [load])
  const s = server.settings
  if (!s) return null
  return (
    <Card id="api-keys" icon={Plug} title={t('server.apiKeys.title')} text={t('server.apiKeys.text')}>
      <Toggle label={t('server.apiKeys.allow')} hint={t('server.apiKeys.allowHint')} checked={s.api_keys_allowed} onChange={(api_keys_allowed) => void server.save({ api_keys_allowed })} />
      {keys && keys.length > 0 && (
        <ul className="divide-y divide-line rounded-xl border border-line text-sm" data-testid="admin-api-keys">
          {keys.map((key) => (
            <li key={key.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <span className="min-w-0 flex-1">
                <span className="font-semibold">{key.name}</span> <code className="font-mono text-xs text-muted">{key.prefix}…</code>
                <span className="block text-xs text-muted">
                  {key.account} · {key.last_used_at ? new Date(key.last_used_at).toLocaleString(i18n.language, { dateStyle: 'short', timeStyle: 'short' }) : t('apiKeys.unused')}
                </span>
              </span>
              {key.blocked ? (
                <span className="text-xs font-semibold text-bad">{t('server.apiKeys.blocked')}</span>
              ) : (
                <Button small danger busy={busy} onClick={() => setBlocking(key)} label={t('server.apiKeys.blockNamed', { name: key.name, account: key.account })}>
                  {t('server.apiKeys.block')}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted">{t('server.apiKeys.offHint')}</p>
      <p className="text-sm">
        <Link to="/konto?tab=devices" className="font-semibold text-accent underline decoration-accent/40 underline-offset-4">
          {t('server.apiKeys.own')}
        </Link>
      </p>
      <Feedback problem={problem ?? server.problem} done={server.done} />
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
        <div className="sm:col-span-2">
          <Button type="submit" primary busy={server.busy}>
            {t('common.save')}
          </Button>
        </div>
      </form>
      <Feedback problem={server.problem} done={server.done} />
      <SubHead title={t('server.mailTestTitle')} />
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void test.run(() => api('/api/v1/settings/mail-test', { method: 'POST', body: { to } }), t('server.mailSent'))
        }}
      >
        <Input label={t('server.mailTest')} value={to} onChange={setTo} placeholder="jule@example.com" className="min-w-60 flex-1" />
        <Button type="submit" busy={test.busy} disabled={!to.trim()}>
          {t('server.send')}
        </Button>
      </form>
      <Feedback problem={test.problem} done={test.done} />
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
  if (brief.rebuilds_index) lines.push(t('server.restorePreview.index'))
  return (
    <ul className="mt-2 space-y-1 text-xs" data-testid="restore-preview">
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  )
}

export function BackupsCard({ server }: { server: Server }) {
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
  const size = (bytes: number) => (bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`)
  const icon = 'rounded-full p-1.5 text-muted hover:bg-sheet hover:text-ink'
  return (
    <Card id="backups" icon={HardDrive} title={t('server.backups')} text={t('server.backupsHint')}>
      <div className="flex items-start gap-3 rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm" data-testid="backup-without-documents">
        <AlertTriangle size={16} className="mt-0.5 shrink-0 text-warn" aria-hidden />
        <span>
          <span className="font-semibold">{t('server.backupNoDocuments')}</span>
          <span className="block text-xs text-ink-2">{t('server.backupNoDocumentsText')}</span>
        </span>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Select
          label={t('server.schedule')}
          value={s.backup_schedule}
          onChange={(backup_schedule) => void server.save({ backup_schedule })}
          options={[
            { value: 'off', label: t('server.off') },
            { value: 'daily', label: t('server.daily') },
            { value: 'weekly', label: t('server.weekly') },
          ]}
          className="w-48"
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
      </div>
      <Feedback problem={server.problem} done={server.done} />
      <div className="flex flex-wrap gap-2">
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
          <Upload size={16} />
          {t('server.uploadBackup')}
        </Button>
      </div>
      <ul className="space-y-2 text-sm">
        {list.length === 0 && <li className="text-muted">{t('server.noBackups')}</li>}
        {list.map((entry) => (
          <li key={entry.name} className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-sheet-2/50 px-4 py-2.5">
            <span className="min-w-0 flex-1">
              <span className="block font-semibold">{new Date(entry.created).toLocaleString(i18n.language)}</span>
              <span className="block text-xs text-muted">
                {entry.uploaded ? t('server.uploaded') : t(`server.kinds.${entry.kind}`)} · {t('server.countAccounts', { count: entry.accounts })}
                {entry.documents ? `, ${t('server.countDocuments', { count: entry.documents })}` : ''} · {size(entry.size)} · {entry.version}
              </span>
            </span>
            <button type="button" className={icon} title={t('server.check')} aria-label={t('server.check')} onClick={() => void action.run(async () => setBrief({ ...(await api<Brief>(`/api/v1/backups/${entry.name}/check`, { method: 'POST' })), name: entry.name }))}>
              <ShieldCheck size={16} />
            </button>
            <button type="button" className={icon} title={t('server.download')} aria-label={t('server.download')} onClick={() => setAsking({ kind: 'download', name: entry.name })}>
              <Download size={16} />
            </button>
            <button
              type="button"
              className={icon}
              title={t('server.restore')}
              aria-label={t('server.restore')}
              onClick={() =>
                // The trial run first: the dialog that asks for the password tells what the restore would do.
                void action.run(async () => {
                  const found = await api<Brief>(`/api/v1/backups/${entry.name}/check`, { method: 'POST' })
                  if (found.usable) setAsking({ kind: 'restore', name: entry.name, brief: found })
                  else setBrief({ ...found, name: entry.name })
                })
              }
            >
              <RotateCcw size={16} />
            </button>
            <button type="button" className={icon + ' hover:text-bad'} title={t('server.deleteBackup')} aria-label={t('server.deleteBackup')} onClick={() => setAsking({ kind: 'delete', name: entry.name })}>
              <Trash2 size={16} />
            </button>
          </li>
        ))}
      </ul>
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
    <Card id="languages" icon={Languages} title={t('server.languages')} text={t('server.languagesHint')}>
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

type LogLine = { time: string; level: string; logger: string; message: string }
type LogMode = { mode: string; until: string | null; fixed_by_env: boolean; modes: string[] }

export function LogCard() {
  const { t } = useTranslation()
  const [lines, setLines] = useState<LogLine[] | null>(null)
  const [level, setLevel] = useState('')
  const [words, setWords] = useState('')
  const [mode, setMode] = useState<LogMode | null>(null)
  const [clearing, setClearing] = useState(false)
  const action = useAction()
  const load = useCallback(() => {
    api<LogLine[]>('/api/v1/logs', { query: { level: level || undefined, search: words.trim() || undefined, limit: 300 } }).then(setLines, () => undefined)
  }, [level, words])
  useEffect(() => {
    const timer = window.setTimeout(load, 250)
    return () => window.clearTimeout(timer)
  }, [load])
  useEffect(() => {
    api<LogMode>('/api/v1/logs/level').then(setMode, () => undefined)
  }, [])
  const tone = (line: LogLine) => (line.level === 'ERROR' || line.level === 'CRITICAL' ? 'text-bad' : line.level === 'WARNING' ? 'text-warn' : '')
  return (
    <Card id="log" icon={ScrollText} title={t('server.log')} text={t('server.logHint')}>
      <div className="flex flex-wrap items-end gap-2">
        <Select
          label={t('server.level')}
          value={level}
          onChange={setLevel}
          options={[
            { value: '', label: t('server.allLevels') },
            { value: 'INFO', label: 'INFO' },
            { value: 'WARNING', label: 'WARNING' },
            { value: 'ERROR', label: 'ERROR' },
          ]}
          className="w-40"
        />
        <Input label={t('server.logSearch')} value={words} onChange={setWords} className="min-w-40 flex-1" />
        <Button onClick={load}>{t('server.refresh')}</Button>
      </div>
      <div className="max-h-[28rem] overflow-auto rounded-xl border border-line font-mono text-xs" role="log">
        {lines?.length === 0 && <p className="px-4 py-2.5 text-muted">{t('server.logEmpty')}</p>}
        {lines?.map((line, index) => (
          <div key={index} className={'flex gap-4 border-b border-line px-4 py-2 break-words whitespace-pre-wrap last:border-b-0 ' + tone(line)}>
            <span className="w-36 shrink-0 text-muted">{line.time}</span>
            <span className="min-w-0">
              {line.level} <span className="text-muted">{line.logger}</span> {line.message}
            </span>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        {mode && (
          <label className="block text-sm">
            <span className="font-semibold">{t('server.detail')}</span>
            <select
              className="mt-1 block h-11 w-56 rounded-xl border border-line bg-sheet px-3 text-ink"
              value={mode.mode}
              disabled={mode.fixed_by_env}
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
        <a href="/api/v1/logs/download" className="inline-flex h-10 items-center justify-center gap-2 rounded-full border border-line px-4 text-sm font-semibold text-ink-2 hover:bg-sheet-2">
          <Download size={16} />
          {t('server.download')}
        </a>
        <Button onClick={() => setClearing(true)}>
          <Trash2 size={15} /> {t('server.logClear')}
        </Button>
      </div>
      {mode?.until && <p className="text-xs text-muted">{t('server.logUntil', { time: new Date(mode.until).toLocaleTimeString() })}</p>}
      <Feedback problem={action.problem} done={action.done} />
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
