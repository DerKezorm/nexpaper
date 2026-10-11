/**
 * Settings, Sign-in: "Ready for the internet?", which nexpaper checks about itself each time the page opens. The server
 * checks, the card says what it means.
 */
import { AlertTriangle, Check, Shield, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, type Readiness } from '../../api/client'
import { Card } from './ui'

type Point = Readiness['points'][number]

/** The sentence of a point: some points have a sentence of their own for a special case. */
function sentence(point: Point): string {
  const { key, state, values } = point
  if (key === 'secrets' && state === 'bad') return values.missing ? 'ready.secrets.missing' : 'ready.secrets.bad'
  if (key === 'secrets' && state === 'ok') return values.source ? 'ready.secrets.env' : 'ready.secrets.ok'
  if (key === 'proxy' && state === 'ok') return values.forwarded ? 'ready.proxy.ok' : 'ready.proxy.direct'
  if (key === 'brake' && state === 'bad') return values.broken ? 'ready.brake.broken' : 'ready.brake.bad'
  return `ready.${key}.${state}`
}

export function ReadinessCard() {
  const { t, i18n } = useTranslation()
  const [found, setFound] = useState<Readiness | null>(null)
  useEffect(() => {
    api<Readiness>('/api/v1/settings/readiness').then(setFound, () => undefined)
  }, [])
  if (!found) return null
  const open = found.open
  return (
    <Card icon={Shield} title={t('ready.title')} text={t('ready.text')}>
      <div data-testid="ready-summary" className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold ${open ? 'bg-warn/15 text-warn' : 'bg-accent-soft text-accent'}`}>
        {open ? <AlertTriangle size={14} aria-hidden /> : <Check size={14} aria-hidden />}
        {open ? t('ready.open', { count: open }) : t('ready.allGood')}
      </div>
      <ul className="space-y-2">
        {found.points.map((point) => {
          const when = typeof point.values.when === 'string' ? new Date(point.values.when).toLocaleString(i18n.language, { dateStyle: 'long', timeStyle: 'short' }) : ''
          return (
            <li key={point.key} data-state={point.state} className="flex gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-3 text-sm">
              <span
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${point.state === 'ok' ? 'bg-accent text-accent-ink' : point.state === 'warn' ? 'bg-warn text-white' : 'bg-bad text-white'}`}
                aria-label={t(`ready.state.${point.state}`)}
              >
                {point.state === 'ok' ? <Check size={12} strokeWidth={3} /> : point.state === 'warn' ? <AlertTriangle size={11} strokeWidth={3} /> : <X size={12} strokeWidth={3} />}
              </span>
              <span className="min-w-0">
                <span className="font-semibold">{t(`ready.${point.key}.title`)}</span>
                <span className="block text-xs break-words text-muted">{t(sentence(point), { ...point.values, when, ...(typeof point.values.days === 'number' ? { count: point.values.days } : {}) })}</span>
              </span>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
