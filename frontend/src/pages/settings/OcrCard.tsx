/**
 * Settings, Storage: the card "Text recognition" of the mock. The languages the recognition reads (the six the server
 * carries), straightening, the switch for blank separator pages (kept now, acted on by the page tools later) and the
 * queue: how many documents are being read, how many wait, and how long a page took. A switch or a language is saved at
 * once; the longest time for one document (shown in minutes, kept in seconds) with its own button.
 */
import { ScanText } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ocrApi, type OcrSettings } from '../../api/client'
import { Button, Card, Feedback, Input, Toggle, useAction } from './ui'

export function OcrCard() {
  const { t, i18n } = useTranslation()
  const [settings, setSettings] = useState<OcrSettings | null>(null)
  const action = useAction()
  const [minutes, setMinutes] = useState<string | null>(null)
  const [invalid, setInvalid] = useState(false)
  const look = useCallback(() => ocrApi.read().then(setSettings, () => undefined), [])
  useEffect(() => {
    void look()
    // The queue changes while the page is open.
    const timer = window.setInterval(() => void look(), 5000)
    return () => window.clearInterval(timer)
  }, [look])
  if (!settings) return null
  const save = (change: Parameters<typeof ocrApi.save>[0]) => {
    // Shown at once; the server's answer is what stays (it may order or refuse).
    setSettings({ ...settings, ...change })
    void action.run(async () => setSettings(await ocrApi.save(change))).then((worked) => {
      if (!worked) void look()
    })
  }
  const toggle = (code: string) => {
    const on = settings.languages.includes(code)
    // At least one language: the last one cannot be switched off.
    if (on && settings.languages.length === 1) return
    save({ languages: on ? settings.languages.filter((x) => x !== code) : settings.offered.filter((x) => x === code || settings.languages.includes(x)) })
  }
  const saveMinutes = () => {
    if (minutes === null) return
    const number = Number(minutes)
    if (!/^\d+$/.test(minutes.trim()) || number < 1 || number > 1440) {
      setInvalid(true)
      return
    }
    setInvalid(false)
    setMinutes(null)
    if (number * 60 !== settings.max_seconds) save({ max_seconds: number * 60 })
  }
  const seconds = settings.seconds_per_page === null ? null : new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 }).format(settings.seconds_per_page)
  return (
    <Card icon={ScanText} title={t('ocr.title')} text={t('ocr.text')}>
      {!settings.available && (
        <p role="note" className="rounded-xl border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-ink-2">
          {t('ocr.unavailable')}
        </p>
      )}
      <div>
        <p className="text-sm font-semibold">{t('ocr.languages')}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {settings.offered.map((code) => {
            const on = settings.languages.includes(code)
            return (
              <button
                key={code}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(code)}
                className={`rounded-full border px-3.5 py-1.5 text-sm font-semibold ${on ? 'border-accent/50 bg-accent-soft text-accent' : 'border-line text-ink-2'}`}
              >
                {t(`ocr.language.${code}`)}
              </button>
            )
          })}
        </div>
        <p className="mt-2 text-xs text-muted">{t('ocr.languagesHint')}</p>
      </div>
      <div className="space-y-2 pt-1">
        <Toggle label={t('ocr.straighten')} hint={t('ocr.straightenHint')} checked={settings.straighten} onChange={(straighten) => save({ straighten })} />
        <Toggle label={t('ocr.blank')} hint={t('ocr.blankHint')} checked={settings.blank_pages} onChange={(blank_pages) => save({ blank_pages })} />
      </div>
      <div className="rounded-xl bg-sheet-2 px-4 py-3 text-sm">
        <p className="font-semibold">{t('ocr.queue')}</p>
        <p className="text-ink-2" data-testid="queue-line">
          {t('ocr.queueLine', { count: settings.running, waiting: settings.waiting })}
          {seconds !== null && ' ' + t('ocr.pace', { seconds })}
          {' ' + t('ocr.oneAtATime')}
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Input
          className="w-full sm:w-72"
          label={t('ocr.maxMinutes')}
          hint={t('ocr.maxMinutesHint')}
          type="number"
          min={1}
          max={1440}
          value={minutes ?? String(Math.round(settings.max_seconds / 60))}
          onChange={setMinutes}
        />
        <div className="pb-6">
          <Button busy={action.busy} onClick={saveMinutes}>
            {t('ocr.save')}
          </Button>
        </div>
      </div>
      {invalid && (
        <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {t('ocr.maxMinutesInvalid')}
        </p>
      )}
      <Feedback problem={action.problem} values={action.values} />
    </Card>
  )
}
