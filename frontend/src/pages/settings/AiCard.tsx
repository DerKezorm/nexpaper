/**
 * "KI-Vorschläge im Eingang", as the mock's card under Settings, AI: the operator chooses one service for
 * everybody (none from the start), with its address, key (for a local model only where its service asks for one)
 * and model, and tries it. The key is typed once and never shown again; a new address or another kind of service
 * forgets it (the server does that). Nobody else can set this.
 */
import { Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { aiApi, type AiModel, type AiProvider, type AiSettings } from '../../api/client'
import { AI_PROVIDERS, LOCAL_URL, MESSAGES_URL, providerName } from '../../lib/aiProviders'
import { Button, Card, Feedback, Input, Select, Toggle, useAction } from './ui'

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
    <Card id="ai" icon={Sparkles} title={t('server.ai.title')} text={t('server.ai.text')}>
      <div className="grid gap-2 sm:grid-cols-2">
        {AI_PROVIDERS.map((provider) => {
          const on = chosen === provider
          return (
            <button
              key={provider}
              type="button"
              onClick={() => provider !== chosen && choose(provider)}
              aria-pressed={on}
              className={`rounded-xl border px-4 py-3 text-left text-sm transition ${on ? 'border-accent bg-accent-soft/50' : 'border-line hover:bg-sheet-2'}`}
            >
              <span className="font-semibold">{providerName(provider, t)}</span>
              <span className="mt-0.5 block text-xs text-muted">{t(`server.ai.${provider}Note`)}</span>
            </button>
          )
        })}
      </div>
      {chosen !== 'none' && (
        <form
          className="mt-4 grid gap-3 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault()
            saveAndTry()
          }}
        >
          {chosen !== 'messages' && <Input label={t('server.ai.address')} value={url} onChange={setUrl} placeholder={chosen === 'local' ? LOCAL_URL : 'https://api.example.com/v1'} />}
          {/* A local model takes a key too, where its service asks for one (LiteLLM in the own network). */}
          <Input
            label={chosen === 'local' ? t('server.ai.keyOptional') : t('server.ai.key')}
            type="password"
            autoComplete="new-password"
            value={key}
            onChange={setKey}
            placeholder={keyKept ? t('server.ai.keyKept') : ''}
            hint={chosen === 'local' ? t('server.ai.keyLocalHint') : undefined}
          />
          {models ? (
            <Select label={t('server.ai.pick')} value={model} onChange={setModel} options={[...(models.some((entry) => entry.id === model) ? [] : [{ value: model, label: model || '…' }]), ...models.map((entry) => ({ value: entry.id, label: entry.name || entry.id }))]} />
          ) : (
            <Input label={t('server.ai.model')} value={model} onChange={setModel} placeholder={chosen === 'local' ? 'llama3.1:8b' : ''} />
          )}
          <div className="sm:col-span-2">
            {/* Saved at once, apart from the service: it says what may go to any model (B6). */}
            <Toggle
              label={t('sorting.ai.skipPersonal')}
              hint={t('sorting.ai.skipPersonalHint')}
              checked={stored.skip_personal !== false}
              onChange={(skip_personal) => {
                setStored({ ...stored, skip_personal })
                void action.run(async () => setStored(await aiApi.save({ skip_personal })))
              }}
            />
          </div>
          <div className="flex flex-wrap items-end gap-3 sm:col-span-2">
            <Input
              className="w-full sm:w-72"
              label={t('sorting.ai.dailyLimit')}
              hint={t('sorting.ai.dailyLimitHint')}
              type="number"
              min={0}
              max={100000}
              value={limit ?? String(stored.daily_limit ?? 200)}
              onChange={setLimit}
            />
            <div className="pb-6">
              <Button busy={action.busy} onClick={saveLimit}>
                {t('sorting.ai.dailyLimitSave')}
              </Button>
            </div>
            <p className="pb-6 text-sm text-ink-2" data-testid="ai-used-today">
              {t('sorting.ai.usedToday', { count: stored.used_today ?? 0 })}
            </p>
          </div>
          {limitInvalid && (
            <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad sm:col-span-2">
              {t('sorting.ai.dailyLimitInvalid')}
            </p>
          )}
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button primary type="submit" busy={action.busy} disabled={!address || !model.trim()}>
              {t('server.ai.saveTry')}
            </Button>
            {/* The models the service offers, with what is typed: the list is the test that address and key are right. */}
            <Button
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
      <Feedback problem={listing.problem} values={listing.values} />
      {chosen !== 'none' && chosen !== 'local' && <p className="mt-4 rounded-xl bg-sheet-2 px-4 py-3 text-xs leading-relaxed text-ink-2">{t('server.ai.outgoing')}</p>}
      <Feedback
        problem={action.problem}
        values={action.values}
        done={probed !== null ? t('server.ai.probed', { seconds: new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(probed) }) : action.done}
      />
    </Card>
  )
}
