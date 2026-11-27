/**
 * Server › "Accounts", the operator's list as the shared account module lays it out (konten 1.1.0, `ACCOUNT_LIST`,
 * `capsOf`), the same in every nex app: one row per account with its picture, name, badges and "username · email", and
 * "Manage" on the right, which opens a dialog with every fact and every act in words (`MANAGE_DIALOG`: change, rights,
 * access, end). No table, no menu of three dots.
 *
 * Everything the table of 1.12.0 could do is in the dialog: the role, a link for a new password, resetting the second
 * factor, signing out everywhere, taking a provider's link, blocking and unblocking, deleting; new are renaming and
 * taking an address away. Since konten 1.1.0 the module brings several operators, the storage limit of an account
 * (with what its documents take), "KI erlaubt" under "Rights" and bringing a deleted account back within 30 days. nexpaper's
 * own parts stand at the module's fixed places: the documents of the own vault as a fact, and "Delete account" opens
 * nexpaper's own dialog of handing the documents over (to a person, into a shared vault, or deleting them along; the
 * hand-over happens when the 30 days are over; refused while the account manages a shared vault alone; the account's
 * name typed once more). The open invitations are the module's card under the list (expired ones stay until
 * withdrawn), then "Was du siehst" with nexpaper's sentence; "API-Schlüssel aller Konten" follows (`KeysCards.tsx`).
 */
import { Mail, Users } from 'lucide-react'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import {
  accountsApi,
  invitesApi,
  oidcApi,
  vaultsApi,
  type AccountLeaving,
  type AccountLink,
  type AccountRow,
  type DocumentsChoice,
  type FactorResetOverview,
  type Invite,
  type Person,
} from '../../api/client'
import { DEVICES_AT, deviceRequest } from '../../api/devices'
import { AccountButton } from '../../components/AccountButton'
import { confirmOf } from '../../lib/accountButton'
import { formatBytes } from '../../lib/bytes'
import { useAuth } from '../../state/auth'
import { AccountDevicesPart } from '../../vendor/nexgeraete'
import { WhatYouSeeCard } from '../../vendor/nexkonten/AccountCards'
import {
  ACCOUNT_LIST,
  accountActions,
  accountBadges,
  accountCount,
  accountFacts,
  accountLine,
  accountName,
  accountPicture,
  confirmLine,
  DELETE_DAYS,
  DISPLAY_NAME_MAX,
  FACTOR_RESET_DEFAULTS,
  factorResetParts,
  INVITE_DIALOG,
  inviteFields,
  inviteRow,
  linkSubmit,
  MANAGE_CONFIRM,
  MANAGE_DIALOG,
  manageGroups,
  OPEN_INVITES,
  RESET_DAYS,
  RESET_DAYS_DEFAULT,
  RESET_LINK_DIALOG,
  removeLines,
  STORAGE_LIMIT_DIALOG,
  STORAGE_LIMIT_UNIT,
  storageFact,
  FIELDS,
  USERNAME_MAX,
  type AccountAction,
  type BadgeShown,
  type ListedAccount,
  type ListedInvite,
} from '../../vendor/nexkonten/konten'
import { Avatar, Badge, Button, ButtonGroup, Card, CheckboxRow, ConfirmDialog, CopyRow, Dialog, Facts, Field, Notice, Row, Rows, SelectField, formatDay, formatMoment, type IconName } from '../../vendor/nexui'
import { APP_CAPS, appOwnFacts, listedOf } from './accountList'
import { useAction } from './actions'
import { Outcome } from './Outcome'

/** A day as all nex apps write it (E65, ui `formatDay`: "25.11.2026"). */
function day(value: string, lang: string): string {
  return formatDay(value, lang)
}

/** A moment as all nex apps write it (E65, ui `formatMoment`: "heute, 14:05", else "25.11.2026, 14:05"). */
function moment(value: string, lang: string): string {
  return formatMoment(value, lang)
}

/** The badges of a row or an invitation, in the kit's look; a day in the app's way of writing it. */
function Badges({ shown }: { shown: BadgeShown[] }) {
  const { t, i18n } = useTranslation()
  return (
    <>
      {shown.map((badge, index) => (
        <Badge key={`${badge.badge}-${index}`} tone={badge.tone}>
          {badge.label ?? t(badge.text, badge.date ? { day: day(badge.date, i18n.language) } : undefined)}
        </Badge>
      ))}
    </>
  )
}

/** The picture of an account: its own, else the letter on the hue of its name (the same on server and iPhone). */
function Picture({ row, size }: { row: ListedAccount; size: 32 | 48 }) {
  const picture = accountPicture(row)
  return <Avatar src={picture.src} letter={picture.letter} hue={picture.hue} size={size} />
}

export function AccountsTab() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [rows, setRows] = useState<AccountRow[] | null>(null)
  const [links, setLinks] = useState<AccountLink[]>([])
  const [invites, setInvites] = useState<Invite[]>([])
  const [inviting, setInviting] = useState(false)
  const [managing, setManaging] = useState<number | null>(null)
  const [withdrawing, setWithdrawing] = useState<Invite | null>(null)
  const action = useAction()

  const load = useCallback(() => {
    accountsApi.list().then(setRows, () => setRows([]))
    oidcApi.links().then(setLinks, () => setLinks([]))
    invitesApi.list().then(setInvites, () => undefined)
  }, [])
  useEffect(load, [load])

  if (!rows || !me) return null
  // The operator's own account first, the others as the server orders them.
  const ordered = [...rows.filter((row) => row.id === me.id), ...rows.filter((row) => row.id !== me.id)]
  const listed = ordered.map((row) => listedOf(row, me.id, links))
  const open = managing === null ? null : (ordered.find((row) => row.id === managing) ?? null)

  return (
    <>
      <Card id="accounts" icon={Users} title={t(ACCOUNT_LIST.title)} subtitle={t(ACCOUNT_LIST.subtitle, { count: accountCount(listed) })} testId="account-list">
        <div>
          <AccountButton name="account.invite" testId="invite-open" onClick={() => setInviting(true)} />
        </div>
        <Rows label={t(ACCOUNT_LIST.title)} testId="account-rows">
          {listed.map((row) => (
            <Row
              key={row.id}
              testId={`account-row-${row.username}`}
              lead={<Picture row={row} size={32} />}
              name={accountName(row)}
              badge={<Badges shown={accountBadges(row)} />}
              sub={accountLine(row)}
              action={
                <AccountButton name="account.manage" aria-label={t(ACCOUNT_LIST.manageLabel, { name: accountName(row) })} testId="account-manage" onClick={() => setManaging(Number(row.id))}>
                  {t(ACCOUNT_LIST.manage)}
                </AccountButton>
              }
            />
          ))}
        </Rows>
        <Outcome problem={action.problem} done={action.done} />
      </Card>

      {invites.length > 0 && (
        <Card id="open-invites" icon={Mail} title={t(OPEN_INVITES.title)} testId="open-invites">
          <Rows label={t(OPEN_INVITES.title)}>
            {invites.map((invite) => {
              const shown = inviteRow(inviteOf(invite))
              return (
                <Row
                  key={invite.id}
                  testId="invite-row"
                  icon={Mail}
                  name={shown.name || t(shown.nameText)}
                  badge={<Badges shown={shown.badges} />}
                  sub={shown.sub || undefined}
                  action={<AccountButton name="account.inviteWithdraw" onClick={() => setWithdrawing(invite)} />}
                />
              )
            })}
          </Rows>
        </Card>
      )}

      <WhatYouSeeCard t={t} text={t('server.whatYouSee')} />

      {open && (
        <ManageDialog
          row={open}
          ownId={me.id}
          links={links}
          operatorHasPassword={me.sign_in === 'password'}
          mailServer={Boolean(me.mail)}
          onClose={() => setManaging(null)}
          onChanged={load}
          onGone={() => {
            setManaging(null)
            load()
          }}
        />
      )}
      {inviting && <InviteDialog onClose={() => setInviting(false)} onMade={load} />}
      {withdrawing && (
        <ConfirmDialog
          title={t('account.inviteWithdraw')}
          text={t(MANAGE_CONFIRM['account.inviteWithdraw'].text)}
          confirm={confirmOf('account.inviteWithdraw', t('account.inviteWithdraw'))}
          cancel={t('common.cancel')}
          closeLabel={t('common.close')}
          busy={action.busy}
          onCancel={() => setWithdrawing(null)}
          onConfirm={() =>
            void action.run(async () => {
              await invitesApi.withdraw(withdrawing.id)
              setWithdrawing(null)
              load()
            })
          }
        />
      )}
    </>
  )
}

/** An invitation of nexpaper's answer as the module's list knows it. */
function inviteOf(invite: Invite): ListedInvite {
  return {
    id: invite.id,
    displayName: invite.display_name ?? '',
    email: invite.email,
    expiresAt: invite.expires_at,
    expired: invite.expired,
  }
}

/** An act of the dialog waiting for its confirmation, with what a reset of the second factor would take. */
type Pending = { action: Extract<AccountAction, { type: 'button' }>; overview?: FactorResetOverview | null }

/** The dialog "Manage" (`MANAGE_DIALOG`): the head with picture, name, badges and line; the facts with the documents of
 * the own vault; then the groups with their buttons in words and the box "AI allowed". */
function ManageDialog({ row, ownId, links, operatorHasPassword, mailServer, onClose, onChanged, onGone }: {
  row: AccountRow
  ownId: number
  links: AccountLink[]
  operatorHasPassword: boolean
  mailServer: boolean
  onClose: () => void
  onChanged: () => void
  onGone: () => void
}) {
  const { t, i18n } = useTranslation()
  const lang = i18n.language
  const listed = listedOf(row, ownId, links)
  const name = accountName(listed)
  const action = useAction()
  const [pending, setPending] = useState<Pending | null>(null)
  const [naming, setNaming] = useState<'name' | 'display_name' | null>(null)
  const [resetting, setResetting] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [limiting, setLimiting] = useState(false)

  const facts = accountFacts(listed, [...appOwnFacts(row, lang), storageFact(listed, (size) => formatBytes(size, lang, 1000))]).map((fact) => ({
    label: t(fact.label),
    value: (
      <>
        {fact.raw ?? (fact.date ? moment(fact.date, lang) : fact.text ? t(fact.text, fact.values) : '')}
        {fact.state && <span className="text-[var(--nexui-text-muted)]"> · {t(fact.state)}</span>}
      </>
    ),
    note: fact.note ? t(fact.note) : undefined,
    testId: `fact-${fact.fact}`,
  }))
  const groups = manageGroups(accountActions(listed, APP_CAPS))

  const start = (act: Extract<AccountAction, { type: 'button' }>) => {
    const base = act.name.split(':')[0]
    if (base === 'account.changeUsername') return setNaming('name')
    if (base === 'account.changeDisplayName') return setNaming('display_name')
    if (base === 'account.resetLink') return setResetting(true)
    if (base === 'account.storageLimit') return setLimiting(true)
    // nexpaper's own question at the module's place: where the documents of the own vault go (SCHNITTSTELLE 0.3.9).
    if (base === 'account.remove') return setRemoving(true)
    if (base === 'account.factorReset') {
      return void accountsApi.resetOverview(row.id).then(
        (overview) => setPending({ action: act, overview }),
        () => setPending({ action: act, overview: null }),
      )
    }
    setPending({ action: act })
  }

  /** "KI erlaubt", the module's right (konten 1.1.0), saved at once without a password as before. */
  const tick = (checked: boolean) =>
    void action.run(async () => {
      await accountsApi.permissions(row.id, checked)
      onChanged()
    })

  return (
    <>
      {/* While a window of an act stands above it, Escape belongs to that one: "Verwalten" stays (ui `dismissable`). */}
      <Dialog title={t(MANAGE_DIALOG.title, { name })} onClose={onClose} closeLabel={t('common.close')} testId="manage-dialog" dismissable={!pending && !naming && !resetting && !removing && !limiting}>
        <div className="flex flex-col gap-4">
          <Rows>
            <Row lead={<Picture row={listed} size={48} />} name={name} badge={<Badges shown={accountBadges(listed)} />} sub={accountLine(listed)} />
          </Rows>
          <Facts items={facts} label={t(MANAGE_DIALOG.title, { name })} testId="manage-facts" />
          {/* The account's iPhones and iPads (geraete 0.1.0, G28): how many, which, last seen; "Geräte trennen". */}
          <AccountDevicesPart
            request={deviceRequest}
            base={DEVICES_AT}
            accountId={row.id}
            name={name}
            blocked={row.blocked || Boolean(row.deleted_at)}
            language={lang}
            onChanged={onChanged}
          />
          {groups.map((group) => (
            <ButtonGroup key={group.group} title={t(group.title)} layout={group.layout} testId={`manage-${group.group}`}>
              {group.actions.map((act) =>
                act.type === 'button' ? (
                  <Button key={act.name} kind={act.kind} icon={act.icon as IconName} disabled={action.busy} onClick={() => start(act)} testId={`manage-${act.name}`}>
                    {t(act.label, act.values)}
                  </Button>
                ) : (
                  <CheckboxRow key={act.name} label={t(act.label)} hint={act.hint ? t(act.hint) : undefined} checked={act.checked} disabled={action.busy} onChange={tick} testId={`manage-${act.name}`} />
                ),
              )}
            </ButtonGroup>
          ))}
          <Outcome problem={action.problem} done={action.done} values={action.values} />
        </div>
      </Dialog>
      {pending && (
        <ConfirmAct
          row={row}
          name={name}
          pending={pending}
          operatorHasPassword={operatorHasPassword}
          onCancel={() => setPending(null)}
          onDone={() => {
            setPending(null)
            onChanged()
          }}
        />
      )}
      {naming && <NameDialog row={row} field={naming} operatorHasPassword={operatorHasPassword} onClose={() => setNaming(null)} onSaved={onChanged} />}
      {resetting && <ResetLinkDialog row={row} name={name} mailServer={mailServer} operatorHasPassword={operatorHasPassword} onClose={() => setResetting(false)} />}
      {removing && <DeleteAccount row={row} name={name} operatorHasPassword={operatorHasPassword} onCancel={() => setRemoving(false)} onDeleted={onGone} />}
      {limiting && <LimitDialog row={row} name={name} operatorHasPassword={operatorHasPassword} onClose={() => setLimiting(false)} onSaved={onChanged} />}
    </>
  )
}

/** The question of one act: the act's own words, kind and symbol on the confirming button, the module's sentence
 * (`MANAGE_CONFIRM`), for the reset of the second factor its parts (`factorResetParts`); with the operator's own
 * password where it asks for one (`confirmLine`; an operator without one signs in fresh at the provider instead). */
function ConfirmAct({ row, name, pending, operatorHasPassword, onCancel, onDone }: {
  row: AccountRow
  name: string
  pending: Pending
  operatorHasPassword: boolean
  onCancel: () => void
  onDone: () => void
}) {
  const { t } = useTranslation()
  const [password, setPassword] = useState('')
  const [disconnect, setDisconnect] = useState<boolean>(FACTOR_RESET_DEFAULTS.factorResetDevices)
  const [removePasskeys, setRemovePasskeys] = useState<boolean>(FACTOR_RESET_DEFAULTS.factorResetPasskeys)
  const action = useAction()
  const act = pending.action
  const base = act.name.split(':')[0] as keyof typeof MANAGE_CONFIRM
  const spec = MANAGE_CONFIRM[base]
  const asksPassword = (spec?.confirm ?? 'password') === 'password'
  const values = { name, provider: act.values?.provider ?? '', email: row.email, app: 'nexpaper' }
  const passkeys = pending.overview?.passkeys ?? []

  const lines: ReactNode[] = []
  if (spec?.text && base !== 'account.factorReset') {
    lines.push(
      <p key="text" className="m-0 text-sm">
        {t(spec.text, values)}
      </p>,
    )
  }
  if (base === 'account.factorReset') {
    for (const part of factorResetParts({ passkeys })) {
      if (part === 'factorResetHint') lines.push(<p key={part} className="m-0 text-sm">{t('account.factorResetHint')}</p>)
      if (part === 'passkeys') {
        lines.push(
          <p key={part} className="m-0 text-sm">
            {t('account.passkeys')}: {passkeys.map((key) => key.name).join(', ')}
          </p>,
        )
      }
      if (part === 'factorResetPasskeys') lines.push(<CheckboxRow key={part} label={t('account.factorResetPasskeys')} checked={removePasskeys} onChange={setRemovePasskeys} />)
      if (part === 'factorResetDevices') lines.push(<CheckboxRow key={part} label={t('account.factorResetDevices')} checked={disconnect} onChange={setDisconnect} />)
    }
  }
  if (asksPassword) {
    lines.push(
      <p key="confirm" className="m-0 text-sm text-[var(--nexui-text-muted)]">
        {t(confirmLine(operatorHasPassword))}
      </p>,
    )
  }

  return (
    <ConfirmDialog
      title={t(act.label, act.values)}
      confirm={confirmOf(act.button, t(act.label, act.values))}
      cancel={t('common.cancel')}
      closeLabel={t('common.close')}
      busy={action.busy}
      confirmDisabled={asksPassword && operatorHasPassword && !password}
      testId="manage-confirm"
      onCancel={onCancel}
      onConfirm={() =>
        void action.run(async () => {
          if (base === 'account.makeOperator') await accountsApi.role(row.id, 'operator', password)
          if (base === 'account.makeMember') await accountsApi.role(row.id, 'member', password)
          if (base === 'account.emailRemove') await accountsApi.removeEmail(row.id, password)
          if (base === 'account.factorReset') await accountsApi.resetSecondFactor(row.id, password, disconnect, removePasskeys && passkeys.length > 0)
          if (base === 'account.signOutAccount') await accountsApi.signOut(row.id)
          if (base === 'account.unlinkProvider' && act.provider) await oidcApi.unlinkAccount(row.id, Number(act.provider.id), password)
          if (base === 'account.block') await accountsApi.block(row.id, password)
          if (base === 'account.unblock') await accountsApi.unblock(row.id, password)
          if (base === 'account.restore') await accountsApi.restore(row.id, password)
          onDone()
        })
      }
    >
      {lines}
      {asksPassword && operatorHasPassword && (
        <Field label={t(FIELDS.password.label)} type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
      )}
      <Outcome problem={action.problem} values={action.values} />
    </ConfirmDialog>
  )
}

/**
 * "Delete account", nexpaper's own question at the module's place (SCHNITTSTELLE "Seit 0.3.9", point 4): the module's
 * sentence (`account.askRemove`), then nexpaper's numbers (the documents of the own vault, the trash included) and
 * where they go (to a person's own vault, into a shared vault, or deleted along), where the operator would see them
 * afterwards, then `removeLines` ("cannot be undone"). Refused while the account manages a shared vault alone; the
 * account's name typed once more, the operator's own password. The route and its fields are 1.12.0's.
 */
function DeleteAccount({ row, name, operatorHasPassword, onCancel, onDeleted }: {
  row: AccountRow
  name: string
  operatorHasPassword: boolean
  onCancel: () => void
  onDeleted: () => void
}) {
  const { t, i18n } = useTranslation()
  const [leaving, setLeaving] = useState<AccountLeaving | null>(null)
  const [people, setPeople] = useState<Person[]>([])
  const [choice, setChoice] = useState<DocumentsChoice | ''>('')
  const [heir, setHeir] = useState('')
  const [place, setPlace] = useState('')
  const [typed, setTyped] = useState('')
  const [secret, setSecret] = useState('')
  const action = useAction()
  useEffect(() => {
    let alive = true
    Promise.all([accountsApi.leaving(row.id), vaultsApi.people()]).then(
      ([found, everybody]) => {
        if (!alive) return
        setLeaving(found)
        setPeople(everybody.filter((person) => person.id !== row.id))
      },
      () => undefined,
    )
    return () => {
      alive = false
    }
  }, [row.id])
  const count = leaving?.documents ?? 0
  const ready =
    leaving !== null &&
    leaving.sole_manager_of.length === 0 &&
    typed.trim() === row.name &&
    (!operatorHasPassword || secret !== '') &&
    (count === 0 || (choice === 'transfer_to_user' && heir !== '') || (choice === 'transfer_to_vault' && place !== '') || choice === 'delete_documents')
  const seesHeir = heir !== '' && (leaving?.heirs_you_see ?? []).includes(Number(heir))
  const seesVault = place !== '' && (leaving?.shared_vaults ?? []).some((vault) => String(vault.id) === place && vault.you_see)
  // Said plainly where the operator would see the documents afterwards (allowed, but in the open).
  const youSee = (
    <p role="note" className="m-0 rounded-[9px] bg-[var(--nexui-surface-hover)] px-2.5 py-1.5 text-xs font-semibold">
      {t('server.remove.youSee')}
    </p>
  )
  // One of three ways: a choice of one, so radio buttons in the kit's colours.
  const way = (value: DocumentsChoice, label: string, hint: string, extra?: ReactNode) => (
    <div className="rounded-[12px] border border-[var(--nexui-line)] px-3 py-2.5 text-sm" data-testid={`remove-${value}`}>
      <label className="flex items-start gap-2.5">
        <input type="radio" name="documents" checked={choice === value} onChange={() => setChoice(value)} className="mt-0.5 h-4 w-4 accent-[var(--nexui-accent)]" />
        <span>
          <span className="block font-semibold">{label}</span>
          <span className="block text-xs text-[var(--nexui-text-muted)]">{hint}</span>
        </span>
      </label>
      {choice === value && extra && <div className="mt-2 flex flex-col gap-2 pl-6">{extra}</div>}
    </div>
  )
  return (
    <Dialog title={t('account.remove')} onClose={onCancel} closeLabel={t('common.close')} testId="remove-dialog">
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (!ready) return
          void action.run(async () => {
            await accountsApi.remove(row.id, {
              current_password: secret,
              confirm_name: typed.trim(),
              ...(count > 0 && choice ? { documents: choice } : {}),
              ...(count > 0 && choice === 'transfer_to_user' ? { target_user_id: Number(heir) } : {}),
              ...(count > 0 && choice === 'transfer_to_vault' ? { target_vault_id: Number(place) } : {}),
            })
            onDeleted()
          })
        }}
      >
        <p className="m-0 text-sm">{t(MANAGE_CONFIRM['account.remove'].text, { name, app: 'nexpaper' })}</p>
        {!leaving && <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t('server.remove.loading')}</p>}
        {leaving && leaving.sole_manager_of.length > 0 && (
          <Notice tone="danger" testId="remove-sole-manager">
            {t('server.remove.soleManager', { name, vaults: leaving.sole_manager_of.map((vault) => `„${vault.name}“`).join(', ') })}
          </Notice>
        )}
        {leaving && count === 0 && <p className="m-0 text-sm">{t('server.remove.none')}</p>}
        {leaving && count > 0 && (
          <fieldset className="flex flex-col gap-2" data-testid="remove-documents">
            <legend className="mb-2 text-sm font-semibold">{t('server.remove.documents', { count, n: count.toLocaleString(i18n.language) })}</legend>
            {way(
              'transfer_to_user',
              t('server.remove.toPerson'),
              t('server.remove.toPersonHint'),
              people.length > 0 ? (
                <>
                  <SelectField
                    label={t('server.remove.choosePerson')}
                    value={heir}
                    onChange={(event) => setHeir(event.target.value)}
                    options={[{ value: '', label: '' }, ...people.map((person) => ({ value: String(person.id), label: person.display_name || person.name }))]}
                  />
                  {seesHeir && youSee}
                </>
              ) : (
                <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t('server.remove.noPerson')}</p>
              ),
            )}
            {way(
              'transfer_to_vault',
              t('server.remove.toVault'),
              t('server.remove.toVaultHint'),
              leaving.shared_vaults.length > 0 ? (
                <>
                  <SelectField
                    label={t('server.remove.chooseVault')}
                    value={place}
                    onChange={(event) => setPlace(event.target.value)}
                    options={[{ value: '', label: '' }, ...leaving.shared_vaults.map((vault) => ({ value: String(vault.id), label: vault.name }))]}
                  />
                  {seesVault && youSee}
                </>
              ) : (
                <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t('server.remove.noVault')}</p>
              ),
            )}
            {way('delete_documents', t('server.remove.deleteAll'), t('server.remove.deleteAllHint'))}
          </fieldset>
        )}
        {removeLines(APP_CAPS).map((line) => (
          <p key={line} className="m-0 text-sm">
            {t(line, { count: DELETE_DAYS })}
          </p>
        ))}
        <Field label={t('server.remove.typeName', { name: row.name })} value={typed} onChange={(event) => setTyped(event.target.value)} autoComplete="off" />
        <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t(confirmLine(operatorHasPassword))}</p>
        {operatorHasPassword && <Field label={t(FIELDS.password.label)} type="password" autoComplete="current-password" value={secret} onChange={(event) => setSecret(event.target.value)} />}
        <Outcome problem={action.problem} values={action.values} />
        <div className="flex flex-wrap justify-end gap-2">
          <AccountButton name="cancel" onClick={onCancel}>
            {t('common.cancel')}
          </AccountButton>
          <AccountButton name="account.remove" type="submit" busy={action.busy} disabled={!ready} testId="remove-submit" />
        </div>
      </form>
    </Dialog>
  )
}

/** "Change display name" or "Change username" (the module's fields and hints), with the operator's own password. */
function NameDialog({ row, field, operatorHasPassword, onClose, onSaved }: {
  row: AccountRow
  field: 'name' | 'display_name'
  operatorHasPassword: boolean
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const [value, setValue] = useState(field === 'name' ? row.name : row.display_name)
  const [own, setOwn] = useState('')
  const action = useAction()
  const title = field === 'name' ? t('account.changeUsername') : t('account.changeDisplayName')
  return (
    <Dialog title={title} onClose={onClose} closeLabel={t('common.close')} testId="name-dialog">
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          void action.run(async () => {
            if (field === 'name') await accountsApi.rename(row.id, value.trim(), own)
            else await accountsApi.displayName(row.id, value.trim(), own)
            onSaved()
            onClose()
          })
        }}
      >
        {field === 'name' && <p className="m-0 text-sm">{t('account.askChangeUsername', { name: row.display_name || row.name })}</p>}
        <Field
          label={field === 'name' ? t('account.username') : t('account.displayName')}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          maxLength={field === 'name' ? USERNAME_MAX : DISPLAY_NAME_MAX}
          hints={[field === 'name' ? t('account.usernameRules') : t('account.displayNameHint')]}
        />
        <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t(confirmLine(operatorHasPassword))}</p>
        {operatorHasPassword && <Field label={t(FIELDS.password.label)} type="password" autoComplete="current-password" value={own} onChange={(event) => setOwn(event.target.value)} />}
        <Outcome problem={action.problem} values={action.values} />
        <div className="flex flex-wrap justify-end gap-2">
          <AccountButton name="cancel" onClick={onClose}>
            {t('common.cancel')}
          </AccountButton>
          <AccountButton name="account.save" type="submit" disabled={action.busy || (operatorHasPassword && !own) || (field === 'name' && !value.trim())} />
        </div>
      </form>
    </Dialog>
  )
}

/** The storage limit of the account (konten 1.1.0, `STORAGE_LIMIT_DIALOG`; an upload past it is refused with a sentence,
 * nexpaper's line), with the operator's own password. */
function LimitDialog({ row, name, operatorHasPassword, onClose, onSaved }: {
  row: AccountRow
  name: string
  operatorHasPassword: boolean
  onClose: () => void
  onSaved: () => void
}) {
  const { t, i18n } = useTranslation()
  const [value, setValue] = useState(row.storage_limit ? String(Math.round((row.storage_limit / STORAGE_LIMIT_UNIT) * 10) / 10) : '')
  const [own, setOwn] = useState('')
  const action = useAction()
  const save = (limit: number | null) =>
    void action.run(async () => {
      await accountsApi.limit(row.id, limit, own)
      onSaved()
      onClose()
    })
  return (
    <Dialog title={t(STORAGE_LIMIT_DIALOG.title, { name })} onClose={onClose} closeLabel={t('common.close')} testId="limit-dialog">
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          const gigabytes = Number(value.replace(',', '.'))
          if (!gigabytes || gigabytes <= 0) return
          save(Math.round(gigabytes * STORAGE_LIMIT_UNIT))
        }}
      >
        <p className="m-0 text-sm">{t('server.limitText')}</p>
        <Field
          label={t(STORAGE_LIMIT_DIALOG.field)}
          type="number"
          min={0}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          hints={[t(STORAGE_LIMIT_DIALOG.used, { used: formatBytes(row.storage_used ?? 0, i18n.language, 1000) })]}
        />
        <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t(confirmLine(operatorHasPassword))}</p>
        {operatorHasPassword && <Field label={t(FIELDS.password.label)} type="password" autoComplete="current-password" value={own} onChange={(event) => setOwn(event.target.value)} />}
        <Outcome problem={action.problem} values={action.values} />
        <div className="flex flex-wrap justify-end gap-2">
          {row.storage_limit != null && (
            <AccountButton name="account.storageLimitRemove" disabled={action.busy || (operatorHasPassword && !own)} onClick={() => save(null)}>
              {t(STORAGE_LIMIT_DIALOG.remove)}
            </AccountButton>
          )}
          <AccountButton name="account.save" type="submit" disabled={action.busy || !value || (operatorHasPassword && !own)}>
            {t(STORAGE_LIMIT_DIALOG.save)}
          </AccountButton>
        </div>
      </form>
    </Dialog>
  )
}

/** A link to hand on: its name, the kit's row that copies it, and a line under it. */
function CopyField({ value, label, hint }: { value: string; label: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-sm font-medium">{label}</span>
      <CopyRow value={value} label={label} />
      {hint && <span className="text-xs text-[var(--nexui-text-muted)]">{hint}</span>}
    </div>
  )
}

/** "Link for a new password" (`RESET_LINK_DIALOG`): the operator never sets another account's password; with a mail
 * server and an address that counts the link goes there, else it shows once to hand on (then only "Fertig" or the close
 * button end the window, ui `dismissable`, E38). Also for a blocked account. */
function ResetLinkDialog({ row, name, mailServer, operatorHasPassword, onClose }: {
  row: AccountRow
  name: string
  mailServer: boolean
  operatorHasPassword: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [days, setDays] = useState(String(RESET_DAYS_DEFAULT))
  const [own, setOwn] = useState('')
  const [link, setLink] = useState<string | null>(null)
  const [sent, setSent] = useState<string | null>(null)
  const action = useAction()
  const sends = mailServer && Boolean(row.email) && row.email_counts !== false
  return (
    <Dialog title={t(RESET_LINK_DIALOG.title)} onClose={onClose} closeLabel={t('common.close')} testId="reset-link-dialog" dismissable={!link && sent === null}>
      {sent !== null ? (
        <div className="flex flex-col gap-3" data-testid="reset-link">
          <Notice tone="ok">{t(RESET_LINK_DIALOG.sent, { email: sent, name })}</Notice>
          <div className="flex justify-end">
            <AccountButton name="done" onClick={onClose}>
              {t('common.done')}
            </AccountButton>
          </div>
        </div>
      ) : link ? (
        <div className="flex flex-col gap-3" data-testid="reset-link">
          <p className="m-0 text-sm">{t(RESET_LINK_DIALOG.shown, { name })}</p>
          <CopyField value={link} label={t(RESET_LINK_DIALOG.title)} />
          <div className="flex justify-end">
            <AccountButton name="done" onClick={onClose}>
              {t('common.done')}
            </AccountButton>
          </div>
        </div>
      ) : (
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            void action.run(async () => {
              const answer = await accountsApi.resetLink(row.id, Number(days), own, sends)
              if (answer.sent) setSent(answer.email ?? row.email)
              else setLink(answer.link ?? '')
            })
          }}
        >
          <p className="m-0 text-sm">{t(RESET_LINK_DIALOG.text, { name })}</p>
          <SelectField
            label={t(RESET_LINK_DIALOG.days.label)}
            value={days}
            onChange={(event) => setDays(event.target.value)}
            options={RESET_DAYS.map((value) => ({ value: String(value), label: t('account.days', { count: value }) }))}
          />
          <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t(confirmLine(operatorHasPassword))}</p>
          {operatorHasPassword && <Field label={t(FIELDS.password.label)} type="password" autoComplete="current-password" value={own} onChange={(event) => setOwn(event.target.value)} />}
          <Outcome problem={action.problem} values={action.values} />
          <div className="flex flex-wrap justify-end gap-2">
            <AccountButton name="cancel" onClick={onClose}>
              {t('common.cancel')}
            </AccountButton>
            <AccountButton name={linkSubmit(sends)} type="submit" disabled={action.busy || (operatorHasPassword && !own)} />
          </div>
        </form>
      )}
    </Dialog>
  )
}

/** "Invite a person" (`INVITE_DIALOG`): the address, the display name, how long it holds, "Send by mail" only with a
 * mail server and an address; afterwards always the link to copy. No username: the person picks it. */
function InviteDialog({ onClose, onMade }: { onClose: () => void; onMade: () => void }) {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [days, setDays] = useState(String(INVITE_DIALOG.days.default))
  const [send, setSend] = useState(true)
  const [made, setMade] = useState<{ link: string; sent: boolean; email: string; expires: string } | null>(null)
  const action = useAction()
  const fields = inviteFields({ ...APP_CAPS, roles: false }, { mailServer: Boolean(me?.mail), email })
  const sends = fields.includes('sendMail') && send
  return (
    <Dialog title={t(INVITE_DIALOG.title)} onClose={onClose} closeLabel={t('common.close')} testId="invite-dialog" dismissable={!made}>
      {made ? (
        <div className="flex flex-col gap-3">
          {made.sent && (
            <Notice tone="ok" testId="invite-sent">
              {t(INVITE_DIALOG.done.sent, { email: made.email })}
            </Notice>
          )}
          <CopyField value={made.link} label={t(INVITE_DIALOG.done.link)} hint={t(INVITE_DIALOG.done.linkHint, { day: day(made.expires, i18n.language) })} />
          <div className="flex justify-end">
            <AccountButton name="done" onClick={onClose}>
              {t('common.done')}
            </AccountButton>
          </div>
        </div>
      ) : (
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            void action.run(async () => {
              const answer = await invitesApi.make({ email: email.trim(), display_name: displayName.trim(), days: Number(days), send: sends })
              setMade({ link: answer.link, sent: answer.sent, email: email.trim(), expires: answer.expires_at })
              onMade()
            })
          }}
        >
          {fields.includes('email') && <Field label={t('account.email')} type="email" value={email} onChange={(event) => setEmail(event.target.value)} hints={[t(INVITE_DIALOG.emailHint)]} />}
          {fields.includes('displayName') && <Field label={t('account.displayName')} value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={DISPLAY_NAME_MAX} />}
          {fields.includes('days') && (
            <SelectField
              label={t(INVITE_DIALOG.days.label)}
              value={days}
              onChange={(event) => setDays(event.target.value)}
              options={INVITE_DIALOG.days.options.map((value) => ({ value: String(value), label: t('account.days', { count: value }) }))}
            />
          )}
          {fields.includes('sendMail') && <CheckboxRow label={t(INVITE_DIALOG.sendMail)} checked={send} onChange={setSend} />}
          <Outcome problem={action.problem} values={action.values} />
          <div className="flex flex-wrap justify-end gap-2">
            <AccountButton name="cancel" onClick={onClose}>
              {t('common.cancel')}
            </AccountButton>
            <AccountButton name={linkSubmit(sends)} type="submit" testId="invite-submit" disabled={action.busy} />
          </div>
        </form>
      )}
    </Dialog>
  )
}
