/**
 * At a document that a link of another document shows too (N2): for whoever may see the links of this document (the
 * managers of its vault and its owner), to whom, until when and through which document (only when the person may see
 * that one, else "another document"), with "Herausnehmen" to take it out of that link. Taking out asks first: only a
 * new link can show it again. Nobody should have a document open to the outside without seeing it here.
 *
 * Shown on the document page (details) and in the share dialog; it loads what it shows itself.
 */
import { Link2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, sharingApi, type ShownThrough as Through } from '../api/client'
import { shortDate } from '../lib/dates'
import { errorText } from '../lib/errors'
import { iso } from '../lib/say'
import { useConfirm } from './useConfirm'

type Props = {
  document: { id: number; title: string; can_share?: boolean }
  /** What was done, in a sentence, for the page to show (a toast). */
  say?: (text: string) => void
  /** After something was taken out (the page counts its links again). */
  onChange?: () => void
  /** Without the frame of its own (inside the share dialog). */
  bare?: boolean
}

export function ShownThroughNotice({ document, say, onChange, bare = false }: Props) {
  const { t, i18n } = useTranslation()
  const [found, setFound] = useState<Through[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const { ask, dialog } = useConfirm()

  const load = useCallback(() => {
    if (!document.can_share) {
      setFound([])
      return Promise.resolve()
    }
    return sharingApi.shownThrough(document.id).then(
      (list) => setFound(Array.isArray(list) ? list : []),
      () => setFound([]),
    )
  }, [document.id, document.can_share])

  useEffect(() => {
    void load()
  }, [load])

  if (!found.length) return null
  const takeOut = (entry: Through) =>
    ask({
      title: t('linkRelated.confirm.title'),
      text: t('linkRelated.confirm.text', { to: iso(entry.recipient), title: iso(document.title) }),
      confirm: t('linkRelated.confirm.confirm'),
      run: async () => {
        setProblem(null)
        try {
          await sharingApi.takeOut(document.id, entry.id)
          say?.(t('linkRelated.takenOut'))
        } catch (error) {
          setProblem(error instanceof ApiError ? error.code : 'internal_error')
        }
        await load()
        onChange?.()
      },
    })
  return (
    <div className={bare ? 'mt-3' : 'mt-2 rounded-2xl border border-line p-4 text-sm'} data-testid="shown-through">
      <p className={bare ? 'text-xs font-semibold text-ink-2' : 'font-semibold'}>{t('linkRelated.through')}</p>
      <ul className="mt-1 space-y-1">
        {found.map((entry) => {
          const until = shortDate(entry.until, i18n.language)
          const line = entry.document_title
            ? t('linkRelated.throughLine', { to: iso(entry.recipient), title: iso(entry.document_title), until })
            : t('linkRelated.throughLineOther', { to: iso(entry.recipient), until })
          return (
            <li key={entry.id} className={`flex items-start gap-2 text-ink-2 ${bare ? 'text-xs' : ''}`}>
              <Link2 size={14} className="mt-0.5 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 break-words">{line}</span>
              <button type="button" onClick={() => takeOut(entry)} className="shrink-0 text-xs font-semibold text-muted hover:text-ink" aria-label={t('linkRelated.takeOutFor', { to: entry.recipient })}>
                {t('linkRelated.takeOut')}
              </button>
            </li>
          )
        })}
      </ul>
      {problem && (
        <p role="alert" className="mt-2 text-xs text-bad">
          {errorText(problem)}
        </p>
      )}
      {dialog}
    </div>
  )
}
