/**
 * A document open to the outside (N2b): a link that works shows it, as its own document or as a further one, and so
 * whatever is changed in its pages is seen there at once. The server tells everybody who may change the document
 * (`shown_outside`), only yes or no.
 *
 * `ShownOutsideNotice` is the short notice at the document for who may change it but not share it (who may share it sees
 * to whom and until when as before). `useOutsideAsk` asks before a change of the pages (the page tools, joining,
 * splitting, a new version, an old version back; `useOutsideAsk.tsx`).
 */
import { Link2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { DocumentInfo } from '../api/client'

export function ShownOutsideNotice({ document }: { document: Pick<DocumentInfo, 'shown_outside' | 'can_share'> }) {
  const { t } = useTranslation()
  if (!document.shown_outside || document.can_share) return null
  return (
    <p className="mt-2 flex items-start gap-2 rounded-2xl border border-line p-4 text-sm text-ink-2" data-testid="shown-outside">
      <Link2 size={14} className="mt-0.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1">{t('shownOutside.notice')}</span>
    </p>
  )
}
