/**
 * The pages before signing in, built as the mock's: the first account (with the setup code from the server's log),
 * signing in (password, then the second factor; a passkey alone; or the provider's button), setting up the second
 * factor right after the password where the operator asks for one, and accepting an invitation.
 */
import { Fingerprint } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { ApiError, api, authApi, intakeApi, passkeyApi, type Me, type Methods } from '../api/client'
import { Wordmark } from '../components/Logo'
import { KeepCodes, RecoveryCodes } from '../components/RecoveryCodes'
import { ThemeSwitcher } from '../components/ThemeSwitcher'
import i18n from '../i18n'
import { errorText } from '../lib/errors'
import { answerWithPasskey, passkeysAvailable } from '../lib/webauthn'
import { safeNext, useAuth } from '../state/auth'
import { Input } from './settings/ui'

function AuthFrame({ title, text, children, wide = false }: { title: string; text?: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex items-center justify-between px-5 py-4">
        <Wordmark size={32} />
        <ThemeSwitcher />
      </header>
      <main className="flex flex-1 items-start justify-center px-4 pt-[8vh] pb-10">
        <div className={`card w-full p-7 ${wide ? 'max-w-lg' : 'max-w-sm'}`}>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{title}</h1>
          {text && <p className="mt-1 text-sm text-ink-2">{text}</p>}
          <div className="mt-6">{children}</div>
        </div>
      </main>
    </div>
  )
}

function Primary({ children, busy = false }: { children: ReactNode; busy?: boolean }) {
  return (
    <button type="submit" disabled={busy} className="h-11 w-full rounded-full bg-accent px-4 font-semibold text-accent-ink hover:brightness-105 disabled:opacity-50">
      {children}
    </button>
  )
}

function Problem({ code }: { code: string | null }) {
  if (!code) return null
  return (
    <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {errorText(code)}
    </p>
  )
}

function Or() {
  const { t } = useTranslation()
  return (
    <div className="my-5 flex items-center gap-3 text-xs text-muted">
      <span className="h-px flex-1 bg-line" />
      {t('auth.or')}
      <span className="h-px flex-1 bg-line" />
    </div>
  )
}

const OUTLINE = 'flex h-11 w-full items-center justify-center gap-2 rounded-full border border-line text-sm font-semibold hover:bg-sheet-2'

const codeOf = (error: unknown) => (error instanceof ApiError ? error.code : 'internal_error')

export function SetupPage() {
  const { t } = useTranslation()
  const { status, setMe } = useAuth()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  if (status === 'loading') return null
  if (status !== 'setup') return <Navigate to="/" replace />
  return (
    <AuthFrame title={t('auth.setup.title')} text={t('auth.setup.text')}>
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault()
          if (!name.trim()) return setProblem('name_missing')
          setBusy(true)
          setProblem(null)
          try {
            setMe(await authApi.setup(name.trim(), password, code.trim(), i18n.language))
          } catch (error) {
            setProblem(codeOf(error))
          } finally {
            setBusy(false)
          }
        }}
      >
        <Problem code={problem} />
        <Input label={t('auth.setup.code')} value={code} onChange={setCode} autoFocus hint={t('auth.setup.codeHint')} />
        <Input label={t('auth.name')} value={name} onChange={setName} autoComplete="username" />
        <Input label={t('auth.password')} value={password} onChange={setPassword} type="password" autoComplete="new-password" hint={t('auth.passwordHint')} />
        <Primary busy={busy}>{t('auth.setup.submit')}</Primary>
      </form>
    </AuthFrame>
  )
}

/** "Auf diesem Gerät angemeldet bleiben", as the mock: on from the start. */
function Remember({ on, onChange }: { on: boolean; onChange: (value: boolean) => void }) {
  const { t } = useTranslation()
  return (
    <label className="flex items-start gap-3 text-sm">
      <input type="checkbox" checked={on} onChange={(event) => onChange(event.target.checked)} className="mt-0.5 h-5 w-5 shrink-0 accent-[var(--accent)]" />
      <span>
        <span className="font-semibold">{t('auth.remember.label')}</span>
        <span className="block text-xs text-muted">{t('auth.remember.hint')}</span>
      </span>
    </label>
  )
}

/** The browser said no to a passkey: cancelled, or none there. Anything else is the server's word. */
function passkeyProblem(error: unknown): string {
  if (error instanceof ApiError) return error.code
  if (error instanceof DOMException && (error.name === 'NotAllowedError' || error.name === 'AbortError')) return 'passkey_cancelled'
  if (error instanceof Error && error.message === 'cancelled') return 'passkey_cancelled'
  return 'passkey_unsupported'
}

export function LoginPage() {
  const { t } = useTranslation()
  const { status, me, setMe } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [methods, setMethods] = useState<Methods | null>(null)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  // Back from the provider with a second factor to give: the code step at once.
  const [step, setStep] = useState<'password' | 'code'>(params.get('step') === 'code' ? 'code' : 'password')
  const [waiting, setWaiting] = useState<{ totp: boolean; passkey: boolean }>({ totp: true, passkey: false })
  const [code, setCode] = useState('')
  const [remember, setRemember] = useState(true)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(params.get('error'))
  const next = safeNext(params.get('next'))

  useEffect(() => {
    void authApi.methods().then(setMethods, () => setMethods({ password: true, oidc: false, oidc_name: '', passkeys: false }))
  }, [])

  if (status === 'loading') return null
  if (status === 'setup') return <Navigate to="/setup" replace />
  if (status === 'signedIn' && me && (me.session_stage === 'setup' || me.session_stage === 'codes')) return <SecondFactorSetup me={me} next={next} />
  if (status === 'signedIn') return <Navigate to={next} replace />

  const passkeys = Boolean(methods?.passkeys) && passkeysAvailable()

  const signedIn = async () => {
    const account = await authApi.me()
    setMe(account)
    if (account.session_stage === 'full' || !account.session_stage) navigate(next, { replace: true })
  }

  const submit = async () => {
    if (step === 'password' && !name.trim()) return setProblem('name_missing')
    if (step === 'password' && !password) return setProblem('password_missing')
    setBusy(true)
    setProblem(null)
    try {
      if (step === 'code') await authApi.code(code.trim(), remember)
      else {
        const answer = await authApi.login(name.trim(), password, remember)
        if ('second_factor' in answer) {
          setPassword('')
          setCode('')
          setWaiting({ totp: answer.totp, passkey: answer.passkey })
          setStep('code')
          return
        }
      }
      await signedIn()
    } catch (error) {
      const found = codeOf(error)
      setProblem(found)
      if (found === 'second_factor_expired') {
        setStep('password')
        setCode('')
      }
    } finally {
      setBusy(false)
    }
  }

  const withPasskey = async () => {
    setBusy(true)
    setProblem(null)
    try {
      const { options } = await passkeyApi.signInBegin()
      const credential = await answerWithPasskey(options)
      await passkeyApi.signIn(credential, remember)
      await signedIn()
    } catch (error) {
      setProblem(passkeyProblem(error))
    } finally {
      setBusy(false)
    }
  }

  const passkeyButton = (
    <button type="button" disabled={busy} onClick={() => void withPasskey()} className={OUTLINE + ' disabled:opacity-50'}>
      <Fingerprint size={17} aria-hidden /> {t('auth.login.passkey')}
    </button>
  )

  if (step === 'code') {
    const onlyPasskey = !waiting.totp && waiting.passkey
    return (
      <AuthFrame title={t('auth.code.title')} text={onlyPasskey ? t('auth.code.textPasskey') : t('auth.code.text')}>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (code.trim()) void submit()
          }}
        >
          <Problem code={problem} />
          <Input
            label={onlyPasskey ? t('auth.code.recoveryLabel') : t('auth.code.label')}
            value={code}
            onChange={setCode}
            autoComplete="one-time-code"
            autoFocus
            hint={onlyPasskey ? undefined : t('auth.code.hint')}
          />
          <Remember on={remember} onChange={setRemember} />
          <Primary busy={busy}>{t('auth.login.submit')}</Primary>
          {waiting.passkey && passkeys && passkeyButton}
          <button
            type="button"
            className="w-full text-center text-xs text-muted hover:text-ink"
            onClick={() => {
              void authApi.cancelCode().catch(() => undefined)
              setStep('password')
              setCode('')
              setProblem(null)
            }}
          >
            {t('auth.code.back')}
          </button>
        </form>
      </AuthFrame>
    )
  }

  return (
    <AuthFrame title={t('auth.login.title')} text={t('auth.login.text')}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <Problem code={problem} />
        <Input label={t('auth.name')} value={name} onChange={setName} autoComplete="username webauthn" autoFocus />
        <Input label={t('auth.password')} value={password} onChange={setPassword} type="password" autoComplete="current-password" />
        <Remember on={remember} onChange={setRemember} />
        <Primary busy={busy}>{t('auth.login.submit')}</Primary>
        {methods?.forgot && (
          <Link to="/forgot" className="block text-center text-xs text-muted hover:text-ink">
            {t('auth.login.forgot')}
          </Link>
        )}
        {methods && !methods.password && <p className="text-xs text-muted">{t('auth.login.passwordOff')}</p>}
      </form>
      {(passkeys || methods?.oidc) && <Or />}
      <div className="space-y-2.5">
        {passkeys && passkeyButton}
        {methods?.oidc && (
          <a href={`/api/v1/oidc/start?next=${encodeURIComponent(next)}`} className={OUTLINE}>
            {t('auth.login.oidc', { name: methods.oidc_name || 'OpenID Connect' })}
          </a>
        )}
      </div>
    </AuthFrame>
  )
}

type Enrolment = { secret: string; uri: string; qr_svg: string }

/**
 * Right after the password, an account without a second factor sets it up here before it gets anywhere (the mock):
 * the QR code and the key for the app, a code to confirm, then the recovery codes, shown once, and "I have them".
 * Only then does the server make the session a full one.
 */
function SecondFactorSetup({ me, next }: { me: Me; next: string }) {
  const { t } = useTranslation()
  const { setMe, signOut } = useAuth()
  const navigate = useNavigate()
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null)
  const [codes, setCodes] = useState<string[] | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const started = useRef(false)

  useEffect(() => {
    // Once: a second start would draw a new key and the QR code on the page would no longer fit.
    if (started.current) return
    started.current = true
    const work =
      me.session_stage === 'codes'
        ? authApi.setupCodes().then((answer) => setCodes(answer.recovery_codes))
        : api<Enrolment>('/api/v1/auth/totp/begin', { method: 'POST' }).then(setEnrolment)
    work.catch((error) => setProblem(codeOf(error)))
  }, [me.session_stage])

  const run = async (work: () => Promise<void>) => {
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

  const leave = (
    <button type="button" onClick={() => void signOut()} className="mt-3 w-full text-center text-xs text-muted hover:text-ink">
      {t('auth.setup2fa.leave')}
    </button>
  )

  if (codes)
    return (
      <AuthFrame wide title={t('auth.codes.title')} text={t('auth.codes.text')}>
        <Problem code={problem} />
        <RecoveryCodes codes={codes} />
        <KeepCodes codes={codes} account={me.name} className="mt-4" />
        <div className="mt-4">
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                setMe(await authApi.setupDone())
                navigate(next, { replace: true })
              })
            }
            className="h-11 w-full rounded-full bg-accent px-4 font-semibold text-accent-ink hover:brightness-105 disabled:opacity-50"
          >
            {t('auth.codes.done')}
          </button>
        </div>
      </AuthFrame>
    )

  return (
    <AuthFrame wide title={t('auth.setup2fa.title')} text={t('auth.setup2fa.text')}>
      <Problem code={problem} />
      <div className="grid gap-5 sm:grid-cols-[10rem_1fr]">
        {enrolment ? (
          <img src={'data:image/svg+xml;utf8,' + encodeURIComponent(enrolment.qr_svg)} alt={t('twofactor.qr')} className="h-40 w-40 rounded-xl bg-white p-1" />
        ) : (
          <span className="h-40 w-40 rounded-xl bg-sheet-2" aria-hidden />
        )}
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (!code.trim()) return
            void run(async () => {
              const answer = await api<{ recovery_codes: string[] | null }>('/api/v1/auth/totp/confirm', { method: 'POST', body: { code: code.trim() } })
              setCodes(answer.recovery_codes ?? [])
            })
          }}
        >
          <p className="text-sm text-ink-2">{t('auth.setup2fa.scan')}</p>
          <p className="font-mono text-xs break-all text-muted" data-testid="totp-secret">
            {enrolment ? enrolment.secret.replace(/(.{4})/g, '$1 ').trim() : '…'}
          </p>
          <Input label={t('auth.code.label')} value={code} onChange={setCode} autoFocus autoComplete="one-time-code" />
          <Primary busy={busy}>{t('twofactor.confirm')}</Primary>
        </form>
      </div>
      <p className="mt-5 border-t border-line pt-4 text-xs text-muted">{t('auth.setup2fa.passkeyLater')}</p>
      {leave}
    </AuthFrame>
  )
}

type InviteState = { min_password: number; signed_in_as: string | null }

export function InvitePage() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  const { setMe } = useAuth()
  const navigate = useNavigate()
  const [state, setState] = useState<InviteState | null>(null)
  const [invalid, setInvalid] = useState(false)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [methods, setMethods] = useState<Methods | null>(null)

  useEffect(() => {
    api<InviteState>(`/api/v1/invite/${encodeURIComponent(token)}`).then(setState, () => setInvalid(true))
    authApi.methods().then(setMethods, () => undefined)
  }, [token])

  if (invalid) {
    return (
      <AuthFrame title={t('auth.invite.invalidTitle')}>
        <p className="text-sm text-ink-2">{t('auth.invite.invalidText')}</p>
        <Link to="/login" className={OUTLINE + ' mt-5'}>
          {t('auth.backToLogin')}
        </Link>
      </AuthFrame>
    )
  }
  if (!state) return null

  if (state.signed_in_as) {
    // A link for a new account, opened by somebody signed in already: there is nothing to join.
    return (
      <AuthFrame title={t('auth.invite.title')} text={t('auth.invite.haveAccount', { name: state.signed_in_as })}>
        <Link to="/" className="flex h-11 w-full items-center justify-center rounded-full bg-accent px-4 font-semibold text-accent-ink hover:brightness-105">
          {t('auth.invite.toApp')}
        </Link>
      </AuthFrame>
    )
  }

  return (
    <AuthFrame title={t('auth.invite.title')} text={t('auth.invite.text')}>
      {methods && !methods.password && !methods.oidc && <p className="text-sm text-ink-2">{t('auth.invite.noWay')}</p>}
      {(!methods || methods.password) && (
        <form
          className="space-y-4"
          onSubmit={async (event) => {
            event.preventDefault()
            if (!name.trim()) return setProblem('name_missing')
            setBusy(true)
            setProblem(null)
            try {
              setMe(await api<Me>(`/api/v1/invite/${encodeURIComponent(token)}`, { method: 'POST', body: { name: name.trim(), password } }))
              navigate('/', { replace: true })
            } catch (error) {
              setProblem(codeOf(error))
            } finally {
              setBusy(false)
            }
          }}
        >
          <Problem code={problem} />
          <Input label={t('auth.name')} value={name} onChange={setName} autoComplete="username" autoFocus hint={t('auth.nameHint')} />
          <Input label={t('auth.password')} value={password} onChange={setPassword} type="password" autoComplete="new-password" hint={t('auth.passwordHint')} />
          <Primary busy={busy}>{t('auth.invite.submit')}</Primary>
        </form>
      )}
      {/* Through the sign-in provider: the invitation is the permission for the new account. */}
      {methods?.oidc && (
        <>
          {methods.password && <Or />}
          <a href={`/api/v1/oidc/start?invite=${encodeURIComponent(token)}`} className={OUTLINE}>
            {t('auth.invite.withProvider', { name: methods.oidc_name || 'OpenID Connect' })}
          </a>
        </>
      )}
    </AuthFrame>
  )
}

/** "Forgot your password?": the name or the address on record, and the same answer whether there is such an account. */
export function ForgotPage() {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [sent, setSent] = useState(false)
  // Asked beforehand, so that a server without mail says so at once instead of answering a request with a refusal.
  const [off, setOff] = useState(false)
  useEffect(() => {
    let alive = true
    void authApi.methods().then((methods) => alive && setOff(methods.forgot === false), () => undefined)
    return () => {
      alive = false
    }
  }, [])
  if (off) {
    return (
      <AuthFrame title={t('auth.forgot.title')}>
        <p role="status" className="text-sm text-ink-2">
          {errorText('reset_off')}
        </p>
        <Link to="/login" className={OUTLINE + ' mt-5'}>
          {t('auth.backToLogin')}
        </Link>
      </AuthFrame>
    )
  }
  if (sent) {
    return (
      <AuthFrame title={t('auth.forgot.title')}>
        <p role="status" className="text-sm text-ink-2">
          {t('auth.forgot.sent')}
        </p>
        <Link to="/login" className={OUTLINE + ' mt-5'}>
          {t('auth.backToLogin')}
        </Link>
      </AuthFrame>
    )
  }
  return (
    <AuthFrame title={t('auth.forgot.title')} text={t('auth.forgot.text')}>
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault()
          if (!name.trim()) return setProblem('name_missing')
          setBusy(true)
          setProblem(null)
          try {
            await authApi.forgot(name.trim())
            setSent(true)
          } catch (error) {
            setProblem(codeOf(error))
          } finally {
            setBusy(false)
          }
        }}
      >
        <Problem code={problem} />
        <Input label={t('auth.forgot.label')} value={name} onChange={setName} autoComplete="username" autoFocus />
        <Primary busy={busy}>{t('auth.forgot.submit')}</Primary>
        <Link to="/login" className="block text-center text-xs text-muted hover:text-ink">
          {t('auth.backToLogin')}
        </Link>
      </form>
    </AuthFrame>
  )
}

type ResetState = { name: string; min_password: number }

/** The page of the link: the person chooses the new password themselves. Nobody is signed in by it; the sign-in follows. */
export function ResetPage() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  const [state, setState] = useState<ResetState | null>(null)
  const [invalid, setInvalid] = useState(false)
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    api<ResetState>(`/api/v1/reset/${encodeURIComponent(token)}`).then(setState, () => setInvalid(true))
  }, [token])

  if (invalid) {
    return (
      <AuthFrame title={t('auth.reset.invalidTitle')}>
        <p className="text-sm text-ink-2">{t('auth.reset.invalidText')}</p>
        <Link to="/login" className={OUTLINE + ' mt-5'}>
          {t('auth.backToLogin')}
        </Link>
      </AuthFrame>
    )
  }
  if (done) {
    return (
      <AuthFrame title={t('auth.reset.doneTitle')}>
        <p role="status" className="text-sm text-ink-2">
          {t('auth.reset.doneText')}
        </p>
        <Link to="/login" className="mt-5 flex h-11 w-full items-center justify-center rounded-full bg-accent px-4 font-semibold text-accent-ink hover:brightness-105">
          {t('auth.login.submit')}
        </Link>
      </AuthFrame>
    )
  }
  if (!state) return null
  return (
    <AuthFrame title={t('auth.reset.title')} text={t('auth.reset.text', { name: state.name })}>
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault()
          if (password !== again) return setProblem('password_mismatch')
          setBusy(true)
          setProblem(null)
          try {
            await api<void>(`/api/v1/reset/${encodeURIComponent(token)}`, { method: 'POST', body: { password } })
            setDone(true)
          } catch (error) {
            const found = codeOf(error)
            if (found === 'reset_invalid') setInvalid(true)
            else setProblem(found)
          } finally {
            setBusy(false)
          }
        }}
      >
        <Problem code={problem} />
        <Input label={t('auth.reset.password')} value={password} onChange={setPassword} type="password" autoComplete="new-password" autoFocus hint={t('auth.passwordHint')} />
        <Input label={t('auth.reset.again')} value={again} onChange={setAgain} type="password" autoComplete="new-password" />
        <Primary busy={busy}>{t('auth.reset.submit')}</Primary>
      </form>
    </AuthFrame>
  )
}

type MailState = { name: string; address: string }
type MailDone = MailState & { old_told: boolean }

/** The page of the link in the mail to a new address: one press confirms it (a mail program that only looks at a link
 * must not do it for the person). Nobody has to be signed in. */
export function MailConfirmPage() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  const { status } = useAuth()
  const [state, setState] = useState<MailState | null>(null)
  const [invalid, setInvalid] = useState(false)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [told, setTold] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    api<MailState>(`/api/v1/email/confirm/${encodeURIComponent(token)}`).then(setState, () => setInvalid(true))
  }, [token])

  const next = status === 'signedIn' ? { to: '/konto', label: t('auth.mail.toAccount') } : { to: '/login', label: t('auth.backToLogin') }
  if (invalid) {
    return (
      <AuthFrame title={t('auth.mail.invalidTitle')}>
        <p className="text-sm text-ink-2">{t('auth.mail.invalidText')}</p>
        <Link to={next.to} className={OUTLINE + ' mt-5'}>
          {next.label}
        </Link>
      </AuthFrame>
    )
  }
  if (done && state) {
    return (
      <AuthFrame title={t('auth.mail.doneTitle')}>
        <p role="status" className="text-sm text-ink-2">
          {t('auth.mail.doneText', { address: state.address })}
          {told && ' ' + t('auth.mail.oldTold')}
        </p>
        <Link to={next.to} className="mt-5 flex h-11 w-full items-center justify-center rounded-full bg-accent px-4 font-semibold text-accent-ink hover:brightness-105">
          {next.label}
        </Link>
      </AuthFrame>
    )
  }
  if (!state) return null
  return (
    <AuthFrame title={t('auth.mail.title')} text={t('auth.mail.text', { name: state.name, address: state.address })}>
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault()
          setBusy(true)
          setProblem(null)
          try {
            const result = await api<MailDone>(`/api/v1/email/confirm/${encodeURIComponent(token)}`, { method: 'POST' })
            setTold(result.old_told === true)
            setDone(true)
          } catch (error) {
            const found = codeOf(error)
            if (found === 'email_link_invalid') setInvalid(true)
            else setProblem(found)
          } finally {
            setBusy(false)
          }
        }}
      >
        <Problem code={problem} />
        <Primary busy={busy}>{t('auth.mail.submit')}</Primary>
      </form>
    </AuthFrame>
  )
}

/** The page of the link in the mail to an address a person forwards documents from (block B8): one press confirms it,
 * as with the own mail address (a mail program that only looks at a link must not do it). Nobody has to be signed in. */
export function SenderConfirmPage() {
  const { t } = useTranslation()
  const { token = '' } = useParams()
  const { status } = useAuth()
  const [state, setState] = useState<{ name: string; address: string } | null>(null)
  const [invalid, setInvalid] = useState(false)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    intakeApi.senderLink(token).then(setState, () => setInvalid(true))
  }, [token])

  const next = status === 'signedIn' ? { to: '/konto?tab=upload', label: t('auth.mail.toAccount') } : { to: '/login', label: t('auth.backToLogin') }
  if (invalid) {
    return (
      <AuthFrame title={t('intake.confirm.invalidTitle')}>
        <p className="text-sm text-ink-2">{t('intake.confirm.invalidText')}</p>
        <Link to={next.to} className={OUTLINE + ' mt-5'}>
          {next.label}
        </Link>
      </AuthFrame>
    )
  }
  if (done && state) {
    return (
      <AuthFrame title={t('intake.confirm.doneTitle')}>
        <p role="status" className="text-sm text-ink-2">
          {t('intake.confirm.doneText', { address: state.address, name: state.name })}
        </p>
        <Link to={next.to} className="mt-5 flex h-11 w-full items-center justify-center rounded-full bg-accent px-4 font-semibold text-accent-ink hover:brightness-105">
          {next.label}
        </Link>
      </AuthFrame>
    )
  }
  if (!state) return null
  return (
    <AuthFrame title={t('intake.confirm.title')} text={t('intake.confirm.text', { name: state.name, address: state.address })}>
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault()
          setBusy(true)
          setProblem(null)
          try {
            await intakeApi.confirmSender(token)
            setDone(true)
          } catch (error) {
            const found = codeOf(error)
            if (found === 'sender_link_invalid') setInvalid(true)
            else setProblem(found)
          } finally {
            setBusy(false)
          }
        }}
      >
        <Problem code={problem} />
        <Primary busy={busy}>{t('intake.confirm.submit')}</Primary>
      </form>
    </AuthFrame>
  )
}
