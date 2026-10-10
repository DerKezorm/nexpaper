/**
 * "+ Neue Art": a small field at the end of the choice of kinds, in the inbox and on the page of a document. The kind
 * is made for the vault the document lies in and chosen at once. What sounds like a kind the vault can already choose is
 * offered first ("Meintest du ..."), and the very same name takes the kind that exists instead of making a second one.
 */
import { Plus } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, catalogApi, type DocumentKind } from '../api/client'
import { errorText } from '../lib/errors'
import { likeness } from '../lib/kinds'
import { Button } from './Button'
import { KindPill } from './docs'

/** The pill at the end of the choice that opens the field. */
export function NewKindButton({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-full border border-dashed border-line px-2.5 py-0.5 text-xs font-semibold text-ink-2 hover:bg-sheet-2 hover:text-ink"
    >
      <Plus size={13} aria-hidden /> {t('kinds.new.button')}
    </button>
  )
}

export function NewKindForm({ vaultId, kinds, onMade, onClose }: { vaultId: number; kinds: DocumentKind[]; onMade: (kind: DocumentKind) => void; onClose: () => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<{ code: string; values?: Record<string, unknown> } | null>(null)
  const field = useId()
  const found = likeness(name, kinds)

  const make = async (event?: FormEvent) => {
    event?.preventDefault()
    const typed = name.trim()
    if (!typed || busy) return
    // The same name: the kind that is there is the one meant.
    if (found.same) {
      onMade(found.same)
      return
    }
    setBusy(true)
    setProblem(null)
    try {
      onMade(await catalogApi.createKind(typed, vaultId, (kinds.length * 47) % 360))
    } catch (error) {
      setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="mt-2 space-y-2 rounded-xl border border-line bg-sheet-2 p-3" onSubmit={(event) => void make(event)} onKeyDown={(event) => event.key === 'Escape' && (event.stopPropagation(), onClose())}>
      <label htmlFor={field} className="block text-xs font-semibold text-ink-2">
        {t('kinds.new.label')}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <input id={field} value={name} maxLength={60} autoFocus onChange={(event) => setName(event.target.value)} placeholder={t('kinds.new.placeholder')} className="input h-9 min-w-40 flex-1" />
        <Button size="sm" variant="primary" type="submit" disabled={!name.trim() || busy}>
          {found.same ? t('kinds.new.take') : t('kinds.new.make')}
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          {t('common.cancel')}
        </Button>
      </div>
      {found.same && (
        <p className="text-xs text-ink-2" role="status">
          {t('kinds.new.exists', { name: found.same.name })}
        </p>
      )}
      {!found.same && found.like.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-2" role="status">
          <span>{t('kinds.new.like')}</span>
          {found.like.map((kind) => (
            <button key={kind.id} type="button" onClick={() => onMade(kind)} className="rounded-full ring-2 ring-transparent hover:ring-accent" aria-label={t('kinds.new.useThis', { name: kind.name })}>
              <KindPill kind={kind} small />
            </button>
          ))}
        </div>
      )}
      {problem && (
        <p role="alert" className="text-xs text-bad">
          {errorText(problem.code, problem.values)}
        </p>
      )}
    </form>
  )
}
