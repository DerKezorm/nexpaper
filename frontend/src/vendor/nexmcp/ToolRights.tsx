/**
 * "Rechte je Werkzeug" for one key or connected program, in the place `extra(key)` of schluessel's `ToolsCard`: a `sm`
 * secondary button opens a dialog with a table, per tool its name (the app's word), its group and a `Segment`
 * Erlauben/Fragen/Verweigern (without "Fragen" for a tool that only looks). A tool out of reach whatever its right says
 * (blocked by the operator, above the key's level, only for operators, needs an extra) stands greyed with the reason.
 * The module's own `request_status` is never shown. "Speichern" sends every right of the list at once.
 *
 * Copied unchanged into frontend/src/vendor/nexmcp/ by bauplaene/mcp/tools/sync.py; changed only there.
 */
import { useState } from 'react'

import { Button, Dialog, Notice, Segment, Table, useNexuiTexts, type SegmentOption } from '../nexui'
import {
  MCP_BASE,
  MCP_BUTTONS,
  fillMcp,
  groupLabel,
  levelLabel,
  refusalText,
  toolLabel,
  useMcpTexts,
  type KeyRights,
  type KeyToolRight,
  type McpRequest,
  type McpTexts,
  type McpWords,
  type ToolRight,
} from './mcp'

export type ToolRightsProps = {
  request: McpRequest
  /** The key's or program's `id` (`KeyEntry.id` of schluessel). */
  keyId: number | string
  base?: string
  words?: McpWords
  language?: string
  /** Called with what the server keeps after "Speichern". */
  onSaved?: (rights: KeyRights) => void
  testId?: string
}

type Column = 'tool' | 'group' | 'right'

function rightOptions(texts: McpTexts, row: KeyToolRight): SegmentOption<ToolRight>[] {
  const all: SegmentOption<ToolRight>[] = [
    { value: 'allow', label: texts.rights.allow, testId: 'tool-right-allow' },
    { value: 'ask', label: texts.rights.ask, testId: 'tool-right-ask' },
    { value: 'deny', label: texts.rights.deny, testId: 'tool-right-deny' },
  ]
  return row.asks_never ? all.filter((option) => option.value !== 'ask') : all
}

export function ToolRights({ request, keyId, base = MCP_BASE, words, language, onSaved, testId = 'tool-rights' }: ToolRightsProps) {
  const { texts } = useMcpTexts(language)
  const kit = useNexuiTexts()
  const [open, setOpen] = useState(false)
  const [rights, setRights] = useState<KeyRights | null>(null)
  const [chosen, setChosen] = useState<Record<string, ToolRight>>({})
  const [problem, setProblem] = useState<string>()
  const [busy, setBusy] = useState(false)
  const path = `${base}/keys/${encodeURIComponent(String(keyId))}/rights`

  const take = (answer: KeyRights) => {
    setRights(answer)
    setChosen(Object.fromEntries(answer.tools.filter((row) => !row.always).map((row) => [row.name, row.right])))
  }

  const show = async () => {
    setOpen(true)
    setProblem(undefined)
    setRights(null)
    try {
      take(await request<KeyRights>(path))
    } catch (failure) {
      setProblem(refusalText(texts, failure))
    }
  }

  const save = async () => {
    setBusy(true)
    setProblem(undefined)
    try {
      const answer = await request<KeyRights>(path, { method: 'PUT', body: { rights: chosen } })
      take(answer)
      onSaved?.(answer)
      setOpen(false)
    } catch (failure) {
      setProblem(refusalText(texts, failure))
    } finally {
      setBusy(false)
    }
  }

  const rows = rights?.tools.filter((row) => !row.always) ?? []
  const cell = (row: KeyToolRight, column: Column) => {
    const out = row.reason !== null
    switch (column) {
      case 'tool':
        return (
          <span className={`flex flex-col gap-0.5${out ? ' opacity-60' : ''}`}>
            <span className="font-medium">{toolLabel(texts, words, row.name)}</span>
            {out && (
              <span className="text-[var(--nexui-text-muted)]" data-testid="tool-right-reason">
                {texts.reasons[row.reason as keyof McpTexts['reasons']]}
              </span>
            )}
          </span>
        )
      case 'group':
        return <span className={out ? 'text-[var(--nexui-text-muted)] opacity-60' : 'text-[var(--nexui-text-muted)]'}>{groupLabel(texts, row.group)}</span>
      case 'right':
        return (
          <Segment<ToolRight>
            label={`${texts.rights.right}: ${toolLabel(texts, words, row.name)}`}
            hideLabel
            value={chosen[row.name] ?? row.right}
            onChange={(value) => setChosen({ ...chosen, [row.name]: value })}
            options={rightOptions(texts, row)}
            disabled={out || busy}
            testId="tool-right"
          />
        )
    }
  }

  return (
    <>
      <Button kind={MCP_BUTTONS.rights.kind} icon={MCP_BUTTONS.rights.icon} size="sm" onClick={() => void show()} testId={testId}>
        {texts.rights.open}
      </Button>
      {open && (
        <Dialog title={fillMcp(texts.rights.title, { name: rights?.key.name ?? '' })} onClose={() => setOpen(false)} closeLabel={kit.close} wide testId="tool-rights-dialog">
          <div className="flex flex-col gap-4">
            <p className="m-0 text-sm leading-5 text-[var(--nexui-text)]">{texts.rights.hint}</p>
            {rights && (
              <p className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]" data-testid="tool-rights-level">
                {fillMcp(texts.rights.level, { level: levelLabel(texts, words, rights.level) })}
              </p>
            )}
            {problem && (
              <Notice tone="danger" testId="tool-rights-problem">
                {problem}
              </Notice>
            )}
            {rights && (
              <Table<KeyToolRight, Column>
                label={texts.rights.table}
                columns={[
                  { key: 'tool', label: texts.rights.tool },
                  { key: 'group', label: texts.rights.group, width: '7rem' },
                  { key: 'right', label: texts.rights.right, width: '17rem' },
                ]}
                rows={rows}
                cell={cell}
                rowKey={(row) => row.name}
                rowProps={(row) => ({
                  'data-testid': 'tool-right-row',
                  'data-tool': row.name,
                  'data-group': row.group,
                  'data-reason': row.reason ?? undefined,
                  'data-disabled': row.reason !== null ? 'true' : 'false',
                })}
                testId="tool-rights-table"
              />
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button kind={MCP_BUTTONS.cancel.kind} icon={MCP_BUTTONS.cancel.icon} onClick={() => setOpen(false)} testId="tool-rights-cancel">
                {texts.rights.cancel}
              </Button>
              <Button kind={MCP_BUTTONS.save.kind} icon={MCP_BUTTONS.save.icon} busy={busy} disabled={!rights} onClick={() => void save()} testId="tool-rights-save">
                {texts.rights.save}
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </>
  )
}
