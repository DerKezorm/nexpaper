/**
 * The own API keys on the account page, under Devices and apps, as nexlore's tokens: for scripts and programs such as
 * a dashboard card (`/api/v1`). List, make, delete. A key is shown once, right after it was made, with the header line
 * a program needs and a command to try it; afterwards only its first characters.
 *
 * A key only reads, or only uploads (a scanner, a script: "Schlüssel zum Hochladen", as the mock), and never more than
 * its account; it runs out after 30, 90 or 365 days, or never. A week before, the list marks it. A key the operator blocked stays in the list, marked, until the account deletes it.
 */
import { KeyRound, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { apiKeysApi, type ApiKey } from '../api/client'
import { copyText } from '../lib/copy'
import { Button, Card, Feedback, Input, Segment, useAction } from '../pages/settings/ui'
import { iso } from '../lib/say'
import { useConfirm } from './useConfirm'
import { useAuth } from '../state/auth'

/** Days until a key runs out. A key to read with has a year as the default: a key that never runs out is the one nobody
 * remembers when it leaks. A key to upload with (the iPhone shortcut, a scanner) has no end as the default: it can only
 * put documents into its owner's inbox, and a shortcut that stops working after a year is a worse surprise than that.
 * Everything stays a choice (the operator's decision of 10.10.2026). */
const LIFETIMES = ['365', '90', '30', 'never'] as const
type Lifetime = (typeof LIFETIMES)[number]
const WEEK = 7 * 24 * 60 * 60 * 1000

/** One line to copy: what it is for, the text, and a button. */
function Line({ label, text, copied, onCopy }: { label: string; text: string; copied: boolean; onCopy: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="mt-2">
      <div className="mb-1 flex items-center gap-2 text-xs text-muted">
        <span className="flex-1">{label}</span>
        <Button small onClick={onCopy} label={t('apiKeys.copyNamed', { what: label })}>
          {copied ? t('common.copied') : t('common.copy')}
        </Button>
      </div>
      <pre className="overflow-x-auto rounded-lg bg-sheet px-2 py-1.5 font-mono text-[11px] leading-5 whitespace-pre">{text}</pre>
    </div>
  )
}

export function ApiKeys() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [state, setState] = useState<{ allowed: boolean; keys: ApiKey[] } | null>(null)
  const [making, setMaking] = useState(false)
  const [name, setName] = useState('')
  const [chosen, setChosen] = useState<Lifetime | null>(null)
  const [scope, setScope] = useState<ApiKey['scope']>('read')
  // What the person picked, else the default of the kind of key.
  const days: Lifetime = chosen ?? (scope === 'upload' ? 'never' : '365')
  const [shown, setShown] = useState<{ name: string; secret: string; scope: ApiKey['scope'] } | null>(null)
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
  if (!state.allowed)
    return (
      <Card id="api-keys" icon={KeyRound} title={t('apiKeys.title')} text={t('apiKeys.text')}>
        <p className="text-sm text-ink-2" data-testid="api-keys-off">
          {operator ? t('apiKeys.offForOperator') : t('apiKeys.off')}{' '}
          {operator && (
            <Link to="/einstellungen?tab=api" className="font-semibold text-accent underline decoration-accent/40 underline-offset-4">
              {t('apiKeys.offOperator')}
            </Link>
          )}
        </p>
        {operator && (
          <div>
            <Button
              primary
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
          </div>
        )}
        {dialog}
      </Card>
    )

  const day = (value: string) => new Date(value).toLocaleDateString(i18n.language)
  const moment = (value: string) => new Date(value).toLocaleString(i18n.language, { dateStyle: 'short', timeStyle: 'short' })
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
      {shown && (
        <div className="rounded-xl border border-accent/40 bg-accent-soft/50 p-4 text-sm" data-testid="api-key-shown">
          <p className="font-semibold">{t('apiKeys.shownOnce', { name: shown.name })}</p>
          <Line label={t('apiKeys.key')} text={shown.secret} copied={copied === 'key'} onCopy={() => copy('key', shown.secret)} />
          <Line label={t('apiKeys.header')} text={header(shown.secret)} copied={copied === 'header'} onCopy={() => copy('header', header(shown.secret))} />
          <Line label={t('apiKeys.tryIt')} text={curl(shown.secret, shown.scope)} copied={copied === 'curl'} onCopy={() => copy('curl', curl(shown.secret, shown.scope))} />
          <Button small className="mt-3" onClick={() => setShown(null)}>
            {t('apiKeys.done')}
          </Button>
        </div>
      )}
      {state.keys.length > 0 && (
        <ul className="space-y-2">
          {state.keys.map((key) => {
            const end = ending(key)
            return (
              <li key={key.id} className="flex items-center gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-3 text-sm" data-testid="api-key">
                <KeyRound size={17} className="shrink-0 text-accent" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="font-semibold">{key.name}</span> <code className="font-mono text-xs text-muted">{key.prefix}…</code>
                  <span className="block text-xs text-muted">
                    {key.scope === 'upload' ? t('phone.keys.uploadOne') : t('apiKeys.readOnlyOne')} ·{' '}
                    {key.blocked ? (
                      <span className="font-semibold text-bad" data-testid="api-key-blocked">
                        {t('apiKeys.blocked')}
                      </span>
                    ) : (
                      <span className={end.soon ? 'font-semibold text-warn' : ''} data-testid="api-key-end">
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
                  className="rounded-full p-1.5 text-muted hover:bg-sheet hover:text-ink"
                  aria-label={t('apiKeys.deleteNamed', { name: key.name })}
                >
                  <Trash2 size={15} />
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {shown ? null : !making ? (
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => {
              setScope('read')
              setChosen(null)
              setMaking(true)
            }}
          >
            <Plus size={16} /> {t('apiKeys.new')}
          </Button>
          <Button
            onClick={() => {
              setScope('upload')
              setChosen(null)
              setMaking(true)
            }}
          >
            <Plus size={16} /> {t('phone.keys.uploadButton')}
          </Button>
        </div>
      ) : (
        <form
          className="space-y-3 rounded-xl border border-dashed border-line p-4"
          onSubmit={(event) => {
            event.preventDefault()
            if (!name.trim()) return
            void action.run(async () => {
              const made = await apiKeysApi.make(name.trim(), days === 'never' ? null : Number(days), scope)
              setShown({ name: made.key.name, secret: made.secret, scope: made.key.scope })
              setCopied(null)
              setMaking(false)
              setName('')
              setChosen(null)
              await load()
            })
          }}
        >
          <Input label={t('apiKeys.name')} value={name} onChange={setName} maxLength={100} autoFocus placeholder={scope === 'upload' ? t('phone.keys.uploadPlaceholder') : t('apiKeys.namePlaceholder')} />
          <div className="text-sm">
            <p className="mb-1 font-semibold">{t('phone.keys.scope')}</p>
            <Segment
              label={t('phone.keys.scope')}
              value={scope}
              onChange={setScope}
              options={[
                { value: 'read', label: t('phone.keys.read') },
                { value: 'upload', label: t('phone.keys.uploadOne') },
              ]}
            />
          </div>
          <div className="text-sm">
            <p className="mb-1 font-semibold">{t('apiKeys.lifetime')}</p>
            <Segment
              label={t('apiKeys.lifetime')}
              value={days}
              onChange={setChosen}
              options={LIFETIMES.map((value) => ({ value, label: value === 'never' ? t('apiKeys.lifetimeNever') : t(`apiKeys.lifetimeDays.${value}`) }))}
            />
            <p className="mt-1 text-xs text-muted">{t(scope === 'upload' ? 'apiKeys.lifetimeHintUpload' : 'apiKeys.lifetimeHint')}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" primary busy={action.busy} disabled={!name.trim()}>
              {t('apiKeys.make')}
            </Button>
            <Button onClick={() => setMaking(false)}>{t('common.cancel')}</Button>
          </div>
        </form>
      )}
      <p className="text-xs text-muted" data-testid="api-keys-upload-note">
        {t('apiKeys.uploadNote')}
      </p>
      <p className="text-xs text-muted">
        {t('apiKeys.docs')} {t('phone.keys.limits')}
      </p>
      <Feedback problem={action.problem} />
      {dialog}
    </Card>
  )
}
