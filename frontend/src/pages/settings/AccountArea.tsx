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

import { api, authApi, type Me } from '../../api/client'
import { ApiKeys } from '../../components/ApiKeys'
import { Avatar } from '../../components/Avatar'
import { KeysWait } from '../../components/KeysWait'
import { MyProviders } from '../../components/MyProviders'
import { PairedDevices } from '../../components/PairedDevices'
import { useConfirm } from '../../components/useConfirm'
import { iso } from '../../lib/say'
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
import { Button, Card, Feedback, Input, Toggle, useAction } from './ui'

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
        <Button
          busy={busy}
          onClick={() => {
            setBusy(true)
            void signOut().then(() => navigate('/login', { replace: true }))
          }}
        >
          {t('me.signOut.button')}
        </Button>
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
 * "Profil" as in nexnotes (`AccountTab.tsx` there, part `profile`): one card with the picture, then name and mail address
 * side by side with "Speichern", the role below, and the language at the end. nexpaper's own on top of it, so nothing is
 * lost: the login name stands beside the role (an empty name shows it); a new address counts only after the link mailed
 * to it is opened, and asks for the password first (the address is the way back into the account), its state and a
 * link waiting stand below the fields; an emptied address is removed after a question.
 */
function ProfileCard({ me }: { me: Me }) {
  const { t, i18n } = useTranslation()
  const { setMe } = useAuth()
  const [name, setName] = useState(me.display_name ?? '')
  const [email, setEmail] = useState(me.email ?? '')
  const [password, setPassword] = useState('')
  /** "Bestätigung schicken" for the address there is, which also asks for the password. */
  const [resend, setResend] = useState(false)
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
  const withPassword = me.sign_in === 'password'
  const nameChanged = name.trim() !== (me.display_name ?? '')
  const emailChanged = !me.email_pending && email.trim() !== (me.email ?? '')
  const asksPassword = withPassword && (emailChanged || resend)
  const sendMail = (address: string) =>
    api<Me>('/api/v1/me/email', { method: 'PUT', body: { email: address, password } }).then((saved) => {
      setMe(saved)
      setEmail(saved.email ?? address)
      setPassword('')
      setResend(false)
    })
  const save = () => {
    if (resend && !emailChanged) return void action.run(() => sendMail(me.email), t('mail.sent'))
    const work = async () => {
      if (nameChanged) {
        const saved = await authApi.profile(name.trim())
        setName(saved.display_name)
        setMe(saved)
      }
      if (emailChanged) await sendMail(email.trim())
    }
    const done = emailChanged ? (email.trim() ? t('mail.sent') : t('mail.removed')) : t('me.profile.displaySaved')
    if (emailChanged && !email.trim())
      return ask({
        title: t('confirm.mailAddress.title'),
        text: t('confirm.mailAddress.text', { address: iso(me.email) }),
        confirm: t('confirm.mailAddress.confirm'),
        run: async () => {
          await action.run(work, done)
        },
      })
    void action.run(work, done)
  }
  return (
    <Card id="profile" icon={User} title={t('me.tabs.profile')}>
      <div className="flex items-center gap-3" data-testid="profile-picture">
        <Avatar person={me} size={56} />
        <div className="flex flex-wrap gap-2">
          <Button busy={action.busy} onClick={() => picker.current?.click()}>
            {me.avatar ? t('me.profile.change') : t('me.profile.upload')}
          </Button>
          {me.avatar && (
            <Button
              small
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
            >
              {t('me.profile.remove')}
            </Button>
          )}
        </div>
        <input
          ref={picker}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif,image/bmp,image/heic,image/heif,image/avif,.heic,.heif"
          aria-label={t('me.profile.upload')}
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            event.target.value = ''
            if (file) void action.run(async () => setMe(await api<Me>('/api/v1/auth/avatar', { method: 'PUT', raw: file })), t('me.profile.saved'))
          }}
        />
      </div>
      <form
        className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        <Input label={t('me.profile.name')} value={name} onChange={setName} autoComplete="name" placeholder={me.name} maxLength={80} />
        <Input label={t('me.profile.email')} type="email" value={me.email_pending ? me.email : email} onChange={setEmail} autoComplete="email" placeholder="name@example.com" />
        <Button type="submit" primary busy={action.busy} disabled={(!nameChanged && !emailChanged && !resend) || (asksPassword && !password)}>
          {t('common.save')}
        </Button>
        {asksPassword && (
          <Input
            label={t('auth.password')}
            type="password"
            value={password}
            onChange={setPassword}
            autoComplete="current-password"
            hint={t('mail.passwordHint')}
            className="sm:col-span-2"
          />
        )}
      </form>
      <p className="text-xs text-muted" data-testid="account-facts">
        {t('me.profile.roleLine', { role: t(`me.role.${me.role}`), name: me.name })}
        {me.email && !me.email_pending && (
          <>
            {' · '}
            <span className={me.email_confirmed ? 'text-ok' : 'text-warn'} data-testid="mail-state">
              {me.email_confirmed ? t('mail.confirmedLine') : t('mail.unconfirmedLine')}
            </span>
            {!me.email_confirmed && !resend && me.mail !== false && (
              <>
                {' · '}
                <button type="button" className="font-semibold text-accent hover:underline" onClick={() => (withPassword ? setResend(true) : void action.run(() => sendMail(me.email), t('mail.sent')))}>
                  {t('mail.confirmNow')}
                </button>
              </>
            )}
          </>
        )}
      </p>
      {me.email_pending && (
        <div className="rounded-[12px] border border-accent/40 bg-accent-soft/50 px-3.5 py-3 text-sm" data-testid="mail-pending">
          {t('mail.pending', { address: me.email_pending })} {me.email ? t('mail.stays', { address: me.email }) : ''}
          <div className="mt-2 flex gap-2">
            <Button
              small
              busy={action.busy}
              onClick={() =>
                void action.run(async () => {
                  await api('/api/v1/me/email/pending', { method: 'DELETE' })
                  setMe(await authApi.me())
                })
              }
            >
              {t('mail.withdraw')}
            </Button>
          </div>
        </div>
      )}
      {!me.email_pending && !me.email_confirmed && me.mail === false && <p className="text-xs text-muted">{t('mail.off')}</p>}
      <label className="block text-sm">
        <span className="font-medium">{t('settings.language.title')}</span> <span className="text-xs text-muted">{t('settings.language.hint')}</span>
        <select
          className="input mt-1"
          value={i18n.language}
          data-testid="language-select"
          onChange={(event) => {
            const code = event.target.value
            void changeLanguage(code)
            // Kept with the account, so the next browser speaks it too.
            void authApi.language(code).then(setMe, () => undefined)
          }}
        >
          {languages.map((option) => (
            <option key={option.code} value={option.code}>
              {option.name}
            </option>
          ))}
        </select>
      </label>
      <Feedback problem={action.problem} done={action.done} values={action.values} />
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
      <Card id="security" icon={ShieldCheck} title={t('me.security.title')}>
        {restricted && (
          <p role="note" className="rounded-[9px] border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-warn">
            {t('me.setupFirst')}
          </p>
        )}
        {!restricted && <MyProviders me={me} bare />}
        {!restricted && me.sign_in === 'password' && <PasswordRow />}
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

/** The password as a row that opens, as in nexnotes: the three fields and the button inside. */
function PasswordRow() {
  const { t } = useTranslation()
  const [pw, setPw] = useState({ current: '', next: '', again: '' })
  const password = useAction()
  const [unsent, setUnsent] = useState<string | null>(null)
  return (
    <details className="rounded-[12px] border border-line px-3 py-2.5 text-sm" data-testid="password-row">
      <summary className="flex cursor-pointer list-none items-center gap-3">
        <KeyRound className="h-4 w-4 text-muted" aria-hidden />
        <span className="flex-1 font-medium">{t('me.password.title')}</span>
        <span className="text-xs text-muted">{t('me.password.text')}</span>
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
            await authApi.password(pw.current, pw.next)
            setPw({ current: '', next: '', again: '' })
          }, t('me.password.done'))
        }}
      >
        <Input label={t('me.password.current')} type="password" value={pw.current} onChange={(current) => setPw({ ...pw, current })} autoComplete="current-password" />
        <Input label={t('me.password.new')} type="password" value={pw.next} onChange={(next) => setPw({ ...pw, next })} autoComplete="new-password" />
        <Input label={t('me.password.again')} type="password" value={pw.again} onChange={(again) => setPw({ ...pw, again })} autoComplete="new-password" />
        <Button type="submit" primary busy={password.busy}>
          {t('me.password.submit')}
        </Button>
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
        <Button
          small
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
        >
          {t('me.devices.everywhereElse')}
        </Button>
      </div>
      <Feedback problem={action.problem} done={action.done} />
      {dialog}
    </div>
  )
}
