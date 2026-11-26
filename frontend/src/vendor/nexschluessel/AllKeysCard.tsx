/**
 * Server › Accounts: the card "API-Schlüssel aller Konten" (KeyRound), for operators. A `Table` of account, name,
 * right, last use, the app's own columns (`extra`, since E36) and the button: "Sperren" (danger `sm`, asks first) or
 * "Entsperren" (secondary `sm`). Never the key itself, not even its start (since E36), never what it reached. Replaces nextime's line of counts, nextasks' table and nexdiary's card.
 *
 * Copied unchanged into frontend/src/vendor/nexschluessel/ by bauplaene/schluessel/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { Badge, Button, Card, ConfirmDialog, Notice, Table, useNexuiTexts } from '../nexui'
import { useKeyTexts } from './hooks'
import {
  ADMIN_COLUMNS,
  BUTTONS,
  COLUMN_WIDTHS,
  KEYS_BASE,
  defaultWhen,
  fillKeys,
  refusalText,
  rightLabel,
  type AdminColumn,
  type AdminExtraColumn,
  type AdminKey,
  type AppWords,
  type KeyRequest,
  type WhenFormat,
} from './schluessel'

export type AllKeysCardProps = {
  request: KeyRequest
  base?: string
  words?: AppWords
  language?: string
  when?: WhenFormat
  /** Since E36: the app's own columns, before the button; each shows `row.extra[key]` unless it has its own `cell`. */
  extra?: readonly AdminExtraColumn[]
  /** Since 1.0.2 (E58): the app's own parts at the end of the card (nexpaper: the link to make keys of one's own). */
  children?: ReactNode
  testId?: string
}

export function AllKeysCard({ request, base = KEYS_BASE, words, language, when = defaultWhen, extra = [], children, testId = 'all-keys-card' }: AllKeysCardProps) {
  const { texts, code } = useKeyTexts(language)
  const kit = useNexuiTexts()
  const [rows, setRows] = useState<AdminKey[] | null>(null)
  const [problem, setProblem] = useState<string>()
  const [asking, setAsking] = useState<AdminKey | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => request<{ keys: AdminKey[] }>(`${base}/admin/keys`), [request, base])
  useEffect(() => {
    load().then(
      (found) => setRows(found.keys),
      (failure: unknown) => setProblem(refusalText(texts, failure)),
    )
  }, [load, texts])

  const set = async (row: AdminKey, lock: boolean) => {
    setBusy(true)
    setProblem(undefined)
    try {
      const changed = await request<AdminKey>(`${base}/admin/keys/${encodeURIComponent(String(row.id))}/${lock ? 'block' : 'unblock'}`, { method: 'POST' })
      setRows((before) => (before ?? []).map((found) => (String(found.id) === String(changed.id) ? changed : found)))
      setAsking(null)
    } catch (failure) {
      setProblem(refusalText(texts, failure))
      setAsking(null)
    } finally {
      setBusy(false)
    }
  }

  const own = new Map(extra.map((column) => [column.key, column]))
  const cell = (row: AdminKey, column: AdminColumn | string): ReactNode => {
    const app = own.get(column)
    if (app) return app.cell ? app.cell(row) : <span>{String(row.extra?.[app.key] ?? '')}</span>
    switch (column) {
      case 'account':
        return <span className="font-medium">{row.account.display_name || row.account.name}</span>
      case 'name':
        return (
          <span className="flex flex-col gap-1">
            <span className="flex flex-wrap items-center gap-1.5">
              {row.name ? <span>{row.name}</span> : <span className="text-[var(--nexui-text-muted)]">{texts.allKeys.hidden}</span>}
              {row.program && <Badge tone="accent">{texts.key.program}</Badge>}
              {row.options.mcp && <Badge tone="accent">{texts.key.mcp}</Badge>}
              {row.blocked && <Badge tone="danger">{texts.key.blocked}</Badge>}
              {row.expired && <Badge tone="off">{texts.key.expired}</Badge>}
            </span>
          </span>
        )
      case 'right':
        return <span>{rightLabel(texts, words, row.right)}</span>
      case 'used':
        return <span className="text-[var(--nexui-text-muted)]">{row.last_used_at ? when(row.last_used_at, code) : texts.key.neverUsed}</span>
      case 'action':
        return row.blocked ? (
          <Button kind={BUTTONS.unblock.kind} icon={BUTTONS.unblock.icon} size="sm" busy={busy} onClick={() => void set(row, false)} testId="all-keys-unblock">
            {texts.allKeys.unblock}
          </Button>
        ) : (
          <Button kind={BUTTONS.block.kind} icon={BUTTONS.block.icon} size="sm" onClick={() => setAsking(row)} testId="all-keys-block">
            {texts.allKeys.block}
          </Button>
        )
    }
  }

  return (
    <Card id="all-api-keys" icon="KeyRound" title={texts.allKeys.title} subtitle={texts.allKeys.hint} testId={testId}>
      {problem && (
        <Notice tone="danger" testId="all-keys-problem">
          {problem}
        </Notice>
      )}
      {rows && (
        <Table<AdminKey, string>
          label={texts.allKeys.title}
          columns={[
            ...ADMIN_COLUMNS.filter((key) => key !== 'action').map((key) => ({ key: key as string, label: texts.columns[key], width: COLUMN_WIDTHS[key] })),
            ...extra.map((column) => ({ key: column.key, label: column.label, width: column.width })),
            { key: 'action', label: texts.columns.action, width: COLUMN_WIDTHS.action },
          ]}
          rows={rows}
          cell={cell}
          rowKey={(row) => String(row.id)}
          rowProps={(row) => ({ 'data-testid': 'all-keys-row', 'data-blocked': row.blocked ? 'true' : 'false' })}
          empty={texts.allKeys.empty}
          testId="all-keys-table"
        />
      )}
      {children}
      {asking && (
        <ConfirmDialog
          title={fillKeys(texts.allKeys.askBlock, { name: asking.name ?? texts.allKeys.hidden, account: asking.account.display_name || asking.account.name })}
          text={texts.allKeys.askBlockText}
          confirm={{ label: texts.allKeys.block, kind: BUTTONS.block.kind, icon: BUTTONS.block.icon }}
          cancel={texts.key.cancel}
          closeLabel={kit.close}
          busy={busy}
          onCancel={() => setAsking(null)}
          onConfirm={() => void set(asking, true)}
          testId="all-keys-block-dialog"
        />
      )}
    </Card>
  )
}
