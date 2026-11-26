/**
 * The cards of the shared key module (schluessel 1.0.0, plan "Einstellungen") with nexpaper's words: "API-Schlüssel" in
 * My account › Connections (a key reads or only uploads, nexpaper's sentences for both), "Schnittstellen" in Server ›
 * General (the switch "Programmschnittstelle (API) für Mitglieder"; before the card "Funktionen für alle Konten" and the
 * area "API"), "API-Schlüssel aller Konten" in Server › Accounts. The routes are the module's under
 * `/api/v1/connections`; nexpaper's older ways (`/api/v1/api-keys`, `/api/v1/admin/api-keys`) stay for nexpaper-ios, the
 * shortcut and scripts. Since mcp 1.1.0 the operator's settings of MCP follow its switch in "Schnittstellen"
 * (`McpCards.tsx`, which has the card "KI-Werkzeuge (MCP)" too).
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ApiError } from '../../api/client'
import { errorText } from '../../lib/errors'
import { shortDate } from '../../lib/dates'
import { useAuth } from '../../state/auth'
import { AllKeysCard, ApiKeysCard, InterfacesCard, type AppWords, type KeyRequest } from '../../vendor/nexschluessel'
import { Button, ConfirmDialog, CopyRow, Row, Rows, TextLink } from '../../vendor/nexui'
import { McpOperator } from './McpCards'

/** nexpaper's client for the cards (its headers, its errors with their codes). */
// eslint-disable-next-line react-refresh/only-export-components
export const keyRequest: KeyRequest = <T,>(path: string, init: Parameters<KeyRequest>[1] = {}) =>
  api<T>(path, { method: init.method, query: init.query, body: init.body })

/** Where the module's routes are mounted in nexpaper. */
export const KEYS_AT = '/api/v1/connections'

/** Where the programming interface is described. */
export const DOCS = '/api/v1/docs'

function useWords(): AppWords {
  const { t } = useTranslation()
  return { rightHints: { read: t('apiKeys.scope.readHint'), upload: t('apiKeys.scope.uploadHint') } }
}

/** My account › Connections, place 5: "API-Schlüssel", with nexpaper's own parts in the card's places (Bauplan E57,
 * schluessel 1.0.1): the operator's "Jetzt freigeben" in the note that keys are off, the curl command of a new key, and
 * at the end what a key for uploading may do, the limits of every key and how long a key should live. */
export function ApiKeys() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  // Allowing keys here reloads the card (its own list says whether keys are on).
  const [round, setRound] = useState(0)
  return (
    <ApiKeysCard
      key={round}
      request={keyRequest}
      base={KEYS_AT}
      things={t('settings.things')}
      thingsDative={t('settings.thingsDative')}
      words={useWords()}
      docsHref={DOCS}
      operator={me?.role === 'operator'}
      language={i18n.language}
      when={(iso, language) => shortDate(iso, language)}
      offAction={me?.role === 'operator' ? <AllowKeys onAllowed={() => setRound((count) => count + 1)} /> : undefined}
      made={({ name, secret }) => <TryIt name={name} secret={secret} />}
    >
      {/* nexpaper's own lines at the end of the card: what a key for uploading may do, and the limits of every key. */}
      <p className="m-0 text-xs text-[var(--nexui-text-muted)]" data-testid="keys-upload-note">
        {t('apiKeys.keyUploadNote')}
      </p>
      <p className="m-0 text-xs text-[var(--nexui-text-muted)]" data-testid="keys-limits">
        {t('apiKeys.keyLimits')}
      </p>
      {/* How long a key should live (in the window of a new key before the module). */}
      <p className="m-0 text-xs text-[var(--nexui-text-muted)]" data-testid="keys-lifetime">
        {t('apiKeys.lifetimeHint')} {t('apiKeys.lifetimeHintUpload')}
      </p>
    </ApiKeysCard>
  )
}

/** The operator allows API keys for everybody (the switch of Server › General › Interfaces), after a question. */
function AllowKeys({ onAllowed }: { onAllowed: () => void }) {
  const { t } = useTranslation()
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const allow = async () => {
    setBusy(true)
    setError('')
    try {
      await keyRequest(`${KEYS_AT}/interfaces`, { method: 'PUT', body: { api: true } })
      setAsking(false)
      onAllowed()
    } catch (problem) {
      setError(problem instanceof ApiError ? errorText(problem.code, problem.values) : errorText('internal_error'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Button kind="secondary" size="sm" icon="CircleCheck" onClick={() => setAsking(true)} testId="api-keys-allow">
        {t('apiKeys.enable')}
      </Button>
      {asking && (
        <ConfirmDialog
          title={t('apiKeys.enableTitle')}
          text={t('apiKeys.enableText')}
          confirm={{ label: t('apiKeys.enableConfirm'), kind: 'primary', icon: 'CircleCheck' }}
          cancel={t('common.cancel')}
          closeLabel={t('common.close')}
          busy={busy}
          error={error || undefined}
          onConfirm={() => void allow()}
          onCancel={() => setAsking(false)}
          testId="api-keys-allow-dialog"
        />
      )}
    </>
  )
}

/** "Zum Ausprobieren": the curl command for the new key, by what it may (an upload, or who it belongs to). */
export function TryIt({ name, secret }: { name: string; secret: string }) {
  const { t } = useTranslation()
  const [right, setRight] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    keyRequest<{ keys: { name: string; right: string }[] }>(`${KEYS_AT}/keys`).then(
      (found) => live && setRight(found.keys.find((key) => key.name === name)?.right ?? 'read'),
      () => live && setRight('read'),
    )
    return () => {
      live = false
    }
  }, [name])
  if (right === null) return null
  const origin = window.location.origin
  const command =
    right === 'upload'
      ? `curl -H "Authorization: Bearer ${secret}" -F file=@Rechnung.pdf ${origin}/api/v1/documents`
      : `curl -H "Authorization: Bearer ${secret}" ${origin}/api/v1/me`
  return (
    <div className="space-y-1" data-testid="key-try-it-part">
      <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t('apiKeys.tryIt')}</p>
      <CopyRow label={t('apiKeys.tryIt')} value={command} testId="key-try-it" />
    </div>
  )
}

/** Server › General, place 3: "Schnittstellen". */
export function Interfaces() {
  const { t, i18n } = useTranslation()
  // nexpaper's own rows at the end (before the area "API"): the machine-readable description, how a device connects
  // and how a program signs in; the description of the routes is the module's link.
  const rows: [string, string, string][] = [
    [t('server.interface.schema'), '/api/v1/openapi.json', t('server.interface.schemaText')],
    [t('server.interface.pair'), 'POST /api/v1/devices/pair', t('server.interface.pairText')],
    [t('server.interface.auth'), 'Authorization: Bearer …', t('server.interface.authText')],
  ]
  return (
    <InterfacesCard request={keyRequest} base={KEYS_AT} docsHref={DOCS} language={i18n.language} after={{ mcp: <McpOperator /> }}>
      <Rows label={t('server.interface.auth')} testId="interface-facts">
        {rows.map(([name, code, text]) => (
          <Row
            key={name}
            icon="Webhook"
            name={name}
            sub={text}
            detail={
              code.startsWith('/') ? (
                <a href={code} target="_blank" rel="noreferrer" className="font-mono underline underline-offset-2">
                  {code}
                </a>
              ) : (
                <code className="font-mono">{code}</code>
              )
            }
          />
        ))}
      </Rows>
    </InterfacesCard>
  )
}

/** Server › Accounts, place 4: "API-Schlüssel aller Konten", at its end the way to the own keys (as before the
 * module: "Eigene API-Schlüssel anlegen" leads to My account › Connections; schluessel 1.0.2, Bauplan E58). */
export function AllKeys() {
  const { t, i18n } = useTranslation()
  return (
    <AllKeysCard request={keyRequest} base={KEYS_AT} words={useWords()} language={i18n.language} when={(iso, language) => shortDate(iso, language)}>
      <p className="m-0">
        <TextLink href="/settings/connections" testId="all-keys-own">
          {t('apiKeys.ownKeys')}
        </TextLink>
      </p>
    </AllKeysCard>
  )
}
