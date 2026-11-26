/**
 * Server › General: the card "Sprachen" (Globe) as nexnotes has it (plan "Einstellungen", Allgemein 5, E48), built only
 * from the ui kit. The line names the languages the app has built in; below, each built-in one as a `Chip` ("Deutsch ·
 * eingebaut"), each of the operator's files as a `Chip` with removing (E19: the symbol alone, named "<Name>
 * entfernen"); "Vorlage herunterladen" (secondary, Download); the field "Sprachcode" with its own button "Sprache
 * hochladen" (`Field action`, secondary, Upload), which opens the choice of a file.
 *
 * The app hands over how it calls its server (`fetcher`), where the routes are (`base`), its name (the template's
 * file), its English texts if its page makes the template (nexnotes; else the server hands it out), and what to do
 * after a change (`onChange`: its i18n forgets the list). The words come with the module (de, en, fr), in the language
 * the kit uses (`NexuiLanguage`, else the page's) unless `language` says otherwise.
 *
 * Copied unchanged into frontend/src/vendor/nexsprachen/ by bauplaene/sprachen/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

import { Button, Buttons, Card, Chip, Field, Notice, NEXUI_TEXTS, useNexuiTexts } from '../nexui'
import {
  BASE,
  CODE,
  errorText,
  hintOf,
  makeSprachenApi,
  plainFetch,
  saveFile,
  templateFile,
  textsCount,
  useSprachenTexts,
  type Fetcher,
  type LanguageEntry,
  type Texts,
} from './sprachen'

export type LanguagesCardProps = {
  /** The app's way to the server (its cookies, a base path); default `fetch`. */
  fetcher?: Fetcher
  /** Where the routes are mounted: `/api/locales`. */
  base?: string
  /** The app's name, for the template's file (`<app>-language-template.json`). */
  app: string
  /** The app's English texts as its i18n has them; given, the page makes the template itself (nexnotes), else it
   * fetches `<base>/template`. */
  template?: Texts
  /** After a language was added or removed (the app's i18n forgets its list). */
  onChange?: () => void
  /** `de`, `en` or `fr`; default the kit's. */
  language?: string
  testId?: string
}

export function LanguagesCard({ fetcher = plainFetch, base = BASE, app, template, onChange, language, testId = 'languages-card' }: LanguagesCardProps) {
  const texts = useSprachenTexts(language)
  const kit = useNexuiTexts()
  const shownIn = language ?? (kit === NEXUI_TEXTS.de ? 'de' : kit === NEXUI_TEXTS.fr ? 'fr' : 'en')
  const api = useMemo(() => makeSprachenApi(fetcher, base), [fetcher, base])
  const [list, setList] = useState<LanguageEntry[] | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  const load = useCallback(() => api.list().then(setList, (error: unknown) => setProblem(errorText(texts, error))), [api, texts])
  useEffect(() => {
    void load()
  }, [load])

  const run = async (work: () => Promise<unknown>, success: string | null) => {
    setBusy(true)
    setProblem(null)
    setDone(null)
    try {
      await work()
      if (success) setDone(success)
    } catch (error) {
      setProblem(errorText(texts, error))
    } finally {
      setBusy(false)
    }
  }
  const changed = async () => {
    onChange?.()
    await load()
  }
  const upload = (file: File) =>
    void run(async () => {
      await api.upload(code, file)
      setCode('')
      await changed()
    }, texts.added)
  const remove = (entry: LanguageEntry) =>
    void run(async () => {
      await api.remove(entry.code)
      await changed()
    }, null)
  const download = () =>
    void run(async () => saveFile(`${app}-language-template.json`, template ? templateFile(template) : await api.template()), null)

  const entries = list ?? []
  const builtIn = entries.filter((entry) => entry.built_in)
  const own = entries.filter((entry) => entry.own)
  return (
    <Card id="languages" icon="Globe" title={texts.title} subtitle={builtIn.length ? hintOf(texts, entries, shownIn) : undefined} testId={testId}>
      <div className="flex flex-wrap gap-2" data-testid="languages-list">
        {builtIn.map((entry) => (
          <Chip key={`built-in-${entry.code}`} testId={`language-built-in-${entry.code}`}>{`${entry.name} · ${texts.builtIn}`}</Chip>
        ))}
        {own.map((entry) => (
          <Chip key={entry.code} name={entry.name} disabled={busy} testId={`language-${entry.code}`} onRemove={() => remove(entry)}>
            {`${entry.name} (${entry.code}) · ${textsCount(texts, entry.keys)}`}
          </Chip>
        ))}
      </div>
      <Buttons>
        <Button kind="secondary" icon="Download" onClick={download} disabled={busy} testId="language-template">
          {texts.template}
        </Button>
      </Buttons>
      <Field
        label={texts.code}
        value={code}
        onChange={(event) => setCode(event.target.value.trim())}
        placeholder="nl"
        autoComplete="off"
        spellCheck={false}
        data-testid="language-code"
        action={
          <Button kind="secondary" icon="Upload" disabled={!CODE.test(code)} busy={busy} accept="application/json,.json" onFile={upload} testId="language-upload">
            {texts.upload}
          </Button>
        }
      />
      {problem && (
        <Notice tone="danger" testId="languages-problem">
          {problem}
        </Notice>
      )}
      {done && (
        <Notice tone="ok" testId="languages-done">
          {done}
        </Notice>
      )}
    </Card>
  )
}
