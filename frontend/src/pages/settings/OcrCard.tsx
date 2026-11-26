/**
 * Server › Text recognition: the card "Texterkennung", as nexnotes' card: the languages the recognition reads (the six
 * the server carries) as the kit's choice of several (`Segment multiple`, plan "Einstellungen") right under the head. Below, under "Verarbeitung", nexpaper's own:
 * straightening, the switch for blank separator pages (kept now, acted on by the page tools later) and the
 * queue: how many documents are being read, how many wait, and how long a page took. A switch or a language is saved at
 * once; the longest time for one document (shown in minutes, kept in seconds) with its own button.
 */
import { ScanText } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ocrApi, type OcrSettings } from '../../api/client'
import { Box, Button, Card, CheckboxRow, Field, Notice, Segment } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'

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
    <Card id="ocr" icon={ScanText} title={t('ocr.title')} subtitle={t('ocr.text')}>
      {!settings.available && <Notice tone="warn">{t('ocr.unavailable')}</Notice>}
      {/* At least one language: the last one cannot be switched off (`min`). */}
      <Segment<string>
        multiple
        min={1}
        label={t('ocr.languages')}
        hints={[t('ocr.languagesHint')]}
        value={settings.languages}
        onChange={(next) => save({ languages: settings.offered.filter((code) => next.includes(code)) })}
        options={settings.offered.map((code) => ({ value: code, label: t(`ocr.language.${code}`), testId: `ocr-${code}` }))}
        testId="ocr-languages"
      />
      <Box title={t('ocr.processing')} testId="ocr-processing">
        <CheckboxRow label={t('ocr.straighten')} hint={t('ocr.straightenHint')} checked={settings.straighten} onChange={(straighten) => save({ straighten })} />
        <CheckboxRow label={t('ocr.blank')} hint={t('ocr.blankHint')} checked={settings.blank_pages} onChange={(blank_pages) => save({ blank_pages })} />
      </Box>
      <Box title={t('ocr.queue')} testId="ocr-queue">
        <p className="m-0 text-sm" data-testid="queue-line">
          {t('ocr.queueLine', { count: settings.running, waiting: settings.waiting })}
          {seconds !== null && ' ' + t('ocr.pace', { seconds })}
          {' ' + t('ocr.oneAtATime')}
        </p>
      </Box>
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          saveMinutes()
        }}
      >
        <Field
          label={t('ocr.maxMinutes')}
          hints={[t('ocr.maxMinutesHint')]}
          type="number"
          min={1}
          max={1440}
          value={minutes ?? String(Math.round(settings.max_seconds / 60))}
          onChange={(event) => setMinutes(event.target.value)}
          action={
            <Button kind="secondary" icon="Check" type="submit" busy={action.busy}>
              {t('ocr.save')}
            </Button>
          }
        />
      </form>
      {invalid && <Notice tone="danger">{t('ocr.maxMinutesInvalid')}</Notice>}
      <Outcome problem={action.problem} values={action.values} />
    </Card>
  )
}
