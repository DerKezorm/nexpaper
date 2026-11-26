/**
 * My account › Security (plan "Einstellungen", Sicherheit): one card "Sicherheit" as the shared account module lays it
 * out (`PAGES.security`, konten 1.1.0), each part a `Box` in its order (password with when it was changed last, second
 * factor, recovery codes, passkeys, signed-in devices with "sign out everywhere else", the mail of a new sign-in), then
 * nexpaper's own part: the sign-in providers. Titles, hints, buttons and password fields are the module's. Built only
 * from the ui kit, as nexnotes' Security is. Until the second factor is set up the server answers nothing else: only its
 * part and the passkeys are shown.
 */
import { Fingerprint, Laptop, Smartphone } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { api, ApiError, authApi, oidcApi, passkeyApi, type Me, type MyProvider, type Passkey, type RemainingAccess, type SignedSession } from '../../api/client'
import { AccountButton } from '../../components/AccountButton'
import { KeepCodes, RecoveryCodes } from '../../components/RecoveryCodes'
import { confirmOf } from '../../lib/accountButton'
import { ago, daysAgo } from '../../lib/ago'
import { errorText } from '../../lib/errors'
import { iso } from '../../lib/say'
import { createPasskey, passkeysAvailable } from '../../lib/webauthn'
import { useAuth } from '../../state/auth'
import { PasskeyAddition } from '../../vendor/nexkonten/AccountCards'
import { FIELDS, newSignInMailHint, PAGES, pageOrder, passwordChanged, SECOND_FACTOR_STATE } from '../../vendor/nexkonten/konten'
import { Badge, Box, Button, Card, CheckboxRow, ConfirmDialog, Field, Notice, Row, Rows } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'
import { useAsk } from './useAsk'

/** Below this many recovery codes the account is told to make new ones. */
const LOW_CODES = 3

/** The parts of Security, top to bottom: the module's in its order, then nexpaper's own (the sign-in providers). */
// eslint-disable-next-line react-refresh/only-export-components
export const SECURITY_PARTS = pageOrder('security', ['providers'])

/** One part of the module's page by its name: its title, hint and buttons. */
const part = (name: string) => PAGES.security.parts.find((entry) => entry.part === name)!

/** Said after "Überall sonst abmelden": the list of devices asks again. */
export const SESSIONS_CHANGED = 'nexpaper:sessions-changed'

export function SecurityArea({ me }: { me: Me }) {
  const { t } = useTranslation()
  const restricted = Boolean(me.second_factor_setup_required)
  const shown = (name: string): boolean => {
    if (name === 'secondFactor' || name === 'passkeys') return true
    if (restricted) return false
    if (name === 'password') return me.sign_in === 'password'
    if (name === 'recoveryCodes') return Boolean(me.two_factor)
    return true
  }
  return (
    <>
      {me.second_factor_off && (
        <Notice tone="warn" title={t('account.secondFactorOff')} testId="second-factor-off">
          {t('account.secondFactorOffHint')}
        </Notice>
      )}
      {!restricted && me.new_password_origin && <RemainingAccessNotice />}
      <Card id="security" icon="ShieldCheck" title={t(PAGES.security.title)}>
        {restricted && <Notice tone="warn">{t('me.setupFirst')}</Notice>}
        {SECURITY_PARTS.filter(shown).map((name) => {
          switch (name) {
            case 'password':
              return <PasswordBox key={name} changedAt={me.password_changed_at ?? null} />
            case 'secondFactor':
              return <SecondFactorBox key={name} me={me} part="factor" />
            case 'recoveryCodes':
              return <SecondFactorBox key={name} me={me} part="codes" />
            case 'passkeys':
              return <PasskeysBox key={name} me={me} />
            case 'sessions':
              return <SessionsBox key={name} />
            case 'newSignInMail':
              return <SignInMailRow key={name} me={me} />
            case 'providers':
              return <ProvidersBox key={name} me={me} />
            default:
              return null
          }
        })}
      </Card>
    </>
  )
}

/**
 * "These devices still have access" (the shared account module): after a password set through a link, the paired
 * devices, API keys and passkeys that stayed, with "Disconnect all" and putting the list away. After the operator's or
 * the server's link it says so first.
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
    <Notice tone="warn" title={list.access.length > 0 ? t('account.remainingAccess') : t('account.resetByOperator')} testId="remaining-access">
      {list.origin !== 'self' && list.access.length > 0 && <span className="mb-1 block">{t('account.resetByOperator')}</span>}
      {list.access.length > 0 && <span className="mb-2 block">{list.access.map((item) => item.label).join(', ')}</span>}
      <span className="mt-2 flex flex-wrap gap-2">
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
      <Outcome problem={action.problem} values={action.values} />
    </Notice>
  )
}

/** The module's part "password": when it was changed last (`passwordChanged`) and "Change password", which opens the
 * module's three fields in a dialog. */
function PasswordBox({ changedAt }: { changedAt: string | null }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const [pw, setPw] = useState({ current: '', next: '', again: '' })
  const [unsent, setUnsent] = useState<string | null>(null)
  const action = useAction()
  const line = passwordChanged(changedAt)
  const close = () => {
    setOpen(false)
    setPw({ current: '', next: '', again: '' })
    setUnsent(null)
  }
  return (
    <Box
      title={t(part('password').title)}
      hint={<span data-testid="password-changed">{t(line.text, { day: line.date ? new Date(line.date).toLocaleDateString(i18n.language) : '' })}</span>}
      testId="password-row"
      actions={<AccountButton name="account.passwordChange" testId="password-change" onClick={() => setOpen(true)} />}
    >
      <Outcome problem={null} done={action.done} />
      {open && (
        <ConfirmDialog
          title={t('account.passwordChange')}
          confirm={confirmOf('resetSubmit', t('me.password.submit'))}
          cancel={t('common.cancel')}
          closeLabel={t('common.close')}
          busy={action.busy}
          error={unsent || action.problem ? errorText((unsent ?? action.problem)!, action.values) : undefined}
          onCancel={close}
          testId="password-form"
          onConfirm={() => {
            // Said here, before anything goes to the server.
            const missing = !pw.current ? 'current_password_missing' : !pw.next ? 'password_missing' : pw.next !== pw.again ? 'password_mismatch' : null
            setUnsent(missing)
            if (missing) return
            void action
              .run(async () => {
                await authApi.password(pw.current, pw.next, pw.again)
              }, t('me.password.done'))
              .then((worked) => worked && close())
          }}
        >
          <Field label={t(FIELDS.currentPassword.label)} type="password" autoComplete="current-password" value={pw.current} onChange={(event) => setPw({ ...pw, current: event.target.value })} />
          <Field label={t(FIELDS.newPassword.label)} type="password" autoComplete="new-password" hints={[t(FIELDS.newPassword.hint)]} value={pw.next} onChange={(event) => setPw({ ...pw, next: event.target.value })} />
          <Field label={t(FIELDS.passwordRepeat.label)} type="password" autoComplete="new-password" value={pw.again} onChange={(event) => setPw({ ...pw, again: event.target.value })} />
        </ConfirmDialog>
      )}
    </Box>
  )
}

/** The codes, shown once right after they were made, to copy or keep as a file, and "I have them". */
function FreshCodes({ codes, me, onDone }: { codes: string[]; me: Me; onDone: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-3">
      <Notice tone="warn" title={t('twofactor.codesTitle')}>
        {t('twofactor.codesLead')}
      </Notice>
      <RecoveryCodes codes={codes} />
      <div className="flex flex-wrap gap-2">
        <KeepCodes codes={codes} account={me.name} />
        <AccountButton name="done" onClick={onDone}>
          {t('twofactor.codesDone')}
        </AccountButton>
      </div>
    </div>
  )
}

type Enrolment = { secret: string; uri: string; qr_svg: string }

/**
 * The module's part "secondFactor" (`part="factor"`: its state beside the title, set up and remove the authenticator)
 * or "recoveryCodes" (`part="codes"`: how many are left, new ones). Where the operator asks for a second factor, the
 * last one cannot be turned off. An account from a provider gives no password; the server takes a sign-in of the last
 * few minutes instead.
 */
export function SecondFactorBox({ me, part: which }: { me: Me; part: 'factor' | 'codes' }) {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null)
  const [asking, setAsking] = useState<'disable' | 'renew' | null>(null)
  const [digits, setDigits] = useState('')
  const [password, setPassword] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const action = useAction()
  const withPassword = me.sign_in === 'password'
  const last = Boolean(me.second_factor_required) && me.passkeys === 0

  const close = () => {
    setEnrolment(null)
    setAsking(null)
    setDigits('')
    setPassword('')
    action.clear()
  }

  const passwordField = withPassword && (
    <Field label={t(FIELDS.password.label)} value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" hints={enrolment ? [t('twofactor.passwordHint')] : undefined} />
  )
  const dialog = asking && (
    <ConfirmDialog
      title={asking === 'disable' ? t('account.totpRemove') : t('account.recoveryCodesNew')}
      text={asking === 'disable' ? t('twofactor.disableText') : t('twofactor.renewText')}
      confirm={asking === 'disable' ? confirmOf('account.totpRemove', t('twofactor.disable')) : confirmOf('account.recoveryCodesNew', t('twofactor.renew'))}
      cancel={t('common.cancel')}
      closeLabel={t('common.close')}
      busy={action.busy}
      error={action.problem ? errorText(action.problem, action.values) : undefined}
      confirmDisabled={withPassword && !password}
      onCancel={close}
      onConfirm={() =>
        void action.run(async () => {
          if (asking === 'disable') {
            await api('/api/v1/auth/totp/disable', { method: 'POST', body: { password } })
            close()
            await refresh()
          } else {
            const result = await api<{ recovery_codes: string[] }>('/api/v1/auth/totp/recovery', { method: 'POST', body: { password } })
            close()
            setCodes(result.recovery_codes)
          }
        })
      }
    >
      {passwordField}
    </ConfirmDialog>
  )

  if (which === 'codes') {
    const left = me.two_factor_recovery_left
    return (
      <Box
        title={t(part('recoveryCodes').title)}
        hint={t(part('recoveryCodes').hint)}
        badge={!codes && <Badge tone={left < LOW_CODES ? 'warn' : 'off'}>{t('twofactor.codesLeft', { count: left })}</Badge>}
        testId="recovery-codes-part"
        actions={!codes && <AccountButton name="account.recoveryCodesNew" onClick={() => setAsking('renew')} />}
      >
        {codes ? (
          <FreshCodes
            codes={codes}
            me={me}
            onDone={() => {
              setCodes(null)
              void refresh()
            }}
          />
        ) : (
          left < LOW_CODES && <Notice tone="warn">{t('twofactor.lowCodes')}</Notice>
        )}
        {dialog}
      </Box>
    )
  }

  return (
    <Box
      title={t(part('secondFactor').title)}
      hint={t(part('secondFactor').hint)}
      badge={
        <Badge tone={me.totp ? 'on' : 'off'} testId="second-factor-state">
          {t(me.totp ? SECOND_FACTOR_STATE.active : SECOND_FACTOR_STATE.none)}
        </Badge>
      }
      testId="second-factor"
      actions={
        !enrolment && !codes ? (
          me.totp ? (
            !last && <AccountButton name="account.totpRemove" onClick={() => setAsking('disable')} />
          ) : (
            <AccountButton
              name="account.totpSetup"
              busy={action.busy}
              onClick={() => void action.run(async () => setEnrolment(await api<Enrolment>('/api/v1/auth/totp/begin', { method: 'POST' })))}
            />
          )
        ) : undefined
      }
    >
      {codes ? (
        <FreshCodes
          codes={codes}
          me={me}
          onDone={() => {
            setCodes(null)
            void refresh()
          }}
        />
      ) : enrolment ? (
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            void action.run(async () => {
              const result = await api<{ recovery_codes: string[] | null }>('/api/v1/auth/totp/confirm', { method: 'POST', body: { code: digits.trim(), password } })
              close()
              if (result.recovery_codes) setCodes(result.recovery_codes)
              else await refresh()
            })
          }}
        >
          <p className="m-0 text-sm">{withPassword ? t('twofactor.scan') : t('twofactor.scanNoPassword')}</p>
          <div className="flex justify-center">
            <img src={'data:image/svg+xml;utf8,' + encodeURIComponent(enrolment.qr_svg)} alt={t('twofactor.qr')} width={160} height={160} className="rounded-[9px] bg-white p-1" />
          </div>
          <code className="block rounded-[9px] bg-[var(--nexui-field)] px-3 py-2 font-mono text-xs break-all" data-testid="totp-secret">
            {enrolment.secret.replace(/(.{4})/g, '$1 ').trim()}
          </code>
          <Field label={t('twofactor.code')} value={digits} onChange={(event) => setDigits(event.target.value)} autoComplete="one-time-code" autoFocus mono />
          {passwordField}
          <Outcome problem={action.problem} values={action.values} />
          <div className="flex flex-wrap justify-end gap-2">
            <AccountButton name="cancel" onClick={close}>
              {t('common.cancel')}
            </AccountButton>
            <AccountButton name="confirm" type="submit" busy={action.busy} disabled={digits.trim().length !== 6 || (withPassword && !password)}>
              {t('twofactor.confirm')}
            </AccountButton>
          </div>
        </form>
      ) : (
        <>
          {me.totp && last && <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t('twofactor.required')}</p>}
          {!asking && <Outcome problem={action.problem} values={action.values} />}
        </>
      )}
      {dialog}
    </Box>
  )
}

/** A name for a new passkey from what the browser says about the device; the person may change it. */
function guessName(agent: string): string {
  if (/iPhone/.test(agent)) return 'iPhone'
  if (/iPad/.test(agent)) return 'iPad'
  if (/Android/.test(agent)) return 'Android'
  if (/Windows/.test(agent)) return 'Windows Hello'
  if (/Macintosh|Mac OS X/.test(agent)) return 'Touch ID'
  return 'Passkey'
}

/** "Passkeys": the own ones with when they were made and last used, add one, remove one with the password. A first
 * passkey of an account without codes brings its recovery codes, shown once. */
export function PasskeysBox({ me }: { me: Me }) {
  const { t, i18n } = useTranslation()
  const { refresh } = useAuth()
  const [list, setList] = useState<Passkey[]>([])
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const action = useAction()
  const { ask, dialog } = useAsk()
  const withPassword = me.sign_in === 'password'
  const load = useCallback(() => {
    passkeyApi.list().then(setList, () => undefined)
  }, [])
  useEffect(load, [load])
  // The browser has the API, and the server offers passkeys here (under its public https address, or on localhost).
  const [offered, setOffered] = useState(true)
  useEffect(() => {
    authApi.methods().then((found) => setOffered(found.passkeys !== false), () => undefined)
  }, [])
  const inBrowser = passkeysAvailable()
  const startAdding = () => {
    setName(guessName(navigator.userAgent))
    setPassword('')
    action.clear()
    setAdding(true)
  }
  const add = () =>
    void action
      .run(async () => {
        const { options } = await passkeyApi.begin()
        let credential
        try {
          credential = await createPasskey(options)
        } catch {
          throw new ApiError(0, 'passkey_cancelled')
        }
        const added = await passkeyApi.add(credential, name.trim(), password)
        setAdding(false)
        setPassword('')
        load()
        if (added.recovery_codes) setCodes(added.recovery_codes)
        else await refresh()
      }, t('me.passkeys.added'))
  return (
    <Box
      title={t(part('passkeys').title)}
      hint={t(part('passkeys').hint)}
      testId="passkeys-part"
      actions={
        !codes &&
        (inBrowser ? (
          // Since E49 the module's box part: the button where the server can add a passkey (a public https address,
          // or the page on localhost), else what is missing (an operator gets the way to Server › Anmeldung).
          <PasskeyAddition
            t={t}
            canAdd={(me.passkeys_can_add ?? true) && offered}
            operator={me.role === 'operator'}
            onAdd={startAdding}
            signInHref="/settings/sign-in"
          />
        ) : (
          // This browser has no passkeys at all: the button stays, greyed, as before.
          <AccountButton name="account.passkeyAdd" disabled onClick={() => undefined} />
        ))
      }
    >
      {list.length > 0 && (
        <Rows label={t(part('passkeys').title)} testId="passkeys">
          {list.map((key) => (
            <Row
              key={key.id}
              icon={Fingerprint}
              name={key.name}
              detail={t('me.passkeys.meta', {
                since: daysAgo(key.created_at, i18n.language),
                used: key.last_used_at ? ago(key.last_used_at, i18n.language, t('me.justNow')) : t('me.passkeys.never'),
              })}
              action={
                <AccountButton
                  name="account.passkeyRemove"
                  aria-label={t('me.passkeys.remove', { name: key.name })}
                  onClick={() =>
                    ask({
                      title: t('me.passkeys.removeTitle', { name: iso(key.name) }),
                      text: t('me.passkeys.removeText'),
                      confirm: t('me.passkeys.removeButton'),
                      password: withPassword,
                      run: async (own) => {
                        await passkeyApi.remove(key.id, own)
                        load()
                        await refresh()
                        void action.run(async () => undefined, t('me.passkeys.removed'))
                      },
                    })
                  }
                />
              }
            />
          ))}
        </Rows>
      )}
      {codes && (
        <FreshCodes
          codes={codes}
          me={me}
          onDone={() => {
            setCodes(null)
            void refresh()
          }}
        />
      )}
      {!inBrowser && (
        // The browser cannot (no https, no API). A missing public address says the module's box part above.
        <p className="m-0 text-xs text-[var(--nexui-text-muted)]" data-testid="passkeys-unavailable">
          {t('me.passkeys.unavailable')}
        </p>
      )}
      {!adding && <Outcome problem={action.problem} done={action.done} values={action.values} />}
      {adding && (
        <ConfirmDialog
          title={t('me.passkeys.add')}
          text={t('me.passkeys.how')}
          confirm={{ label: t('me.passkeys.create'), kind: 'primary', icon: 'Fingerprint' }}
          cancel={t('common.cancel')}
          closeLabel={t('common.close')}
          busy={action.busy}
          error={action.problem && action.problem !== 'passkey_cancelled' ? errorText(action.problem, action.values) : action.problem ? errorText(action.problem) : undefined}
          confirmDisabled={withPassword && !password}
          onCancel={() => setAdding(false)}
          onConfirm={add}
        >
          <Field label={t('me.passkeys.name')} value={name} onChange={(event) => setName(event.target.value)} maxLength={64} />
          {withPassword && <Field label={t(FIELDS.password.label)} type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />}
        </ConfirmDialog>
      )}
      {dialog}
    </Box>
  )
}

/** The module's part "sessions": the browsers where the account is signed in (this one marked), sign out one, and
 * "sign out everywhere else" (the module's button). The paired devices and apps stand under Connections, "Geräte". How
 * long a sign-in lasts without use comes last, once the server said it. */
export function SessionsBox() {
  const { t, i18n } = useTranslation()
  const [list, setList] = useState<SignedSession[] | null>(null)
  const action = useAction()
  const { ask, dialog } = useAsk()
  // How long a sign-in lasts without use (NEXPAPER_SESSION_DAYS); the sentence waits until the server said it.
  const [days, setDays] = useState<number | null>(null)
  useEffect(() => {
    let alive = true
    authApi.methods().then((methods) => alive && typeof methods.session_days === 'number' && setDays(methods.session_days), () => undefined)
    return () => {
      alive = false
    }
  }, [])
  const load = useCallback(() => {
    authApi.sessions().then(setList, () => undefined)
  }, [])
  useEffect(load, [load])
  useEffect(() => {
    window.addEventListener(SESSIONS_CHANGED, load)
    return () => window.removeEventListener(SESSIONS_CHANGED, load)
  }, [load])
  return (
    <Box
      title={t(part('sessions').title)}
      hint={t('account.signOutEverywhereHint')}
      testId="sessions-part"
      actions={
        <AccountButton
          name="account.signOutEverywhere"
          busy={action.busy}
          testId="sign-out-everywhere"
          onClick={() =>
            ask({
              title: t('confirm.logoutOthers.title'),
              text: t('confirm.logoutOthers.text'),
              confirm: t('confirm.logoutOthers.confirm'),
              icon: 'LogOut',
              run: async () => {
                await authApi.logoutOthers()
                load()
                window.dispatchEvent(new Event(SESSIONS_CHANGED))
                void action.run(async () => undefined, t('me.devices.endedAll'))
              },
            })
          }
        />
      }
    >
      {list && (
        <Rows label={t(part('sessions').title)} testId="sessions">
          {list.map((row) => (
            <Row
              key={row.id}
              icon={row.phone || row.kind === 'device' ? Smartphone : Laptop}
              name={row.device}
              badge={row.here ? <Badge tone="on">{t('me.devices.here')}</Badge> : undefined}
              detail={t('me.devices.meta', { where: row.network ?? '', when: ago(row.last_seen_at ?? row.created_at, i18n.language, t('me.justNow')) })}
              action={
                !row.here && (
                  <AccountButton
                    name="account.sessionSignOut"
                    busy={action.busy}
                    onClick={() =>
                      ask({
                        title: t('confirm.session.title'),
                        text: t('confirm.session.text'),
                        confirm: t('confirm.session.confirm'),
                        icon: 'LogOut',
                        run: async () => {
                          await authApi.endSession(row.id)
                          load()
                          void action.run(async () => undefined, t('me.devices.ended', { name: row.device }))
                        },
                      })
                    }
                  >
                    {t('me.devices.signOut')}
                  </AccountButton>
                )
              }
            />
          ))}
        </Rows>
      )}
      {days !== null && days > 0 && (
        <p className="m-0 text-xs text-[var(--nexui-text-muted)]" data-testid="session-days">
          {t('me.devices.ends', { count: days })}
        </p>
      )}
      <Outcome problem={action.problem} done={action.done} values={action.values} />
      {dialog}
    </Box>
  )
}

/** The module's part "newSignInMail": the mail and the push of a new sign-in, on from the start. */
function SignInMailRow({ me }: { me: Me }) {
  const { t } = useTranslation()
  const { setMe } = useAuth()
  const action = useAction()
  return (
    <div className="flex flex-col gap-2" data-testid="security-newSignInMail">
      <CheckboxRow
        label={t(part('newSignInMail').title)}
        hint={newSignInMailHint(t(part('newSignInMail').hint), t('me.newSignInMailPush'))}
        checked={me.profile.notify_login !== false}
        disabled={action.busy}
        onChange={(notify_login) => {
          setMe({ ...me, profile: { ...me.profile, notify_login } })
          void action.run(async () => setMe({ ...me, profile: await authApi.preferences({ notify_login }) })).then((worked) => worked || setMe(me))
        }}
      />
      <Outcome problem={action.problem} />
    </div>
  )
}

/**
 * nexpaper's own part of Security: the sign-in providers, one row per active provider with its state and "Link" or
 * "Unlink". Linking asks for the own password first and then goes to the provider; the way back lands here with
 * `?linked=<short name>`, said by the provider's name. An account that signs in through a provider only keeps its last
 * link. Where the provider knows the account by another address, the row offers it; taken, it is not confirmed yet.
 */
function ProvidersBox({ me }: { me: Me }) {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const [params] = useSearchParams()
  const [providers, setProviders] = useState<MyProvider[] | null>(null)
  const [linking, setLinking] = useState<MyProvider | null>(null)
  const [password, setPassword] = useState('')
  const [linkProblem, setLinkProblem] = useState<string | null>(null)
  const [linkBusy, setLinkBusy] = useState(false)
  const [shownBack, setShownBack] = useState(true)
  const action = useAction()
  const { ask, dialog } = useAsk()
  const linked = params.get('linked')
  const said = params.get('error')
  const load = useCallback(async () => {
    const found = await oidcApi.mine()
    setProviders(Array.isArray(found) ? found : [])
  }, [])
  useEffect(() => {
    void load().catch(() => setProviders([]))
  }, [load])
  if (providers === null || (providers.length === 0 && me.sign_in !== 'oidc')) return null
  const backFrom = linked && shownBack ? providers.find((entry) => entry.slug === linked) : undefined
  const linkedCount = providers.filter((entry) => entry.linked).length
  const run = (work: () => Promise<unknown>, success: string) => {
    setShownBack(false)
    void action.run(async () => {
      await work()
      await load()
    }, success)
  }
  return (
    <Box title={t('oidc.account.title')} hint={t('oidc.account.text')} testId="my-providers-part">
      {backFrom && !action.done && !action.problem && <Notice tone="ok">{t('me.oidc.linkedTo', { name: backFrom.label })}</Notice>}
      {said && shownBack && !action.problem && <Notice tone="danger">{errorText(said)}</Notice>}
      <Rows label={t('oidc.account.title')} testId="my-providers">
        {providers.map((provider) => {
          const lastLink = me.sign_in === 'oidc' && provider.linked && linkedCount === 1
          const offer = provider.linked && provider.address && me.sign_in === 'password'
          return (
            <Row
              key={provider.slug}
              icon="KeyRound"
              name={provider.label}
              badge={<Badge tone={provider.linked ? 'on' : 'off'}>{provider.linked ? t('oidc.account.linked') : t('oidc.account.notLinked')}</Badge>}
              sub={offer ? t('me.oidc.addressOffer', { provider: provider.label, address: provider.address }) : undefined}
              note={lastLink ? t('oidc.account.only', { name: provider.label }) : undefined}
              action={
                <span className="flex flex-wrap items-center gap-2">
                  {offer && (
                    <Button kind="secondary" size="sm" icon="Mail" busy={action.busy} onClick={() => run(async () => {
                      await oidcApi.takeAddress(provider.slug)
                      await refresh()
                    }, t('me.oidc.addressTaken'))}>
                      {t('me.oidc.takeAddress')}
                    </Button>
                  )}
                  {provider.linked && !lastLink && (
                    <AccountButton
                      name="oidc.account.unlink"
                      busy={action.busy}
                      aria-label={`${t('oidc.account.unlink')}: ${provider.label}`}
                      onClick={() =>
                        ask({
                          title: t('confirm.oidcLink.title'),
                          text: t('confirm.oidcLink.text', { name: iso(provider.label) }),
                          confirm: t('confirm.oidcLink.confirm'),
                          icon: 'Unlink',
                          run: async () => run(() => oidcApi.unlink(provider.slug), t('me.oidc.unlinkedFrom', { name: provider.label })),
                        })
                      }
                    />
                  )}
                  {!provider.linked && me.sign_in === 'password' && (
                    <AccountButton
                      name="oidc.account.link"
                      busy={action.busy}
                      aria-label={`${t('oidc.account.link')}: ${provider.label}`}
                      onClick={() => {
                        setPassword('')
                        setLinkProblem(null)
                        setLinking(provider)
                      }}
                    />
                  )}
                </span>
              }
            />
          )
        })}
      </Rows>
      <Outcome problem={action.problem} done={action.done} values={action.values} />
      {linking && (
        <ConfirmDialog
          title={`${t('oidc.account.link')}: ${linking.label}`}
          text={t('oidc.account.text')}
          confirm={confirmOf('oidc.account.link', t('oidc.account.link'))}
          cancel={t('common.cancel')}
          closeLabel={t('common.close')}
          busy={linkBusy}
          error={linkProblem ? errorText(linkProblem) : undefined}
          confirmDisabled={!password}
          onCancel={() => setLinking(null)}
          onConfirm={() => {
            setLinkBusy(true)
            setLinkProblem(null)
            oidcApi.link(linking.slug, password).then(
              ({ url }) => window.location.assign(url),
              (error) => {
                setLinkProblem(error instanceof ApiError ? error.code : 'internal_error')
                setLinkBusy(false)
              },
            )
          }}
        >
          <Field label={t(FIELDS.password.label)} type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
        </ConfirmDialog>
      )}
      {dialog}
    </Box>
  )
}
