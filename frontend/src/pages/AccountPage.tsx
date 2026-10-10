/**
 * The own account in tabs, everything personal in one place, as the mock: Profile (picture, display name, name, role,
 * mail address with its link, language), Security (password, second factor, passkeys, the link to the provider, the
 * signed-in devices and the notice of a new sign-in), Devices and apps (pairing by a QR code, the iPhone shortcut, API
 * keys, Web Push on the devices), Upload (where uploads go, where a phone starts), AI (the own switch, and what the operator set up) and Looks (light or dark, the
 * archive). The tab stands in the address (`?tab=`). Settings are the operator's.
 */
import { AtSign, Camera, KeyRound, MonitorSmartphone, Palette, ShieldCheck, Sparkles, Trash2, Upload, User } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { api, authApi, type Me, type Methods } from '../api/client'
import { ApiKeys } from '../components/ApiKeys'
import { Avatar } from '../components/Avatar'
import { PairedDevices } from '../components/PairedDevices'
import { useConfirm } from '../components/useConfirm'
import { iso } from '../lib/say'
import { ShortcutCard, UploadVaultCard } from '../components/PhoneCards'
import { providerName } from '../lib/aiProviders'
import { useAiState } from '../state/ai'
import { useAuth } from '../state/auth'
import { MyIntakeCards } from './settings/IntakeCards'
import { LanguageCard, LooksCard, PhoneCard } from './settings/PersonalCards'
import { PushDevicesCard } from './settings/PushCards'
import { DevicesCard, PasskeysCard, SecondFactorCard } from './settings/SecurityCards'
import { Button, Card, Feedback, Input, TabRow, Toggle, useAction, type Tab } from './settings/ui'

type Part = 'profile' | 'security' | 'devices' | 'upload' | 'ai' | 'looks'
const PARTS: Part[] = ['profile', 'security', 'devices', 'upload', 'ai', 'looks']

export function AccountPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [params, setParams] = useSearchParams()
  const asked = params.get('tab') as Part | null
  // Back from the provider (linking the account): its answer stands on the security tab.
  const part: Part = asked && PARTS.includes(asked) ? asked : params.get('linked') || params.get('error') ? 'security' : 'profile'
  if (!me) return null
  const tabs: Tab<Part>[] = [
    { value: 'profile', label: t('me.tabs.profile'), icon: User },
    { value: 'security', label: t('me.tabs.security'), icon: ShieldCheck },
    { value: 'devices', label: t('me.tabs.devices'), icon: MonitorSmartphone },
    { value: 'upload', label: t('me.tabs.upload'), icon: Upload },
    { value: 'ai', label: t('me.tabs.ai'), icon: Sparkles },
    { value: 'looks', label: t('me.tabs.looks'), icon: Palette },
  ]
  return (
    <div className="page space-y-5 pt-8 pb-28 lg:pb-12">
      <h1 className="font-display text-3xl font-semibold tracking-tight">{t('me.title')}</h1>
      <TabRow tabs={tabs} active={part} label={t('me.title')} onChange={(value) => setParams(value === 'profile' ? {} : { tab: value }, { replace: true })} />
      <div className="space-y-6 pt-1">
        {part === 'profile' && (
          <>
            <Profile me={me} />
            <MailAddress me={me} />
            <LanguageCard />
          </>
        )}
        {part === 'security' && <Security me={me} />}
        {part === 'devices' && (
          <>
            <PairedDevices />
            <ShortcutCard />
            <ApiKeys />
            <PushDevicesCard me={me} />
          </>
        )}
        {part === 'upload' && (
          <>
            <UploadVaultCard />
            <PhoneCard />
            <MyIntakeCards />
          </>
        )}
        {part === 'ai' && <AiPart me={me} />}
        {part === 'looks' && <LooksCard />}
      </div>
    </div>
  )
}

/** "KI beim Einsortieren", as the mock: the own switch, and below it what the operator set up for everybody. */
function AiPart({ me }: { me: Me }) {
  const { t } = useTranslation()
  const { setMe } = useAuth()
  const ai = useAiState()
  const action = useAction()
  const mine = me.profile.ai !== false
  const provider = ai?.provider ?? 'none'
  return (
    <Card icon={Sparkles} title={t('me.ai.title')} text={t('me.ai.text')}>
      <Toggle
        label={t('me.ai.mine')}
        hint={t('me.ai.mineHint')}
        checked={mine}
        onChange={(value) => {
          setMe({ ...me, profile: { ...me.profile, ai: value } })
          void action.run(async () => setMe({ ...me, profile: await authApi.preferences({ ai: value }) })).then(
            (worked) => worked || setMe(me),
          )
        }}
      />
      {me.ai_allowed === false && (
        <p className="mt-4 rounded-xl bg-sheet-2 px-4 py-3 text-sm text-ink-2" role="status" data-ai-not-allowed>
          {t('me.ai.notAllowed')}
        </p>
      )}
      {ai && me.ai_allowed !== false && (
        <div className="mt-4 rounded-xl bg-sheet-2 px-4 py-3 text-sm">
          <p>
            <span className="font-semibold">{t('me.ai.byOperator')}</span> {providerName(provider, t)}
            {provider === 'local' && ai.model && ` (${ai.model})`}
          </p>
          <p className="mt-1 text-ink-2">{t(`server.ai.${provider}Note`)}</p>
          {provider !== 'none' && ai.skip_personal !== false && <p className="mt-1 text-ink-2">{t('sorting.ai.skipNote')}</p>}
        </div>
      )}
      <Feedback problem={action.problem} />
    </Card>
  )
}

/**
 * The own mail address, for "Forgot your password?" and the notices. A new one counts only after the link mailed to it
 * is opened; until then the old one stays. Changing it asks for the password once more, because the address is the way
 * back into the account.
 */
function MailAddress({ me }: { me: Me }) {
  const { t } = useTranslation()
  const { setMe } = useAuth()
  const [next, setNext] = useState('')
  const [password, setPassword] = useState('')
  const action = useAction()
  const { ask: confirm, dialog } = useConfirm()
  const withPassword = me.sign_in === 'password'
  const ask = (email: string, done: string) =>
    action.run(async () => {
      setMe(await api<Me>('/api/v1/me/email', { method: 'PUT', body: { email, password } }))
      setNext('')
      setPassword('')
    }, done)
  return (
    <Card icon={AtSign} title={t('mail.title')} text={t('mail.text')}>
      <p className="text-sm">
        {me.email ? (
          <>
            <span className="font-semibold">{me.email}</span>{' '}
            <span className={`ml-1 rounded-full px-2 py-0.5 text-xs font-semibold ${me.email_confirmed ? 'bg-ok-soft text-ok' : 'bg-warn-soft text-warn'}`} data-testid="mail-state">
              {me.email_confirmed ? t('mail.confirmed') : t('mail.unconfirmed')}
            </span>
          </>
        ) : (
          <span className="text-muted">{t('mail.none')}</span>
        )}
      </p>
      {me.email_pending ? (
        <div className="rounded-xl border border-accent/40 bg-accent-soft/50 px-4 py-3 text-sm" data-testid="mail-pending">
          {t('mail.pending', { address: me.email_pending })} {me.email ? t('mail.stays', { address: me.email }) : ''}
          <div className="mt-2 flex gap-2">
            <Button
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
      ) : (
        <form
          className="flex flex-wrap items-start gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            if (next.trim()) void ask(next.trim(), t('mail.sent'))
          }}
        >
          <Input label={t('mail.new')} type="email" value={next} onChange={setNext} placeholder="name@example.com" autoComplete="email" className="min-w-60 flex-1" />
          {withPassword && <Input label={t('auth.password')} type="password" value={password} onChange={setPassword} autoComplete="current-password" hint={t('mail.passwordHint')} className="min-w-48" />}
          <Button type="submit" busy={action.busy} disabled={!next.trim() || (withPassword && !password)} className="mt-6">
            {t('mail.send')}
          </Button>
        </form>
      )}
      {me.email && !me.email_pending && (
        <p className="text-xs text-muted">
          {!me.email_confirmed && (
            <>
              <button type="button" className="font-semibold text-accent underline decoration-accent/40 underline-offset-4" disabled={action.busy || (withPassword && !password)} onClick={() => void ask(me.email, t('mail.sent'))}>
                {t('mail.confirmNow')}
              </button>{' '}
              ·{' '}
            </>
          )}
          <button type="button" className="font-semibold text-accent underline decoration-accent/40 underline-offset-4" disabled={action.busy || (withPassword && !password)} onClick={() =>
              confirm({
                title: t('confirm.mailAddress.title'),
                text: t('confirm.mailAddress.text', { address: iso(me.email) }),
                confirm: t('confirm.mailAddress.confirm'),
                run: async () => {
                  await ask('', t('mail.removed'))
                },
              })
            }
          >
            {t('mail.remove')}
          </button>
          {withPassword && !password ? ` · ${t('mail.passwordFirst')}` : ''}
        </p>
      )}
      {!me.email_pending && !me.email_confirmed && me.mail === false && <p className="text-xs text-muted">{t('mail.off')}</p>}
      <Feedback problem={action.problem} done={action.done} />
      {dialog}
    </Card>
  )
}

function Profile({ me }: { me: Me }) {
  const { t } = useTranslation()
  const { setMe } = useAuth()
  const [shownAs, setShownAs] = useState(me.display_name)
  const picker = useRef<HTMLInputElement>(null)
  const action = useAction()
  const { ask, dialog } = useConfirm()
  return (
    <Card icon={User} title={t('me.tabs.profile')} text={t('me.profile.text')}>
      <div className="flex flex-wrap items-center gap-5">
        <Avatar person={me} size={72} />
        <div className="flex flex-wrap gap-2">
          <Button busy={action.busy} onClick={() => picker.current?.click()}>
            <Camera size={16} /> {me.avatar ? t('me.profile.change') : t('me.profile.upload')}
          </Button>
          {me.avatar && (
            <Button
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
              <Trash2 size={16} /> {t('me.profile.remove')}
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
      <p className="-mt-1 text-xs text-muted">{t('me.profile.hint')}</p>
      <form
        className="flex flex-wrap items-start gap-2 pt-2"
        onSubmit={(event) => {
          event.preventDefault()
          void action.run(async () => {
            const saved = await authApi.profile(shownAs.trim())
            setShownAs(saved.display_name)
            setMe(saved)
          }, t('me.profile.displaySaved'))
        }}
      >
        <Input
          label={t('me.profile.displayName')}
          value={shownAs}
          onChange={setShownAs}
          autoComplete="name"
          className="min-w-60 flex-1"
          hint={t(me.sign_in === 'password' ? 'me.profile.displayHintPassword' : 'me.profile.displayHint', { name: me.name })}
        />
        <Button type="submit" busy={action.busy} disabled={shownAs.trim() === me.display_name} className="mt-6">
          {t('common.save')}
        </Button>
      </form>
      <dl className="grid grid-cols-[8rem_1fr] gap-y-2 pt-2 text-sm" data-testid="account-facts">
        <dt className="text-muted">{t('me.profile.name')}</dt>
        <dd className="font-semibold">{me.name}</dd>
        <dt className="text-muted">{t('me.profile.role')}</dt>
        <dd className="font-semibold">{t(`me.role.${me.role}`)}</dd>
        <dt className="text-muted">{t('me.profile.email')}</dt>
        <dd className="font-semibold">{me.email || t('mail.none')}</dd>
      </dl>
      <Feedback problem={action.problem} done={action.done} values={action.values} />
      {dialog}
    </Card>
  )
}

function Security({ me }: { me: Me }) {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const [params] = useSearchParams()
  const [methods, setMethods] = useState<Methods | null>(null)
  const [pw, setPw] = useState({ current: '', next: '', again: '', link: '' })
  const password = useAction()
  const [unsent, setUnsent] = useState<string | null>(null)
  const link = useAction()
  const { ask, dialog } = useConfirm()
  const [linkDone] = useState(params.get('linked') ? t('me.oidc.linkedNow') : null)
  const [linkProblem] = useState(params.get('error'))
  // Until the second factor is set up, the server answers nothing else: only its cards are shown.
  const restricted = Boolean(me.second_factor_setup_required)
  useEffect(() => {
    if (!restricted) authApi.methods().then(setMethods, () => setMethods(null))
  }, [restricted])
  const provider = methods?.oidc_name || 'OpenID Connect'
  if (restricted)
    return (
      <>
        <p role="note" className="rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm font-semibold text-warn">
          {t('me.setupFirst')}
        </p>
        <SecondFactorCard me={me} />
        <PasskeysCard me={me} />
      </>
    )
  return (
    <>
      {me.sign_in === 'password' && (
        <Card icon={KeyRound} title={t('me.password.title')} text={t('me.password.text')}>
          <form
            className="grid gap-3 sm:grid-cols-3"
            onSubmit={(event) => {
              event.preventDefault()
              // Said here, before anything goes to the server.
              const missing = !pw.current ? 'current_password_missing' : !pw.next ? 'password_missing' : pw.next !== pw.again ? 'password_mismatch' : null
              setUnsent(missing)
              if (missing) return
              void password.run(async () => {
                await authApi.password(pw.current, pw.next)
                setPw({ ...pw, current: '', next: '', again: '' })
              }, t('me.password.done'))
            }}
          >
            <Input label={t('me.password.current')} type="password" value={pw.current} onChange={(current) => setPw({ ...pw, current })} autoComplete="current-password" />
            <Input label={t('me.password.new')} type="password" value={pw.next} onChange={(next) => setPw({ ...pw, next })} autoComplete="new-password" />
            <Input label={t('me.password.again')} type="password" value={pw.again} onChange={(again) => setPw({ ...pw, again })} autoComplete="new-password" />
            <div className="sm:col-span-3">
              <Button type="submit" busy={password.busy}>
                {t('me.password.submit')}
              </Button>
            </div>
          </form>
          <Feedback problem={unsent ?? password.problem} done={password.done} />
        </Card>
      )}

      <SecondFactorCard me={me} />
      <PasskeysCard me={me} />

      {(methods?.oidc || me.sign_in === 'oidc' || me.oidc_linked) && (
        <Card icon={ShieldCheck} title={t('me.oidc.title')} text={t('me.oidc.text', { name: provider })}>
          {me.sign_in === 'oidc' ? (
            <p className="text-sm text-ink-2">{t('me.oidc.only', { name: provider })}</p>
          ) : me.oidc_linked ? (
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="text-ink-2">{t('me.oidc.linked', { name: provider })}</span>
              <Button
                busy={link.busy}
                onClick={() =>
                  ask({
                    title: t('confirm.oidcLink.title'),
                    text: t('confirm.oidcLink.text', { name: provider }),
                    confirm: t('confirm.oidcLink.confirm'),
                    run: async () => {
                      await link.run(async () => {
                        await api('/api/v1/oidc/link', { method: 'DELETE' })
                        await refresh()
                      }, t('me.oidc.unlinked'))
                    },
                  })
                }
              >
                {t('me.oidc.unlink')}
              </Button>
            </div>
          ) : (
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault()
                void link.run(async () => {
                  const { url } = await api<{ url: string }>('/api/v1/oidc/link/start', { method: 'POST', body: { password: pw.link } })
                  window.location.assign(url)
                })
              }}
            >
              <p className="text-sm text-ink-2">{t('me.oidc.how', { name: provider })}</p>
              <Input label={t('auth.password')} type="password" value={pw.link} onChange={(value) => setPw({ ...pw, link: value })} autoComplete="current-password" className="max-w-sm" />
              <Button type="submit" busy={link.busy}>
                {t('me.oidc.link', { name: provider })}
              </Button>
            </form>
          )}
          <Feedback problem={link.problem ?? linkProblem} done={link.done ?? linkDone} />
          {dialog}
        </Card>
      )}

      <DevicesCard me={me} />
    </>
  )
}
