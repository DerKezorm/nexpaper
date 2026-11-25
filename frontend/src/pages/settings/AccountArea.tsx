/**
 * The areas of "My account" in the settings (`settings/areas.ts`), as in nexnotes: Profile (picture, display name,
 * name, role, mail address with its link, language, signing out), Security (password, second factor, passkeys, the
 * sign-in providers, the signed-in browsers), Appearance (light or dark, the archive), Connections (in nexnotes' order
 * the paired devices and the API keys, then nexpaper's own: the iPhone shortcut and Web Push on the devices), and nexpaper's own: Upload (where uploads go, where a phone
 * starts), Reminders (of deadlines), AI (the own switch, and what the operator set up).
 */
import { KeyRound, Lock, LogOut, ShieldCheck, Sparkles, User } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { api, authApi, type Me, type ProfileChange, type RemainingAccess } from '../../api/client'
import { AccountButton } from '../../components/AccountButton'
import { confirmOf } from '../../lib/accountButton'
import { PAGES, screenFields } from '../../vendor/nexkonten/konten'
import { ConfirmDialog, Field, Notice, SelectField } from '../../vendor/nexui'
import { ApiKeys } from '../../components/ApiKeys'
import { Avatar } from '../../components/Avatar'
import { KeysWait } from '../../components/KeysWait'
import { MyProviders } from '../../components/MyProviders'
import { PairedDevices } from '../../components/PairedDevices'
import { useConfirm } from '../../components/useConfirm'
import { changeLanguage, languageOptions, type LanguageOption } from '../../i18n'
import { ShortcutCard, UploadVaultCard } from '../../components/PhoneCards'
import { providerName } from '../../lib/aiProviders'
import { useAiState } from '../../state/ai'
import { useAuth } from '../../state/auth'
import { UploadRequestsCard } from '../../components/UploadRequests'
import { MyIntakeCards } from './IntakeCards'
import { LooksCard, PhoneCard } from './PersonalCards'
import { PdfPasswordsCard } from './PdfPasswordsCard'
import { PushDevicesCard } from './PushCards'
import { RemindersPart } from './RemindersCards'
import { DevicesCard, PasskeysCard, SecondFactorCard, SESSIONS_CHANGED } from './SecurityCards'
import { Card, Feedback, Input, Toggle, useAction } from './ui'

export type AccountPart = 'profile' | 'security' | 'appearance' | 'connections' | 'upload' | 'reminders' | 'ai'

/** One area of the own account. */
export function AccountArea({ part }: { part: AccountPart }) {
  const { me } = useAuth()
  if (!me) return null
  return (
    <div className="space-y-6" data-testid={`account-${part}`}>
      {part === 'profile' && (
        <>
          <ProfileCard me={me} />
          <SignOutCard viaProvider={me.sign_in === 'oidc'} />
        </>
      )}
      {part === 'security' && <Security me={me} />}
      {part === 'appearance' && <LooksCard />}
      {part === 'connections' && (
        <>
          <KeysWait />
          <PairedDevices />
          <ApiKeys />
          <ShortcutCard />
          <PushDevicesCard me={me} />
        </>
      )}
      {part === 'upload' && (
        <>
          <UploadVaultCard />
          <PhoneCard />
          <MyIntakeCards />
          <PdfPasswordsCard />
          <UploadRequestsCard />
        </>
      )}
      {part === 'reminders' && <RemindersPart me={me} />}
      {part === 'ai' && <AiPart me={me} />}
    </div>
  )
}

/**
 * "Sign out", as in nexnotes: the one button for it, here in the profile (the account menu of before is gone). Only
 * nexpaper's session ends; whoever came in through a provider stays signed in there.
 */
function SignOutCard({ viaProvider }: { viaProvider: boolean }) {
  const { t } = useTranslation()
  const { signOut } = useAuth()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  return (
    <Card id="sign-out" icon={LogOut} title={t('me.signOut.title')} text={t('me.signOut.text')}>
      <div data-testid="sign-out-card" className="space-y-3">
        {viaProvider && <p className="text-xs text-muted">{t('me.signOut.provider')}</p>}
        <AccountButton
          name="signOut"
          busy={busy}
          onClick={() => {
            setBusy(true)
            void signOut().then(() => navigate('/login', { replace: true }))
          }}
        >
          {t('me.signOut.button')}
        </AccountButton>
      </div>
    </Card>
  )
}

/** "KI beim Einsortieren": the own switch, and below it what the operator set up for everybody. */
function AiPart({ me }: { me: Me }) {
  const { t } = useTranslation()
  const { setMe } = useAuth()
  const ai = useAiState()
  const action = useAction()
  const mine = me.profile.ai !== false
  const provider = ai?.provider ?? 'none'
  // The own switch only does something when there is an AI for this account: the operator set one up and allowed it
  // for the account. Otherwise it stands locked, says why, and keeps the own choice for later (nothing is changed).
  const noProvider = ai !== null && provider === 'none'
  const notAllowed = me.ai_allowed === false
  const locked = noProvider || notAllowed
  return (
    <Card icon={Sparkles} title={t('me.ai.title')} text={t('me.ai.text')}>
      <Toggle
        label={t('me.ai.mine')}
        hint={t('me.ai.mineHint')}
        checked={mine && !locked}
        disabled={locked}
        onChange={(value) => {
          setMe({ ...me, profile: { ...me.profile, ai: value } })
          void action.run(async () => setMe({ ...me, profile: await authApi.preferences({ ai: value }) })).then(
            (worked) => worked || setMe(me),
          )
        }}
      />
      {notAllowed && (
        <p className="rounded-[12px] border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-warn" role="status" data-ai-not-allowed>
          {t('me.ai.notAllowed')}
        </p>
      )}
      {!notAllowed && noProvider && (
        <p className="rounded-[12px] border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-warn" role="status" data-ai-none>
          {me.role === 'operator' ? (
            <Trans i18nKey="me.ai.noneOperator" components={{ settings: <Link to="/settings/ai-setup" className="font-semibold underline underline-offset-2" /> }} />
          ) : (
            t('me.ai.none')
          )}
        </p>
      )}
      {ai && !locked && (
        <div className="rounded-[12px] bg-sheet-2 px-4 py-3 text-sm">
          <p>
            <span className="font-semibold">{t('me.ai.byOperator')}</span> {providerName(provider, t)}
            {provider === 'local' && ai.model && ` (${ai.model})`}
          </p>
          <p className="mt-1 text-ink-2">{t(`server.ai.${provider}Note`)}</p>
          {ai.skip_personal !== false && <p className="mt-1 text-ink-2">{t('sorting.ai.skipNote')}</p>}
        </div>
      )}
      <Feedback problem={action.problem} />
    </Card>
  )
}

/**
 * "Profil" as the shared account module lays it out (`PAGES.profile`, konten 0.3.9), the same in every nex app: the
 * picture, then display name, username and address one under the other, one "Save" for all (a new username or address
 * asks for the password once, `confirmOnSave`), the address a provider offers, the language, the role small at the end.
 * nexpaper's own beside it, so nothing is lost: under the address whether it is proven by a link (only then does the
 * intake trust it) with "Send link" for one that only counts; a new address waiting for its link with "Send again" and
 * "Withdraw"; the former username under the field after a change.
 */
function ProfileCard({ me }: { me: Me }) {
  const { t, i18n } = useTranslation()
  const { setMe } = useAuth()
  const [values, setValues] = useState({ displayName: me.display_name ?? '', username: me.name, email: me.email ?? '' })
  const [password, setPassword] = useState('')
  const [asking, setAsking] = useState(false)
  const [languages, setLanguages] = useState<LanguageOption[]>([])
  const picker = useRef<HTMLInputElement>(null)
  const action = useAction()
  const { ask, dialog } = useConfirm()
  useEffect(() => {
    let alive = true
    void languageOptions().then((list) => alive && setLanguages(list))
    return () => {
      alive = false
    }
  }, [])
  useEffect(() => {
    setValues({ displayName: me.display_name ?? '', username: me.name, email: me.email ?? '' })
  }, [me.display_name, me.name, me.email])
  const withPassword = me.has_password ?? me.sign_in === 'password'
  const changed = {
    displayName: values.displayName.trim() !== (me.display_name ?? ''),
    username: values.username.trim().toLowerCase() !== me.name.toLowerCase(),
    email: values.email.trim().toLowerCase() !== (me.email ?? '').toLowerCase(),
  }
  const confirms = PAGES.profile.confirmOnSave.some((field) => changed[field])
  const any = changed.displayName || changed.username || changed.email
  const save = (own: string) =>
    void action.run(async () => {
      const change: ProfileChange = {}
      if (changed.displayName) change.display_name = values.displayName.trim()
      if (changed.username) change.name = values.username.trim()
      if (changed.email) change.email = values.email.trim()
      if (confirms) change.password = own
      setMe(await authApi.profile(change))
      setAsking(false)
      setPassword('')
    }, t('me.profile.saved'))
  /** "Send link" to the address there is, which counts but is not proven yet: the intake trusts it once opened. */
  const prove = (own: string) =>
    void action.run(async () => {
      setMe(await api<Me>('/api/v1/me/email', { method: 'PUT', body: { email: me.email, password: own } }))
      setAsking(false)
      setPassword('')
    }, t('mailAddress.sent'))
  const [proving, setProving] = useState(false)
  const fields = screenFields('profile')
  const field = (name: 'displayName' | 'username' | 'email') => fields.find((entry) => entry.field === name)!
  return (
    <Card id="profile" icon={User} title={t(PAGES.profile.title)}>
      <div className="flex items-center gap-3" data-testid="profile-picture">
        <Avatar person={me} size={56} />
        <div className="flex flex-wrap gap-2">
          <AccountButton name="account.pictureUpload" busy={action.busy} onClick={() => picker.current?.click()} />
          {me.avatar && (
            <AccountButton
              name="account.pictureRemove"
              busy={action.busy}
              onClick={() =>
                ask({
                  title: t('confirm.avatar.title'),
                  text: t('confirm.avatar.text'),
                  confirm: t('confirm.avatar.confirm'),
                  run: async () => {
                    await action.run(async () => setMe(await api<Me>('/api/v1/auth/avatar', { method: 'DELETE' })), t('me.profile.removed'))
                  },
                })
              }
            />
          )}
        </div>
        <input
          ref={picker}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif,image/bmp,image/heic,image/heif,image/avif,.heic,.heif"
          aria-label={t('account.pictureUpload')}
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            event.target.value = ''
            if (file) void action.run(async () => setMe(await api<Me>('/api/v1/auth/avatar', { method: 'PUT', raw: file })), t('me.profile.saved'))
          }}
        />
      </div>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (!any) return
          if (confirms && withPassword) return setAsking(true)
          save('')
        }}
      >
        {(['displayName', 'username', 'email'] as const).map((name) => {
          const spec = field(name)
          const hints = spec.hints.map((hint) => t(hint))
          if (name === 'username' && me.former_name) hints.push(t('account.formerUsername'))
          return (
            <Field
              key={name}
              label={t(spec.label)}
              type={spec.type === 'email' ? 'email' : 'text'}
              autoComplete={spec.autoComplete}
              maxLength={spec.maxLength || undefined}
              placeholder={name === 'displayName' ? me.name : undefined}
              hints={hints}
              value={values[name]}
              onChange={(event) => setValues({ ...values, [name]: event.target.value })}
            />
          )
        })}
        {me.email && !me.email_pending && (
          <p className="m-0 text-xs text-muted" data-testid="mail-state">
            <span className={me.email_confirmed ? 'text-ok' : 'text-warn'}>
              {me.email_confirmed ? t('mailAddress.confirmedLine') : t('mailAddress.unconfirmedLine')}
            </span>
            {!me.email_confirmed && me.mail_links && (
              <>
                {' · '}
                <button type="button" className="font-semibold text-accent hover:underline" onClick={() => (withPassword ? setProving(true) : prove(''))}>
                  {t('mailAddress.confirmNow')}
                </button>
              </>
            )}
          </p>
        )}
        {me.email_pending && (
          <Notice tone="ok" testId="mail-pending">
            {t('account.emailPending', { email: me.email_pending })}
            <span className="mt-2 flex flex-wrap gap-2">
              <AccountButton name="account.emailResend" busy={action.busy} onClick={() => void action.run(async () => setMe(await authApi.emailResend()), t('mailAddress.sent'))} />
              <AccountButton
                name="account.emailWithdraw"
                busy={action.busy}
                onClick={() =>
                  void action.run(async () => {
                    await authApi.emailWithdraw()
                    setMe(await authApi.me())
                  })
                }
              />
            </span>
          </Notice>
        )}
        {!me.email_pending && me.email && !me.email_confirmed && !me.mail_links && <p className="m-0 text-xs text-muted">{t('mailAddress.off')}</p>}
        <div>
          <AccountButton name="account.save" type="submit" busy={action.busy} disabled={!any} testId="profile-save" />
        </div>
      </form>
      {me.offered_email && (
        <Notice tone="ok" testId="provider-email-offer">
          {t('account.providerEmailOffer', { provider: me.offered_email_provider || '' })} {me.offered_email}
          <span className="mt-2 flex flex-wrap gap-2">
            <AccountButton
              name="account.providerEmailTake"
              busy={action.busy}
              onClick={() => (withPassword ? setValues({ ...values, email: me.offered_email ?? '' }) : void action.run(async () => setMe(await authApi.takeOffered(''))))}
            />
            <AccountButton
              name="account.providerEmailDismiss"
              busy={action.busy}
              onClick={() =>
                void action.run(async () => {
                  await authApi.declineOffered()
                  setMe(await authApi.me())
                })
              }
            />
          </span>
        </Notice>
      )}
      <SelectField
        label={t('account.language')}
        hints={[t('settings.language.hint')]}
        value={i18n.language}
        data-testid="language-select"
        onChange={(event) => {
          const code = event.target.value
          void changeLanguage(code)
          // Kept with the account, so the next browser speaks it too.
          void authApi.language(code).then(setMe, () => undefined)
        }}
        options={languages.map((option) => ({ value: option.code, label: option.name }))}
      />
      <p className="m-0 text-xs text-muted" data-testid="account-role">
        {t('account.role')}: {t(me.role === 'operator' ? 'account.roleOperator' : 'account.roleMember')}
      </p>
      <Feedback problem={action.problem} done={action.done} values={action.values} />
      {(asking || proving) && (
        <ConfirmDialog
          title={t('account.save')}
          text={
            changed.email && !values.email.trim() && !proving
              ? `${t('confirm.mailAddress.text', { address: me.email })} ${t('account.confirmWithPassword')}`
              : t('account.confirmWithPassword')
          }
          confirm={confirmOf('account.save', t('account.save'))}
          cancel={t('common.cancel')}
          closeLabel={t('common.close')}
          busy={action.busy}
          confirmDisabled={!password}
          onCancel={() => {
            setAsking(false)
            setProving(false)
            setPassword('')
          }}
          onConfirm={() => {
            if (proving) {
              setProving(false)
              prove(password)
            } else save(password)
          }}
        >
          <Field label={t('account.currentPassword')} type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          <Feedback problem={action.problem} values={action.values} />
        </ConfirmDialog>
      )}
      {dialog}
    </Card>
  )
}

/**
 * "Sicherheit" as in nexnotes: one card "Anmeldung und Sicherheit" with a row each for the providers, the password (it
 * opens to change it), the second factor and signing out everywhere else. nexpaper's own cards follow it, as nexnotes'
 * own follow there: passkeys, and the signed-in devices with the notice of a new sign-in. Until the second factor is
 * set up the server answers nothing else: only its row and the passkeys are shown.
 */
function Security({ me }: { me: Me }) {
  const { t } = useTranslation()
  const restricted = Boolean(me.second_factor_setup_required)
  return (
    <>
      {!restricted && me.new_password_origin && <RemainingAccessNotice />}
      <Card id="security" icon={ShieldCheck} title={t('me.security.title')}>
        {restricted && (
          <p role="note" className="rounded-[9px] border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-warn">
            {t('me.setupFirst')}
          </p>
        )}
        {!restricted && <MyProviders me={me} bare />}
        {!restricted && me.sign_in === 'password' && <PasswordRow changedAt={me.password_changed_at ?? null} />}
        <div className="rounded-[12px] border border-line px-3 py-2.5" data-testid="second-factor-row">
          <h3 className="mb-2 text-sm font-medium">{t('twofactor.title')}</h3>
          <SecondFactorCard me={me} bare />
        </div>
        {!restricted && <EverywhereElseRow />}
      </Card>
      <PasskeysCard me={me} />
      {!restricted && <DevicesCard me={me} />}
    </>
  )
}

/**
 * "These devices still have access" (the shared account module): after a password set through a link, the paired
 * devices, API keys and passkeys that stayed, with "Disconnect all" and putting the list away. After the operator's
 * or the server's link it says so first.
 */
function RemainingAccessNotice() {
  const { t } = useTranslation()
  const { setMe } = useAuth()
  const [list, setList] = useState<RemainingAccess | null>(null)
  const action = useAction()
  useEffect(() => {
    authApi.access().then(setList, () => undefined)
  }, [])
  if (!list) return null
  return (
    <Notice tone="warn" testId="remaining-access">
      {list.origin !== 'self' && <span className="mb-1 block">{t('account.resetByOperator')}</span>}
      {list.access.length > 0 && (
        <>
          <span className="block">{t('account.remainingAccess')}</span>
          <span className="mb-2 block">{list.access.map((item) => item.label).join(', ')}</span>
        </>
      )}
      <span className="flex flex-wrap gap-2">
        {list.access.length > 0 && (
          <AccountButton
            name="account.disconnectAll"
            busy={action.busy}
            onClick={() =>
              void action.run(async () => {
                await authApi.disconnectAll()
                setMe(await authApi.me())
              })
            }
          />
        )}
        <AccountButton name="done" busy={action.busy} onClick={() => void action.run(async () => setMe(await authApi.accessSeen()))}>
          {t('common.done')}
        </AccountButton>
      </span>
      <Feedback problem={action.problem} values={action.values} />
    </Notice>
  )
}

/** The password as a row that opens, as in nexnotes: the three fields and the button inside; when it was last set. */
function PasswordRow({ changedAt }: { changedAt: string | null }) {
  const { t, i18n } = useTranslation()
  const [pw, setPw] = useState({ current: '', next: '', again: '' })
  const password = useAction()
  const [unsent, setUnsent] = useState<string | null>(null)
  return (
    <details className="rounded-[12px] border border-line px-3 py-2.5 text-sm" data-testid="password-row">
      <summary className="flex cursor-pointer list-none items-center gap-3">
        <KeyRound className="h-4 w-4 text-muted" aria-hidden />
        <span className="flex-1 font-medium">{t('me.password.title')}</span>
        <span className="text-xs text-muted">
          {changedAt ? t('me.password.lastChanged', { when: new Date(changedAt).toLocaleDateString(i18n.language) }) : t('me.password.text')}
        </span>
        <span className="btn btn-ghost h-8 px-3 text-xs font-medium">{t('me.password.change')}</span>
      </summary>
      <form
        className="mt-3 space-y-3"
        onSubmit={(event) => {
          event.preventDefault()
          // Said here, before anything goes to the server.
          const missing = !pw.current ? 'current_password_missing' : !pw.next ? 'password_missing' : pw.next !== pw.again ? 'password_mismatch' : null
          setUnsent(missing)
          if (missing) return
          void password.run(async () => {
            await authApi.password(pw.current, pw.next, pw.again)
            setPw({ current: '', next: '', again: '' })
          }, t('me.password.done'))
        }}
      >
        <Input label={t('me.password.current')} type="password" value={pw.current} onChange={(current) => setPw({ ...pw, current })} autoComplete="current-password" />
        <Input label={t('me.password.new')} type="password" value={pw.next} onChange={(next) => setPw({ ...pw, next })} autoComplete="new-password" />
        <Input label={t('me.password.again')} type="password" value={pw.again} onChange={(again) => setPw({ ...pw, again })} autoComplete="new-password" />
        <AccountButton name="account.passwordChange" type="submit" busy={password.busy}>
          {t('me.password.submit')}
        </AccountButton>
        <Feedback problem={unsent ?? password.problem} done={password.done} />
      </form>
    </details>
  )
}

/** "Überall sonst abmelden" as nexnotes' row: every other browser and paired device, after a question. */
function EverywhereElseRow() {
  const { t } = useTranslation()
  const action = useAction()
  const { ask, dialog } = useConfirm()
  return (
    <div className="space-y-2 rounded-[12px] border border-line px-3 py-2.5 text-sm" data-testid="everywhere-else">
      <div className="flex flex-wrap items-center gap-3">
        <Lock className="h-4 w-4 text-muted" aria-hidden />
        {/* At least 12rem wide: on a phone the button goes to the next line instead of squeezing the text. */}
        <span className="min-w-0 grow basis-48 text-ink-2">{t('me.sessions.text')}</span>
        <AccountButton
          name="account.signOutEverywhere"
          busy={action.busy}
          onClick={() =>
            ask({
              title: t('confirm.logoutOthers.title'),
              text: t('confirm.logoutOthers.text'),
              confirm: t('confirm.logoutOthers.confirm'),
              run: async () => {
                await action.run(async () => {
                  await authApi.logoutOthers()
                  window.dispatchEvent(new Event(SESSIONS_CHANGED))
                }, t('me.devices.endedAll'))
              },
            })
          }
        />
      </div>
      <Feedback problem={action.problem} done={action.done} />
      {dialog}
    </div>
  )
}
