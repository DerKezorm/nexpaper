/**
 * Settings, Storage: the limits on what comes in (with the card that shows how the files lie on
 * the disk; the queue is on the card of the text recognition, `OcrCard`). The operator's numbers count from the next file on.
 */
import { FolderTree, Upload } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Card, Feedback, Input } from './ui'
import { useServerSettings, type ServerSettings } from './ServerCards'

type Field = keyof Pick<ServerSettings, 'upload_max_mb' | 'upload_max_pages' | 'upload_max_megapixels' | 'upload_open_count' | 'upload_open_mb' | 'process_timeout_seconds' | 'process_memory_mb' | 'cache_max_mb'>

/** The fields, the range the server takes for each, and the texts. */
const FIELDS: { key: Field; label: string; hint: string; min: number; max: number }[] = [
  { key: 'upload_max_mb', label: 'maxFile', hint: 'maxFileHint', min: 1, max: 10240 },
  { key: 'upload_max_pages', label: 'maxPages', hint: 'maxPagesHint', min: 1, max: 20000 },
  { key: 'upload_max_megapixels', label: 'maxMegapixels', hint: 'maxMegapixelsHint', min: 1, max: 1000 },
  { key: 'upload_open_count', label: 'openCount', hint: 'openCountHint', min: 1, max: 100 },
  { key: 'upload_open_mb', label: 'openMb', hint: 'openMbHint', min: 1, max: 1048576 },
  { key: 'process_timeout_seconds', label: 'timeout', hint: 'timeoutHint', min: 5, max: 86400 },
  { key: 'process_memory_mb', label: 'memory', hint: 'memoryHint', min: 0, max: 65536 },
  { key: 'cache_max_mb', label: 'cache', hint: 'cacheHint', min: 64, max: 1048576 },
]

export function LimitsCard() {
  const { t } = useTranslation()
  const server = useServerSettings()
  const settings = server.settings
  const [typed, setTyped] = useState<Partial<Record<Field, string>>>({})
  const [invalid, setInvalid] = useState(false)
  if (!settings) return null
  const shown = (key: Field) => typed[key] ?? String(settings[key])
  const save = async () => {
    const change: Partial<Record<Field, number>> = {}
    for (const field of FIELDS) {
      const text = typed[field.key]
      if (text === undefined) continue
      const number = Number(text)
      // A memory limit under 256 MB is none PDFium and Pillow can work under: 0 (no limit) or at least that.
      const belowFloor = field.key === 'process_memory_mb' && number > 0 && number < 256
      if (!/^\d+$/.test(text.trim()) || number < field.min || number > field.max || belowFloor) {
        setInvalid(true)
        return
      }
      if (number !== settings[field.key]) change[field.key] = number
    }
    setInvalid(false)
    if (Object.keys(change).length === 0) return
    await server.save(change, t('storage.limits.saved'))
    setTyped({})
  }
  return (
    <Card icon={Upload} title={t('storage.limits.title')} text={t('storage.limits.text')}>
      <div className="grid gap-4 sm:grid-cols-2">
        {FIELDS.map((field) => (
          <Input
            key={field.key}
            label={t(`storage.limits.${field.label}`)}
            hint={t(`storage.limits.${field.hint}`)}
            type="number"
            min={field.min}
            max={field.max}
            value={shown(field.key)}
            onChange={(value) => setTyped({ ...typed, [field.key]: value })}
          />
        ))}
      </div>
      {invalid && (
        <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {t('storage.limits.invalid')}
        </p>
      )}
      <Feedback problem={server.problem} done={server.done} values={server.values} />
      <div>
        <Button primary busy={server.busy} onClick={() => void save()}>
          {t('storage.limits.save')}
        </Button>
      </div>
    </Card>
  )
}

/** How the files lie on the disk (read only: the scheme is fixed). */
export function DiskCard() {
  const { t } = useTranslation()
  return (
    <Card icon={FolderTree} title={t('storage.disk.title')} text={t('storage.disk.text')}>
      <pre className="overflow-x-auto rounded-xl bg-sheet-2 p-3 font-mono text-xs leading-relaxed text-ink-2">
        {`/data/dokumente/Haushalt/2026/Stadtwerke Lindenau/2026-10-01 Rechnung.jpg
/data/dokumente/Haushalt/2026/Stadtwerke Lindenau/2026-10-01 Rechnung (searchable).pdf`}
      </pre>
      <p className="text-xs text-muted">{t('storage.disk.note')}</p>
      <p className="text-xs text-muted">{t('storage.disk.english')}</p>
    </Card>
  )
}
