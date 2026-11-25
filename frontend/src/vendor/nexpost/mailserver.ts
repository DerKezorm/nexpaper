// Since 1.1.0: what the card "Mail" (MailCard.tsx, page Server › Mail) needs beside post.ts: the answer of the server,
// what it saves, the app's way to call its server, and the module's words in German, English and French. post.ts stays
// without imports (it runs as it is in node, for the module's own test).
//
// Copied unchanged into frontend/src/vendor/nexpost/ by bauplaene/post/tools/sync.py; changed only there.

import { mailErrorKey } from './post'
import de from './post.de.json'
import en from './post.en.json'
import fr from './post.fr.json'

/** `GET <base>`: the mail server as the page shows it (never the password). */
export type MailView = {
  host: string
  port: number
  security: string
  user: string
  password_set: boolean
  sender: string
  sender_name: string
  /** The app's name: what an empty sender name stands for, the placeholder of the field. */
  sender_name_default: string
  configured: boolean
  warnings: string[]
  last_ok_at: string | null
  last_error: string
  last_error_at: string | null
  /** Mails waiting in the outbox; null where the app's store cannot tell. */
  waiting: number | null
}

/** `PUT <base>`: `password` null keeps the stored one. */
export type MailChange = {
  host: string
  port: number
  security: string
  user: string
  password: string | null
  sender: string
  sender_name: string
}

/** The app's way to call its server (its own client with its headers). A refusal rejects with an object that has the
 * server's `code` (as the app's client gives it: `code`, or `detail.code`). */
export type PostRequest = <T>(path: string, init?: { method?: 'GET' | 'PUT' | 'POST'; body?: unknown }) => Promise<T>

export type PostTexts = (typeof de)['mail']

export const POST_TEXTS: Record<'de' | 'en' | 'fr', PostTexts> = { de: de.mail, en: en.mail, fr: fr.mail }

/** Fills `{{name}}` in one of the module's sentences. */
export function fillPost(text: string, values: Record<string, string | number>): string {
  return text.replace(/\{\{(\w+)\}\}/g, (whole, name: string) => (Object.hasOwn(values, name) ? String(values[name]) : whole))
}

/** The server's code in a refusal of the app's client, "" when it has none. */
export function errorCodeOf(reason: unknown): string {
  if (typeof reason !== 'object' || reason === null) return ''
  const own = (reason as { code?: unknown }).code
  if (typeof own === 'string') return own
  const detail = (reason as { detail?: unknown }).detail
  if (typeof detail === 'object' && detail !== null && typeof (detail as { code?: unknown }).code === 'string') {
    return (detail as { code: string }).code
  }
  return ''
}

/** The words for an error code of the server (`mail.error.<code>`, else "unknown"); `appCodes` maps an app's older
 * codes to the module's. */
export function errorText(texts: PostTexts, code: string, appCodes: Readonly<Record<string, string>> = {}): string {
  const key = mailErrorKey(code, appCodes).split('.').pop() ?? 'unknown'
  return (texts.error as Record<string, string>)[key] ?? texts.error.unknown
}

/** The lines under the card, in this order: last sent, the last error, mails waiting (only those there are). */
export function statusLines(
  view: MailView,
  texts: PostTexts,
  when: (iso: string) => string,
  appCodes: Readonly<Record<string, string>> = {},
): { key: 'lastOk' | 'lastError' | 'waiting'; text: string }[] {
  const lines: { key: 'lastOk' | 'lastError' | 'waiting'; text: string }[] = []
  if (view.last_ok_at) lines.push({ key: 'lastOk', text: fillPost(texts.lastOk, { when: when(view.last_ok_at) }) })
  if (view.last_error && view.last_error_at) {
    lines.push({ key: 'lastError', text: fillPost(texts.lastError, { when: when(view.last_error_at), error: errorText(texts, view.last_error, appCodes) }) })
  }
  if (view.waiting) lines.push({ key: 'waiting', text: fillPost(texts.waiting, { count: view.waiting }) })
  return lines
}

/** What `PUT <base>` gets from the card: the password only when one was typed. */
export function mailChange(values: Omit<MailChange, 'password'>, typedPassword: string): MailChange {
  return { ...values, port: Number(values.port), password: typedPassword === '' ? null : typedPassword }
}
