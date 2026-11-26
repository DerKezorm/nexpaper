/**
 * The operator's settings of MCP, in the place `after.mcp` of schluessel's `InterfacesCard` (Server › Allgemein ›
 * Schnittstellen): "Programme dürfen sich verbinden" (`CheckboxRow`), "Höchste Stufe" (`Segment`, the app's words for
 * its levels) and "Gesperrte Werkzeuge" (folded, one `CheckboxRow` per tool, ticked = blocked). Like the switches of
 * the card each change is saved at once (`PUT <base>/admin` with just that part), since 1.1.2 with a short "Gespeichert."
 * (MCP 21); switching off deletes nothing.
 *
 * Copied unchanged into frontend/src/vendor/nexmcp/ by bauplaene/mcp/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState } from 'react'

import { Badge, CheckboxRow, Collapsible, Notice, Segment } from '../nexui'
import { MCP_BASE, fillMcp, groupLabel, levelLabel, refusalText, toolLabel, useMcpTexts, type McpAdmin, type McpRequest, type McpWords } from './mcp'

export type McpOperatorSettingsProps = {
  request: McpRequest
  base?: string
  words?: McpWords
  language?: string
  testId?: string
}

type Change = Partial<Pick<McpAdmin, 'programs' | 'max_level' | 'blocked_tools'>>

export function McpOperatorSettings({ request, base = MCP_BASE, words, language, testId = 'mcp-operator' }: McpOperatorSettingsProps) {
  const { texts } = useMcpTexts(language)
  const [state, setState] = useState<McpAdmin | null>(null)
  const [problem, setProblem] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)

  const load = useCallback(() => request<McpAdmin>(`${base}/admin`), [request, base])
  useEffect(() => {
    load().then(setState, (failure: unknown) => setProblem(refusalText(texts, failure)))
  }, [load, texts])

  const change = async (body: Change) => {
    setBusy(true)
    setProblem(undefined)
    setSaved(false)
    try {
      setState(await request<McpAdmin>(`${base}/admin`, { method: 'PUT', body }))
      setSaved(true)
    } catch (failure) {
      setProblem(refusalText(texts, failure))
    } finally {
      setBusy(false)
    }
  }

  const blocked = state?.blocked_tools ?? []
  return (
    <div className="flex flex-col gap-3" data-testid={testId}>
      {problem && (
        <Notice tone="danger" testId="mcp-operator-problem">
          {problem}
        </Notice>
      )}
      {state && (
        <>
          <CheckboxRow
            label={texts.operator.programs}
            hint={texts.operator.programsHint}
            checked={state.programs}
            disabled={busy}
            onChange={(on) => void change({ programs: on })}
            testId="mcp-operator-programs"
          />
          <Segment<string>
            label={texts.operator.maxLevel}
            hints={[texts.operator.maxLevelHint]}
            value={state.max_level}
            disabled={busy}
            onChange={(value) => void change({ max_level: value })}
            options={state.levels.map((value) => ({ value, label: levelLabel(texts, words, value), testId: `mcp-operator-level-${value}` }))}
            testId="mcp-operator-level"
          />
          <Collapsible
            title={texts.operator.blocked}
            subtitle={texts.operator.blockedHint}
            status={
              <Badge tone={blocked.length ? 'warn' : 'off'} testId="mcp-operator-blocked-count">
                {blocked.length ? fillMcp(texts.operator.blockedCount, { count: blocked.length }) : texts.operator.blockedNone}
              </Badge>
            }
            testId="mcp-operator-blocked"
          >
            {state.tools.map((tool) => (
              <CheckboxRow
                key={tool.name}
                label={toolLabel(texts, words, tool.name)}
                hint={groupLabel(texts, tool.group)}
                checked={blocked.includes(tool.name)}
                disabled={busy}
                onChange={(on) => void change({ blocked_tools: on ? [...blocked, tool.name] : blocked.filter((name) => name !== tool.name) })}
                testId={`mcp-operator-block-${tool.name}`}
              />
            ))}
          </Collapsible>
          {saved && (
            <p className="m-0 text-xs leading-4 text-[var(--nexui-ok)]" role="status" data-testid="mcp-operator-saved">
              {texts.operator.saved}
            </p>
          )}
        </>
      )}
    </div>
  )
}
