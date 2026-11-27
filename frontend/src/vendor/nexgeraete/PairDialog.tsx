/**
 * "iPhone oder iPad verbinden": `POST <base>/app-pairing` makes a code for one device; the window shows it as a QR
 * picture with three steps, the time left ("Gilt noch 9:41 Minuten, für ein Gerät."), the link into the App Store
 * where the app has one, and for a device without a camera the address and the code to type in. It asks
 * `GET <base>/app-pairing/{id}` every two seconds: once a device took the code it says "<device> ist verbunden" with
 * "Fertig"; a code that ran out says so, with "Neuen Code zeigen". "Abbrechen", the close button and Escape withdraw
 * a code nobody used (`DELETE`); closing stops the asking. Built only from the ui kit.
 *
 * Copied unchanged into frontend/src/vendor/nexgeraete/ by bauplaene/geraete/tools/sync.py; changed only there.
 */
import { useEffect, useRef, useState } from 'react'

import { Box, Button, Buttons, Dialog, Facts, Notice, TextLink, useNexuiTexts } from '../nexui'
import { useDeviceTexts } from './hooks'
import {
  BUTTONS,
  DEVICES_BASE,
  POLL_MS,
  asPairing,
  asPairingState,
  fillDevices,
  hostOf,
  kindLabel,
  qrSource,
  refusalCode,
  refusalText,
  remaining,
  type Device,
  type DeviceRequest,
  type Pairing,
} from './geraete'

export type PairDialogProps = {
  request: DeviceRequest
  base?: string
  /** The app's name ("nexnotes"). */
  app: string
  language?: string
  /** The window closes: after "Fertig" with the new device, else without. */
  onClose: (device?: Device) => void
  /** A device took the code (the list may reload at once). */
  onPaired?: (device: Device | null) => void
  /** An operator reads where the app and new devices are switched on (Server › Verbindungen) when they are off. */
  operator?: boolean
  /** The app's way to Server › Verbindungen, for that hint. */
  serverHref?: string
  testId?: string
}

/** The refusals an operator can lift under Server › Verbindungen. */
const SWITCHED_OFF = ['app_disabled', 'app_pairing_disabled']

type Phase = 'waiting' | 'used' | 'expired'

export function PairDialog({ request, base = DEVICES_BASE, app, language, onClose, onPaired, operator = false, serverHref, testId = 'pair-dialog' }: PairDialogProps) {
  const { texts } = useDeviceTexts(language)
  const kit = useNexuiTexts()
  const [pairing, setPairing] = useState<Pairing | null>(null)
  const [phase, setPhase] = useState<Phase>('waiting')
  const [device, setDevice] = useState<Device | null>(null)
  const [problem, setProblem] = useState<string>()
  const [switchedOff, setSwitchedOff] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const [round, setRound] = useState(0)
  const current = useRef<Pairing | null>(null)
  const taken = useRef(false)
  const paired = useRef(onPaired)
  useEffect(() => {
    paired.current = onPaired
  }, [onPaired])

  const withdraw = (found: Pairing | null) => {
    if (found && !taken.current) void request(`${base}/app-pairing/${encodeURIComponent(found.id)}`, { method: 'DELETE' }).catch(() => undefined)
  }

  // A new code on opening and on "Neuen Code zeigen"; one that comes back after the window closed is withdrawn.
  useEffect(() => {
    let live = true
    request<unknown>(`${base}/app-pairing`, { method: 'POST', body: { address: window.location.origin } }).then(asPairing).then(
      (made) => {
        if (!live) {
          void request(`${base}/app-pairing/${encodeURIComponent(made.id)}`, { method: 'DELETE' }).catch(() => undefined)
          return
        }
        current.current = made
        setPairing(made)
        setPhase('waiting')
        setNow(Date.now())
      },
      (failure: unknown) => {
        if (!live) return
        setProblem(refusalText(texts, failure))
        setSwitchedOff(SWITCHED_OFF.includes(refusalCode(failure).code ?? ''))
      },
    )
    return () => {
      live = false
    }
  }, [request, base, texts, round])

  // While it waits: the time left every second, the server every two.
  useEffect(() => {
    if (!pairing || phase !== 'waiting') return
    const clock = window.setInterval(() => setNow(Date.now()), 1000)
    const ask = window.setInterval(() => {
      request<unknown>(`${base}/app-pairing/${encodeURIComponent(pairing.id)}`).then(asPairingState).then(
        (found) => {
          if (current.current?.id !== pairing.id) return
          if (found.state === 'used') {
            taken.current = true
            setDevice(found.device)
            setPhase('used')
            paired.current?.(found.device)
          } else if (found.state === 'expired') setPhase('expired')
        },
        () => undefined,
      )
    }, POLL_MS)
    return () => {
      window.clearInterval(clock)
      window.clearInterval(ask)
    }
  }, [pairing, phase, request, base])

  const close = () => {
    withdraw(current.current)
    onClose()
  }

  const renew = () => {
    withdraw(current.current)
    current.current = null
    setPairing(null)
    setProblem(undefined)
    setSwitchedOff(false)
    setRound((value) => value + 1)
  }

  if (phase === 'used') {
    const name = device?.name || (device ? kindLabel(texts, device.kind) : kindLabel(texts, 'ios'))
    return (
      <Dialog title={fillDevices(texts.pair.paired, { name })} onClose={() => onClose(device ?? undefined)} closeLabel={kit.close} testId={testId}>
        <div className="flex flex-col gap-4" data-testid="pair-paired">
          <p className="m-0 text-sm leading-5 text-[var(--nexui-text)]">{texts.pair.pairedText}</p>
          <Buttons end>
            <Button kind={BUTTONS.done.kind} icon={BUTTONS.done.icon} onClick={() => onClose(device ?? undefined)} testId="pair-done">
              {texts.pair.done}
            </Button>
          </Buttons>
        </div>
      </Dialog>
    )
  }

  const expired = phase === 'expired' || (pairing !== null && Date.parse(pairing.expires_at) <= now)
  const storeUrl = pairing?.app_store_url
  return (
    <Dialog title={texts.pair.title} onClose={close} closeLabel={kit.close} wide testId={testId}>
      <div className="flex flex-col gap-4" data-state={expired ? 'expired' : pairing ? 'waiting' : 'loading'} data-testid="pair-body">
        <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]">{fillDevices(texts.pair.intro, { app })}</p>
        <div className="flex flex-wrap gap-6">
          <div className="flex w-[220px] flex-none flex-col items-center gap-2">
            <div className="h-[220px] w-[220px] rounded-[12px] border border-solid border-[var(--nexui-line)] bg-white p-3.5">
              {pairing && !expired && <img src={qrSource(pairing.qr_svg)} alt={texts.pair.qr} className="block h-full w-full" data-testid="pair-qr" />}
              {expired && (
                <p className="m-0 flex h-full items-center justify-center text-center text-sm leading-5 text-[#14141a]" data-testid="pair-expired">
                  {texts.pair.expired}
                </p>
              )}
            </div>
            {pairing && !expired && (
              <span className="text-center text-xs leading-4 text-[var(--nexui-text-muted)]" role="timer" data-testid="pair-valid">
                {fillDevices(texts.pair.valid, { time: remaining(pairing.expires_at, now) })}
              </span>
            )}
            {expired && (
              <Button kind={BUTTONS.renew.kind} icon={BUTTONS.renew.icon} size="sm" onClick={renew} testId="pair-renew">
                {texts.pair.renew}
              </Button>
            )}
          </div>
          <div className="flex min-w-[240px] flex-1 flex-col gap-3">
            <ol className="m-0 flex list-decimal flex-col gap-1 pl-5 text-sm leading-5 text-[var(--nexui-text)]" data-testid="pair-steps">
              <li>{fillDevices(texts.pair.step1, { app })}</li>
              <li>{texts.pair.step2}</li>
              <li>{texts.pair.step3}</li>
            </ol>
            {storeUrl && (
              <Buttons>
                <Button kind={BUTTONS.store.kind} icon={BUTTONS.store.icon} size="sm" href={storeUrl} testId="pair-store">
                  {fillDevices(texts.pair.store, { app })}
                </Button>
              </Buttons>
            )}
          </div>
        </div>
        {pairing && !expired && (
          <Box title={texts.pair.noCamera} testId="pair-code-box">
            <Facts
              items={[
                { label: texts.pair.address, value: hostOf(pairing.address), testId: 'pair-address' },
                { label: texts.pair.code, value: <span className="font-mono tracking-wider">{pairing.code}</span>, testId: 'pair-code' },
              ]}
            />
          </Box>
        )}
        {problem && (
          <Notice tone="danger" testId="pair-problem">
            {problem}
            {operator && switchedOff && (
              <span className="mt-1 block text-[var(--nexui-text)]" data-testid="pair-operator-hint">
                {texts.pair.operatorOff}
                {serverHref !== undefined && (
                  <>
                    {' '}
                    <TextLink href={serverHref} testId="pair-to-server">
                      {texts.pair.toServer}
                    </TextLink>
                  </>
                )}
              </span>
            )}
          </Notice>
        )}
        <Buttons end>
          <Button kind={BUTTONS.cancel.kind} icon={BUTTONS.cancel.icon} onClick={close} testId="pair-cancel">
            {texts.pair.cancel}
          </Button>
        </Buttons>
      </div>
    </Dialog>
  )
}
