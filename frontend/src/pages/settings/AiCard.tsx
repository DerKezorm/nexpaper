/**
 * "KI-Vorschläge im Eingang", the cards under Server › AI provider: the operator chooses one service for
 * everybody (none from the start), with its address, key (for a local model only where its service asks for one)
 * and model, and tries it. The key is typed once and never shown again; a new address or another kind of service
 * forgets it (the server does that). Nobody else can set this.
 */
import { Sparkles } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { aiApi, type AiModel, type AiProvider, type AiSettings } from '../../api/client'
import { AI_PROVIDERS, LOCAL_URL, MESSAGES_URL, providerName } from '../../lib/aiProviders'
import { Button, Card, CheckboxRow, Field, Notice, Segment, SelectField } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'

/** The most the operator's own wishes may be, as the server keeps them. */
const WISHES_MAX = 2000
const AREA = 'block min-h-28 w-full rounded-[9px] border border-solid border-[var(--nexui-edge)] bg-[var(--nexui-field)] px-3 py-2 text-sm text-[var(--nexui-text)] outline-none focus:border-[var(--nexui-accent)]'

export function AiCard() {
  const { t, i18n } = useTranslation()
  const [stored, setStored] = useState<AiSettings | null>(null)
  const [chosen, setChosen] = useState<AiProvider>('none')
  const [url, setUrl] = useState('')
  const [key, setKey] = useState('')
  const [model, setModel] = useState('')
  const [models, setModels] = useState<AiModel[] | null>(null)
  const action = useAction()
  const listing = useAction()
  const [probed, setProbed] = useState<number | null>(null)
  const [limit, setLimit] = useState<string | null>(null)
  const [limitInvalid, setLimitInvalid] = useState(false)
  const [wishes, setWishes] = useState<string | null>(null)
  const wishesHint = useId()
  const wishesField = useId()

  const take = (found: AiSettings) => {
    setStored(found)
    setChosen(found.provider)
    setUrl(found.provider === 'local' && !found.url ? LOCAL_URL : found.url)
    setModel(found.model)
    setKey('')
  }
  useEffect(() => {
    let alive = true
    aiApi.settings().then((found) => alive && take(found), () => undefined)
    return () => {
      alive = false
    }
  }, [])
  if (!stored) return null

  const choose = (provider: AiProvider) => {
    setChosen(provider)
    setModels(null)
    action.clear()
    listing.clear()
    setProbed(null)
    // Back to what is stored for it, or a sensible start; nothing is saved before "Save".
    if (provider === stored.provider) {
      setUrl(stored.url || (provider === 'local' ? LOCAL_URL : ''))
      setModel(stored.model)
    } else {
      setUrl(provider === 'local' ? LOCAL_URL : '')
      setModel('')
    }
    setKey('')
    // "Keine KI" needs nothing else: it counts at once.
    if (provider === 'none') void action.run(async () => take(await aiApi.save({ provider: 'none' })), t('server.ai.saved'))
  }

  /** The day's limit is saved on its own, apart from the service (0 is no limit). */
  const saveLimit = () => {
    if (limit === null) return
    const number = Number(limit)
    if (!/^\d+$/.test(limit.trim()) || number > 100000) {
      setLimitInvalid(true)
      return
    }
    setLimitInvalid(false)
    setLimit(null)
    void action.run(async () => setStored(await aiApi.save({ daily_limit: number })))
  }

  /** The operator's own wishes for the proposals, saved on their own; empty leaves the fixed rules alone. */
  const saveWishes = () => {
    if (wishes === null) return
    void action.run(async () => {
      setStored(await aiApi.save({ instructions: wishes }))
      setWishes(null)
    }, t('sorting.ai.instructionsSaved'))
  }

  const address = chosen === 'messages' ? MESSAGES_URL : url.trim()
  const keyKept = stored.key_set && stored.provider === chosen && (chosen === 'messages' || stored.url === address || stored.url === `${address}/`)

  /** Saves what is typed, then asks the stored service one tiny question with nothing of a document in it. */
  const saveAndTry = () => {
    setProbed(null)
    void action.run(async () => {
      const change: Parameters<typeof aiApi.save>[0] = { provider: chosen, url: address, model: model.trim() }
      if (key.trim()) change.key = key.trim()
      take(await aiApi.save(change))
      const { seconds } = await aiApi.probe()
      setProbed(seconds)
    })
  }

  return (
    <Card id="ai-provider" icon={Sparkles} title={t('server.ai.title')} subtitle={t('server.ai.text')}>
      {/* The providers to choose from, each with what it means; nothing is saved before "Save and try". */}
      <Segment<AiProvider>
        label={t('server.ai.title')}
        hideLabel
        value={chosen}
        onChange={(provider) => choose(provider)}
        options={AI_PROVIDERS.map((provider) => ({ value: provider, label: providerName(provider, t), testId: `ai-${provider}` }))}
        hints={[t(`server.ai.${chosen}Note`)]}
        testId="ai-providers"
      />
      {chosen !== 'none' && (
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            saveAndTry()
          }}
        >
          {chosen !== 'messages' && <Field label={t('server.ai.address')} value={url} onChange={(event) => setUrl(event.target.value)} placeholder={chosen === 'local' ? LOCAL_URL : 'https://api.example.com/v1'} />}
          {/* A local model takes a key too, where its service asks for one (LiteLLM in the own network). */}
          <Field
            label={chosen === 'local' ? t('server.ai.keyOptional') : t('server.ai.key')}
            type="password"
            autoComplete="new-password"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            placeholder={keyKept ? t('server.ai.keyKept') : ''}
            hints={chosen === 'local' ? [t('server.ai.keyLocalHint')] : undefined}
          />
          {models ? (
            <SelectField
              label={t('server.ai.pick')}
              value={model}
              onChange={(event) => setModel(event.target.value)}
              options={[...(models.some((entry) => entry.id === model) ? [] : [{ value: model, label: model || '…' }]), ...models.map((entry) => ({ value: entry.id, label: entry.name || entry.id }))]}
            />
          ) : (
            <Field label={t('server.ai.model')} value={model} onChange={(event) => setModel(event.target.value)} placeholder={chosen === 'local' ? 'llama3.1:8b' : ''} />
          )}
          <div className="sm:col-span-2">
            {/* Saved at once, apart from the service: it says what may go to any model. */}
            <CheckboxRow
              label={t('sorting.ai.skipPersonal')}
              hint={t('sorting.ai.skipPersonalHint')}
              checked={stored.skip_personal !== false}
              onChange={(skip_personal) => {
                setStored({ ...stored, skip_personal })
                void action.run(async () => setStored(await aiApi.save({ skip_personal })))
              }}
            />
          </div>
          <div className="flex flex-col gap-1 sm:col-span-2">
            <Field
              label={t('sorting.ai.dailyLimit')}
              hints={[t('sorting.ai.dailyLimitHint')]}
              type="number"
              min={0}
              max={100000}
              value={limit ?? String(stored.daily_limit ?? 200)}
              onChange={(event) => setLimit(event.target.value)}
              action={
                <Button kind="secondary" icon="Check" busy={action.busy} onClick={saveLimit}>
                  {t('sorting.ai.dailyLimitSave')}
                </Button>
              }
            />
            <p className="m-0 text-sm" data-testid="ai-used-today">
              {t('sorting.ai.usedToday', { count: stored.used_today ?? 0 })}
            </p>
          </div>
          <div className="flex flex-col gap-1 text-sm sm:col-span-2">
            <label htmlFor={wishesField} className="font-medium">
              {t('sorting.ai.instructions')}
            </label>
            <textarea
              id={wishesField}
              value={wishes ?? stored.instructions ?? ''}
              onChange={(event) => setWishes(event.target.value)}
              rows={4}
              maxLength={WISHES_MAX}
              placeholder={t('sorting.ai.instructionsPlaceholder')}
              aria-describedby={wishesHint}
              className={AREA}
            />
            <span id={wishesHint} className="text-xs text-[var(--nexui-text-muted)]">
              {t('sorting.ai.instructionsHint', { max: WISHES_MAX })}
            </span>
            <div className="mt-1">
              <Button kind="secondary" icon="Check" busy={action.busy} disabled={wishes === null} onClick={saveWishes}>
                {t('sorting.ai.instructionsSave')}
              </Button>
            </div>
          </div>
          {limitInvalid && (
            <div className="sm:col-span-2">
              <Notice tone="danger">{t('sorting.ai.dailyLimitInvalid')}</Notice>
            </div>
          )}
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button kind="primary" icon="Check" type="submit" busy={action.busy} disabled={!address || !model.trim()}>
              {t('server.ai.saveTry')}
            </Button>
            {/* The models the service offers, with what is typed: the list is the test that address and key are right. */}
            <Button
              kind="secondary"
              icon="RefreshCw"
              busy={listing.busy}
              disabled={!address}
              onClick={() =>
                void listing.run(async () =>
                  setModels(await aiApi.models({ provider: chosen, url: address, ...(key.trim() ? { key: key.trim() } : {}) })),
                )
              }
            >
              {t('server.ai.models')}
            </Button>
          </div>
        </form>
      )}
      <Outcome problem={listing.problem} values={listing.values} />
      {chosen !== 'none' && chosen !== 'local' && <p className="m-0 text-xs leading-relaxed text-[var(--nexui-text-muted)]">{t('server.ai.outgoing')}</p>}
      <Outcome
        problem={action.problem}
        values={action.values}
        done={probed !== null ? t('server.ai.probed', { seconds: new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(probed) }) : action.done}
      />
    </Card>
  )
}
