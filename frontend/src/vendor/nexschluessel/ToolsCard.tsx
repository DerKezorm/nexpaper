/**
 * My account › Connections: the card "KI-Werkzeuge (MCP)" (Sparkles), in all eight apps. First the programs that
 * connected themselves with the account's consent (OAuth), then the MCP keys made by hand (where the app has them,
 * nexlore; nexnotes' older ones), each with "Widerrufen" (danger `sm`); the address AI tools connect to. Where the
 * app's API keys carry the extra "Auch für KI-Werkzeuge (MCP)" (nexnotes, nextime) the card says so. An app without
 * MCP says "{app} hat noch keinen MCP-Zugang."
 *
 * Copied unchanged into frontend/src/vendor/nexschluessel/ by bauplaene/schluessel/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Box, Button, Card, CopyRow, Notice } from '../nexui'
import { useKeyTexts } from './hooks'
import { KeyDialog, KeyFactorHint, KeysTable, MadeBox, RevokeDialog, type DialogState } from './parts'
import { BUTTONS, KEYS_BASE, fillKeys, mcpKeys, programs, refusalText, type AppWords, type KeyEntry, type KeyListing, type KeyRequest, type WhenFormat } from './schluessel'

export type ToolsCardProps = {
  request: KeyRequest
  base?: string
  words?: AppWords
  securityHref?: string
  language?: string
  when?: WhenFormat
  /** The app's own button per key or program (nexlore: rights per tool), before the module's. */
  extra?: (key: KeyEntry) => ReactNode
  /** The app's own parts at the end (nexlore: requests waiting for approval). */
  children?: ReactNode
  testId?: string
}

export function ToolsCard({ request, base = KEYS_BASE, words, securityHref = '/settings/security', language, when, extra, children, testId = 'tools-card' }: ToolsCardProps) {
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
  const kind = listing?.kinds.find((found) => found.id === 'mcp')
  const viaApiKey = listing?.kinds.some((found) => found.id === 'api' && found.options.includes('mcp'))

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

  const table = (rows: KeyEntry[], label: string, empty: string, id: string) =>
    listing && (
      <KeysTable
        rows={rows}
        listing={listing}
        texts={texts}
        code={code}
        words={words}
        when={when}
        label={label}
        empty={empty}
        showExpiry={kind !== undefined && kind.expiry_days !== null && rows.some((key) => !key.program)}
        onEdit={kind ? (key) => setDialog({ mode: 'edit', kind, key }) : undefined}
        onRevoke={setRevoking}
        extra={extra}
        testId={id}
      />
    )

  return (
    <Card id="ai-tools" icon="Sparkles" title={texts.tools.title} subtitle={texts.tools.hint} testId={testId}>
      {listing && listing.mcp === null && (
        <Notice tone="warn" testId="tools-none">
          {fillKeys(texts.tools.none, { app: listing.app })}
        </Notice>
      )}
      {listing && listing.mcp === false && (
        <Notice tone="warn" testId="tools-off">
          {texts.tools.off}
        </Notice>
      )}
      {listing?.mcp !== null && listing?.keys_wait && <KeyFactorHint texts={texts} securityHref={securityHref} />}
      {problem && (
        <Notice tone="danger" testId="tools-problem">
          {problem}
        </Notice>
      )}
      {made && listing && <MadeBox texts={texts} name={made.name} secret={made.secret} app={listing.app} onDone={() => setMade(null)} />}
      {listing?.programs && (
        <Box title={texts.tools.programs} hint={texts.tools.programsHint} testId="tools-programs">
          {table(programs(listing), texts.tools.programs, texts.tools.programsEmpty, 'tools-programs-table')}
        </Box>
      )}
      {listing && (kind || mcpKeys(listing).length > 0) && (
        <Box
          title={texts.tools.keys}
          testId="tools-keys"
          actions={
            kind?.creatable ? (
              <Button
                kind={BUTTONS.newKey.kind}
                icon={BUTTONS.newKey.icon}
                disabled={!listing.mcp || kind.count >= kind.max_keys}
                onClick={() => {
                  setProblem(undefined)
                  setDialog({ mode: 'new', kind })
                }}
                testId="tools-new"
              >
                {texts.tools.new}
              </Button>
            ) : undefined
          }
        >
          {table(mcpKeys(listing), texts.tools.keys, texts.tools.keysEmpty, 'tools-keys-table')}
        </Box>
      )}
      {viaApiKey && listing?.mcp !== null && <p className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]">{texts.tools.viaApiKey}</p>}
      {listing?.mcp_path && (
        <CopyRow value={`${listing.address}${listing.mcp_path}`} label={texts.tools.address} testId="tools-address" />
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
