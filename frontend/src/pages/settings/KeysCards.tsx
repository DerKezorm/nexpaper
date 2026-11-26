/**
 * The cards of the shared key module (schluessel 1.0.0, plan "Einstellungen") with nexpaper's words: "API-Schlüssel" in
 * My account › Connections (a key reads or only uploads, nexpaper's sentences for both), "Schnittstellen" in Server ›
 * General (the switch "Programmschnittstelle (API) für Mitglieder"; before the card "Funktionen für alle Konten" and the
 * area "API"), "API-Schlüssel aller Konten" in Server › Accounts. The routes are the module's under
 * `/api/v1/connections`; nexpaper's older ways (`/api/v1/api-keys`, `/api/v1/admin/api-keys`) stay for nexpaper-ios, the
 * shortcut and scripts. nexpaper has no MCP access (E27): no card "KI-Werkzeuge (MCP)".
 */
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import { shortDate } from '../../lib/dates'
import { useAuth } from '../../state/auth'
import { AllKeysCard, ApiKeysCard, InterfacesCard, type AppWords, type KeyRequest } from '../../vendor/nexschluessel'

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

/** My account › Connections, place 5: "API-Schlüssel". */
export function ApiKeys() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  return (
    <ApiKeysCard
      request={keyRequest}
      base={KEYS_AT}
      things={t('settings.things')}
      thingsDative={t('settings.thingsDative')}
      words={useWords()}
      docsHref={DOCS}
      operator={me?.role === 'operator'}
      language={i18n.language}
      when={(iso, language) => shortDate(iso, language)}
    >
      {/* nexpaper's own lines at the end of the card: what a key for uploading may do, and the limits of every key. */}
      <p className="m-0 text-xs text-[var(--nexui-text-muted)]" data-testid="keys-upload-note">
        {t('apiKeys.keyUploadNote')}
      </p>
      <p className="m-0 text-xs text-[var(--nexui-text-muted)]" data-testid="keys-limits">
        {t('apiKeys.keyLimits')}
      </p>
    </ApiKeysCard>
  )
}

/** Server › General, place 3: "Schnittstellen". */
export function Interfaces() {
  const { i18n } = useTranslation()
  return <InterfacesCard request={keyRequest} base={KEYS_AT} docsHref={DOCS} language={i18n.language} />
}

/** Server › Accounts, place 4: "API-Schlüssel aller Konten". */
export function AllKeys() {
  const { i18n } = useTranslation()
  return <AllKeysCard request={keyRequest} base={KEYS_AT} words={useWords()} language={i18n.language} when={(iso, language) => shortDate(iso, language)} />
}
