/**
 * AI tools (the shared MCP module, mcp 1.1.0) in nexpaper: the card "KI-Werkzeuge (MCP)" in My account › Connections
 * (schluessel's `ToolsCard`, place 6) with "Rechte je Werkzeug" per key and the requests waiting for a yes, the
 * operator's settings after the switch "MCP-Zugang" in Server › General › Schnittstellen, the consent page
 * "Programm verbinden" (`/mcp/authorize`; `/oauth/authorize` is the iPhone app's pairing and stays) and the page of one
 * request (`/mcp/requests/<id>`, where a notice of a waiting request leads). Only the module's parts from the ui kit;
 * nexpaper gives its words for the tools, the levels and the vaults.
 */
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { shortDate } from '../../lib/dates'
import { ConsentPage, McpOperatorSettings, PendingRequests, RequestPage, ToolRights, type McpRequest, type McpWords } from '../../vendor/nexmcp'
import { ToolsCard } from '../../vendor/nexschluessel'
import { KEYS_AT, keyRequest } from './KeysCards'

/** Where the module's routes for the account and the operator are mounted, and its OAuth for programs. */
export const MCP_AT = '/api/v1/connections/mcp'
export const OAUTH_AT = '/api/oauth'

/** nexpaper's tools, in the order of the server. */
const TOOLS = ['list_vaults', 'search_documents', 'read_document', 'list_inbox', 'list_deadlines', 'accept_suggestions', 'set_document_fields', 'trash_document'] as const

// Through nexpaper's client; a function, not the client itself: KeysCards imports this file too.
const mcpRequest: McpRequest = (path, init) => keyRequest(path, init)

/** nexpaper's words for its tools and levels (de, en, fr). */
// eslint-disable-next-line react-refresh/only-export-components
export function useMcpWords(): McpWords {
  const { t } = useTranslation()
  return {
    tools: Object.fromEntries(TOOLS.map((name) => [name, t(`mcp.tools.${name}`)])),
    levels: { read: t('mcp.levels.read'), write: t('mcp.levels.write') },
    levelHints: { read: t('mcp.levels.readHint'), write: t('mcp.levels.writeHint') },
  }
}

/** My account › Connections, place 6: "KI-Werkzeuge (MCP)". */
export function AiTools() {
  const { i18n } = useTranslation()
  const words = useMcpWords()
  return (
    <ToolsCard
      request={keyRequest}
      base={KEYS_AT}
      language={i18n.language}
      when={(iso, language) => shortDate(iso, language)}
      extra={(key) => (key.kind === 'mcp' ? <ToolRights request={mcpRequest} keyId={key.id} base={MCP_AT} words={words} language={i18n.language} /> : null)}
    >
      <PendingRequests request={mcpRequest} base={MCP_AT} words={words} language={i18n.language} viewHref={(entry) => `/mcp/requests/${entry.id}`} />
    </ToolsCard>
  )
}

/** Server › General › Schnittstellen, after "MCP-Zugang": programs, the highest level, blocked tools. */
export function McpOperator() {
  const { i18n } = useTranslation()
  return <McpOperatorSettings request={mcpRequest} base={MCP_AT} words={useMcpWords()} language={i18n.language} />
}

/** `/mcp/authorize`: a program asks to work as the signed-in account. */
export function McpConsentPage() {
  const { t, i18n } = useTranslation()
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col justify-center px-4 py-10">
      <ConsentPage request={mcpRequest} oauthBase={OAUTH_AT} areaWord={t('mcp.vaults')} words={useMcpWords()} language={i18n.language} />
    </div>
  )
}

/** `/mcp/requests/<id>`: one request of a program, to allow or turn down. */
export function McpRequestPage() {
  const { i18n } = useTranslation()
  const { id } = useParams()
  const navigate = useNavigate()
  const number = Number(id)
  return (
    <div className="mx-auto max-w-2xl px-4 py-6">
      <RequestPage
        request={mcpRequest}
        id={Number.isInteger(number) && number > 0 ? number : 0}
        base={MCP_AT}
        words={useMcpWords()}
        language={i18n.language}
        when={(iso) => shortDate(iso, i18n.language)}
        onDecided={() => navigate('/settings/connections')}
      />
    </div>
  )
}
