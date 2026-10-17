/**
 * Into the trash while the keeping time still runs: the question names "Aufbewahren bis …",
 * where it came from, and the button says "Trotzdem in den Papierkorb", so that nobody throws away by mistake what has
 * to be kept. Without a running keeping time the question stays as it always was. Used through `useConfirm`.
 */
import type { TFunction } from 'i18next'

import { TRASH_DAYS, type DocumentInfo } from '../api/client'
import { dayInDays, shortDate } from '../lib/dates'
import { keptOf } from '../lib/keeping'
import { iso } from '../lib/say'

export type TrashQuestion = { title: string; text: React.ReactNode; confirm: string }

/** Title, text and button of the question before one document goes to the trash. */
export function trashQuestion(d: DocumentInfo, t: TFunction, language: string, today: string = dayInDays(0)): TrashQuestion {
  const base = t('confirm.trash.text', { title: iso(d.title), days: TRASH_DAYS })
  const kept = keptOf(d)
  if (!kept || kept.date < today) return { title: t('confirm.trash.title'), text: base, confirm: t('confirm.trash.confirm') }
  return {
    title: t('confirm.trash.title'),
    text: (
      <>
        <p>{base}</p>
        <div className="mt-3 rounded-xl bg-warn-soft px-4 py-3 text-sm text-warn" data-testid="keep-running">
          <p className="font-semibold">{t('keeping.trashTitle', { date: shortDate(kept.date, language) })}</p>
          <p>
            {kept.from === 'kind' && d.kind ? t('keeping.trashKind', { kind: d.kind.name, years: t('keeping.years', { count: kept.years ?? 0 }) }) : t('keeping.trashHand')} {t('keeping.trashRunning')}
          </p>
        </div>
      </>
    ),
    confirm: t('keeping.trashAnyway'),
  }
}
