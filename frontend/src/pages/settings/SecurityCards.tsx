/**
 * The own account, Security, as the mock: the second factor (a code from an app), passkeys, and the signed-in devices
 * with "sign out everywhere else" and the notice of a new sign-in. The server decides; the cards show and ask.
 */
import { Fingerprint, Laptop, ShieldCheck, Smartphone, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { api, ApiError, authApi, devicesApi, passkeyApi, type Me, type PairedDevice, type Passkey, type SignedSession } from '../../api/client'
import { Dialog } from '../../components/Dialog'
import { useConfirm } from '../../components/useConfirm'
import { KeepCodes, RecoveryCodes } from '../../components/RecoveryCodes'
import { ago, daysAgo } from '../../lib/ago'
import { createPasskey, passkeysAvailable } from '../../lib/webauthn'
import { useAuth } from '../../state/auth'
import { SignInNoticeCard } from './PushCards'
import { Button, Card, Confirm, Feedback, Input, useAction } from './ui'

/** Below this many recovery codes the account is told to make new ones. */
const LOW_CODES = 3

type Enrolment = { secret: string; uri: string; qr_svg: string }

/** The codes, shown once right after they were made, and "I have them". */
function FreshCodes({ codes, me, onDone }: { codes: string[]; me: Me; onDone: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-2">{t('twofactor.codesLead')}</p>
      <RecoveryCodes codes={codes} />
      <div className="flex flex-wrap gap-2">
        <KeepCodes codes={codes} account={me.name} className="flex-1" />
        <Button primary onClick={onDone}>
          {t('twofactor.codesDone')}
        </Button>
      </div>
    </div>
  )
}

/**
 * "Zweiter Faktor": set up (scan the code, type one code, and the password), new recovery codes, turn off. Where the
 * operator asks for a second factor, the last one cannot be turned off. An account from the provider gives no
 * password; the server takes a sign-in of the last few minutes instead.
 */
export function SecondFactorCard({ me }: { me: Me }) {
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

  let body
  if (codes)
    body = (
      <FreshCodes
        codes={codes}
        me={me}
        onDone={() => {
          setCodes(null)
          void refresh()
        }}
      />
    )
  else if (enrolment)
    body = (
      <div className="grid gap-5 sm:grid-cols-[10rem_1fr]">
        <img src={'data:image/svg+xml;utf8,' + encodeURIComponent(enrolment.qr_svg)} alt={t('twofactor.qr')} className="h-40 w-40 rounded-xl bg-white p-1" />
        <form
          className="space-y-3"
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
          <p className="text-sm text-ink-2">{withPassword ? t('twofactor.scan') : t('twofactor.scanNoPassword')}</p>
          <p className="font-mono text-xs break-all text-muted" data-testid="totp-secret">
            {enrolment.secret.replace(/(.{4})/g, '$1 ').trim()}
          </p>
          <Input label={t('twofactor.code')} value={digits} onChange={setDigits} autoComplete="one-time-code" autoFocus />
          {withPassword && <Input label={t('auth.password')} value={password} onChange={setPassword} type="password" autoComplete="current-password" hint={t('twofactor.passwordHint')} />}
          <Feedback problem={action.problem} />
          <div className="flex flex-wrap gap-2">
            <Button type="submit" primary busy={action.busy} disabled={digits.trim().length !== 6 || (withPassword && !password)}>
              {t('twofactor.confirm')}
            </Button>
            <Button onClick={close}>{t('common.cancel')}</Button>
          </div>
        </form>
      </div>
    )
  else if (asking)
    body = (
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault()
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
        }}
      >
        <p className="text-sm text-ink-2">{asking === 'disable' ? t('twofactor.disableText') : t('twofactor.renewText')}</p>
        {withPassword && <Input label={t('auth.password')} value={password} onChange={setPassword} type="password" autoComplete="current-password" autoFocus className="max-w-sm" />}
        <Feedback problem={action.problem} />
        <div className="flex flex-wrap gap-2">
          <Button type="submit" busy={action.busy} disabled={withPassword && !password} primary={asking === 'renew'} danger={asking === 'disable'}>
            {asking === 'disable' ? t('twofactor.disable') : t('twofactor.renew')}
          </Button>
          <Button onClick={close}>{t('common.cancel')}</Button>
        </div>
      </form>
    )
  else
    body = (
      <div className="space-y-3">
        {me.totp ? (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-ink-2">{t('twofactor.on', { count: me.two_factor_recovery_left })}</span>
            <Button onClick={() => setAsking('renew')}>{t('twofactor.renew')}</Button>
            {!last && (
              <Button danger onClick={() => setAsking('disable')}>
                {t('twofactor.disable')}
              </Button>
            )}
            {last && <span className="text-xs text-muted">{t('twofactor.required')}</span>}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-ink-2">{t('twofactor.off')}</span>
            <Button primary busy={action.busy} onClick={() => void action.run(async () => setEnrolment(await api<Enrolment>('/api/v1/auth/totp/begin', { method: 'POST' })))}>
              {t('twofactor.enable')}
            </Button>
          </div>
        )}
        {!me.totp && me.passkeys > 0 && (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-ink-2">{t('twofactor.codesLeft', { count: me.two_factor_recovery_left })}</span>
            <Button onClick={() => setAsking('renew')}>{t('twofactor.renew')}</Button>
          </div>
        )}
        {me.two_factor && me.two_factor_recovery_left < LOW_CODES && (
          <p role="note" className="rounded-xl border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
            {t('twofactor.lowCodes')}
          </p>
        )}
        <Feedback problem={action.problem} />
      </div>
    )
  return (
    <Card icon={ShieldCheck} title={t('twofactor.title')} text={t('twofactor.lead')}>
      {body}
    </Card>
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

function AddPasskey({ me, onClose, onAdded }: { me: Me; onClose: () => void; onAdded: (codes: string[] | null) => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState(guessName(navigator.userAgent))
  const [password, setPassword] = useState('')
  const action = useAction()
  const withPassword = me.sign_in === 'password'
  return (
    <Dialog title={t('me.passkeys.add')} onClose={onClose}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault()
          void action.run(async () => {
            const { options } = await passkeyApi.begin()
            let credential
            try {
              credential = await createPasskey(options)
            } catch {
              throw new ApiError(0, 'passkey_cancelled')
            }
            const added = await passkeyApi.add(credential, name.trim(), password)
            onAdded(added.recovery_codes)
          })
        }}
      >
        <p className="text-sm text-ink-2">{t('me.passkeys.how')}</p>
        <Input label={t('me.passkeys.name')} value={name} onChange={setName} maxLength={64} />
        {withPassword && <Input label={t('auth.password')} type="password" value={password} onChange={setPassword} autoComplete="current-password" />}
        <Feedback problem={action.problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" primary busy={action.busy} disabled={withPassword && !password}>
            <Fingerprint size={16} /> {t('me.passkeys.create')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

/** "Passkeys": the own ones with when they were made and last used, add one, remove one with the password. */
export function PasskeysCard({ me }: { me: Me }) {
  const { t, i18n } = useTranslation()
  const { refresh } = useAuth()
  const [list, setList] = useState<Passkey[]>([])
  const [adding, setAdding] = useState(false)
  const [removing, setRemoving] = useState<Passkey | null>(null)
  const [codes, setCodes] = useState<string[] | null>(null)
  const [done, setDone] = useState<string | null>(null)
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
  const available = inBrowser && offered
  return (
    <Card icon={Fingerprint} title={t('me.passkeys.title')} text={t('me.passkeys.text')}>
      {list.length > 0 && (
        <ul className="space-y-2" data-testid="passkeys">
          {list.map((key) => (
            <li key={key.id} className="flex items-center gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-3 text-sm">
              <Fingerprint size={18} className="shrink-0 text-accent" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold">{key.name}</span>
                <span className="block text-xs text-muted">
                  {t('me.passkeys.meta', {
                    since: daysAgo(key.created_at, i18n.language),
                    used: key.last_used_at ? ago(key.last_used_at, i18n.language, t('me.justNow')) : t('me.passkeys.never'),
                  })}
                </span>
              </span>
              <button type="button" onClick={() => setRemoving(key)} className="rounded-full p-1.5 text-muted hover:bg-sheet hover:text-ink" aria-label={t('me.passkeys.remove', { name: key.name })}>
                <Trash2 size={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
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
        <div>
          <Button primary={list.length === 0} disabled={!available} onClick={() => setAdding(true)}>
            <Fingerprint size={16} /> {t('me.passkeys.add')}
          </Button>
          {!available && (
            <p className="mt-2 text-xs text-muted" data-testid="passkeys-unavailable">
              {/* The browser cannot (no https, no API): that is said first. Otherwise the server has no public address. */}
              {!inBrowser ? (
                t('me.passkeys.unavailable')
              ) : me.role === 'operator' ? (
                <Trans i18nKey="me.passkeys.noAddressOperator" components={{ settings: <Link to="/einstellungen?tab=signin" className="font-semibold text-accent underline-offset-2 hover:underline" /> }} />
              ) : (
                t('me.passkeys.noAddressMember')
              )}
            </p>
          )}
        </div>
      )}
      <Feedback problem={null} done={done} />
      {adding && (
        <AddPasskey
          me={me}
          onClose={() => setAdding(false)}
          onAdded={(fresh) => {
            setAdding(false)
            setDone(t('me.passkeys.added'))
            load()
            if (fresh) setCodes(fresh)
            else void refresh()
          }}
        />
      )}
      {removing && (
        <Confirm
          title={t('me.passkeys.removeTitle', { name: removing.name })}
          text={t('me.passkeys.removeText')}
          confirm={t('me.passkeys.removeButton')}
          danger
          password={me.sign_in === 'password'}
          onCancel={() => setRemoving(null)}
          onConfirm={async (password) => {
            await passkeyApi.remove(removing.id, password)
            setRemoving(null)
            setDone(t('me.passkeys.removed'))
            load()
            await refresh()
          }}
        />
      )}
    </Card>
  )
}

/** "Angemeldete Geräte": where the account is signed in, sign out one or all others; and the notice of a new one. */
export function DevicesCard({ me }: { me: Me }) {
  const { t, i18n } = useTranslation()
  const [list, setList] = useState<SignedSession[] | null>(null)
  // The paired devices and apps stand here too, as the mock: a phone paired by a QR code, the iPhone shortcut, an app.
  const [paired, setPaired] = useState<PairedDevice[]>([])
  const [taking, setTaking] = useState<PairedDevice | null>(null)
  const action = useAction()
  const { ask, dialog } = useConfirm()
  const load = useCallback(() => {
    authApi.sessions().then(setList, () => undefined)
    devicesApi.list().then((found) => setPaired(Array.isArray(found) ? found : []), () => setPaired([]))
  }, [])
  useEffect(load, [load])
  const how = (device: PairedDevice) => t(device.via === 'qr' ? 'phone.devices.qr' : device.via?.startsWith('app:') ? 'phone.devices.app' : 'phone.devices.token')
  return (
    <SignInNoticeCard me={me}>
      {list && (
        <ul className="space-y-2" data-testid="sessions">
          {list.map((row) => {
            const Icon = row.phone ? Smartphone : Laptop
            return (
              <li key={row.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-3 text-sm">
                <Icon size={18} className="shrink-0 text-accent" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="font-semibold">{row.device}</span>
                  {row.here && <span className="ml-2 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold text-accent">{t('me.devices.here')}</span>}
                  <span className="block text-xs text-muted">{t('me.devices.meta', { where: row.network, when: ago(row.last_seen_at, i18n.language, t('me.justNow')) })}</span>
                </span>
                {!row.here && (
                  <Button
                    busy={action.busy}
                    onClick={() =>
                      ask({
                        title: t('confirm.session.title'),
                        text: t('confirm.session.text'),
                        confirm: t('confirm.session.confirm'),
                        run: async () => {
                          await action.run(async () => {
                            await authApi.endSession(row.id)
                            load()
                          }, t('me.devices.ended', { name: row.device }))
                        },
                      })
                    }
                  >
                    {t('me.devices.signOut')}
                  </Button>
                )}
              </li>
            )
          })}
          {paired.map((device) => (
            <li key={device.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-3 text-sm" data-testid="paired-device">
              <Smartphone size={18} className="shrink-0 text-accent" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="font-semibold break-words">{device.name}</span>
                <span className="block text-xs text-muted">
                  {t('phone.devices.meta', { how: how(device), when: device.last_used_at ? ago(device.last_used_at, i18n.language, t('me.justNow')) : t('phone.devices.never') })}
                </span>
              </span>
              <Button busy={action.busy} onClick={() => setTaking(device)} label={t('pairing.takeOffNamed', { name: device.name })}>
                {t('me.devices.signOut')}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {taking && (
        <Confirm
          title={t('phone.devices.revokeTitle', { name: taking.name })}
          text={t('phone.devices.revokeText')}
          confirm={t('me.devices.signOut')}
          danger
          onCancel={() => setTaking(null)}
          onConfirm={async () => {
            const name = taking.name
            await action.run(async () => {
              await devicesApi.revoke(taking.id)
              load()
            }, t('phone.devices.revoked', { name }))
            setTaking(null)
          }}
        />
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          busy={action.busy}
          onClick={() =>
            ask({
              title: t('confirm.logoutOthers.title'),
              text: t('confirm.logoutOthers.text'),
              confirm: t('confirm.logoutOthers.confirm'),
              run: async () => {
                await action.run(async () => {
                  await authApi.logoutOthers()
                  load()
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
    </SignInNoticeCard>
  )
}
