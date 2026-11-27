/**
 * The page `/app-connect`: the app opens it in the system's sign-in sheet to connect by address. New form
 * `?state=<random>&challenge=<S256>` (nexnotes, nextime, every new app), old form `?device=<name>` (nextasks, nexlore).
 * Nobody signed in: the app's own sign-in comes in (`signIn`) and leads back here. Signed in: "<app>-App mit deinem
 * Konto verbinden?" with the account (name, username), primary "Verbinden" and "Abbrechen". "Verbinden" asks
 * `POST <base>/app-connect` and goes to the `redirect` it answers (only the app's own scheme); "Abbrechen" tells the
 * app (`<scheme>://connected?error=cancelled&state=…`; the old form goes home). Nothing happens without the click.
 * Built only from the ui kit.
 *
 * Copied unchanged into frontend/src/vendor/nexgeraete/ by bauplaene/geraete/tools/sync.py; changed only there.
 */
import { useState, type ReactNode } from 'react'

import { AuthCard, Button, Facts, Notice } from '../nexui'
import { useDeviceTexts } from './hooks'
import { BUTTONS, DEVICES_BASE, cancelLink, connectAsk, fillDevices, refusalText, type DeviceRequest } from './geraete'

/** The signed-in account as the page names it. */
export type ConnectAccount = { name: string; login: string }

export type AppConnectPageProps = {
  request: DeviceRequest
  base?: string
  /** The app's name ("nexnotes"). */
  app: string
  /** The app's link scheme ("nexnotes"); a `redirect` elsewhere is refused. */
  scheme: string
  /** The signed-in account; `null` while nobody is signed in. */
  account: ConnectAccount | null
  /** The app's sign-in, shown while nobody is signed in (it comes back to this page). */
  signIn?: ReactNode
  language?: string
  /** The query of the page; default `window.location.search`. */
  search?: string
  /** How the page leaves for the app; default `window.location.assign`. */
  go?: (url: string) => void
  /** The app's frame around the card; default centred on the page. */
  frame?: (card: ReactNode) => ReactNode
  testId?: string
}

function centred(card: ReactNode): ReactNode {
  return <div className="grid min-h-dvh place-items-center p-4">{card}</div>
}

function leave(url: string): void {
  window.location.assign(url)
}

export function AppConnectPage({ request, base = DEVICES_BASE, app, scheme, account, signIn, language, search, go = leave, frame = centred, testId = 'app-connect' }: AppConnectPageProps) {
  const { texts } = useDeviceTexts(language)
  const [ask] = useState(() => connectAsk(search ?? window.location.search))
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string>()
  const [link, setLink] = useState<string | null>(null)
  const [cancelled, setCancelled] = useState(false)

  if (ask.form === 'invalid') {
    return frame(
      <div data-testid={testId} data-state="invalid">
        <AuthCard title={fillDevices(texts.connect.invalidTitle, { app })}>
          <Notice tone="warn" testId="app-connect-invalid">
            {fillDevices(texts.connect.invalid, { app })}
          </Notice>
        </AuthCard>
      </div>,
    )
  }
  if (!account) return <>{signIn ?? null}</>

  const connect = async () => {
    setBusy(true)
    setProblem(undefined)
    try {
      const body = ask.form === 'state' ? { state: ask.state, ...(ask.challenge ? { challenge: ask.challenge } : {}) } : { device: ask.device }
      const { redirect } = await request<{ redirect: string }>(`${base}/app-connect`, { method: 'POST', body })
      // Only the app's own scheme: the page never sends anyone elsewhere.
      if (typeof redirect !== 'string' || !redirect.startsWith(`${scheme}://`)) throw new Error('foreign redirect')
      setLink(redirect)
      go(redirect)
    } catch (failure) {
      setProblem(refusalText(texts, failure))
    } finally {
      setBusy(false)
    }
  }

  const cancel = () => {
    setCancelled(true)
    go(ask.form === 'state' ? cancelLink(scheme, ask.state) : '/')
  }

  if (link) {
    return frame(
      <div data-testid={testId} data-state="done">
        <AuthCard title={texts.connect.doneTitle} subtitle={texts.connect.done}>
          <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]">{texts.connect.notOpened}</p>
          <Button kind={BUTTONS.again.kind} icon={BUTTONS.again.icon} href={link} wide testId="app-connect-again">
            {texts.connect.again}
          </Button>
        </AuthCard>
      </div>,
    )
  }
  if (cancelled) {
    return frame(
      <div data-testid={testId} data-state="cancelled">
        <AuthCard title={fillDevices(texts.connect.invalidTitle, { app })}>
          <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]" role="status">
            {texts.connect.cancelled}
          </p>
        </AuthCard>
      </div>,
    )
  }

  const title = ask.form === 'device' && ask.device ? fillDevices(texts.connect.titleNamed, { device: ask.device }) : fillDevices(texts.connect.title, { app })
  return frame(
    <div data-testid={testId} data-state="ask" data-form={ask.form}>
      <AuthCard title={title} subtitle={texts.connect.text}>
        <Facts
          items={[
            { label: texts.connect.account, value: account.name, testId: 'app-connect-name' },
            { label: texts.connect.login, value: account.login, testId: 'app-connect-login' },
          ]}
        />
        {problem && (
          <Notice tone="danger" testId="app-connect-problem">
            {problem}
          </Notice>
        )}
        <div className="flex flex-col gap-2">
          <Button kind={BUTTONS.confirm.kind} icon={BUTTONS.confirm.icon} wide busy={busy} onClick={() => void connect()} testId="app-connect-confirm">
            {texts.connect.confirm}
          </Button>
          <Button kind={BUTTONS.cancel.kind} icon={BUTTONS.cancel.icon} wide disabled={busy} onClick={cancel} testId="app-connect-cancel">
            {texts.connect.cancel}
          </Button>
        </div>
      </AuthCard>
    </div>,
  )
}
