/**
 * The operator's part of the settings that is not a module's area: the server's settings for the cards (`useServerSettings`),
 * "Sprachen" under General (the card of the shared module sprachen), and the cards of the shared modules with nexpaper's client: "Mail" (post 1.1.0,
 * `/api/v1/server/mail`, nexpaper's sentence of every mail it sends) and "Log" (log 1.0.0, `/api/v1/logs`). Sign-in
 * is `SignInArea.tsx`, Storage and backups `StorageArea.tsx`, the keys `KeysCards.tsx`. Everything here is the
 * server's; it applies to all. The operator manages accounts and does not read the documents in them.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, api, tabFetch, type AddressQuestion } from '../../api/client'
import { APP_NAME, own, TEMPLATE } from '../../i18n'
import { LogCard } from '../../vendor/nexlog/LogCard'
import type { LogLine, LogRequest } from '../../vendor/nexlog/log'
import { MailCard } from '../../vendor/nexpost/MailCard'
import type { PostRequest } from '../../vendor/nexpost/mailserver'
import { LanguagesCard as SprachenCard } from '../../vendor/nexsprachen/LanguagesCard'
import { formatMoment } from '../../vendor/nexui'
import { useAction } from './actions'

export type ServerSettings = {
  public_url: string
  password_login: boolean
  two_factor_required: boolean
  backup_schedule: 'off' | 'daily' | 'weekly' | 'monthly'
  backup_keep: number
  smtp_host: string
  smtp_port: number
  smtp_security: 'starttls' | 'tls' | 'none'
  smtp_user: string
  smtp_password_set: boolean
  smtp_from: string
  /** The name system mail goes out under (the shared post module); empty: "nexpaper". */
  smtp_sender_name?: string
  /** The shared account module's switch: passkeys may be added and used (on from the start). */
  passkeys_allowed?: boolean
  api_keys_allowed: boolean
  update_check: boolean
  links_allowed: boolean
  link_max_days: number
  upload_max_mb: number
  upload_max_pages: number
  upload_max_megapixels: number
  upload_open_count: number
  upload_open_mb: number
  process_timeout_seconds: number
  process_memory_mb: number
  cache_max_mb: number
  /** U1: upload requests, off from the start. */
  upload_requests_allowed?: boolean
  /** The storage limit new accounts start with, in bytes; null: none (Bauplan E44). */
  new_account_storage_limit?: number | null
}

type Change = Partial<ServerSettings> & { smtp_password?: string; current_password?: string; confirm_address?: boolean }

// eslint-disable-next-line react-refresh/only-export-components
export function useServerSettings() {
  const [settings, setSettings] = useState<ServerSettings | null>(null)
  const action = useAction()
  const reload = useCallback(async () => {
    const fresh = await api<ServerSettings>('/api/v1/settings')
    setSettings(fresh)
    return fresh
  }, [])
  useEffect(() => {
    reload().catch(() => undefined)
  }, [reload])
  /** Straight to the server, without the switch moving first (a change asked with the operator's password). */
  const saveNow = async (change: Change) => setSettings(await api<ServerSettings>('/api/v1/settings', { method: 'PUT', body: change }))
  /**
   * The public address. While the authentik button registered the old one, or a provider entered by hand is on, the
   * server asks first (409 `public_url_change`, nothing saved): the question comes back for the page to ask
   *; with `confirm` it is saved. Null: saved, or refused for another reason (shown by `problem`).
   */
  const saveAddress = async (public_url: string, confirm = false): Promise<AddressQuestion | null> => {
    let question: AddressQuestion | null = null
    await action.run(async () => {
      try {
        setSettings(await api<ServerSettings>('/api/v1/settings', { method: 'PUT', body: { public_url, confirm_address: confirm } }))
      } catch (error) {
        if (!(error instanceof ApiError) || error.code !== 'public_url_change') throw error
        question = { count: Number(error.values.count ?? 0), address: String(error.values.address ?? ''), hand: Number(error.values.hand ?? 0) }
      }
    })
    return question
  }
  /** The switch moves at once; the server's answer confirms it, a refusal puts it back. */
  const save = async (change: Change, done?: string) => {
    const before = settings
    if (settings) setSettings({ ...settings, ...change })
    const ok = await action.run(async () => setSettings(await api<ServerSettings>('/api/v1/settings', { method: 'PUT', body: change })), done)
    if (!ok) setSettings(before)
  }
  return { settings, save, saveNow, saveAddress, reload, setSettings, ...action }
}

/** "Sprachen" (General, place 5): the card of the shared module sprachen 1.0.0 with nexpaper's way to the server
 * (`/api/v1/locales`, its tab), the English texts as the template, and the menus asking anew after a change. */
export function LanguagesCard() {
  return <SprachenCard app={APP_NAME} base="/api/v1/locales" fetcher={tabFetch} template={TEMPLATE} onChange={own.forget} />
}

/** nexpaper's client for the cards of the modules post and log (its headers, its errors with their codes). */
const postRequest: PostRequest = <T,>(path: string, init: Parameters<PostRequest>[1] = {}) => api<T>(path, { method: init.method, body: init.body })
const logRequest: LogRequest = <T,>(path: string, init: Parameters<LogRequest>[1] = {}) => api<T>(path, { method: init.method, query: init.query, body: init.body })

/** Server › Mail (post 1.1.0): the module's card "Mail" with nexpaper's sentence of every mail it sends (E26). */
export function MailArea() {
  const { t, i18n } = useTranslation()
  return (
    <MailCard
      request={postRequest}
      base="/api/v1/server/mail"
      subtitle={t('server.mailHint')}
      senderPlaceholder="paper@example.com"
      language={i18n.language}
      when={formatMoment}
    />
  )
}

/** Server › Log (log 1.0.0): the module's card "Log" over nexpaper's routes, the moments in the reader's own time. */
export function LogArea() {
  const { t } = useTranslation()
  const when = (line: LogLine, language: string) => (line.at ? new Date(line.at).toLocaleString(language, { dateStyle: 'short', timeStyle: 'medium' }) : line.time)
  return (
    <LogCard
      request={logRequest}
      base="/api/v1/logs"
      downloadHref="/api/v1/logs/download"
      things={t('settings.things')}
      thingsDative={t('settings.thingsDative')}
      when={when}
      clock={(moment, language) => new Date(moment).toLocaleTimeString(language, { hour: '2-digit', minute: '2-digit' })}
    />
  )
}
