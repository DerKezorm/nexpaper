/**
 * "Gerät koppeln", under My account, Devices and apps: a code shown as a QR code and for typing, valid for
 * five minutes and once. The device trades it for a token of its own (`POST /api/v1/devices/pair`); this page asks the
 * server now and then whether that happened and says so. The paired device then stands with the signed-in devices under
 * Security, where it can be signed out. Apps that sign in through the browser (OAuth with PKCE) need no code here.
 */
import { QrCode } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { authApi, pairingApi, type PairingCode } from '../api/client'
import { Button, Card, Feedback, useAction } from '../pages/settings/ui'

/** How often the page asks whether the code was used. */
const POLL_MS = 2000

function left(expires: string, now: number): string {
  const seconds = Math.max(0, Math.round((new Date(expires).getTime() - now) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export function PairedDevices() {
  const { t } = useTranslation()
  const [shown, setShown] = useState<PairingCode | null>(null)
  const [expired, setExpired] = useState(false)
  const [paired, setPaired] = useState<string | null>(null)
  const [provider, setProvider] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const action = useAction()

  useEffect(() => {
    authApi.methods().then((found) => setProvider(found.providers.map((entry) => entry.label).join(', ') || null), () => undefined)
  }, [])

  // While a code is shown: is it used, has it run out?
  useEffect(() => {
    if (!shown) return
    const timer = window.setInterval(() => {
      setNow(Date.now())
      pairingApi.state().then(
        (state) => {
          if (state.state === 'used') {
            setShown(null)
            setPaired(t('phone.pair.paired'))
          } else if (state.state === 'expired' || state.state === 'none') {
            setShown(null)
            setExpired(true)
          }
        },
        () => undefined,
      )
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [shown, t])

  const start = () =>
    void action.run(async () => {
      const code = await pairingApi.start()
      setExpired(false)
      setPaired(null)
      setNow(Date.now())
      setShown(code)
    })
  const cancel = () => {
    setShown(null)
    void pairingApi.cancel().catch(() => undefined)
  }

  return (
    <Card id="devices" icon={QrCode} title={t('pairing.title')} text={t('pairing.text')}>
      {shown ? (
        <div className="grid gap-5 sm:grid-cols-[10rem_1fr]" data-testid="pairing-code">
          <img src={'data:image/svg+xml;utf8,' + encodeURIComponent(shown.qr_svg)} alt={t('phone.pair.qr')} className="h-40 w-40 rounded-xl bg-white p-1" />
          <div className="space-y-2 text-sm text-ink-2">
            <p>{t('phone.pair.scan')}</p>
            <p>
              {t('phone.pair.byHand')} {t('phone.pair.address')} <span className="font-mono break-all text-ink">{shown.server}</span>, {t('phone.pair.code')}{' '}
              <span className="font-mono text-ink" data-testid="pairing-text">
                {shown.code}
              </span>
            </p>
            <p className="text-xs text-muted">{t('phone.pair.left', { time: left(shown.expires_at, now) })}</p>
            <Button onClick={cancel}>{t('phone.pair.cancel')}</Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <Button primary busy={action.busy} onClick={start}>
            <QrCode size={16} aria-hidden /> {expired ? t('phone.pair.newCode') : t('phone.pair.show')}
          </Button>
          {expired && <span className="text-sm text-warn">{t('phone.pair.expired')}</span>}
        </div>
      )}
      {provider && <p className="text-xs text-muted">{t('phone.pair.provider', { name: provider })}</p>}
      <Feedback problem={action.problem} done={paired} />
    </Card>
  )
}
