/**
 * My account › Connections, first card: "Geräte" (Smartphone, `id="devices"`). Every connected iPhone, iPad and Mac
 * with its symbol, its name, the line "iPhone 15 · App 1.0.2 · zuletzt heute, 14:05" (or "über iCloud übernommen"),
 * a badge "Mitteilungen an/aus", `sm` "Umbenennen" and `sm` danger "Trennen" (with a question first). Below: primary
 * "iPhone oder iPad verbinden" (the pairing window) and, from two devices on, danger "Alle Geräte trennen" (with a
 * question). Without devices: "Noch kein Gerät verbunden." While the app has no iPhone app (`has_app` false) the card
 * shows nothing. Built only from the ui kit.
 *
 * Copied unchanged into frontend/src/vendor/nexgeraete/ by bauplaene/geraete/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Badge, Box, Button, Buttons, Card, ConfirmDialog, Notice, Row, Rows, useNexuiTexts } from '../nexui'
import { useDeviceTexts } from './hooks'
import { PairDialog } from './PairDialog'
import { RenameDialog } from './RenameDialog'
import {
  BUTTONS,
  DEVICES_BASE,
  asListing,
  countText,
  deviceLine,
  fillDevices,
  kindIcon,
  refusalCode,
  refusalText,
  type Device,
  type DeviceListing,
  type DeviceRequest,
  type WhenFormat,
} from './geraete'

export type DevicesCardProps = {
  /** The app's client (its headers, its errors). */
  request: DeviceRequest
  /** Where the module's browser routes are mounted. */
  base?: string
  /** The app's name ("nexnotes"). */
  app: string
  language?: string
  /** How a moment is written; default E65 ("heute, 14:05"). */
  when?: WhenFormat
  /** The account is an operator: when the app or new devices are switched off, the pairing window says where they are
   * switched on (Server › Verbindungen). */
  operator?: boolean
  /** The app's way to Server › Verbindungen, for that hint (no fixed path in the module). */
  serverHref?: string
  /** The app's own parts at the end of the card. */
  children?: ReactNode
  testId?: string
}

export function DevicesCard({ request, base = DEVICES_BASE, app, language, when, operator = false, serverHref, children, testId = 'devices-card' }: DevicesCardProps) {
  const { texts, code } = useDeviceTexts(language)
  const kit = useNexuiTexts()
  const [listing, setListing] = useState<DeviceListing | null>(null)
  const [problem, setProblem] = useState<string>()
  const [pairing, setPairing] = useState(false)
  const [renaming, setRenaming] = useState<Device | null>(null)
  const [leaving, setLeaving] = useState<Device | null>(null)
  const [leavingAll, setLeavingAll] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [fresh, setFresh] = useState<string[]>([])
  const [round, setRound] = useState(0)

  const load = useCallback(() => request<unknown>(`${base}/app-devices`).then(asListing), [request, base])
  useEffect(() => {
    load().then(setListing, (failure: unknown) => setProblem(refusalText(texts, failure)))
  }, [load, round, texts])
  const reload = () => setRound((value) => value + 1)

  const disconnect = async () => {
    if (!leaving) return
    setBusy(true)
    setError(undefined)
    try {
      await request(`${base}/app-devices/${encodeURIComponent(String(leaving.id))}`, { method: 'DELETE' })
      setLeaving(null)
      reload()
    } catch (failure) {
      if (refusalCode(failure).code === 'not_found') {
        setLeaving(null)
        setProblem(refusalText(texts, failure))
        reload()
      } else setError(refusalText(texts, failure))
    } finally {
      setBusy(false)
    }
  }

  const disconnectAll = async () => {
    setBusy(true)
    setError(undefined)
    try {
      await request<{ removed: number }>(`${base}/app-devices`, { method: 'DELETE' })
      setLeavingAll(false)
      reload()
    } catch (failure) {
      setError(refusalText(texts, failure))
    } finally {
      setBusy(false)
    }
  }

  if (listing && !listing.has_app) return null
  const devices = listing?.devices ?? []
  const full = listing !== null && devices.length >= listing.max
  return (
    <Card id="devices" icon="Smartphone" title={texts.devices.title} subtitle={fillDevices(texts.devices.hint, { app })} testId={testId}>
      {problem && (
        <Notice tone="danger" testId="devices-problem">
          {problem}
        </Notice>
      )}
      {listing && devices.length === 0 && (
        <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]" data-testid="devices-none">
          {texts.devices.none}
        </p>
      )}
      {devices.length > 0 && (
        <Box title={countText(texts, devices.length)} testId="devices-box">
          <Rows label={texts.devices.title} testId="devices-list">
            {devices.map((device) => (
              <Row
                key={String(device.id)}
                icon={kindIcon(device.kind)}
                name={<span data-testid="device-name">{device.name}</span>}
                badge={
                  <>
                    {fresh.includes(String(device.id)) && (
                      <Badge tone="accent" testId="device-new">
                        {texts.devices.new}
                      </Badge>
                    )}
                    <Badge tone={device.push ? 'on' : 'off'} testId="device-push">
                      {device.push ? texts.devices.pushOn : texts.devices.pushOff}
                    </Badge>
                  </>
                }
                sub={<span data-testid="device-line">{deviceLine(device, texts, code, when)}</span>}
                action={
                  <span className="flex flex-wrap items-center gap-2">
                    <Button
                      kind={BUTTONS.rename.kind}
                      icon={BUTTONS.rename.icon}
                      size="sm"
                      onClick={() => setRenaming(device)}
                      aria-label={fillDevices(texts.devices.renameName, { name: device.name })}
                      testId="device-rename"
                    >
                      {texts.devices.rename}
                    </Button>
                    <Button
                      kind={BUTTONS.disconnect.kind}
                      icon={BUTTONS.disconnect.icon}
                      size="sm"
                      onClick={() => {
                        setError(undefined)
                        setLeaving(device)
                      }}
                      aria-label={fillDevices(texts.devices.disconnectName, { name: device.name })}
                      testId="device-disconnect"
                    >
                      {texts.devices.disconnect}
                    </Button>
                  </span>
                }
                testId="device-row"
              />
            ))}
          </Rows>
        </Box>
      )}
      {listing && full && (
        <Notice tone="warn" testId="devices-full">
          {fillDevices(texts.devices.full, { max: listing.max })}
        </Notice>
      )}
      {listing && (
        <Buttons>
          <Button
            kind={BUTTONS.connect.kind}
            icon={BUTTONS.connect.icon}
            disabled={full}
            onClick={() => {
              setProblem(undefined)
              setPairing(true)
            }}
            testId="devices-connect"
          >
            {texts.devices.connect}
          </Button>
          {devices.length >= 2 && (
            <Button
              kind={BUTTONS.disconnectAll.kind}
              icon={BUTTONS.disconnectAll.icon}
              onClick={() => {
                setError(undefined)
                setLeavingAll(true)
              }}
              testId="devices-disconnect-all"
            >
              {texts.devices.disconnectAll}
            </Button>
          )}
        </Buttons>
      )}
      {children}
      {pairing && (
        <PairDialog
          request={request}
          base={base}
          app={app}
          language={language}
          operator={operator}
          serverHref={serverHref}
          onPaired={(device) => {
            if (device) setFresh((before) => [...before, String(device.id)])
            reload()
          }}
          onClose={() => {
            setPairing(false)
            reload()
          }}
        />
      )}
      {renaming && (
        <RenameDialog
          request={request}
          base={base}
          device={renaming}
          language={language}
          onClose={() => setRenaming(null)}
          onRenamed={() => {
            setRenaming(null)
            reload()
          }}
        />
      )}
      {leaving && (
        <ConfirmDialog
          title={fillDevices(texts.devices.askDisconnect, { name: leaving.name })}
          text={texts.devices.askDisconnectText}
          confirm={{ label: texts.devices.disconnect, kind: BUTTONS.disconnect.kind, icon: BUTTONS.disconnect.icon }}
          cancel={texts.devices.cancel}
          closeLabel={kit.close}
          busy={busy}
          error={error}
          onCancel={() => setLeaving(null)}
          onConfirm={() => void disconnect()}
          testId="device-disconnect-dialog"
        />
      )}
      {leavingAll && (
        <ConfirmDialog
          title={fillDevices(texts.devices.askAll, { count: devices.length })}
          text={texts.devices.askAllText}
          confirm={{ label: texts.devices.all, kind: BUTTONS.disconnectAll.kind, icon: BUTTONS.disconnectAll.icon }}
          cancel={texts.devices.cancel}
          closeLabel={kit.close}
          busy={busy}
          error={error}
          onCancel={() => setLeavingAll(false)}
          onConfirm={() => void disconnectAll()}
          testId="devices-disconnect-all-dialog"
        />
      )}
    </Card>
  )
}
