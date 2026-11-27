/**
 * "Andere nex-Apps" under Server › Verbindungen (draft "Apps verbinden", decisions V1 1b and 7a): the operator's switch
 * "Verbindungen mit anderen nex-Apps" (on unless switched off; off, nobody connects anew and existing connections
 * rest, nothing is deleted), since 0.1.4 "Verbindungen ins eigene Netz" (V-12, the app's setting
 * `connections_local_network`), then the addresses of the other apps of the server, set up for every account.
 *
 * Since 0.1.10: opened at `#nex-apps` (the cards' "Einrichten", `OPERATOR_PAGE`), the card scrolls itself into view once
 * it has loaded, since the settings pages render after the browser looked for the anchor.
 *
 * Since 0.2.0 (verbinden B11 to B20, decided 27.11.2026): the head shows the mark of the nex apps and "nex-Apps" as
 * the wordmark (B19, B20, ui 1.3.0); each address has the mark of its app in front (B17); one "Speichern" keeps the
 * switches and every address and then says what it kept (B18, V60); every address kept anew is asked what answers
 * there, and the field says it ("Gefunden: nextasks 0.9.0", or what is wrong; kept anyway, B11, V57); addresses another
 * nex app passed on stand at their field as a suggestion to take with a click, asked first (B16, V58).
 *
 * Copied unchanged into frontend/src/vendor/nexverbinden/ by bauplaene/verbinden/tools/sync.py; changed only there.
 */
import { useEffect, useState } from 'react'

import { Button, Buttons, Card, CheckboxRow, Field, NexMark, NexWordmark, Notice } from '../nexui'
import {
  VERBINDEN_BASE,
  VERBINDEN_BUTTONS,
  codeText,
  fillVerbinden,
  markOf,
  refusalFields,
  refusalText,
  usePageDark,
  useVerbindenTexts,
  type AddressCheck,
  type ConnectionsAdmin,
  type VerbindenRequest,
  type VerbindenTexts,
} from './verbinden'

export type ConnectionsOperatorCardProps = {
  app: string
  request: VerbindenRequest
  base?: string
  language?: string
  testId?: string
}

/** B11: what the field says about the address it keeps. */
function checkText(texts: VerbindenTexts, app: string, partner: string, check: AddressCheck): string {
  const words = texts.operator.checks as Record<string, string>
  const text = words[check.code] ?? words.unreachable ?? ''
  return fillVerbinden(text, { app, partner, found: check.app ?? '', version: check.version ?? '' }).replace(/ +\./g, '.').trim()
}

export function ConnectionsOperatorCard({ app, request, base = VERBINDEN_BASE, language, testId = 'connections-operator' }: ConnectionsOperatorCardProps) {
  const { texts } = useVerbindenTexts(language)
  const dark = usePageDark()
  const [admin, setAdmin] = useState<ConnectionsAdmin | null>(null)
  const [typed, setTyped] = useState<Record<string, string>>({})
  const [switches, setSwitches] = useState({ connections: true, local: false })
  const [checks, setChecks] = useState<Record<string, AddressCheck>>({})
  const [wrong, setWrong] = useState<Record<string, string>>({})
  const [notTaken, setNotTaken] = useState<Record<string, AddressCheck>>({})
  const [problem, setProblem] = useState<string>()
  const [said, setSaid] = useState<string>()
  const [busy, setBusy] = useState(false)
  const loaded = admin !== null

  // 0.1.10: "Einrichten" leads here with `#nex-apps`; once the card stands, it comes into view. Since 0.1.11 found by its
  // id, without a box around the card (the card stands directly in the app's row of cards, as before 0.1.10).
  useEffect(() => {
    if (loaded && typeof document !== 'undefined' && window.location.hash === '#nex-apps') document.getElementById('nex-apps')?.scrollIntoView?.({ block: 'start' })
  }, [loaded])

  useEffect(() => {
    request<ConnectionsAdmin>(`${base}/admin`).then(
      (found) => {
        setAdmin(found)
        setTyped(found.addresses)
        setSwitches({ connections: found.connections, local: found.local })
      },
      (failure: unknown) => setProblem(refusalText(texts, failure, app)),
    )
  }, [request, base, texts, app])

  /** B18: what the server kept, in words ("Verbindungen ins eigene Netz, nextasks"). */
  const savedText = (saved: string[]) => {
    if (saved.length === 0) return texts.operator.nothingChanged
    const names = saved.map((name) => (name === 'connections' ? texts.operator.switch : name === 'local' ? texts.operator.local : name))
    return fillVerbinden(texts.operator.savedWhat, { what: names.join(', ') })
  }

  const save = async () => {
    if (!admin) return
    setBusy(true)
    setProblem(undefined)
    setSaid(undefined)
    setWrong({})
    try {
      const addresses = Object.fromEntries(admin.partners.map((partner) => [partner, typed[partner] ?? '']))
      const found = await request<ConnectionsAdmin>(`${base}/admin`, { method: 'PUT', body: { ...switches, addresses } })
      setAdmin(found)
      setTyped((all) => ({ ...all, ...found.addresses }))
      setSwitches({ connections: found.connections, local: found.local })
      setChecks((all) => ({ ...all, ...(found.checks ?? {}) }))
      setNotTaken({})
      setSaid(savedText(found.saved ?? []))
    } catch (failure) {
      const fields = refusalFields(failure)
      if (Object.keys(fields).length > 0) {
        setWrong(fields)
        setSaid(texts.operator.notSaved)
      } else {
        setProblem(refusalText(texts, failure, app))
      }
    }
    setBusy(false)
  }

  /** B16: a suggestion taken (asked first; kept only where the right app answers) or turned down. */
  const suggestion = async (partner: string, take: boolean) => {
    setBusy(true)
    setProblem(undefined)
    setSaid(undefined)
    try {
      const found = await request<ConnectionsAdmin>(`${base}/admin/suggestions/${encodeURIComponent(partner)}`, { method: take ? 'POST' : 'DELETE' })
      setAdmin(found)
      const check = found.checks?.[partner]
      if (take && found.saved?.includes(partner)) {
        setTyped((all) => ({ ...all, [partner]: found.addresses[partner] ?? '' }))
        if (check) setChecks((all) => ({ ...all, [partner]: check }))
        setSaid(savedText(found.saved))
      }
      setNotTaken((all) => {
        const rest = { ...all }
        delete rest[partner]
        return take && check && !found.saved?.includes(partner) ? { ...rest, [partner]: check } : rest
      })
    } catch (failure) {
      setProblem(refusalText(texts, failure, app))
    }
    setBusy(false)
  }

  return (
    <Card
      id="nex-apps"
      mark={<NexMark />}
      title={
        <>
          {texts.operator.titleBefore}
          <NexWordmark />
        </>
      }
      subtitle={texts.operator.subtitle}
      testId={testId}
    >
      {problem && <Notice tone="danger">{problem}</Notice>}
      {admin && (
        <>
          <CheckboxRow
            label={texts.operator.switch}
            hint={texts.operator.switchHint}
            checked={switches.connections}
            onChange={(on) => setSwitches((all) => ({ ...all, connections: on }))}
            testId="connections-switch"
          />
          <CheckboxRow
            label={texts.operator.local}
            hint={fillVerbinden(texts.operator.localHint, { app })}
            checked={switches.local}
            onChange={(on) => setSwitches((all) => ({ ...all, local: on }))}
            testId="connections-local"
          />
          <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{fillVerbinden(texts.operator.addressesHint, { app })}</p>
          {admin.partners.map((partner) => {
            const check = checks[partner]
            const offered = (admin.suggestions ?? []).find((one) => one.partner === partner)
            const refused = notTaken[partner]
            const mark = markOf(partner, dark)
            const error = wrong[partner] ? codeText(texts, wrong[partner], app, partner) : check && !check.ok ? checkText(texts, app, partner, check) : undefined
            return (
              <div key={partner} className="flex min-w-0 items-start gap-3" data-testid={`connections-field-${partner}`}>
                {/* B17 (0.2.0): the mark of the app in front of its address, light or dark as the page. */}
                {mark ? <img src={mark} alt="" className="mt-7 h-8 w-8 shrink-0 rounded-[10px]" data-testid={`connections-mark-${partner}`} /> : <span className="mt-7 h-8 w-8 shrink-0" />}
                <div className="flex min-w-0 flex-1 flex-col gap-2">
                  <Field
                    label={fillVerbinden(texts.operator.address, { partner })}
                    value={typed[partner] ?? ''}
                    onChange={(event) => setTyped((all) => ({ ...all, [partner]: event.target.value }))}
                    type="url"
                    maxLength={500}
                    placeholder={fillVerbinden(texts.card.addressHint, { partner })}
                    hints={check?.ok ? [checkText(texts, app, partner, check)] : []}
                    error={error}
                    data-testid={`connections-address-${partner}`}
                  />
                  {offered && (
                    <div className="flex flex-col gap-2" data-testid={`connections-suggestion-${partner}`}>
                      <p className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]">
                        {fillVerbinden(texts.operator.suggestion, { from: offered.from || texts.card.otherApp, partner, address: offered.address })}
                      </p>
                      {refused && (
                        <p className="m-0 text-xs leading-4 text-[var(--nexui-danger)]" role="alert" data-testid={`connections-not-taken-${partner}`}>
                          {fillVerbinden(texts.operator.notTaken, { reason: checkText(texts, app, partner, refused) })}
                        </p>
                      )}
                      <Buttons>
                        <Button kind={VERBINDEN_BUTTONS.take.kind} icon={VERBINDEN_BUTTONS.take.icon} size="sm" disabled={busy} onClick={() => void suggestion(partner, true)} testId={`connections-take-${partner}`}>
                          {texts.buttons.take}
                        </Button>
                        <Button kind={VERBINDEN_BUTTONS.dropSuggestion.kind} icon={VERBINDEN_BUTTONS.dropSuggestion.icon} size="sm" disabled={busy} onClick={() => void suggestion(partner, false)} testId={`connections-drop-${partner}`}>
                          {texts.buttons.dropSuggestion}
                        </Button>
                      </Buttons>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
          {/* B18 (0.2.0, V60): one "Speichern" for the switches and every address. */}
          <div className="flex flex-wrap items-center gap-3">
            <Button kind={VERBINDEN_BUTTONS.saveAll.kind} icon={VERBINDEN_BUTTONS.saveAll.icon} busy={busy} onClick={() => void save()} testId="connections-save">
              {texts.buttons.save}
            </Button>
            {said && (
              <p className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]" role="status" data-testid="connections-saved">
                {said}
              </p>
            )}
          </div>
        </>
      )}
    </Card>
  )
}
