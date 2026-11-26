// nexmcp in the browser: what the module's routes answer, the buttons, the module's words and their helpers. The parts
// themselves are ToolRights.tsx, PendingRequests.tsx, RequestPage.tsx, RequestBellRow.tsx, ConsentPage.tsx and
// McpOperatorSettings.tsx (built from the ui kit). Copied unchanged into frontend/src/vendor/nexmcp/ by
// bauplaene/mcp/tools/sync.py; changed only there.

import { NEXUI_TEXTS, languageOf, useNexuiTexts } from '../nexui'

import de from './mcp.de.json'
import en from './mcp.en.json'
import fr from './mcp.fr.json'

/** The groups of tools, in the order of the list "Rechte je Werkzeug". */
export const TOOL_GROUPS = ['read', 'draft', 'change', 'risky', 'admin'] as const
export type ToolGroup = (typeof TOOL_GROUPS)[number]

/** What a key may do with a tool: run it, ask first, or not see it at all. */
export const TOOL_RIGHTS = ['allow', 'ask', 'deny'] as const
export type ToolRight = (typeof TOOL_RIGHTS)[number]

/** One tool as `GET <base>/tools` lists it. */
export type ToolInfo = {
  name: string
  group: ToolGroup
  level: string
  description: string
  admin_only: boolean
  /** The extra a key needs for it (`null`: none). */
  needs: string | null
  /** The module's own `request_status`: never denied, never blocked, never shown in the lists. */
  always: boolean
  blocked: boolean
  default: ToolRight
}

/** `GET <base>/tools`. */
export type ToolListing = { levels: string[]; max_level: string; extras: string[]; tools: ToolInfo[] }

/** Why a tool is out of reach for a key whatever its right says. */
export type ToolReason = 'blocked' | 'level' | 'admin' | 'extra'

/** One row of `GET <base>/keys/{id}/rights`. */
export type KeyToolRight = {
  name: string
  group: ToolGroup
  right: ToolRight
  /** A tool that only looks is never asked about: no "Fragen". */
  asks_never: boolean
  reason: ToolReason | null
  always: boolean
}

/** `GET` and `PUT <base>/keys/{id}/rights`. */
export type KeyRights = {
  key: { id: number | string; name: string | null; program: boolean }
  level: string
  tools: KeyToolRight[]
}

export type RequestStatus = 'waiting' | 'running' | 'done' | 'failed' | 'declined' | 'expired'

/** A request of a program, waiting for the account's answer or decided (`GET <base>/requests`). */
export type ToolRequest = {
  id: number | string
  key_id: number | string
  /** The program or key that asks. */
  key_name: string | null
  tool: string
  arguments: Record<string, unknown>
  summary: string | null
  /** Runs only after a second question ("Wirklich erlauben?"). */
  dangerous: boolean
  status: RequestStatus
  created_at: string
  expires_at: string
  decided_at: string | null
  decided_by: string | null
  result: unknown
}

/** `GET` and `PUT <base>/admin`, the operator's settings. */
export type McpAdmin = {
  programs: boolean
  levels: string[]
  max_level: string
  blocked_tools: string[]
  tools: { name: string; group: ToolGroup; level: string }[]
}

/** `GET <oauthBase>/authorize`: what the consent page shows. */
export type ConsentInfo = {
  app: string
  client: { id: string; name: string }
  redirect_uri: string
  redirect_host: string
  /** The levels the operator allows, lowest first. */
  levels: string[]
  level: string
  areas: { id: number | string; name: string }[]
  extras: string[]
  ai_allowed: boolean
}

/** The values of the consent page's address that go back to the server, in this order. */
export const CONSENT_PARAMS = ['client_id', 'redirect_uri', 'response_type', 'code_challenge', 'code_challenge_method', 'state', 'resource', 'scope'] as const

/** The app's way to call its server (its own client with its headers), as for the cards of schluessel. A refusal
 * throws; the parts read its code with `refusalCode`. */
export type McpRequest = <T>(path: string, init?: { method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'; body?: unknown }) => Promise<T>

/** Where the module's routes for the account and the operator are mounted, and its OAuth routes. */
export const MCP_BASE = '/api/connections/mcp'
export const OAUTH_BASE = '/api/oauth'

/** Kind and symbol of every button. Since 1.1.2 (MCP 20) the pair is the same everywhere: "Ablehnen" secondary with X
 * on the left, "Erlauben" primary with Check on the right, also in the rows of "Wartende Rückfragen". Only the second
 * question before a dangerous request says yes with `danger` ("Ja, wirklich erlauben", MCP 22). */
export const MCP_BUTTONS = {
  rights: { kind: 'secondary', icon: 'SlidersHorizontal' },
  save: { kind: 'primary', icon: 'Check' },
  cancel: { kind: 'secondary', icon: 'X' },
  close: { kind: 'secondary', icon: 'X' },
  approve: { kind: 'primary', icon: 'Check' },
  approveRow: { kind: 'primary', icon: 'Check' },
  confirmApprove: { kind: 'danger', icon: 'Check' },
  decline: { kind: 'secondary', icon: 'X' },
  view: { kind: 'secondary', icon: 'ArrowRight' },
  allow: { kind: 'primary', icon: 'Check' },
  refuse: { kind: 'secondary', icon: 'X' },
} as const

export type McpTexts = typeof de
export const MCP_TEXTS: Record<'de' | 'en' | 'fr', McpTexts> = { de, en, fr }

/** Words the app brings: its name for each tool, level and extra (German "Notiz lesen", "Nur lesen", "Mailtext"). */
export type McpWords = {
  tools?: Record<string, string>
  levels?: Record<string, string>
  levelHints?: Record<string, string>
  extras?: Record<string, string>
  extraHints?: Record<string, string>
}

/** Fills `{name}`, `{app}`, `{host}` … */
export function fillMcp(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key] ?? '') : whole))
}

/** The app's word for a tool, else the module's (its own `request_status`), else the tool's name. */
export function toolLabel(texts: McpTexts, words: McpWords | undefined, name: string): string {
  return words?.tools?.[name] ?? (texts.toolNames as Record<string, string>)[name] ?? name
}

export function levelLabel(texts: McpTexts, words: McpWords | undefined, level: string): string {
  return words?.levels?.[level] ?? (texts.levels as Record<string, string>)[level] ?? level
}

export function extraLabel(words: McpWords | undefined, extra: string): string {
  return words?.extras?.[extra] ?? extra
}

export function groupLabel(texts: McpTexts, group: string): string {
  return (texts.groups as Record<string, string>)[group] ?? group
}

/** The code of a refused request: the module's `{code}` in FastAPI's `detail`, or on the error itself. */
export function refusalCode(error: unknown): string | undefined {
  const found = error as { code?: unknown; detail?: unknown; body?: unknown } | null
  const inner = (found?.detail ?? (found?.body as { detail?: unknown } | undefined)?.detail ?? found) as { code?: unknown } | string | null
  if (typeof inner === 'string') return inner
  return typeof inner?.code === 'string' ? inner.code : undefined
}

/** The words of a refusal of the module. */
export function refusalText(texts: McpTexts, error: unknown): string {
  const code = refusalCode(error)
  return (code ? (texts.errors as Record<string, string>)[code] : undefined) ?? texts.failed
}

/** Answers a request: `approve` (with `confirm: true` only for a dangerous one the account confirmed a second time) or
 * `decline`. Returns the request as the server keeps it afterwards. */
export function decideRequest(request: McpRequest, base: string, entry: ToolRequest, answer: 'approve' | 'decline', confirmed = false): Promise<ToolRequest> {
  const path = `${base}/requests/${encodeURIComponent(String(entry.id))}/${answer}`
  return answer === 'approve' && confirmed ? request<ToolRequest>(path, { method: 'POST', body: { confirm: true } }) : request<ToolRequest>(path, { method: 'POST' })
}

/** The arguments of a request in one short line (a row of the list, the bell). */
export function argumentsShort(args: Record<string, unknown>, max = 80): string {
  const parts = Object.entries(args).map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
  const line = parts.join(', ')
  return line.length > max ? `${line.slice(0, max - 1)}…` : line
}

/** How a moment is written; the app may give its own (nextime: the account's zone). */
export type WhenFormat = (iso: string, language: string) => string

/** Day and time: a request runs out within a day, so the hour matters. */
export function defaultWhen(iso: string, language: string): string {
  const moment = new Date(iso)
  return Number.isNaN(moment.getTime()) ? iso : moment.toLocaleString(language, { dateStyle: 'medium', timeStyle: 'short' })
}

/** The module's words in the kit's language (or the one given). */
export function useMcpTexts(language?: string): { texts: McpTexts; code: 'de' | 'en' | 'fr' } {
  const kit = useNexuiTexts()
  if (language) {
    const code = languageOf(language)
    return { texts: MCP_TEXTS[code], code }
  }
  const code = (Object.keys(NEXUI_TEXTS) as (keyof typeof NEXUI_TEXTS)[]).find((key) => NEXUI_TEXTS[key] === kit) ?? 'en'
  return { texts: MCP_TEXTS[code], code }
}
