/**
 * "Rechte je Werkzeug" for one key or connected program, in the place `extra(key)` of schluessel's `ToolsCard`: a `sm`
 * secondary button opens a dialog with one row per tool, its name (the app's word) and group on the left, a `Segment`
 * Erlauben/Fragen/Verweigern on the right (without "Fragen" for a tool that only looks). A tool out of reach whatever
 * its right says (blocked by the operator, above the key's level, only for operators, needs an extra) stands greyed
 * with the reason. The module's own `request_status` is never shown.
 *
 * Since 1.1.2: a choice is kept at once (MCP 21: switches save themselves, with a short "Gespeichert."), the rows are
 * a list, not a table that stacks in a narrow window (M-4), and from 15 tools a search field finds one (M-11).
 *
 * Copied unchanged into frontend/src/vendor/nexmcp/ by bauplaene/mcp/tools/sync.py; changed only there.
 */
import { useState } from 'react'

import { Button, Dialog, Field, Notice, Rows, Segment, useNexuiTexts, type SegmentOption } from '../nexui'
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
  /** Called with what the server keeps after each change. */
  onSaved?: (rights: KeyRights) => void
  testId?: string
}

/** From this many tools the list has a search field (M-11). */
export const SEARCH_FROM = 15

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
  const [saved, setSaved] = useState(false)
  const [search, setSearch] = useState('')
  const path = `${base}/keys/${encodeURIComponent(String(keyId))}/rights`

  const take = (answer: KeyRights) => {
    setRights(answer)
    setChosen(Object.fromEntries(answer.tools.filter((row) => !row.always).map((row) => [row.name, row.right])))
  }

  const show = async () => {
    setOpen(true)
    setProblem(undefined)
    setSaved(false)
    setSearch('')
    setRights(null)
    try {
      take(await request<KeyRights>(path))
    } catch (failure) {
      setProblem(refusalText(texts, failure))
    }
  }

  const save = async (name: string, value: ToolRight) => {
    const next = { ...chosen, [name]: value }
    setChosen(next)
    setBusy(true)
    setProblem(undefined)
    setSaved(false)
    try {
      const answer = await request<KeyRights>(path, { method: 'PUT', body: { rights: next } })
      take(answer)
      onSaved?.(answer)
      setSaved(true)
    } catch (failure) {
      setProblem(refusalText(texts, failure))
      if (rights) take(rights)
    } finally {
      setBusy(false)
    }
  }

  const rows = rights?.tools.filter((row) => !row.always) ?? []
  const needle = search.trim().toLowerCase()
  const shown = needle
    ? rows.filter((row) => `${toolLabel(texts, words, row.name)} ${row.name}`.toLowerCase().includes(needle))
    : rows

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
            {rights && rows.length >= SEARCH_FROM && (
              <Field
                label={texts.rights.search}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                type="search"
                maxLength={100}
                data-testid="tool-rights-search"
              />
            )}
            {rights && (
              <Rows label={texts.rights.table} testId="tool-rights-table">
                {shown.map((row) => {
                  const out = row.reason !== null
                  return (
                    <li
                      key={row.name}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2"
                      data-testid="tool-right-row"
                      data-tool={row.name}
                      data-group={row.group}
                      data-reason={row.reason ?? undefined}
                      data-disabled={out ? 'true' : 'false'}
                    >
                      <span className={`flex min-w-0 flex-1 flex-col gap-0.5 text-sm leading-5${out ? ' opacity-60' : ''}`}>
                        <span className="font-medium text-[var(--nexui-text)]">{toolLabel(texts, words, row.name)}</span>
                        <span className="text-xs leading-4 text-[var(--nexui-text-muted)]">
                          {groupLabel(texts, row.group)}
                          {out && (
                            <span data-testid="tool-right-reason">
                              {' · '}
                              {texts.reasons[row.reason as keyof McpTexts['reasons']]}
                            </span>
                          )}
                        </span>
                      </span>
                      <Segment<ToolRight>
                        label={`${texts.rights.right}: ${toolLabel(texts, words, row.name)}`}
                        hideLabel
                        value={chosen[row.name] ?? row.right}
                        onChange={(value) => void save(row.name, value)}
                        options={rightOptions(texts, row)}
                        disabled={out || busy}
                        testId="tool-right"
                      />
                    </li>
                  )
                })}
              </Rows>
            )}
            {saved && (
              <p className="m-0 text-xs leading-4 text-[var(--nexui-ok)]" role="status" data-testid="tool-rights-saved">
                {texts.rights.saved}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button kind={MCP_BUTTONS.close.kind} icon={MCP_BUTTONS.close.icon} onClick={() => setOpen(false)} testId="tool-rights-close">
                {texts.rights.close}
              </Button>
            </div>
          </div>
        </Dialog>
      )}
    </>
  )
}
