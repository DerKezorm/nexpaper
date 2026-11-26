/**
 * "Geräte", the first card under My account › Connections (plan "Einstellungen", Verbindungen 1, E4), as nexnotes' card: every paired device and app with its
 * name, how it was paired and its last use, and a small "Trennen" after a question (its token stops at once). "iPhone
 * oder iPad verbinden" opens the code in a dialog: a QR code and the same for typing, valid for five minutes and once. The device trades it
 * for a token of its own (`POST /api/v1/devices/pair`); the dialog asks the server now and then whether that happened,
 * closes itself then and the new device stands in the list. Apps that sign in through the browser (OAuth with PKCE)
 * need no code here, and appear in the list all the same.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { authApi, devicesApi, pairingApi, type PairedDevice, type PairingCode } from '../api/client'
import { ago } from '../lib/ago'
import { useAction } from '../pages/settings/actions'
import { Outcome } from '../pages/settings/Outcome'
import { useAsk } from '../pages/settings/useAsk'
import { KeysWait } from './KeysWait'
import { iso } from '../lib/say'
import { Button, Card, CopyRow, Dialog, Row, Rows } from '../vendor/nexui'

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
  const action = useAction()
  const { ask, dialog } = useAsk()

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
    <Card id="devices" icon="Smartphone" title={t('pairing.title')} subtitle={t('pairing.text')}>
      <KeysWait />
      {devices && devices.length === 0 && (
        <p className="m-0 text-sm text-[var(--nexui-text-muted)]" data-testid="devices-none">
          {t('pairing.none')}
        </p>
      )}
      {devices && devices.length > 0 && (
        <Rows label={t('pairing.title')} testId="devices-list">
          {devices.map((device) => (
            <Row
              key={device.id}
              icon="Smartphone"
              name={device.name}
              sub={t('phone.devices.meta', { how: how(device), when: device.last_used_at ? ago(device.last_used_at, i18n.language, t('me.justNow')) : t('phone.devices.never') })}
              testId="paired-device"
              action={
                <Button
                  kind="danger"
                  size="sm"
                  icon="Unplug"
                  busy={action.busy}
                  aria-label={t('pairing.disconnectNamed', { name: device.name })}
                  onClick={() =>
                    ask({
                      title: t('phone.devices.revokeTitle', { name: iso(device.name) }),
                      text: t('phone.devices.revokeText'),
                      confirm: t('pairing.disconnect'),
                      icon: 'Unplug',
                      run: async () => {
                        await devicesApi.revoke(device.id)
                        load()
                        void action.run(async () => undefined, t('phone.devices.revoked', { name: device.name }))
                      },
                    })
                  }
                >
                  {t('pairing.disconnect')}
                </Button>
              }
            />
          ))}
        </Rows>
      )}
      <div>
        <Button kind="primary" icon="Smartphone" onClick={() => setPairing(true)} testId="pair">
          {t('pairing.connect')}
        </Button>
      </div>
      {provider && <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t('phone.pair.provider', { name: provider })}</p>}
      <Outcome problem={action.problem} done={action.done} />
      {pairing && (
        <PairDialog
          onDone={(paired) => {
            setPairing(false)
            load()
            if (paired) void action.run(async () => undefined, t('phone.pair.paired'))
          }}
        />
      )}
      {dialog}
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
    // It shows a code once and asks the server meanwhile: only "Schließen" ends it (ui `dismissable`, E38).
    <Dialog title={t('pairing.dialogTitle')} onClose={close} closeLabel={t('common.close')} wide dismissable={false}>
      <div className="flex flex-wrap gap-6" data-testid="pairing-dialog">
        <div className="flex w-[11rem] flex-none flex-col items-center gap-2">
          <div className="flex h-44 w-44 items-center justify-center rounded-[12px] bg-white p-2">
            {shown && <img src={'data:image/svg+xml;utf8,' + encodeURIComponent(shown.qr_svg)} alt={t('phone.pair.qr')} className="h-full w-full" />}
            {expired && <p className="px-2 text-center text-sm text-[#222]">{t('phone.pair.expired')}</p>}
          </div>
          {shown && <span className="text-xs text-[var(--nexui-text-muted)]">{t('phone.pair.left', { time: left(shown.expires_at, now) })}</span>}
        </div>
        <div className="flex min-w-[14rem] flex-1 flex-col gap-3 text-sm">
          {shown && (
            <div className="flex flex-col gap-2" data-testid="pairing-code">
              <p className="m-0">{t('phone.pair.scan')}</p>
              <p className="m-0 text-[var(--nexui-text-muted)]">{t('phone.pair.byHand')}</p>
              <span className="text-xs text-[var(--nexui-text-muted)]">{t('phone.pair.address')}</span>
              <CopyRow label={t('phone.pair.address')} value={shown.server} testId="pairing-server" />
              <span className="text-xs text-[var(--nexui-text-muted)]">{t('phone.pair.code')}</span>
              <CopyRow label={t('phone.pair.code')} value={shown.code} testId="pairing-text" />
            </div>
          )}
          {expired && (
            <div>
              <Button kind="primary" icon="RefreshCw" busy={action.busy} onClick={make}>
                {t('phone.pair.newCode')}
              </Button>
            </div>
          )}
          <Outcome problem={action.problem} />
          <div className="mt-auto flex justify-end">
            <Button kind="secondary" icon="Check" onClick={close}>
              {t('common.close')}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}
