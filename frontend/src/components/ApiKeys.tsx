/**
 * The own API keys under My account, Connections, in the form of nexnotes' card "API-Token": for scripts and programs
 * such as a dashboard card or a scanner (`/api/v1`). The address for programs and how they send the key on top, the
 * list with a red word to delete one (after a question), and one button that opens the dialog to make one: name, what
 * the key may (only read, or only upload) and when it runs out. A key is shown once, right after it was made, with the
 * header line a program needs and a command to try it; afterwards only its first characters.
 *
 * A key never may more than its account. A key to read with runs out after a year unless chosen otherwise, one to upload
 * with never (see `LIFETIMES`); a week before, the list marks it. A key the operator blocked stays in the list, marked,
 * until the account deletes it. While the operator has keys switched off, nothing new can be made; the operator can
 * switch them on right here.
 */
import { BookOpen, KeyRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { apiKeysApi, type ApiKey } from '../api/client'
import { copyText } from '../lib/copy'
import { iso } from '../lib/say'
import { Button, Card, Feedback, Input, Select, useAction } from '../pages/settings/ui'
import { useAuth } from '../state/auth'
import { Dialog } from './Dialog'
import { useConfirm } from './useConfirm'

/** Days until a key runs out. A key to read with has a year as the default: a key that never runs out is the one nobody
 * remembers when it leaks. A key to upload with (the iPhone shortcut, a scanner) has no end as the default: it can only
 * put documents into its owner's inbox, and a shortcut that stops working after a year is a worse surprise than that.
 * Everything stays a choice. */
const LIFETIMES = ['365', '90', '30', 'never'] as const
type Lifetime = (typeof LIFETIMES)[number]
const WEEK = 7 * 24 * 60 * 60 * 1000
type Shown = { name: string; secret: string; scope: ApiKey['scope'] }

/** One line to copy: what it is for, the text, and a button. */
function Line({ label, text, copied, onCopy }: { label: string; text: string; copied: boolean; onCopy: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="mt-2">
      <div className="mb-1 flex items-center gap-2 text-xs text-ink-2">
        <span className="flex-1">{label}</span>
        <Button small onClick={onCopy} label={t('apiKeys.copyNamed', { what: label })}>
          {copied ? t('common.copied') : t('common.copy')}
        </Button>
      </div>
      <pre className="overflow-x-auto rounded-[8px] border border-line bg-sheet px-2.5 py-2 font-mono text-[11px] leading-5 whitespace-pre">{text}</pre>
    </div>
  )
}

export function ApiKeys() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [state, setState] = useState<{ allowed: boolean; keys: ApiKey[] } | null>(null)
  const [making, setMaking] = useState(false)
  const [shown, setShown] = useState<Shown | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const action = useAction()
  const { ask, dialog } = useConfirm()
  // The moment of the last load, for "runs out soon": a render must not read the clock.
  const [now, setNow] = useState(0)
  const load = () =>
    apiKeysApi.list().then(
      (found) => {
        setState(found)
        setNow(Date.now())
      },
      () => setState(null),
    )
  useEffect(() => {
    void load()
    // A key made elsewhere on the page (the iPhone shortcut's card) shows at once.
    const again = () => void load()
    window.addEventListener('nexpaper:api-keys-changed', again)
    return () => window.removeEventListener('nexpaper:api-keys-changed', again)
  }, [])

  if (!state) return null
  const operator = me?.role === 'operator'
  const lang = i18n.language
  const day = (value: string) => new Date(value).toLocaleDateString(lang)
  const moment = (value: string) => new Date(value).toLocaleString(lang, { dateStyle: 'short', timeStyle: 'short' })
  const address = `${window.location.origin}/api/v1`
  const header = (secret: string) => `Authorization: Bearer ${secret}`
  const curl = (secret: string, kind: ApiKey['scope']) =>
    kind === 'upload'
      ? `curl -H "Authorization: Bearer ${secret}" -F file=@Rechnung.pdf ${window.location.origin}/api/v1/documents`
      : `curl -H "Authorization: Bearer ${secret}" ${window.location.origin}/api/v1/me`
  const copy = (what: string, text: string) => void copyText(text).then((done) => done && setCopied(what))
  const ending = (key: ApiKey) => {
    if (!key.expires_at) return { text: t('apiKeys.never'), soon: false }
    const at = new Date(key.expires_at).getTime()
    if (at <= now) return { text: t('apiKeys.ranOut', { day: day(key.expires_at) }), soon: true }
    return { text: t('apiKeys.runsOut', { day: day(key.expires_at) }), soon: at - now <= WEEK }
  }

  return (
    <Card id="api-keys" icon={KeyRound} title={t('apiKeys.title')} text={t('apiKeys.text')}>
      {!state.allowed && (
        <div className="space-y-2 rounded-[9px] border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-ink-2" data-testid="api-keys-off">
          <p>
            {operator ? t('apiKeys.offForOperator') : t('apiKeys.off')}{' '}
            {operator && (
              <Link to="/settings/general" className="font-semibold text-accent underline decoration-accent/40 underline-offset-4">
                {t('apiKeys.offOperator')}
              </Link>
            )}
          </p>
          {operator && (
            <Button
              primary
              small
              onClick={() =>
                ask({
                  title: t('apiKeys.enableTitle'),
                  text: t('apiKeys.enableText'),
                  confirm: t('apiKeys.enableConfirm'),
                  danger: false,
                  run: async () => {
                    await apiKeysApi.allow()
                    await load()
                  },
                })
              }
            >
              {t('apiKeys.enable')}
            </Button>
          )}
        </div>
      )}
      {shown && (
        <div className="rounded-[12px] border border-accent/40 bg-accent-soft/50 p-3 text-sm" data-testid="api-key-shown">
          <p>{t('apiKeys.made', { name: shown.name })}</p>
          <p className="text-xs text-ink-2">{t('apiKeys.once')}</p>
          <Line label={t('apiKeys.key')} text={shown.secret} copied={copied === 'key'} onCopy={() => copy('key', shown.secret)} />
          <Line label={t('apiKeys.header')} text={header(shown.secret)} copied={copied === 'header'} onCopy={() => copy('header', header(shown.secret))} />
          <Line label={t('apiKeys.tryIt')} text={curl(shown.secret, shown.scope)} copied={copied === 'curl'} onCopy={() => copy('curl', curl(shown.secret, shown.scope))} />
          <Button small className="mt-3" onClick={() => setShown(null)}>
            {t('apiKeys.done')}
          </Button>
        </div>
      )}
      <div className="space-y-1 text-xs text-muted">
        <p>
          {t('apiKeys.address')}: <code className="font-mono text-ink-2">{address}</code>
        </p>
        <p>{t('apiKeys.headerLine')}</p>
        <a href="/api/v1/docs" target="_blank" rel="noopener" className="inline-flex items-center gap-1.5 text-accent hover:underline">
          <BookOpen className="h-3.5 w-3.5" aria-hidden />
          {t('apiKeys.docsLink')}
        </a>
      </div>
      {state.keys.length === 0 && state.allowed && (
        <p className="text-sm text-muted" data-testid="api-keys-none">
          {t('apiKeys.none')}
        </p>
      )}
      {state.keys.length > 0 && (
        <ul className="flex flex-col" data-testid="api-keys">
          {state.keys.map((key) => {
            const end = ending(key)
            return (
              <li key={key.id} className="flex items-center gap-3 border-b border-line py-2.5 last:border-0" data-testid="api-key">
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className="truncate text-sm">
                    {key.name} <code className="font-mono text-xs text-muted">{key.prefix}…</code>
                  </span>
                  <span className="text-xs text-muted">
                    {key.scope === 'upload' ? t('phone.keys.uploadOne') : t('apiKeys.readOnlyOne')} ·{' '}
                    {key.blocked ? (
                      <span className="text-bad" data-testid="api-key-blocked">
                        {t('apiKeys.blocked')}
                      </span>
                    ) : (
                      <span className={end.soon ? 'text-warn' : ''} data-testid="api-key-end">
                        {end.text}
                      </span>
                    )}
                    {' · '}
                    {key.last_used_at ? t('apiKeys.used', { when: moment(key.last_used_at) }) : t('apiKeys.unused')}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() =>
                    ask({
                      title: t('confirm.apiKey.title'),
                      text: t('confirm.apiKey.text', { name: iso(key.name) }),
                      confirm: t('confirm.apiKey.confirm'),
                      run: async () => {
                        await apiKeysApi.remove(key.id)
                        await load()
                      },
                    })
                  }
                  className="text-[13px] text-bad hover:underline"
                  aria-label={t('apiKeys.deleteNamed', { name: key.name })}
                >
                  {t('apiKeys.delete')}
                </button>
              </li>
            )
          })}
        </ul>
      )}
      <div>
        <Button disabled={!state.allowed} onClick={() => setMaking(true)}>
          {t('apiKeys.new')}
        </Button>
      </div>
      <p className="text-xs text-muted" data-testid="api-keys-upload-note">
        {t('apiKeys.uploadNote')}
      </p>
      <p className="text-xs text-muted">
        {t('apiKeys.docs')} {t('phone.keys.limits')}
      </p>
      <Feedback problem={action.problem} />
      {making && (
        <NewKeyDialog
          onClose={() => setMaking(false)}
          onMade={(made) => {
            setMaking(false)
            setCopied(null)
            setShown(made)
            void load()
          }}
        />
      )}
      {dialog}
    </Card>
  )
}

/** "Neuer API-Schlüssel", as nexnotes' dialog for a new token: a name, what the key may as two cards to choose from,
 * and when it runs out (the default follows the right until the person picks one). */
function NewKeyDialog({ onClose, onMade }: { onClose: () => void; onMade: (made: Shown) => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [scope, setScope] = useState<ApiKey['scope']>('read')
  const [chosen, setChosen] = useState<Lifetime | null>(null)
  // What the person picked, else the default of the kind of key.
  const days: Lifetime = chosen ?? (scope === 'upload' ? 'never' : '365')
  const action = useAction()
  return (
    <Dialog title={t('apiKeys.new')} onClose={onClose} medium>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (!name.trim()) return
          void action.run(async () => {
            const made = await apiKeysApi.make(name.trim(), days === 'never' ? null : Number(days), scope)
            onMade({ name: made.key.name, secret: made.secret, scope: made.key.scope })
          })
        }}
      >
        <Input label={t('apiKeys.name')} value={name} onChange={setName} maxLength={100} autoFocus placeholder={scope === 'upload' ? t('phone.keys.uploadPlaceholder') : t('apiKeys.namePlaceholder')} />
        <fieldset className="space-y-2">
          <legend className="mb-1 text-xs font-medium text-ink-2">{t('apiKeys.right')}</legend>
          {(['read', 'upload'] as const).map((choice) => (
            <label key={choice} className={`flex cursor-pointer gap-3 rounded-[12px] border px-3 py-2.5 ${scope === choice ? 'border-accent/50 bg-accent-soft/40' : 'border-line'}`}>
              <input type="radio" name="api-key-scope" value={choice} checked={scope === choice} onChange={() => setScope(choice)} className="mt-1 h-4 w-4 accent-[var(--accent)]" data-testid={`api-key-scope-${choice}`} />
              <span>
                <span className="block text-sm">{t(`apiKeys.scope.${choice}`)}</span>
                <span className="block text-xs text-muted">{t(`apiKeys.scope.${choice}Hint`)}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <div>
          <Select
            label={t('apiKeys.lifetime')}
            value={days}
            onChange={setChosen}
            options={LIFETIMES.map((value) => ({ value, label: value === 'never' ? t('apiKeys.lifetimeNever') : t(`apiKeys.lifetimeDays.${value}`) }))}
          />
          <p className="mt-1 text-xs text-muted">{t(scope === 'upload' ? 'apiKeys.lifetimeHintUpload' : 'apiKeys.lifetimeHint')}</p>
        </div>
        <Feedback problem={action.problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" primary busy={action.busy} disabled={!name.trim()}>
            {t('apiKeys.make')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
