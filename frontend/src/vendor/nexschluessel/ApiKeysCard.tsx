/**
 * My account › Connections: the card "API-Schlüssel" (KeyRound), in all eight apps. The account's keys as a table
 * (name, right and reach, expiry where the app knows one, last use; "Bearbeiten" and "Widerrufen" as `sm` buttons),
 * "Neuer API-Schlüssel" (primary) with the app's rights, areas, extras and lifetimes, the new key shown once to copy,
 * the address for programs and the description of the interface. While the operator has the interface switched off
 * it says so; while the account's keys rest until it sets up a second factor it says "Wirkt erst, wenn du einen
 * zweiten Faktor einrichtest." (making stays, decided 24.11.2026). Places for the app (since 1.0.1, E57): `extra` per
 * key, `offAction` in the note "switched off", `made` in the box of a new key, `children` at the end.
 *
 * Copied unchanged into frontend/src/vendor/nexschluessel/ by bauplaene/schluessel/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Button, Buttons, Card, CopyRow, Notice } from '../nexui'
import { useKeyTexts } from './hooks'
import { KeyDialog, KeyFactorHint, KeysTable, MadeBox, RevokeDialog, type DialogState } from './parts'
import { BUTTONS, KEYS_BASE, apiKeys, fillKeys, refusalText, type AppWords, type KeyEntry, type KeyListing, type KeyRequest, type WhenFormat } from './schluessel'

export type ApiKeysCardProps = {
  /** The app's client (its headers, its errors). */
  request: KeyRequest
  /** Where the module's routes are mounted. */
  base?: string
  /** The app's word for what it keeps ("Notizen", "Kalender"). */
  things: string
  /** Since E34: the same after "mit deinen" in the card's sentence ("Kalendern"); default `things`. */
  thingsDative?: string
  /** The app's own rights, extras and the word for its areas. */
  words?: AppWords
  /** Where the description of the interface lives (`/api/v1/docs`, a page of the app). */
  docsHref?: string
  /** Where the second factor is set up. */
  securityHref?: string
  /** An operator reads where to switch the interface on. */
  operator?: boolean
  language?: string
  when?: WhenFormat
  /** The app's own button per key, before the module's. */
  extra?: (key: KeyEntry) => ReactNode
  /** Since 1.0.1 (E57): the app's own part in the note "switched off" (an operator's button to switch it on). */
  offAction?: ReactNode
  /** Since 1.0.1 (E57): the app's own parts in the box of a new key, under its copy rows, while the key is shown once
   * (a command to try it, with the key in it). */
  made?: (made: { name: string; secret: string }) => ReactNode
  /** The app's own parts at the end of the card (a link to more, hints on lifetimes). */
  children?: ReactNode
  testId?: string
}

export function ApiKeysCard({
  request,
  base = KEYS_BASE,
  things,
  thingsDative = things,
  words,
  docsHref,
  securityHref = '/settings/security',
  operator = false,
  language,
  when,
  extra,
  offAction,
  made: madeExtra,
  children,
  testId = 'api-keys-card',
}: ApiKeysCardProps) {
  const { texts, code } = useKeyTexts(language)
  const [listing, setListing] = useState<KeyListing | null>(null)
  const [problem, setProblem] = useState<string>()
  const [dialog, setDialog] = useState<DialogState | null>(null)
  const [made, setMade] = useState<{ name: string; secret: string } | null>(null)
  const [revoking, setRevoking] = useState<KeyEntry | null>(null)
  const [busy, setBusy] = useState(false)
  const [round, setRound] = useState(0)

  const load = useCallback(() => request<KeyListing>(`${base}/keys`), [request, base])
  useEffect(() => {
    load().then(setListing, (failure: unknown) => setProblem(refusalText(texts, failure)))
  }, [load, round, texts])

  const reload = () => setRound((value) => value + 1)
  const kind = listing?.kinds.find((found) => found.id === 'api')
  const rows = listing ? apiKeys(listing) : []

  const revoke = async () => {
    if (!revoking) return
    setBusy(true)
    try {
      await request(`${base}/keys/${encodeURIComponent(String(revoking.id))}`, { method: 'DELETE' })
      setRevoking(null)
      reload()
    } catch (failure) {
      setProblem(refusalText(texts, failure))
      setRevoking(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card id="api-keys" icon="KeyRound" title={texts.apiKeys.title} subtitle={fillKeys(texts.apiKeys.hint, { things, thingsDative })} testId={testId}>
      {listing && !listing.api && (
        <Notice tone="warn" testId="api-keys-off">
          {texts.apiKeys.off}
          {operator ? ` ${texts.apiKeys.offOperator}` : ''}
          {offAction && <div className="mt-2">{offAction}</div>}
        </Notice>
      )}
      {listing?.keys_wait && <KeyFactorHint texts={texts} securityHref={securityHref} />}
      {problem && (
        <Notice tone="danger" testId="api-keys-problem">
          {problem}
        </Notice>
      )}
      {made && listing && (
        <MadeBox
          texts={texts}
          name={made.name}
          secret={made.secret}
          app={listing.app}
          onDone={() => {
            setMade(null)
            reload()
          }}
        >
          {madeExtra?.(made)}
        </MadeBox>
      )}
      {listing && kind && (
        <KeysTable
          rows={rows}
          listing={listing}
          texts={texts}
          code={code}
          words={words}
          when={when}
          label={texts.apiKeys.title}
          empty={texts.apiKeys.empty}
          showExpiry={kind.expiry_days !== null}
          onEdit={(key) => setDialog({ mode: 'edit', kind, key })}
          onRevoke={setRevoking}
          extra={extra}
          testId="api-keys-table"
        />
      )}
      {listing && kind?.creatable && (
        <Buttons>
          <Button
            kind={BUTTONS.newKey.kind}
            icon={BUTTONS.newKey.icon}
            disabled={!listing.api || kind.count >= kind.max_keys}
            onClick={() => {
              setProblem(undefined)
              setDialog({ mode: 'new', kind })
            }}
            testId="api-keys-new"
          >
            {texts.apiKeys.new}
          </Button>
          <span className="text-xs leading-4 text-[var(--nexui-text-muted)]" data-testid="api-keys-count">
            {fillKeys(texts.apiKeys.count, { count: kind.count, max: kind.max_keys })}
          </span>
        </Buttons>
      )}
      {listing && (
        <div className="flex flex-col gap-1">
          <CopyRow value={`${listing.address}${listing.api_path}`} label={texts.apiKeys.address} testId="api-keys-address" />
          <span className="text-xs leading-4 text-[var(--nexui-text-muted)]">{texts.apiKeys.addressHint}</span>
        </div>
      )}
      {docsHref && (
        <Buttons>
          <Button kind={BUTTONS.docs.kind} icon={BUTTONS.docs.icon} size="sm" href={docsHref} testId="api-keys-docs">
            {texts.apiKeys.docs}
          </Button>
        </Buttons>
      )}
      {children}
      {dialog && listing && (
        <KeyDialog
          state={dialog}
          request={request}
          base={base}
          texts={texts}
          words={words}
          keysWait={listing.keys_wait}
          securityHref={securityHref}
          onClose={() => setDialog(null)}
          onMade={(result) => {
            setDialog(null)
            if (result.secret) setMade({ name: result.key.name ?? '', secret: result.secret })
            reload()
          }}
          onChanged={() => {
            setDialog(null)
            reload()
          }}
        />
      )}
      {revoking && <RevokeDialog texts={texts} keyEntry={revoking} busy={busy} onCancel={() => setRevoking(null)} onConfirm={() => void revoke()} />}
    </Card>
  )
}
