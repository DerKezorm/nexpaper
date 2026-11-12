/**
 * Asks before a change of the pages of a document open to the outside (N2b, `shown_outside`): the page tools, joining,
 * splitting, a new version, an old version back. One sentence and the buttons of every other question (`ConfirmDialog`);
 * nothing is sent before the click on the button that does it.
 */
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

import { useConfirm } from './useConfirm'

/** `guard(open, confirm, run)`: `run` at once when the document is not open to the outside, else after the question
 * (`confirm` is the word of the button, as the tool's own: "Speichern", "Zusammenfügen" ...). Put `dialog` in once. */
export function useOutsideAsk() {
  const { t } = useTranslation()
  const { ask, dialog } = useConfirm()
  const guard = useCallback(
    (open: boolean | undefined, confirm: string, run: () => Promise<void>) => {
      if (!open) {
        void run()
        return
      }
      ask({ title: t('shownOutside.title'), text: t('shownOutside.text'), confirm, danger: false, run })
    },
    [ask, t],
  )
  return { guard, dialog }
}
