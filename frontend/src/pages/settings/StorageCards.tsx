/**
 * Settings, General: the card "Grenzen" (limits), laid out as nexnotes' card of the same name: the size of one file
 * first, in its own row with its own button; nexpaper's further limits on what comes in below it, two to a row, with one
 * button for all of them. Settings, Storage: the card that shows how the files lie on the disk. The operator's numbers
 * count from the next file on.
 */
import { FolderTree, Gauge } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button, Card, Feedback, Input } from './ui'
import { useServerSettings, type ServerSettings } from './ServerCards'

type Field = keyof Pick<ServerSettings, 'upload_max_mb' | 'upload_max_pages' | 'upload_max_megapixels' | 'upload_open_count' | 'upload_open_mb' | 'process_timeout_seconds' | 'process_memory_mb' | 'cache_max_mb'>
type Limit = { key: Field; label: string; hint: string; min: number; max: number }

/** The size of one file: the limit both apps have, in the row of its own. */
const FILE: Limit = { key: 'upload_max_mb', label: 'maxFile', hint: 'maxFileHint', min: 1, max: 10240 }
/** nexpaper's further limits, the range the server takes for each, and the texts. */
const MORE: Limit[] = [
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
  /** Each button saves the fields of its own part, and only those that changed; a number out of range sends nothing. */
  const save = async (fields: Limit[]) => {
    const change: Partial<Record<Field, number>> = {}
    for (const field of fields) {
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
    setTyped((before) => {
      const left = { ...before }
      for (const field of fields) delete left[field.key]
      return left
    })
  }
  const field = (limit: Limit, className = '') => (
    <Input
      key={limit.key}
      label={t(`storage.limits.${limit.label}`)}
      hint={t(`storage.limits.${limit.hint}`)}
      type="number"
      min={limit.min}
      max={limit.max}
      value={shown(limit.key)}
      onChange={(value) => setTyped({ ...typed, [limit.key]: value })}
      className={className}
    />
  )
  return (
    <Card id="limits" icon={Gauge} title={t('storage.limits.title')} text={t('storage.limits.text')}>
      {/* The page checks the ranges itself and says so in words; the browser's own bubbles would say it twice. */}
      <form
        noValidate
        className="flex flex-wrap items-end gap-2"
        data-testid="limit-file"
        onSubmit={(event) => {
          event.preventDefault()
          void save([FILE])
        }}
      >
        {field(FILE, 'min-w-60 flex-1 sm:max-w-md')}
        <Button type="submit" busy={server.busy}>
          {t('storage.limits.save')}
        </Button>
      </form>
      <form
        noValidate
        className="space-y-3"
        data-testid="limit-more"
        onSubmit={(event) => {
          event.preventDefault()
          void save(MORE)
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">{MORE.map((limit) => field(limit))}</div>
        <Button type="submit" busy={server.busy}>
          {t('storage.limits.save')}
        </Button>
      </form>
      {invalid && (
        <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {t('storage.limits.invalid')}
        </p>
      )}
      <Feedback problem={server.problem} done={server.done} values={server.values} />
    </Card>
  )
}

/** How the files lie on the disk (read only: the scheme is fixed). */
export function DiskCard() {
  const { t } = useTranslation()
  return (
    <Card id="disk" icon={FolderTree} title={t('storage.disk.title')} text={t('storage.disk.text')}>
      <pre className="overflow-x-auto rounded-xl bg-sheet-2 p-3 font-mono text-xs leading-relaxed text-ink-2">
        {`/data/dokumente/Haushalt/2026/Stadtwerke Lindenau/2026-10-01 Rechnung.jpg
/data/dokumente/Haushalt/2026/Stadtwerke Lindenau/2026-10-01 Rechnung (searchable).pdf`}
      </pre>
      <p className="text-xs text-muted">{t('storage.disk.note')}</p>
      <p className="text-xs text-muted">{t('storage.disk.english')}</p>
    </Card>
  )
}
