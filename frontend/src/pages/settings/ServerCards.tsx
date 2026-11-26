/**
 * The operator's part of the settings that is not a module's area: the server's settings for the cards (`useServerSettings`),
 * "Sprachen" under General (the built-in ones, the operator's own as chips, the template and "Sprache hochladen" at
 * the field of the language code), and the cards of the shared modules with nexpaper's client: "Mail" (post 1.1.0,
 * `/api/v1/server/mail`, nexpaper's sentence of every mail it sends) and "Log" (log 1.0.0, `/api/v1/logs`). Sign-in
 * is `SignInArea.tsx`, Storage and backups `StorageArea.tsx`, the keys `KeysCards.tsx`. Everything here is the
 * server's; it applies to all. The operator manages accounts and does not read the documents in them.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, api, type AddressQuestion } from '../../api/client'
import { byName, forgetAddedLanguages, templateFile } from '../../i18n'
import { LogCard } from '../../vendor/nexlog/LogCard'
import type { LogLine, LogRequest } from '../../vendor/nexlog/log'
import { MailCard } from '../../vendor/nexpost/MailCard'
import type { PostRequest } from '../../vendor/nexpost/mailserver'
import { Button, Buttons, Card, Chip, Field } from '../../vendor/nexui'
import { saveAsFile, useAction } from './actions'
import { Outcome } from './Outcome'
import { useAsk } from './useAsk'
import { iso } from '../../lib/say'

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

type Locale = { code: string; name: string; keys: number }

/** "Sprachen" (General, place 5): the built-in ones, the operator's own as chips with "remove", the template, and the
 * language code with its own button that uploads the file. */
export function LanguagesCard() {
  const { t } = useTranslation()
  const [list, setList] = useState<Locale[]>([])
  const [code, setCode] = useState('')
  const action = useAction()
  const { ask, dialog } = useAsk()
  const load = useCallback(() => {
    api<Locale[]>('/api/v1/locales').then((rows) => setList(rows.sort(byName)), () => undefined)
  }, [])
  useEffect(load, [load])
  const upload = (chosen: File) =>
    void action.run(async () => {
      await api(`/api/v1/locales/${encodeURIComponent(code)}`, { method: 'PUT', raw: chosen })
      forgetAddedLanguages()
      load()
    }, t('server.languageAdded'))
  return (
    <Card id="languages" icon="Globe" title={t('server.languages')} subtitle={t('server.languagesHint')}>
      <div className="flex flex-wrap gap-2" data-testid="languages-list">
        <Chip>{`Deutsch · ${t('server.builtIn')}`}</Chip>
        <Chip>{`English · ${t('server.builtIn')}`}</Chip>
        <Chip>{`Français · ${t('server.builtIn')}`}</Chip>
        {list.map((entry) => (
          <Chip
            key={entry.code}
            name={entry.name}
            disabled={action.busy}
            testId={`language-${entry.code}`}
            onRemove={() =>
              ask({
                title: t('confirm.locale.title'),
                text: t('confirm.locale.text', { name: iso(entry.name) }),
                confirm: t('confirm.locale.confirm'),
                run: async () => {
                  await api(`/api/v1/locales/${entry.code}`, { method: 'DELETE' })
                  forgetAddedLanguages()
                  load()
                },
              })
            }
          >
            {`${entry.name} (${entry.code}) · ${t('server.texts', { count: entry.keys })}`}
          </Chip>
        ))}
      </div>
      <Buttons>
        <Button kind="secondary" icon="Download" onClick={() => saveAsFile('nexpaper-language-template.json', templateFile())} testId="language-template">
          {t('server.template')}
        </Button>
      </Buttons>
      <Field
        label={t('server.languageCode')}
        value={code}
        onChange={(event) => setCode(event.target.value.trim())}
        placeholder="es"
        data-testid="language-code"
        action={
          <Button kind="secondary" icon="Upload" disabled={!code} busy={action.busy} accept="application/json,.json" onFile={upload} testId="language-upload">
            {t('server.upload')}
          </Button>
        }
      />
      <Outcome problem={action.problem} done={action.done} />
      {dialog}
    </Card>
  )
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
      when={(moment, language) => new Date(moment).toLocaleString(language, { dateStyle: 'short', timeStyle: 'short' })}
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
