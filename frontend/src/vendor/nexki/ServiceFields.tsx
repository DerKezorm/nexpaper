/**
 * The fields of one AI service, the same for the operator's service (Server › KI-Anbieter, card "KI-Dienst") and an
 * account's own (Mein Konto › KI, card "Eigener Zugang"): interface (`Segment`), template (`Segment` of the tiles,
 * fills in address and interface), address, key (never shown, "Bleibt; nur zum Ändern tippen."), model with "Modelle
 * laden" as the field's own button and the models found as a choice. Saving is the caller's (`onSave` gets only what
 * changed). Copied unchanged into frontend/src/vendor/nexki/ by bauplaene/ki/tools/sync.py; changed only there.
 */
import { useState, type ReactNode } from 'react'

import { Button, Buttons, Field, Segment, SelectField, TextLink } from '../nexui'
import { AI_TILES, fillKi, refusalText, tileOf, type AiApi, type AiModel, type KiTexts } from './ki'

export type ServiceValues = { api: AiApi | ''; url: string; model: string; key_set: boolean }
export type ServiceChange = Partial<{ api: AiApi; url: string; model: string; key: string }>

export type ServiceFieldsProps = {
  texts: KiTexts
  app: string
  value: ServiceValues
  /** Asks the models of the typed (or stored) service. */
  loadModels: (typed: { api: AiApi; url: string; key?: string }) => Promise<AiModel[]>
  onSave: (change: ServiceChange) => Promise<void>
  busy?: boolean
  /** Further buttons in the same row, after "Speichern" (the operator's "Verbindung prüfen"). */
  more?: ReactNode
  testId?: string
}

export function ServiceFields({ texts, app, value, loadModels, onSave, busy = false, more, testId = 'ki-service' }: ServiceFieldsProps) {
  const [api, setApi] = useState<AiApi>(value.api || 'openai')
  const [url, setUrl] = useState(value.url)
  const [model, setModel] = useState(value.model)
  const [key, setKey] = useState('')
  const [models, setModels] = useState<AiModel[]>([])
  const [problem, setProblem] = useState<string>()
  const [loading, setLoading] = useState(false)
  const tile = tileOf(url)

  const load = async () => {
    setLoading(true)
    setProblem(undefined)
    try {
      setModels(await loadModels({ api, url, ...(key ? { key } : {}) }))
    } catch (failure) {
      setProblem(refusalText(texts, failure, app))
    } finally {
      setLoading(false)
    }
  }

  const save = async () => {
    setProblem(undefined)
    const change: ServiceChange = {}
    if (api !== value.api) change.api = api
    if (url !== value.url) change.url = url
    if (model !== value.model) change.model = model
    if (key) change.key = key
    try {
      await onSave(change)
      setKey('')
    } catch (failure) {
      setProblem(refusalText(texts, failure, app))
    }
  }

  return (
    <div className="flex flex-col gap-4" data-testid={testId}>
      <Segment
        label={texts.service.tiles}
        value={tile?.id ?? ''}
        onChange={(id) => {
          const chosen = AI_TILES.find((one) => one.id === id)
          if (!chosen) return
          setApi(chosen.api)
          setUrl(chosen.url)
          setModels([])
        }}
        options={AI_TILES.map((one) => ({ value: one.id, label: one.name, testId: `${testId}-tile-${one.id}` }))}
        testId={`${testId}-tiles`}
      />
      <Segment
        label={texts.service.api}
        value={api}
        onChange={setApi}
        options={[
          { value: 'openai', label: texts.service.apiOpenai },
          { value: 'messages', label: texts.service.apiMessages },
        ]}
        testId={`${testId}-api`}
      />
      <Field label={texts.service.url} hints={[texts.service.urlHint]} value={url} onChange={(event) => setUrl(event.target.value)} mono data-testid={`${testId}-url`} />
      <Field
        label={texts.service.key}
        type="password"
        autoComplete="off"
        placeholder={value.key_set ? texts.service.keyKept : ''}
        hints={[
          texts.service.keyHint,
          ...(tile?.keys
            ? [
                <TextLink key="where" href={tile.keys}>
                  {fillKi(texts.service.keyWhere, { name: tile.name })}
                </TextLink>,
              ]
            : []),
        ]}
        value={key}
        onChange={(event) => setKey(event.target.value)}
        data-testid={`${testId}-key`}
      />
      <Field
        label={texts.service.model}
        value={model}
        onChange={(event) => setModel(event.target.value)}
        mono
        data-testid={`${testId}-model`}
        error={problem}
        action={
          <Button kind="secondary" size="sm" icon="RefreshCw" busy={loading} disabled={!url} onClick={() => void load()} testId={`${testId}-load`}>
            {texts.service.loadModels}
          </Button>
        }
      />
      {models.length > 0 && (
        <SelectField
          label={texts.service.chooseModel}
          value={models.some((one) => one.id === model) ? model : ''}
          onChange={(event) => setModel(event.target.value)}
          options={[{ value: '', label: '…' }, ...models.map((one) => ({ value: one.id, label: one.name || one.id }))]}
          data-testid={`${testId}-models`}
        />
      )}
      <Buttons>
        <Button kind="primary" icon="Check" busy={busy} onClick={() => void save()} testId={`${testId}-save`}>
          {texts.service.save}
        </Button>
        {more}
      </Buttons>
    </div>
  )
}
