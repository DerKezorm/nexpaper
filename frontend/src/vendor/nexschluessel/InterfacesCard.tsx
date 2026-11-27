/**
 * Server › Connections (since 1.1.3, E67; before Server › General): the card "Schnittstellen" (Webhook), for operators. "Programmschnittstelle (API) für Mitglieder"
 * and, where the app has MCP, "MCP-Zugang", each a `CheckboxRow`; where the app has an iPhone app, the places
 * "iPhone-App erlauben" and "Neue Geräte verbinden" (the app fills them by naming the switches in its `AppConfig`;
 * the setting stays where the app keeps it). Then the app's own rows (nexlore: highest level of an MCP key,
 * connectors, blocked tools) and the link "Beschreibung der Schnittstelle". A box is kept at once, since 1.1.1 with a
 * short "Gespeichert." (MCP 21). Switching off deletes nothing.
 *
 * Copied unchanged into frontend/src/vendor/nexschluessel/ by bauplaene/schluessel/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Button, Buttons, Card, CheckboxRow, Notice } from '../nexui'
import { useKeyTexts } from './hooks'
import { BUTTONS, KEYS_BASE, SWITCH_ORDER, refusalText, type Interfaces, type KeyRequest, type SwitchName } from './schluessel'

export type InterfacesCardProps = {
  request: KeyRequest
  base?: string
  /** Where the description of the interface lives. */
  docsHref?: string
  language?: string
  /** The app's own rows after a switch (nexlore after `mcp`: its MCP settings). */
  after?: Partial<Record<SwitchName, ReactNode>>
  /** The app's own rows at the end. */
  children?: ReactNode
  testId?: string
}

export function InterfacesCard({ request, base = KEYS_BASE, docsHref, language, after, children, testId = 'interfaces-card' }: InterfacesCardProps) {
  const { texts } = useKeyTexts(language)
  const [state, setState] = useState<Interfaces | null>(null)
  const [busy, setBusy] = useState<SwitchName | null>(null)
  const [problem, setProblem] = useState<string>()
  const [saved, setSaved] = useState(false)

  const load = useCallback(() => request<Interfaces>(`${base}/interfaces`), [request, base])
  useEffect(() => {
    load().then(setState, (failure: unknown) => setProblem(refusalText(texts, failure)))
  }, [load, texts])

  const change = async (name: SwitchName, on: boolean) => {
    setBusy(name)
    setProblem(undefined)
    setSaved(false)
    try {
      setState(await request<Interfaces>(`${base}/interfaces`, { method: 'PUT', body: { [name]: on } }))
      setSaved(true)
    } catch (failure) {
      setProblem(refusalText(texts, failure))
    } finally {
      setBusy(null)
    }
  }

  const words: Record<SwitchName, { label: string; hint: string }> = {
    api: { label: texts.interfaces.api, hint: texts.interfaces.apiHint },
    mcp: { label: texts.interfaces.mcp, hint: texts.interfaces.mcpHint },
    app: { label: texts.interfaces.app, hint: texts.interfaces.appHint },
    pairing: { label: texts.interfaces.pairing, hint: texts.interfaces.pairingHint },
  }

  return (
    <Card id="interfaces" icon="Webhook" title={texts.interfaces.title} testId={testId}>
      {problem && (
        <Notice tone="danger" testId="interfaces-problem">
          {problem}
        </Notice>
      )}
      {state &&
        SWITCH_ORDER.filter((name) => state[name] !== undefined).map((name) => (
          <div key={name} className="flex flex-col gap-3">
            <CheckboxRow
              label={words[name].label}
              hint={words[name].hint}
              checked={state[name] ?? false}
              disabled={busy !== null}
              onChange={(on) => void change(name, on)}
              testId={`interfaces-${name}`}
            />
            {after?.[name]}
          </div>
        ))}
      {saved && (
        <p className="m-0 text-xs leading-4 text-[var(--nexui-ok)]" role="status" data-testid="interfaces-saved">
          {texts.interfaces.saved}
        </p>
      )}
      {children}
      {docsHref && (
        <Buttons>
          <Button kind={BUTTONS.docs.kind} icon={BUTTONS.docs.icon} size="sm" href={docsHref} testId="interfaces-docs">
            {texts.interfaces.docs}
          </Button>
        </Buttons>
      )}
    </Card>
  )
}
