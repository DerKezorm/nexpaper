/**
 * Web Push: under My account, Devices and apps, the devices of the person ("Benachrichtigungen auf deinen Geräten":
 * each one signed up on its own, renamed, signed off; this one turned on here; a test to all of them). Under Security
 * the switch for the notice of a new sign-in. The operator's card under Settings, Web Push: ready and how many
 * devices, the contact for the push services, the key pair, more push services beyond the known ones.
 */
import { Bell, BellRing, Check, Laptop, MonitorSmartphone, Pencil, Smartphone, Trash2 } from 'lucide-react'
import { useEffect, useId, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, authApi, pushApi, type Me, type PushDevice, type PushSettings } from '../../api/client'
import { useConfirm } from '../../components/useConfirm'
import { dayOfMoment } from '../../lib/dates'
import { currentSubscription, installed, readiness, subscribe, unsubscribe, type PushReadiness } from '../../lib/push'
import { iso } from '../../lib/say'
import { useAuth } from '../../state/auth'
import { Button, Card, Confirm, Feedback, Input, SubHead, Toggle, useAction } from './ui'

/** The devices of the person that get a notice, and this browser's sign-up. */
export function PushDevicesCard({ me }: { me: Me }) {
  const { t, i18n } = useTranslation()
  const [devices, setDevices] = useState<PushDevice[] | null>(null)
  const [key, setKey] = useState('')
  const [here, setHere] = useState<string | null>(null)
  const [state, setState] = useState<PushReadiness>(() => readiness())
  const [naming, setNaming] = useState<{ id: string; name: string } | null>(null)
  const action = useAction()
  const { ask, dialog } = useConfirm()
  const [browserSaid, setBrowserSaid] = useState<string | null>(null)
  /** What the last probe reached, said in place of the line of the action. */
  const [probed, setProbed] = useState<string | null>(null)

  const load = async () => {
    const found = await pushApi.state()
    setDevices(found.devices)
    setKey(found.key)
    const subscription = await currentSubscription().catch(() => null)
    setHere(subscription ? (await pushApi.lookup(subscription.endpoint)).id : null)
  }
  useEffect(() => {
    let alive = true
    pushApi.state().then(
      async (found) => {
        if (!alive) return
        setDevices(found.devices)
        setKey(found.key)
        const subscription = await currentSubscription().catch(() => null)
        const id = subscription ? (await pushApi.lookup(subscription.endpoint).catch(() => ({ id: null }))).id : null
        if (alive) setHere(id)
      },
      () => alive && setDevices([]),
    )
    return () => {
      alive = false
    }
  }, [])

  const enable = () => {
    setBrowserSaid(null)
    setProbed(null)
    void action.run(async () => {
      try {
        const subscription = await subscribe(key)
        await pushApi.add({ ...subscription, installed: installed() })
      } catch (caught) {
        setState(readiness())
        if (caught instanceof ApiError) throw caught
        const message = caught instanceof Error ? caught.message : String(caught)
        if (message === 'denied') throw new ApiError(0, 'push_denied_now')
        setBrowserSaid(t('me.push.browserSaid', { message }))
        throw new ApiError(0, 'push_browser')
      }
      await load()
    }, t('me.push.enabled'))
  }

  const remove = (device: PushDevice) => {
    setProbed(null)
    ask({
      title: t('confirm.pushDevice.title'),
      text: t('confirm.pushDevice.text', { name: iso(device.name) }),
      confirm: t('confirm.pushDevice.confirm'),
      run: async () => {
        await action.run(async () => {
          await pushApi.remove(device.id)
          if (device.id === here) await unsubscribe()
          await load()
        }, t('me.push.removed', { name: device.name }))
      },
    })
  }

  const rename = (id: string, name: string) => {
    setProbed(null)
    void action.run(async () => {
      await pushApi.rename(id, name.trim())
      setNaming(null)
      await load()
    }, t('me.push.renamed'))
  }

  const probe = () => {
    setProbed(null)
    void action.run(async () => {
      const result = await pushApi.probe()
      const all = result.sent + result.gone + result.failed
      if (result.gone) await load()
      setProbed(result.sent === all ? t('me.push.probed') : t('me.push.probedSome', { sent: result.sent, all }))
    })
  }

  const zone = me.profile.timezone || undefined
  const signedUpHere = here !== null && (devices ?? []).some((device) => device.id === here)
  const problem = action.problem === 'push_denied_now' ? null : action.problem === 'push_browser' ? null : action.problem
  return (
    <Card icon={BellRing} title={t('me.push.title')} text={t('me.push.text')}>
      {devices && devices.length > 0 && (
        <ul className="space-y-2">
          {devices.map((device) => (
            <li key={device.id} className="flex items-center gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-3 text-sm">
              {device.phone ? <Smartphone size={18} className="shrink-0 text-accent" aria-hidden /> : <Laptop size={18} className="shrink-0 text-accent" aria-hidden />}
              {naming?.id === device.id ? (
                <form
                  className="flex flex-1 flex-wrap items-end gap-2"
                  onSubmit={(event) => {
                    event.preventDefault()
                    rename(device.id, naming.name)
                  }}
                >
                  <Input label={t('me.push.name')} value={naming.name} onChange={(name) => setNaming({ id: device.id, name })} className="min-w-48 flex-1" autoFocus />
                  <Button type="submit" busy={action.busy} disabled={!naming.name.trim()}>
                    {t('common.save')}
                  </Button>
                  <Button onClick={() => setNaming(null)}>{t('common.cancel')}</Button>
                </form>
              ) : (
                <>
                  <span className="min-w-0 flex-1">
                    <span className="font-semibold break-words">{device.name}</span>
                    {device.id === here && <span className="ml-2 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold text-accent">{t('me.push.here')}</span>}
                    <span className="block text-xs text-muted">
                      {t('me.push.since', { date: dayOfMoment(device.since, i18n.language, zone) })}
                      {device.last && ` · ${t('me.push.last', { date: dayOfMoment(device.last, i18n.language, zone) })}`}
                    </span>
                  </span>
                  <button type="button" onClick={() => setNaming({ id: device.id, name: device.name })} className="rounded-full p-1.5 text-muted hover:bg-sheet hover:text-ink" aria-label={t('me.push.rename')}>
                    <Pencil size={15} aria-hidden />
                  </button>
                  <button type="button" onClick={() => remove(device)} className="rounded-full p-1.5 text-muted hover:bg-sheet hover:text-ink" aria-label={t('me.push.remove')}>
                    <Trash2 size={15} aria-hidden />
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {devices && !signedUpHere && (
        <div className="rounded-xl border border-dashed border-line p-4" data-testid="push-here">
          <p className="text-sm font-semibold">{t('me.push.thisDevice')}</p>
          <p className="mt-1 text-sm text-ink-2">{action.problem === 'push_denied_now' ? t('me.push.deniedNow') : t(`me.push.${state}`)}</p>
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-muted">
            <li>{t('me.push.hintHttps')}</li>
            <li>{t('me.push.hintIphone')}</li>
          </ul>
          <Button primary className="mt-3" busy={action.busy} disabled={state !== 'ready' || !key} onClick={enable}>
            <Bell size={16} aria-hidden /> {t('me.push.enable')}
          </Button>
          {browserSaid && <p className="mt-2 text-xs text-bad">{browserSaid}</p>}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-3 pt-1">
        <Button busy={action.busy} onClick={probe}>
          {t('me.push.probe')}
        </Button>
        <span className="text-xs text-muted">{t('me.push.probeHint')}</span>
      </div>
      <Feedback problem={problem} done={probed ?? action.done} values={action.values} />
      {dialog}
    </Card>
  )
}

/** Under Security: the switch for the notice of a new sign-in, on from the start, and the browsers signed in. */
export function SignInNoticeCard({ me, children }: { me: Me; children?: ReactNode }) {
  const { t } = useTranslation()
  const { setMe } = useAuth()
  const action = useAction()
  const on = me.profile.notify_login !== false
  return (
    <Card icon={MonitorSmartphone} title={t('me.devices.title')} text={t('me.devices.text')}>
      {children}
      <Toggle
        label={t('me.devices.notify')}
        hint={t('me.devices.notifyHint')}
        checked={on}
        onChange={(notify_login) => {
          setMe({ ...me, profile: { ...me.profile, notify_login } })
          void action.run(async () => setMe({ ...me, profile: await authApi.preferences({ notify_login }) })).then((worked) => worked || setMe(me))
        }}
      />
      <Feedback problem={action.problem} />
    </Card>
  )
}

const AREA = 'mt-1 block min-h-24 w-full rounded-xl border border-line bg-sheet px-3.5 py-2.5 font-mono text-[0.9rem] text-ink outline-none placeholder:text-muted/70 focus:border-accent'

export function PushServerCard() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [stored, setStored] = useState<PushSettings | null>(null)
  const [contact, setContact] = useState('')
  const [hosts, setHosts] = useState('')
  const [asking, setAsking] = useState(false)
  const action = useAction()
  const hintId = useId()

  const take = (found: PushSettings) => {
    setStored(found)
    setContact(found.contact)
    setHosts(found.hosts.join('\n'))
  }
  useEffect(() => {
    let alive = true
    pushApi.settings().then((found) => alive && take(found), () => undefined)
    return () => {
      alive = false
    }
  }, [])
  if (!stored) return null

  const lines = () => hosts.split('\n').map((line) => line.trim()).filter(Boolean)
  return (
    <Card id="push-server" icon={BellRing} title={t('server.push.title')} text={t('server.push.text')}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="inline-flex items-center gap-2 rounded-full bg-accent-soft px-3 py-1 text-sm font-semibold text-accent" data-testid="push-ready">
          <Check size={14} aria-hidden /> {t('server.push.ready', { count: stored.devices })}
        </span>
      </div>
      <form
        className="flex flex-wrap items-start gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void action.run(async () => take(await pushApi.saveSettings({ contact: contact.trim() })), t('server.push.saved'))
        }}
      >
        <Input label={t('server.push.contact')} value={contact} onChange={setContact} placeholder={stored.contact_used} hint={t('server.push.contactHint')} className="min-w-72 flex-1" />
        <Button type="submit" className="mt-6" busy={action.busy}>
          {t('common.save')}
        </Button>
      </form>
      <SubHead title={t('server.push.keys')} text={t('server.push.keysText')} />
      <div className="flex flex-wrap items-center gap-3">
        <code className="rounded-lg bg-sheet-2 px-3 py-1.5 font-mono text-xs text-ink-2">{stored.key}</code>
        <Button danger onClick={() => setAsking(true)}>
          {t('server.push.renew')}
        </Button>
        <Button
          busy={action.busy}
          onClick={() =>
            void action.run(async () => {
              await pushApi.probe()
              take(await pushApi.settings())
            }, t('me.push.probed'))
          }
        >
          {t('server.push.probe')}
        </Button>
      </div>
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault()
          void action.run(async () => take(await pushApi.saveSettings({ hosts: lines() })), t('server.push.saved'))
        }}
      >
        <div className="pt-3 text-sm">
          <label className="block">
            <span className="font-semibold">{t('server.push.hosts')}</span>
            <textarea
              value={hosts}
              onChange={(event) => setHosts(event.target.value)}
              rows={2}
              spellCheck={false}
              autoCapitalize="off"
              autoComplete="off"
              maxLength={6000}
              placeholder="push.example.com"
              aria-describedby={hintId}
              className={AREA}
            />
          </label>
          <span id={hintId} className="mt-1 block text-xs text-muted">
            {t('server.push.hostsHint')}
          </span>
        </div>
        <Button type="submit" busy={action.busy}>
          {t('server.push.save')}
        </Button>
      </form>
      <p className="rounded-xl bg-sheet-2 px-4 py-3 text-xs leading-relaxed text-ink-2">{t('server.push.out')}</p>
      <Feedback problem={action.problem} values={action.values} done={action.done} />
      {asking && (
        <Confirm
          title={t('server.push.renewTitle')}
          text={t('server.push.renewText')}
          confirm={t('server.push.renew')}
          danger
          password={me?.sign_in === 'password'}
          onCancel={() => setAsking(false)}
          onConfirm={async (password) => {
            take(await pushApi.renew(password))
            setAsking(false)
            void action.run(async () => undefined, t('server.push.renewed'))
          }}
        />
      )}
    </Card>
  )
}
