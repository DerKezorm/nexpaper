/**
 * Opening a protected PDF (P1): at the card of the inbox and on the document page, where the reading error stands. A
 * field "Passwort" with "Öffnen", a box "Für künftige Dokumente merken" (off from the start) with a name of its own, and
 * one sentence on what happens: the PDF opened is kept without the password on the server, the original stays as it
 * came. The password goes to the server once and is never shown again; the field is emptied after every try.
 */
import { KeyRound, LockOpen } from 'lucide-react'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, pdfPasswordApi, type Unlocked } from '../api/client'
import { errorText } from '../lib/errors'
import { Button } from './Button'

export function UnlockPdf({ documentId, onOpened, compact = false }: { documentId: number; onOpened: (result: Unlocked) => void; compact?: boolean }) {
  const { t } = useTranslation()
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<{ code: string; values?: Record<string, unknown> } | null>(null)
  const id = useId()
  const open = async () => {
    if (!password || busy) return
    if (remember && !name.trim()) {
      setProblem({ code: 'pdf_password_name_missing' })
      return
    }
    setBusy(true)
    setProblem(null)
    try {
      const result = await pdfPasswordApi.unlock(documentId, password, remember, remember ? name.trim() : undefined)
      setPassword('')
      onOpened(result)
    } catch (error) {
      setPassword('')
      setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
    } finally {
      setBusy(false)
    }
  }
  const problemText = problem ? (problem.code === 'pdf_password_name_missing' ? t('pdfPassword.nameMissing') : errorText(problem.code, problem.values)) : ''
  return (
    <form
      className={compact ? 'mt-3 space-y-2' : 'space-y-3'}
      data-testid="unlock-pdf"
      onSubmit={(event) => {
        event.preventDefault()
        void open()
      }}
    >
      <label htmlFor={`${id}-password`} className="block text-sm font-semibold">
        {t('pdfPassword.label')}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <input
          id={`${id}-password`}
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="off"
          maxLength={512}
          className="input min-w-0 flex-1"
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? `${id}-problem` : undefined}
        />
        <Button type="submit" size="sm" variant="primary" disabled={!password || busy}>
          <LockOpen size={14} aria-hidden /> {t('pdfPassword.open')}
        </Button>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
        {t('pdfPassword.remember')}
      </label>
      {remember && (
        <div>
          <label htmlFor={`${id}-name`} className="mb-1 block text-xs text-muted">
            {t('pdfPassword.nameLabel')}
          </label>
          <input id={`${id}-name`} value={name} maxLength={60} onChange={(event) => setName(event.target.value)} placeholder={t('pdfPassword.namePlaceholder')} className="input" />
          <p className="mt-1 flex items-start gap-1.5 text-xs text-muted">
            <KeyRound size={13} className="mt-0.5 shrink-0" aria-hidden /> {t('pdfPassword.rememberHint')}
          </p>
        </div>
      )}
      {problem && (
        <p id={`${id}-problem`} role="alert" className="text-sm font-semibold text-bad">
          {problemText}
        </p>
      )}
      <p className="text-xs text-muted">{t('pdfPassword.openedCopy')}</p>
    </form>
  )
}
