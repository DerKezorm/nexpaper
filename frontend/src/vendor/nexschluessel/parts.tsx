/**
 * What the cards share: the module's words in the kit's language, the hint "Works only once you set up a second
 * factor", the table of an account's keys, the dialog that makes or changes a key, the box that shows a new key once,
 * the question before revoking. Built only from the ui kit.
 *
 * Copied unchanged into frontend/src/vendor/nexschluessel/ by bauplaene/schluessel/tools/sync.py; changed only there.
 */
import { useState, type ReactNode } from 'react'

import { Badge, Box, Button, Buttons, Checkbox, CheckboxRow, ConfirmDialog, CopyRow, Dialog, Field, Notice, Segment, SelectField, Table, TextLink, useNexuiTexts } from '../nexui'
import {
  BUTTONS,
  COLUMN_WIDTHS,
  KEY_COLUMNS,
  daysOf,
  daysValue,
  defaultDays,
  fillKeys,
  defaultWhen,
  newClientRef,
  optionHint,
  optionLabel,
  refusalText,
  rightLabel,
  type KeyColumn,
  type KeyEntry,
  type KeyListing,
  type KeyRequest,
  type AppWords,
  type KeyTexts,
  type KindChoice,
  type NewKeyBody,
  type WhenFormat,
} from './schluessel'

/** "Works only once you set up a second factor", with the way to the setup (decided 24.11.2026: making stays). */
export function KeyFactorHint({ texts, securityHref, compact = false }: { texts: KeyTexts; securityHref: string; compact?: boolean }) {
  if (compact) {
    return (
      <span className="block text-xs leading-4 text-[var(--nexui-warn)]" role="note" data-testid="key-wait">
        {texts.key.wait}
      </span>
    )
  }
  return (
    <Notice tone="warn" testId="keys-wait">
      {texts.key.wait} <TextLink href={securityHref}>{texts.key.waitLink}</TextLink>
    </Notice>
  )
}

/** The account's keys as a table: name with its marks, right and reach, expiry (where the app knows one), last use,
 * the buttons. */
export function KeysTable({
  rows,
  listing,
  texts,
  code,
  words,
  label,
  empty,
  when = defaultWhen,
  onEdit,
  onRevoke,
  extra,
  showExpiry,
  testId,
}: {
  rows: KeyEntry[]
  listing: KeyListing
  texts: KeyTexts
  code: string
  words?: AppWords
  label: string
  empty: string
  when?: WhenFormat
  onEdit?: (key: KeyEntry) => void
  onRevoke: (key: KeyEntry) => void
  /** The app's own button for a key (nexlore: "Rights per tool"), before the module's. */
  extra?: (key: KeyEntry) => ReactNode
  showExpiry: boolean
  testId?: string
}) {
  const columns = KEY_COLUMNS.filter((column) => column !== 'expires' || showExpiry)
  const reach = (key: KeyEntry) =>
    key.areas === null ? texts.key.allAreas : Array.isArray(key.areas) ? key.areas.map((area) => area.name ?? String(area.id)).join(', ') || fillKeys(texts.key.someAreas, { count: 0 }) : fillKeys(texts.key.someAreas, { count: key.areas })
  const editable = (key: KeyEntry) => !key.program && !key.legacy && listing.kinds.find((kind) => kind.id === key.kind)?.editable
  const cell = (key: KeyEntry, column: KeyColumn) => {
    switch (column) {
      case 'name':
        return (
          <span className="flex flex-col gap-1">
            <span className="flex flex-wrap items-center gap-1.5">
              <span className="font-medium">{key.name}</span>
              {key.program && <Badge tone="accent">{texts.key.program}</Badge>}
              {key.options.mcp && <Badge tone="accent">{texts.key.mcp}</Badge>}
              {key.blocked && <Badge tone="danger" testId="key-blocked">{texts.key.blocked}</Badge>}
            </span>
            {key.program ? null : <span className="font-mono text-[var(--nexui-text-muted)]">{key.prefix}…</span>}
            {key.legacy && <span className="text-[var(--nexui-text-muted)]">{(texts.legacy as Record<string, string>)[key.legacy] ?? key.legacy}</span>}
            {listing.keys_wait && <KeyFactorHint texts={texts} securityHref="" compact />}
          </span>
        )
      case 'right':
        return (
          <span className="flex flex-col gap-0.5">
            <span>{rightLabel(texts, words, key.right)}</span>
            {key.areas !== null || listing.kinds.find((kind) => kind.id === key.kind)?.areas ? <span className="text-[var(--nexui-text-muted)]">{reach(key)}</span> : null}
          </span>
        )
      case 'expires':
        if (key.program) return <span className="text-[var(--nexui-text-muted)]">–</span>
        if (key.expired) return <Badge tone="danger" testId="key-expired">{texts.key.expired}</Badge>
        if (!key.expires_at) return <span className="text-[var(--nexui-text-muted)]">{texts.key.neverExpires}</span>
        return key.expiring ? (
          <Badge tone="warn" testId="key-expiring">{fillKeys(texts.key.expires, { date: when(key.expires_at, code) })}</Badge>
        ) : (
          <span>{fillKeys(texts.key.expires, { date: when(key.expires_at, code) })}</span>
        )
      case 'used':
        return <span className="text-[var(--nexui-text-muted)]">{key.last_used_at ? when(key.last_used_at, code) : texts.key.neverUsed}</span>
      case 'action':
        return (
          <span className="flex flex-wrap justify-end gap-2 @min-[640px]:justify-start">
            {extra?.(key)}
            {onEdit && editable(key) && (
              <Button kind={BUTTONS.edit.kind} icon={BUTTONS.edit.icon} size="sm" onClick={() => onEdit(key)} testId="key-edit">
                {texts.key.edit}
              </Button>
            )}
            <Button kind={BUTTONS.revoke.kind} icon={BUTTONS.revoke.icon} size="sm" onClick={() => onRevoke(key)} testId="key-revoke">
              {texts.key.revoke}
            </Button>
          </span>
        )
    }
  }
  return (
    <Table<KeyEntry, KeyColumn>
      label={label}
      columns={columns.map((key) => ({ key, label: texts.columns[key], width: COLUMN_WIDTHS[key] }))}
      rows={rows}
      cell={cell}
      rowKey={(key) => String(key.id)}
      rowProps={(key) => ({ 'data-testid': 'key-row', 'data-kind': key.kind, 'data-program': key.program ? 'true' : 'false' })}
      empty={empty}
      testId={testId}
    />
  )
}

/** The box that shows a new key this once: the key and the header to copy, then "Done". */
export function MadeBox({ texts, name, secret, app, onDone, children }: { texts: KeyTexts; name: string; secret: string; app: string; onDone: () => void; children?: ReactNode }) {
  return (
    <Box title={fillKeys(texts.key.made, { name })} hint={fillKeys(texts.key.madeText, { app })} testId="key-made">
      <CopyRow value={secret} label={texts.key.secret} testId="key-secret" />
      <CopyRow value={`Authorization: Bearer ${secret}`} label={texts.key.header} testId="key-header" />
      {children}
      <Buttons>
        <Button kind={BUTTONS.done.kind} icon={BUTTONS.done.icon} onClick={onDone} testId="key-done">
          {texts.key.done}
        </Button>
      </Buttons>
    </Box>
  )
}

/** The question before revoking. */
export function RevokeDialog({ texts, keyEntry, busy, error, onCancel, onConfirm }: { texts: KeyTexts; keyEntry: KeyEntry; busy: boolean; error?: string; onCancel: () => void; onConfirm: () => void }) {
  const kit = useNexuiTexts()
  return (
    <ConfirmDialog
      title={fillKeys(texts.key.askRevoke, { name: keyEntry.name ?? keyEntry.prefix })}
      text={texts.key.askRevokeText}
      confirm={{ label: texts.key.revoke, kind: BUTTONS.revoke.kind, icon: BUTTONS.revoke.icon }}
      cancel={texts.key.cancel}
      closeLabel={kit.close}
      busy={busy}
      error={error}
      onCancel={onCancel}
      onConfirm={onConfirm}
      testId="key-revoke-dialog"
    />
  )
}

type DialogState = { mode: 'new'; kind: KindChoice } | { mode: 'edit'; kind: KindChoice; key: KeyEntry }

/** Make or change a key: name, right, areas, extras, lifetime (only when making, and only where the app knows one). */
export function KeyDialog({
  state,
  request,
  base,
  texts,
  words,
  keysWait,
  securityHref,
  onClose,
  onMade,
  onChanged,
}: {
  state: DialogState
  request: KeyRequest
  base: string
  texts: KeyTexts
  words?: AppWords
  keysWait: boolean
  securityHref: string
  onClose: () => void
  onMade: (made: { key: KeyEntry; secret: string | null }) => void
  onChanged: (key: KeyEntry) => void
}) {
  const kit = useNexuiTexts()
  const { kind } = state
  const editing = state.mode === 'edit' ? state.key : null
  const startRight = editing?.right ?? kind.default_right ?? kind.rights[0] ?? ''
  const [name, setName] = useState(editing?.name ?? '')
  const [right, setRight] = useState(startRight)
  const [days, setDays] = useState(daysValue(defaultDays(kind, startRight)))
  const [daysTouched, setDaysTouched] = useState(false)
  const [allAreas, setAllAreas] = useState(editing ? editing.areas === null : !kind.areas_required)
  const [areas, setAreas] = useState<string[]>(Array.isArray(editing?.areas) ? editing.areas.map((area) => String(area.id)) : [])
  const [options, setOptions] = useState<Record<string, boolean>>(Object.fromEntries(kind.options.map((option) => [option, editing?.options[option] ?? false])))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [clientRef] = useState(newClientRef)

  const pickRight = (value: string) => {
    setRight(value)
    if (!daysTouched) setDays(daysValue(defaultDays(kind, value)))
  }

  const areaIds = () => (kind.areas ?? []).filter((area) => areas.includes(String(area.id))).map((area) => area.id)

  const submit = async () => {
    setBusy(true)
    setError(undefined)
    try {
      if (editing) {
        const body: Record<string, unknown> = { name, right, options }
        if (kind.areas) body.areas = allAreas ? null : areaIds()
        onChanged(await request<KeyEntry>(`${base}/keys/${encodeURIComponent(String(editing.id))}`, { method: 'PATCH', body }))
      } else {
        const body: NewKeyBody = { kind: kind.id, name, right, options, client_ref: clientRef }
        if (kind.areas) body.areas = allAreas ? 'all' : areaIds()
        if (kind.expiry_days !== null) body.days = daysOf(days)
        onMade(await request<{ key: KeyEntry; secret: string | null }>(`${base}/keys`, { method: 'POST', body }))
      }
    } catch (failure) {
      setError(refusalText(texts, failure))
    } finally {
      setBusy(false)
    }
  }

  const title = editing ? texts.key.editTitle : kind.id === 'mcp' ? texts.key.newMcpTitle : texts.key.newTitle
  const done = editing ? { label: texts.key.save, ...BUTTONS.save } : { label: texts.key.create, ...BUTTONS.create }
  return (
    <Dialog title={title} onClose={onClose} closeLabel={kit.close} testId="key-dialog">
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (!busy) void submit()
        }}
      >
        {keysWait && !editing && <KeyFactorHint texts={texts} securityHref={securityHref} />}
        <Field label={texts.key.name} hints={[texts.key.nameHint]} value={name} maxLength={kind.name_max} required onChange={(event) => setName(event.target.value)} data-testid="key-name" />
        {kind.rights.length > 1 && (
          <Segment<string>
            label={texts.key.right}
            hints={words?.rightHints?.[right] ? [words.rightHints[right]] : []}
            value={right}
            onChange={pickRight}
            options={kind.rights.map((value) => ({ value, label: rightLabel(texts, words, value), testId: `key-right-${value}` }))}
            testId="key-right"
          />
        )}
        {kind.areas && (
          <div className="flex flex-col gap-2" data-testid="key-areas">
            {kind.areas.length === 0 ? (
              <Notice tone="warn">{texts.key.areasNone}</Notice>
            ) : (
              <>
                {!kind.areas_required && (
                  <Segment<'all' | 'some'>
                    label={words?.areas ?? texts.key.areas}
                    value={allAreas ? 'all' : 'some'}
                    onChange={(value) => setAllAreas(value === 'all')}
                    options={[
                      { value: 'all', label: words?.areasAll ?? texts.key.areasAll, testId: 'key-areas-all' },
                      { value: 'some', label: words?.areasSome ?? texts.key.areasSome, testId: 'key-areas-some' },
                    ]}
                  />
                )}
                {kind.areas_required && <span className="text-sm leading-5 font-medium text-[var(--nexui-text)]">{words?.areas ?? texts.key.areas}</span>}
                {!allAreas &&
                  kind.areas.map((area) => (
                    <Checkbox
                      key={String(area.id)}
                      label={area.name ?? String(area.id)}
                      checked={areas.includes(String(area.id))}
                      onChange={(on) => setAreas(on ? [...areas, String(area.id)] : areas.filter((id) => id !== String(area.id)))}
                      testId={`key-area-${area.id}`}
                    />
                  ))}
              </>
            )}
          </div>
        )}
        {kind.options.map((option) => (
          <CheckboxRow
            key={option}
            label={optionLabel(texts, words, option)}
            hint={optionHint(texts, words, option)}
            checked={options[option] ?? false}
            onChange={(on) => setOptions({ ...options, [option]: on })}
            testId={`key-option-${option}`}
          />
        ))}
        {!editing && kind.expiry_days !== null && (
          <SelectField
            label={texts.key.expiry}
            value={days}
            onChange={(event) => {
              setDaysTouched(true)
              setDays(event.target.value)
            }}
            options={kind.expiry_days.map((value) => ({
              value: daysValue(value),
              label: value === null ? texts.key.never : value === 365 ? texts.key.year : fillKeys(texts.key.days, { days: value }),
            }))}
            data-testid="key-expiry"
          />
        )}
        {error && (
          <p role="alert" className="m-0 text-sm leading-5 text-[var(--nexui-danger)]" data-testid="key-error">
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2">
          <Button kind="secondary" icon="X" onClick={onClose}>
            {texts.key.cancel}
          </Button>
          <Button type="submit" kind={done.kind} icon={done.icon} busy={busy} disabled={!name.trim() || (kind.areas !== null && !allAreas && areas.length === 0)} testId="key-submit">
            {done.label}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

export type { DialogState }
