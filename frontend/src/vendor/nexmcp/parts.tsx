/**
 * What the lists of requests share: the lines about one request (program, tool, what it wants, when it runs out) and its
 * buttons, "Ablehnen" (secondary `sm`, X) left of "Erlauben" (primary `sm`, Check; MCP 20); a dangerous request
 * gets "Ansehen" in place of "Erlauben", since it is allowed only on its own page after a second question. Built only
 * from the ui kit.
 *
 * Copied unchanged into frontend/src/vendor/nexmcp/ by bauplaene/mcp/tools/sync.py; changed only there.
 */
import { Badge, Button } from '../nexui'
import { MCP_BUTTONS, argumentsShort, fillMcp, toolLabel, type McpTexts, type McpWords, type ToolRequest, type WhenFormat } from './mcp'

/** The program's name (the key's, for a key made by hand). */
export function RequestProgram({ entry, texts }: { entry: ToolRequest; texts: McpTexts }) {
  return <span data-testid="request-program">{entry.key_name ?? texts.request.unknownProgram}</span>
}

/** The mark of a dangerous request. */
export function DangerBadge({ texts }: { texts: McpTexts }) {
  return (
    <Badge tone="danger" testId="request-dangerous">
      {texts.requests.dangerous}
    </Badge>
  )
}

/** Tool (the app's word), what it wants (its summary, else its arguments in short), when it runs out. */
export function RequestDetails({ entry, texts, code, words, when }: { entry: ToolRequest; texts: McpTexts; code: string; words?: McpWords; when: WhenFormat }) {
  const what = entry.summary || argumentsShort(entry.arguments) || texts.requests.noArguments
  return (
    <>
      <span className="block text-[var(--nexui-text)]" data-testid="request-tool">
        {toolLabel(texts, words, entry.tool)}
      </span>
      <span className="block" data-testid="request-what">
        {what}
      </span>
      <span className="block" data-testid="request-expires">
        {fillMcp(texts.requests.expires, { when: when(entry.expires_at, code) })}
      </span>
    </>
  )
}

/** "Ablehnen", then "Erlauben" (or "Ansehen" for a dangerous one). */
export function RequestButtons({
  entry,
  texts,
  busy,
  viewHref,
  onView,
  onApprove,
  onDecline,
}: {
  entry: ToolRequest
  texts: McpTexts
  busy: boolean
  viewHref?: (entry: ToolRequest) => string
  onView?: (entry: ToolRequest) => void
  onApprove: () => void
  onDecline: () => void
}) {
  const canView = viewHref !== undefined || onView !== undefined
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Button kind={MCP_BUTTONS.decline.kind} icon={MCP_BUTTONS.decline.icon} size="sm" disabled={busy} onClick={onDecline} testId="request-decline">
        {texts.requests.decline}
      </Button>
      {entry.dangerous
        ? canView && (
            <Button
              kind={MCP_BUTTONS.view.kind}
              icon={MCP_BUTTONS.view.icon}
              size="sm"
              href={viewHref?.(entry)}
              onClick={onView ? () => onView(entry) : undefined}
              testId="request-view"
            >
              {texts.requests.view}
            </Button>
          )
        : (
            <Button kind={MCP_BUTTONS.approveRow.kind} icon={MCP_BUTTONS.approveRow.icon} size="sm" disabled={busy} onClick={onApprove} testId="request-approve">
              {texts.requests.approve}
            </Button>
          )}
    </span>
  )
}
