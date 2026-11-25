/**
 * Since 1.1.0: Server › Mail, the card "Mail" (Mail) as nexnotes has it, built only from the ui kit, with the fields and
 * words of the plan: "Server", "Port" (follows the encryption until one is typed), "Verschlüsselung" (STARTTLS, TLS,
 * keine; a warning without), "Benutzer", "Passwort" (placeholder "Bleibt; nur zum Ändern tippen." while one is stored),
 * "Absender", "Absendername" (the app's name as placeholder); "Speichern" (primary, Check). Below "Testmail an" with its
 * own button "Senden" (secondary, Send) level with the field, then the lines "Zuletzt verschickt: …", the last error and
 * the mails waiting. The test mail comes from the module, with the app's logo, the same in every app.
 *
 * The app hands over how it calls its server (`request`), where the routes are (`base`), its sentence under the title
 * (`subtitle`) and, if it has them, its older error codes (`appCodes`) and its way to write a moment (`when`). The words
 * come with the module (de, en, fr), in the language the kit uses (`NexuiLanguage`, else the page's) unless `language`
 * says otherwise.
 *
 * Copied unchanged into frontend/src/vendor/nexpost/ by bauplaene/post/tools/sync.py; changed only there.
 */
import { useEffect, useState, type FormEvent } from 'react'

import { Button, Buttons, Card, Field, NEXUI_TEXTS, Notice, SelectField, languageOf, useNexuiTexts } from '../nexui'
import { POST_TEXTS, errorCodeOf, errorText, fillPost, mailChange, statusLines, type MailView, type PostRequest, type PostTexts } from './mailserver'
import { SECURITY, SECURITY_LABELS, portFor, warnUnencrypted, type Security } from './post'

/** The module's words in the kit's language (or the one given), and that language. */
function usePostTexts(language?: string): [PostTexts, string] {
  const kit = useNexuiTexts()
  if (language) return [POST_TEXTS[languageOf(language)], languageOf(language)]
  const code = (Object.keys(NEXUI_TEXTS) as (keyof typeof NEXUI_TEXTS)[]).find((key) => NEXUI_TEXTS[key] === kit) ?? 'en'
  return [POST_TEXTS[code], code]
}

function defaultWhen(iso: string, language: string): string {
  const moment = new Date(iso)
  return Number.isNaN(moment.getTime()) ? iso : moment.toLocaleString(language, { dateStyle: 'short', timeStyle: 'short' })
}

/** The label of an encryption: its key in the module's words. */
function securityLabel(texts: PostTexts, security: Security): string {
  const key = SECURITY_LABELS[security].split('.').pop() as 'securityStarttls' | 'securityTls' | 'securityNone'
  return texts[key]
}

type Draft = { host: string; port: string; security: Security; user: string; sender: string; sender_name: string }

function draftOf(view: MailView): Draft {
  const security = (SECURITY as readonly string[]).includes(view.security) ? (view.security as Security) : 'starttls'
  return { host: view.host, port: String(view.port), security, user: view.user, sender: view.sender, sender_name: view.sender_name }
}

export type MailCardProps = {
  /** The app's client (its headers, its errors). */
  request: PostRequest
  /** Where the routes are mounted (`nexpost.api.router`): `/api/server/mail`. */
  base?: string
  /** The app's sentence under the title ("Der Mailserver, über den nexnotes Einladungen … verschickt."). */
  subtitle: string
  /** A sender address as example in the empty field ("notes@example.com"). */
  senderPlaceholder?: string
  /** The app's older error codes, mapped to the module's (`AppConfig.error_codes` the other way round). */
  appCodes?: Readonly<Record<string, string>>
  /** `de`, `en` or `fr`; default the kit's. */
  language?: string
  /** How a moment is written (the app's own, in the account's zone); default the browser's. */
  when?: (iso: string, language: string) => string
  testId?: string
}

export function MailCard({ request, base = '/api/server/mail', subtitle, senderPlaceholder = 'robot@example.com', appCodes = {}, language, when = defaultWhen, testId = 'mail-card' }: MailCardProps) {
  const [texts, shownIn] = usePostTexts(language)
  const [view, setView] = useState<MailView | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [password, setPassword] = useState('')
  const [portTyped, setPortTyped] = useState(false)
  const [to, setTo] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [done, setDone] = useState('')
  /** The code of the last refusal ("" when the server named none); null: nothing went wrong. */
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    request<MailView>(base).then(
      (found) => {
        setView(found)
        setDraft(draftOf(found))
      },
      (reason: unknown) => setProblem(errorCodeOf(reason)),
    )
  }, [request, base])

  const refused = (reason: unknown) => setProblem(errorCodeOf(reason))

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!draft) return
    setSaving(true)
    setDone('')
    setProblem(null)
    try {
      const saved = await request<MailView>(base, { method: 'PUT', body: mailChange({ ...draft, port: Number(draft.port) }, password) })
      setView(saved)
      setDraft(draftOf(saved))
      setPassword('')
      setPortTyped(false)
      setDone(texts.saved)
    } catch (reason) {
      refused(reason)
    } finally {
      setSaving(false)
    }
  }

  const test = async (event: FormEvent) => {
    event.preventDefault()
    const address = to.trim()
    if (!address) return
    setTesting(true)
    setDone('')
    setProblem(null)
    try {
      await request<void>(`${base}/test`, { method: 'POST', body: { to: address, language: shownIn } })
      setDone(fillPost(texts.testSent, { email: address }))
      setView(await request<MailView>(base))
    } catch (reason) {
      refused(reason)
      request<MailView>(base).then(setView, () => undefined)
    } finally {
      setTesting(false)
    }
  }

  const changeSecurity = (value: string) => {
    if (!draft) return
    const security = value as Security
    setDraft({ ...draft, security, port: String(portFor(security, Number(draft.port), portTyped)) })
  }

  const warn = draft !== null && view !== null && warnUnencrypted({ security: draft.security, user: draft.user, password, passwordSet: view.password_set })
  const lines = view ? statusLines(view, texts, (iso) => when(iso, shownIn), appCodes) : []

  return (
    <Card id="mail" icon="Mail" title={texts.title} subtitle={subtitle} testId={testId}>
      {draft && view && (
        <form className="grid gap-3 @min-[640px]:grid-cols-2" onSubmit={(event) => void save(event)} data-testid="mail-form">
          <Field label={texts.server} value={draft.host} placeholder="smtp.example.com" autoComplete="off" onChange={(event) => setDraft({ ...draft, host: event.target.value })} data-testid="mail-server" />
          <Field
            label={texts.port}
            type="number"
            min={1}
            max={65535}
            value={draft.port}
            onChange={(event) => {
              setPortTyped(true)
              setDraft({ ...draft, port: event.target.value })
            }}
            data-testid="mail-port"
          />
          <SelectField
            label={texts.security}
            value={draft.security}
            options={SECURITY.map((value) => ({ value, label: securityLabel(texts, value) }))}
            onChange={(event) => changeSecurity(event.target.value)}
            data-testid="mail-security"
          />
          <Field label={texts.user} value={draft.user} autoComplete="off" onChange={(event) => setDraft({ ...draft, user: event.target.value })} data-testid="mail-user" />
          <Field
            label={texts.password}
            type="password"
            autoComplete="new-password"
            value={password}
            placeholder={view.password_set ? texts.passwordKept : ''}
            onChange={(event) => setPassword(event.target.value)}
            data-testid="mail-password"
          />
          <Field label={texts.sender} type="email" value={draft.sender} placeholder={senderPlaceholder} onChange={(event) => setDraft({ ...draft, sender: event.target.value })} data-testid="mail-sender" />
          <Field
            label={texts.senderName}
            value={draft.sender_name}
            placeholder={view.sender_name_default}
            onChange={(event) => setDraft({ ...draft, sender_name: event.target.value })}
            data-testid="mail-sender-name"
          />
          {warn && (
            <div className="@min-[640px]:col-span-2">
              <Notice tone="warn" testId="mail-warning">
                {texts.warningUnencrypted}
              </Notice>
            </div>
          )}
          <div className="@min-[640px]:col-span-2">
            <Buttons>
              <Button kind="primary" icon="Check" type="submit" busy={saving} testId="mail-save">
                {texts.save}
              </Button>
            </Buttons>
          </div>
        </form>
      )}
      <form onSubmit={(event) => void test(event)} data-testid="mail-test-form">
        <Field
          label={texts.test}
          type="email"
          value={to}
          placeholder="you@example.com"
          onChange={(event) => setTo(event.target.value)}
          data-testid="mail-test-to"
          action={
            <Button kind="secondary" icon="Send" type="submit" busy={testing} disabled={!to.trim()} testId="mail-test">
              {texts.send}
            </Button>
          }
        />
      </form>
      {lines.length > 0 && (
        <div className="flex flex-col gap-1" data-testid="mail-status">
          {lines.map((line) => (
            <p key={line.key} className="m-0 text-xs leading-4 tracking-normal text-[var(--nexui-text-muted)]" data-testid={`mail-${line.key}`}>
              {line.text}
            </p>
          ))}
        </div>
      )}
      {done && (
        <Notice tone="ok" testId="mail-done">
          {done}
        </Notice>
      )}
      {problem !== null && (
        <Notice tone="danger" testId="mail-problem">
          {problem ? errorText(texts, problem, appCodes) : texts.failed}
        </Notice>
      )}
    </Card>
  )
}
