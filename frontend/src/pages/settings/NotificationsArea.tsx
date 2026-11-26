/**
 * My account › Notifications (plan "Einstellungen", Benachrichtigungen, E1; before "Erinnerungen"): first the card of
 * every app that notifies, "Auf welchem Weg" (ui `NotifyWays`) with nexpaper's ways: mail (the account's address), this
 * browser (Web Push: turn on, turn off, a test notice), the browsers and phones with notifications (each renamed and
 * removed on its own; before the card "Benachrichtigungen auf deinen Geräten" under Connections), and the iPhone and
 * iPad app (under Connections). Then nexpaper's own cards of the deadlines (`RemindersCards.tsx`).
 */
import { Laptop, Smartphone } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { ApiError, pushApi, type Me, type PushDevice } from '../../api/client'
import { dayOfMoment } from '../../lib/dates'
import { currentSubscription, installed, readiness, subscribe, unsubscribe, type PushReadiness } from '../../lib/push'
import { iso } from '../../lib/say'
import { Box, Button, ConfirmDialog, Field, NotifyWays } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'
import { RemindersPart } from './RemindersCards'
import { useAsk } from './useAsk'

export function NotificationsArea({ me }: { me: Me }) {
  return (
    <>
      <Ways me={me} />
      <RemindersPart me={me} />
    </>
  )
}

/** "Auf welchem Weg" with what this browser and the server say about the push. */
function Ways({ me }: { me: Me }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [devices, setDevices] = useState<PushDevice[] | null>(null)
  const [key, setKey] = useState('')
  const [here, setHere] = useState<string | null>(null)
  const [state, setState] = useState<PushReadiness>(() => readiness())
  const [naming, setNaming] = useState<{ id: string; name: string } | null>(null)
  const [browserSaid, setBrowserSaid] = useState<string | null>(null)
  /** What the last test notice reached, said in place of the line of the action. */
  const [probed, setProbed] = useState<string | null>(null)
  const action = useAction()
  const probe = useAction()
  const { ask, dialog } = useAsk()

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
        await pushApi.remove(device.id)
        if (device.id === here) await unsubscribe()
        await load()
        void action.run(async () => undefined, t('me.push.removed', { name: device.name }))
      },
    })
  }

  const sendProbe = () => {
    setProbed(null)
    void probe.run(async () => {
      const result = await pushApi.probe()
      const all = result.sent + result.gone + result.failed
      if (result.gone) await load()
      setProbed(result.sent === all ? t('me.push.probed') : t('me.push.probedSome', { sent: result.sent, all }))
    })
  }

  const zone = me.profile.timezone || undefined
  const list = devices ?? []
  const mine = list.find((device) => device.id === here)
  const problem = action.problem === 'push_denied_now' || action.problem === 'push_browser' ? null : action.problem
  const note = (
    <span className="flex flex-col gap-1" data-testid="push-here">
      <span>{action.problem === 'push_denied_now' ? t('me.push.deniedNow') : mine ? t('me.push.text') : t(`me.push.${state}`)}</span>
      {!mine && (
        <>
          <span>{t('me.push.hintHttps')}</span>
          <span>{t('me.push.hintIphone')}</span>
        </>
      )}
      {browserSaid && <span className="text-[var(--nexui-danger)]">{browserSaid}</span>}
    </span>
  )
  return (
    <>
      <NotifyWays
        mail={me.email ? { address: me.email, confirmed: me.email_confirmed, onChange: () => navigate('/settings/profile') } : undefined}
        browser={
          devices
            ? {
                on: Boolean(mine),
                onTurnOn: enable,
                onTurnOff: () => mine && remove(mine),
                onProbe: sendProbe,
                busy: action.busy,
                probing: probe.busy,
                disabled: state !== 'ready' || !key,
                note,
              }
            : undefined
        }
        browsers={{
          items: list.map((device) => ({
            id: device.id,
            name: device.name,
            current: device.id === here,
            detail: (
              <span className="inline-flex items-center gap-1.5">
                {device.phone ? <Smartphone size={12} aria-hidden /> : <Laptop size={12} aria-hidden />}
                {t('me.push.since', { date: dayOfMoment(device.since, i18n.language, zone) })}
                {device.last && ` · ${t('me.push.last', { date: dayOfMoment(device.last, i18n.language, zone) })}`}
              </span>
            ),
            action: (
              <Button kind="secondary" size="sm" icon="Pencil" onClick={() => setNaming({ id: device.id, name: device.name })} aria-label={`${t('me.push.rename')}: ${device.name}`} testId={`push-rename-${device.id}`}>
                {t('me.push.rename')}
              </Button>
            ),
          })),
          onRemove: (id) => {
            const device = list.find((entry) => entry.id === id)
            if (device) remove(device)
          },
          busy: action.busy,
        }}
        devices={{ onOpen: () => navigate('/settings/connections') }}
      >
        {/* A test notice reaches every device of the person, also while this browser has none. */}
        {devices && !mine && list.length > 0 && (
          <Box
            title={t('me.push.probe')}
            hint={t('me.push.probeHint')}
            testId="push-probe-all"
            actions={
              <Button kind="secondary" icon="Send" busy={probe.busy} onClick={sendProbe} testId="push-probe">
                {t('me.push.probe')}
              </Button>
            }
          />
        )}
        <Outcome problem={problem ?? probe.problem} done={probed ?? action.done} values={problem ? action.values : probe.values} />
      </NotifyWays>
      {naming && (
        <ConfirmDialog
          title={t('me.push.rename')}
          confirm={{ label: t('common.save'), kind: 'primary', icon: 'Check' }}
          cancel={t('common.cancel')}
          closeLabel={t('common.close')}
          busy={action.busy}
          confirmDisabled={!naming.name.trim()}
          onCancel={() => setNaming(null)}
          onConfirm={() =>
            void action.run(async () => {
              await pushApi.rename(naming.id, naming.name.trim())
              setNaming(null)
              await load()
            }, t('me.push.renamed'))
          }
        >
          <Field label={t('me.push.name')} value={naming.name} onChange={(event) => setNaming({ ...naming, name: event.target.value })} autoFocus maxLength={80} />
        </ConfirmDialog>
      )}
      {dialog}
    </>
  )
}
