/**
 * "Andere nex-Apps" under Server › Allgemein (draft "Apps verbinden", decisions V1 1b and 7a): the operator's switch
 * "Verbindungen mit anderen nex-Apps" (on unless switched off; off, nobody connects anew and existing connections
 * rest, nothing is deleted), since 0.1.4 "Verbindungen ins eigene Netz" (V-12, the app's setting
 * `connections_local_network`); both boxes are kept at once with a short "Gespeichert." (MCP 21). Then the addresses
 * of the other apps of the server, each a text field with its own "Speichern", filled in for every account in the
 * cards.
 *
 * Copied unchanged into frontend/src/vendor/nexverbinden/ by bauplaene/verbinden/tools/sync.py; changed only there.
 */
import { useEffect, useState } from 'react'

import { Button, Card, CheckboxRow, Field, Notice } from '../nexui'
import { VERBINDEN_BASE, VERBINDEN_BUTTONS, fillVerbinden, refusalText, useVerbindenTexts, type ConnectionsAdmin, type VerbindenRequest } from './verbinden'

export type ConnectionsOperatorCardProps = {
  app: string
  request: VerbindenRequest
  base?: string
  language?: string
  testId?: string
}

export function ConnectionsOperatorCard({ app, request, base = VERBINDEN_BASE, language, testId = 'connections-operator' }: ConnectionsOperatorCardProps) {
  const { texts } = useVerbindenTexts(language)
  const [admin, setAdmin] = useState<ConnectionsAdmin | null>(null)
  const [typed, setTyped] = useState<Record<string, string>>({})
  const [problem, setProblem] = useState<string>()
  const [saved, setSaved] = useState<string>()

  useEffect(() => {
    request<ConnectionsAdmin>(`${base}/admin`).then(
      (found) => {
        setAdmin(found)
        setTyped(found.addresses)
      },
      (failure: unknown) => setProblem(refusalText(texts, failure, app)),
    )
  }, [request, base, texts, app])

  const send = async (body: Partial<ConnectionsAdmin>, partner?: string) => {
    setProblem(undefined)
    setSaved(undefined)
    try {
      const found = await request<ConnectionsAdmin>(`${base}/admin`, { method: 'PUT', body })
      setAdmin(found)
      setTyped((all) => ({ ...all, ...found.addresses }))
      setSaved(partner)
    } catch (failure) {
      setProblem(refusalText(texts, failure, app))
    }
  }

  return (
    <Card id="nex-apps" icon="Plug" title={texts.operator.title} subtitle={texts.operator.subtitle} testId={testId}>
      {problem && <Notice tone="danger">{problem}</Notice>}
      {admin && (
        <>
          <CheckboxRow label={texts.operator.switch} hint={texts.operator.switchHint} checked={admin.connections} onChange={(on) => void send({ connections: on }, 'switches')} testId="connections-switch" />
          <CheckboxRow
            label={texts.operator.local}
            hint={fillVerbinden(texts.operator.localHint, { app })}
            checked={admin.local}
            onChange={(on) => void send({ local: on }, 'switches')}
            testId="connections-local"
          />
          {saved === 'switches' && (
            <p className="m-0 text-xs leading-4 text-[var(--nexui-ok)]" role="status" data-testid="connections-saved">
              {texts.operator.saved}
            </p>
          )}
          <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{texts.operator.addressesHint}</p>
          {admin.partners.map((partner) => (
            <Field
              key={partner}
              label={fillVerbinden(texts.operator.address, { partner })}
              value={typed[partner] ?? ''}
              onChange={(event) => setTyped((all) => ({ ...all, [partner]: event.target.value }))}
              type="url"
              maxLength={500}
              placeholder={fillVerbinden(texts.card.addressHint, { partner })}
              hints={saved === partner ? [texts.operator.saved] : []}
              data-testid={`connections-address-${partner}`}
              action={
                <Button kind={VERBINDEN_BUTTONS.save.kind} icon={VERBINDEN_BUTTONS.save.icon} onClick={() => void send({ addresses: { [partner]: typed[partner] ?? '' } }, partner)} testId={`connections-save-${partner}`}>
                  {texts.buttons.save}
                </Button>
              }
            />
          ))}
        </>
      )}
    </Card>
  )
}
