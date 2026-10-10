/**
 * "Really?" before everything that deletes or locks out, one dialog for the whole interface. It says what happens (a
 * document in the trash "can be brought back", one deleted for good "cannot", a locked-out device "can no longer ..."),
 * starts with the focus on "Abbrechen", is closed by Escape, and the button that does it is red when it cannot be taken
 * back. The request is made only after the one click on that button, and only once: the button waits while it runs, and
 * a refusal of the server is told inside the dialog, which stays open.
 *
 * A page asks with ``useConfirm()`` (``useConfirm.tsx``).
 */
import { useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../api/client'
import { errorText } from '../lib/errors'
import { Dialog } from './Dialog'

export type ConfirmOptions = {
  title: string
  /** What happens, in plain words; a person's text in it goes through ``iso`` (``lib/say``). */
  text: ReactNode
  /** The words on the button that does it ("In den Papierkorb", "Endgültig löschen", "Sperren"). */
  confirm: string
  /** Red when it cannot be taken back or locks somebody out. On from the start. */
  danger?: boolean
  /** The operator's password again, where the server asks for it. */
  password?: boolean
  /** The request. Its refusal is shown in the dialog; when it works, the dialog closes. */
  run: (password: string) => Promise<void>
}

export function ConfirmDialog({ title, text, confirm, danger = true, password = false, onCancel, onConfirm }: Omit<ConfirmOptions, 'run'> & { onCancel: () => void; onConfirm: (password: string) => Promise<void> }) {
  const { t } = useTranslation()
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<{ code: string; values?: Record<string, unknown> } | null>(null)
  // One click, one request: a second click before the first has been answered does nothing.
  const sent = useRef(false)
  const go = async () => {
    if (sent.current) return
    sent.current = true
    setBusy(true)
    setProblem(null)
    try {
      await onConfirm(value)
    } catch (error) {
      setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
      sent.current = false
      setBusy(false)
    }
  }
  return (
    <Dialog title={title} onClose={onCancel} above>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault()
          void go()
        }}
      >
        <div className="text-sm text-ink-2">{text}</div>
        {password && (
          <label className="block text-sm font-semibold">
            {t('settings.ownPassword')}
            <input type="password" value={value} onChange={(event) => setValue(event.target.value)} autoComplete="current-password" autoFocus className="input mt-1" />
          </label>
        )}
        {problem && (
          <p role="alert" className="text-sm text-bad">
            {errorText(problem.code, problem.values)}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            data-autofocus={password ? undefined : ''}
            onClick={onCancel}
            className="inline-flex h-10 items-center justify-center rounded-full border border-line px-4 text-sm font-semibold text-ink-2 transition hover:bg-sheet-2"
          >
            {t('common.cancel')}
          </button>
          <button
            type="submit"
            disabled={busy}
            className={`inline-flex h-10 items-center justify-center rounded-full px-4 text-sm font-semibold transition disabled:opacity-50 ${danger ? 'bg-bad text-bad-ink hover:brightness-110' : 'bg-accent text-accent-ink hover:brightness-105'}`}
          >
            {busy ? '…' : confirm}
          </button>
        </div>
      </form>
    </Dialog>
  )
}
