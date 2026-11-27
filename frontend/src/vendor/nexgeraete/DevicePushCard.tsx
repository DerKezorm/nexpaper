/**
 * My account › Notifications, after "Auf welchem Weg": the card "Mitteilungen auf deinen Geräten" (BellRing,
 * `id="devices-push"`). One box per device ("Kims iPhone · iPhone 15"), a badge "Mitteilungen erlaubt" or "Keine
 * Mitteilungen angemeldet" (then a line that the ticks apply once the device gets them again), and a `CheckboxRow`
 * per kind the server names for the device (`GET <base>/app-devices/{id}/push-kinds`), marked "nur Betreiber" where only operators
 * get it. A tick is kept at once (`PUT … {<kind>: on}`) with a short "Gespeichert.". Without devices one sentence with
 * the way to Connections. The app's own boxes go after the devices (`children`). Built only from the ui kit.
 *
 * Copied unchanged into frontend/src/vendor/nexgeraete/ by bauplaene/geraete/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Badge, Box, Button, Buttons, Card, CheckboxRow, Notice } from '../nexui'
import { useDeviceTexts } from './hooks'
import { DEVICES_BASE, asListing, asPushKinds, fillDevices, kindLabel, refusalText, type Device, type DeviceRequest, type PushKind } from './geraete'

export type DevicePushCardProps = {
  request: DeviceRequest
  base?: string
  /** The app's name ("nexnotes"). */
  app: string
  language?: string
  /** Where the devices are connected (Mein Konto › Verbindungen), for the sentence without devices. */
  connectionsHref?: string
  /** The app's own boxes at the end of the card. */
  children?: ReactNode
  testId?: string
}

type Loaded = { devices: Device[]; kinds: Record<string, PushKind[] | string> }

export function DevicePushCard({ request, base = DEVICES_BASE, app, language, connectionsHref, children, testId = 'devices-push-card' }: DevicePushCardProps) {
  const { texts } = useDeviceTexts(language)
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [hidden, setHidden] = useState(false)
  const [problem, setProblem] = useState<string>()
  const [busy, setBusy] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [failed, setFailed] = useState<{ device: string; text: string } | null>(null)

  const kindsPath = useCallback((device: Device) => `${base}/app-devices/${encodeURIComponent(String(device.id))}/push-kinds`, [base])

  useEffect(() => {
    let live = true
    request<unknown>(`${base}/app-devices`)
      .then(asListing)
      .then(async (listing) => {
        if (!listing.has_app) {
          if (live) setHidden(true)
          return
        }
        const kinds = await Promise.all(
          listing.devices.map((device) =>
            request<unknown>(kindsPath(device)).then(
              (found): PushKind[] | string => asPushKinds(found).kinds,
              (failure: unknown) => refusalText(texts, failure),
            ),
          ),
        )
        if (live) setLoaded({ devices: listing.devices, kinds: Object.fromEntries(listing.devices.map((device, index) => [String(device.id), kinds[index]!])) })
      })
      .catch((failure: unknown) => {
        if (live) setProblem(refusalText(texts, failure))
      })
    return () => {
      live = false
    }
  }, [request, base, kindsPath, texts])

  const change = async (device: Device, kind: PushKind, on: boolean) => {
    const id = String(device.id)
    setBusy(`${id}:${kind.id}`)
    setSaved(null)
    setFailed(null)
    try {
      const found = asPushKinds(await request<unknown>(kindsPath(device), { method: 'PUT', body: { [kind.id]: on } }))
      setLoaded((before) => (before ? { ...before, kinds: { ...before.kinds, [id]: found.kinds } } : before))
      setSaved(id)
    } catch (failure) {
      setFailed({ device: id, text: refusalText(texts, failure) })
    } finally {
      setBusy(null)
    }
  }

  if (hidden) return null
  return (
    <Card id="devices-push" icon="BellRing" title={texts.push.title} subtitle={texts.push.hint} testId={testId}>
      {problem && (
        <Notice tone="danger" testId="devices-push-problem">
          {problem}
        </Notice>
      )}
      {loaded && loaded.devices.length === 0 && (
        <div className="flex flex-col gap-2" data-testid="devices-push-none">
          <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]">{texts.push.none}</p>
          {connectionsHref !== undefined && (
            <Buttons>
              <Button kind="secondary" size="sm" icon="ArrowRight" href={connectionsHref} testId="devices-push-connections">
                {texts.push.toConnections}
              </Button>
            </Buttons>
          )}
        </div>
      )}
      {loaded?.devices.map((device) => {
        const id = String(device.id)
        const kinds = loaded.kinds[id]
        return (
          <Box
            key={id}
            title={`${device.name} · ${device.model || kindLabel(texts, device.kind)}`}
            badge={
              <Badge tone={device.push ? 'on' : 'warn'} testId="devices-push-state">
                {device.push ? texts.push.allowed : texts.push.systemOff}
              </Badge>
            }
            hint={device.push ? (device.chooses_kinds ? texts.push.inApp : fillDevices(texts.push.inAppLater, { app })) : fillDevices(texts.push.systemOffText, { app })}
            testId="devices-push-device"
          >
            {typeof kinds === 'string' && (
              <Notice tone="danger" testId="devices-push-device-problem">
                {kinds}
              </Notice>
            )}
            {Array.isArray(kinds) && kinds.length === 0 && <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]">{texts.push.noKinds}</p>}
            {Array.isArray(kinds) &&
              kinds.map((kind) => (
                <CheckboxRow
                  key={kind.id}
                  label={kind.title}
                  hint={
                    kind.operator_only || kind.hint ? (
                      <span className="flex flex-wrap items-center gap-1.5">
                        {kind.operator_only && (
                          <Badge tone="accent" testId="devices-push-operator">
                            {texts.push.operatorOnly}
                          </Badge>
                        )}
                        {kind.hint}
                      </span>
                    ) : undefined
                  }
                  checked={kind.on}
                  disabled={busy !== null}
                  onChange={(on) => void change(device, kind, on)}
                  testId={`devices-push-${id}-${kind.id}`}
                />
              ))}
            {failed?.device === id && (
              <p className="m-0 text-xs leading-4 text-[var(--nexui-danger)]" role="alert" data-testid="devices-push-failed">
                {failed.text}
              </p>
            )}
            {saved === id && (
              <p className="m-0 text-xs leading-4 text-[var(--nexui-ok)]" role="status" data-testid="devices-push-saved">
                {texts.push.saved}
              </p>
            )}
          </Box>
        )
      })}
      {children}
    </Card>
  )
}
