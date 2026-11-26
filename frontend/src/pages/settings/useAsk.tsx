/**
 * "Really?" in the settings, from the ui kit (`ConfirmDialog`, plan "Einstellungen" E31): `ask` opens the dialog with
 * what to say and what to do, `dialog` is put in the card once. It works as the app's own `useConfirm` does elsewhere:
 * one click, one request; a refusal of the server stays in the dialog with its sentence; when it works, the dialog
 * closes. Where the server asks for the own password again, the field is the account module's ("Passwort").
 */
import { useCallback, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError } from '../../api/client'
import { errorText } from '../../lib/errors'
import { FIELDS } from '../../vendor/nexkonten/konten'
import { ConfirmDialog, Field, type IconLike } from '../../vendor/nexui'

export type AskOptions = {
  title: string
  text: ReactNode
  /** The words on the button that does it. */
  confirm: string
  /** Red (`danger`) when it removes or ends something; on from the start. */
  danger?: boolean
  /** The symbol of that button; `Trash2` for a danger, else `Check`. */
  icon?: IconLike
  /** The own password again, where the server asks for it. */
  password?: boolean
  /** More between the text and the buttons. */
  children?: ReactNode
  /** False: Escape and a click beside it leave the dialog open. */
  dismissable?: boolean
  run: (password: string) => Promise<void>
}

// eslint-disable-next-line react-refresh/only-export-components
function Asking({ options, onDone }: { options: AskOptions; onDone: () => void }) {
  const { t } = useTranslation()
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const sent = useRef(false)
  const danger = options.danger ?? true
  const go = async () => {
    if (sent.current) return
    sent.current = true
    setBusy(true)
    setProblem(null)
    try {
      await options.run(password)
      onDone()
    } catch (error) {
      setProblem(error instanceof ApiError ? errorText(error.code, error.values) : errorText('internal_error'))
      sent.current = false
      setBusy(false)
    }
  }
  return (
    <ConfirmDialog
      title={options.title}
      text={options.text}
      confirm={{ label: options.confirm, kind: danger ? 'danger' : 'primary', icon: options.icon ?? (danger ? 'Trash2' : 'Check') }}
      cancel={t('common.cancel')}
      closeLabel={t('common.close')}
      busy={busy}
      error={problem}
      confirmDisabled={Boolean(options.password) && !password}
      dismissable={options.dismissable}
      onCancel={onDone}
      onConfirm={() => void go()}
    >
      {options.children}
      {options.password && (
        <Field label={t(FIELDS.password.label)} type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
      )}
    </ConfirmDialog>
  )
}

export function useAsk() {
  const [options, setOptions] = useState<AskOptions | null>(null)
  const count = useRef(0)
  const [number, setNumber] = useState(0)
  const ask = useCallback((next: AskOptions) => {
    count.current += 1
    setNumber(count.current)
    setOptions(next)
  }, [])
  const dialog = options ? <Asking key={number} options={options} onDone={() => setOptions(null)} /> : null
  return { ask, dialog }
}
