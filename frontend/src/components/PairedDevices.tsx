/**
 * "Geräte", under My account, Connections, as nexnotes' card of the same name: every paired device and app with its
 * name, how it was paired and its last use, and "Trennen" after a question (its token stops at once). "Gerät koppeln"
 * opens the code in a dialog: a QR code and the same for typing, valid for five minutes and once. The device trades it
 * for a token of its own (`POST /api/v1/devices/pair`); the dialog asks the server now and then whether that happened,
 * closes itself then and the new device stands in the list. Apps that sign in through the browser (OAuth with PKCE)
 * need no code here, and appear in the list all the same.
 */
import { Smartphone } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { authApi, devicesApi, pairingApi, type PairedDevice, type PairingCode } from '../api/client'
import { ago } from '../lib/ago'
import { Button, Card, Confirm, Feedback, useAction } from '../pages/settings/ui'
import { Dialog } from './Dialog'

/** How often the dialog asks whether the code was used. */
const POLL_MS = 2000

function left(expires: string, now: number): string {
  const seconds = Math.max(0, Math.round((new Date(expires).getTime() - now) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export function PairedDevices() {
  const { t, i18n } = useTranslation()
  const [devices, setDevices] = useState<PairedDevice[] | null>(null)
  const [provider, setProvider] = useState<string | null>(null)
  const [pairing, setPairing] = useState(false)
  const [leaving, setLeaving] = useState<PairedDevice | null>(null)
  const action = useAction()

  const load = useCallback(() => {
    devicesApi.list().then((found) => setDevices(Array.isArray(found) ? found : []), () => setDevices([]))
  }, [])
  useEffect(load, [load])
  useEffect(() => {
    authApi.methods().then((found) => setProvider(found.providers.map((entry) => entry.label).join(', ') || null), () => undefined)
  }, [])

  const how = (device: PairedDevice) =>
    t(device.via === 'qr' ? 'phone.devices.qr' : device.via === 'device' ? 'phone.devices.device' : device.via?.startsWith('app:') ? 'phone.devices.app' : 'phone.devices.token')

  return (
    <Card id="devices" icon={Smartphone} title={t('pairing.title')} text={t('pairing.text')}>
      {devices && devices.length === 0 && (
        <p className="text-sm text-muted" data-testid="devices-none">
          {t('pairing.none')}
        </p>
      )}
      {devices && devices.length > 0 && (
        <ul className="flex flex-col" data-testid="devices-list">
          {devices.map((device) => (
            <li key={device.id} className="flex items-center gap-3 border-b border-line py-2.5 last:border-0" data-testid="paired-device">
              <Smartphone className="h-5 w-5 shrink-0 text-ink-2" strokeWidth={1.8} aria-hidden />
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate text-sm">{device.name}</span>
                <span className="text-xs text-muted">
                  {t('phone.devices.meta', { how: how(device), when: device.last_used_at ? ago(device.last_used_at, i18n.language, t('me.justNow')) : t('phone.devices.never') })}
                </span>
              </span>
              <Button busy={action.busy} onClick={() => setLeaving(device)} label={t('pairing.disconnectNamed', { name: device.name })}>
                {t('pairing.disconnect')}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div>
        <Button primary onClick={() => setPairing(true)}>
          {t('pairing.connect')}
        </Button>
      </div>
      {provider && <p className="text-xs text-muted">{t('phone.pair.provider', { name: provider })}</p>}
      <Feedback problem={action.problem} done={action.done} />
      {pairing && (
        <PairDialog
          onDone={(paired) => {
            setPairing(false)
            load()
            if (paired) void action.run(async () => undefined, t('phone.pair.paired'))
          }}
        />
      )}
      {leaving && (
        <Confirm
          title={t('phone.devices.revokeTitle', { name: leaving.name })}
          text={t('phone.devices.revokeText')}
          confirm={t('pairing.disconnect')}
          danger
          onCancel={() => setLeaving(null)}
          onConfirm={async () => {
            const name = leaving.name
            await action.run(async () => {
              await devicesApi.revoke(leaving.id)
              load()
            }, t('phone.devices.revoked', { name }))
            setLeaving(null)
          }}
        />
      )}
    </Card>
  )
}

/**
 * The code to pair a device, as nexnotes' "iPhone oder iPad verbinden": a code is made when the dialog opens, shown as a
 * QR code and for typing, with the time it still holds. A code that ran out says so and is made anew with one click;
 * closing the dialog withdraws a code nobody used.
 */
function PairDialog({ onDone }: { onDone: (paired: boolean) => void }) {
  const { t } = useTranslation()
  const [shown, setShown] = useState<PairingCode | null>(null)
  const [expired, setExpired] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const action = useAction()
  // The latest way out, kept apart from the timer: the page around may draw anew without the asking starting over.
  const done = useRef(onDone)
  useEffect(() => {
    done.current = onDone
  })

  const { run } = action
  const make = useCallback(
    () =>
      void run(async () => {
        const code = await pairingApi.start()
        setExpired(false)
        setNow(Date.now())
        setShown(code)
      }),
    [run],
  )
  useEffect(make, [make])

  // While a code is shown: is it used, has it run out?
  useEffect(() => {
    if (!shown) return
    const timer = window.setInterval(() => {
      setNow(Date.now())
      pairingApi.state().then(
        (state) => {
          if (state.state === 'used') {
            setShown(null)
            done.current(true)
          } else if (state.state === 'expired' || state.state === 'none') {
            setShown(null)
            setExpired(true)
          }
        },
        () => undefined,
      )
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [shown])

  const close = () => {
    if (shown) void pairingApi.cancel().catch(() => undefined)
    onDone(false)
  }

  return (
    <Dialog title={t('pairing.dialogTitle')} onClose={close} medium>
      <div className="flex flex-wrap gap-6" data-testid="pairing-dialog">
        <div className="flex w-[11rem] flex-none flex-col items-center gap-2">
          <div className="flex h-44 w-44 items-center justify-center rounded-[12px] bg-white p-2">
            {shown && <img src={'data:image/svg+xml;utf8,' + encodeURIComponent(shown.qr_svg)} alt={t('phone.pair.qr')} className="h-full w-full" />}
            {expired && <p className="px-2 text-center text-sm text-[#222]">{t('phone.pair.expired')}</p>}
          </div>
          {shown && <span className="text-xs text-muted">{t('phone.pair.left', { time: left(shown.expires_at, now) })}</span>}
        </div>
        <div className="flex min-w-[14rem] flex-1 flex-col gap-3 text-sm text-ink-2">
          {shown && (
            <div className="space-y-2" data-testid="pairing-code">
              <p>{t('phone.pair.scan')}</p>
              <p className="rounded-[10px] border border-line bg-sheet-2/50 px-3 py-2.5">
                {t('phone.pair.byHand')} {t('phone.pair.address')} <span className="font-mono break-all text-ink">{shown.server}</span>, {t('phone.pair.code')}{' '}
                <span className="font-mono text-ink" data-testid="pairing-text">
                  {shown.code}
                </span>
              </p>
            </div>
          )}
          {expired && (
            <div>
              <Button primary busy={action.busy} onClick={make}>
                {t('phone.pair.newCode')}
              </Button>
            </div>
          )}
          <Feedback problem={action.problem} />
          <div className="mt-auto flex justify-end">
            <Button onClick={close}>{t('common.close')}</Button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}
