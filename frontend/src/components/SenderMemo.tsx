/**
 * "Merkzettel" (K1): the vault's note on a sender (customer number, contract number, telephone), at most 500 characters
 * with line breaks. It stands under the sender on every document of the vault; whoever may change things in the vault
 * writes it, here at the document (the pencil) and under Ordnung, Absender. Somebody who sees a document through a share
 * alone does not see it (the server sends none), and it never reaches the link page or the AI.
 */
import { NotebookPen, Pencil } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, catalogApi, MEMO_MAX } from '../api/client'
import { errorText } from '../lib/errors'
import { Button } from './Button'
import { Dialog } from './Dialog'

export function MemoDialog({ sender, memo, onClose, onSaved }: { sender: { id: number; name: string }; memo: string; onClose: () => void; onSaved: (memo: string) => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState(memo)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const save = async () => {
    setBusy(true)
    setProblem(null)
    try {
      const saved = await catalogApi.setMemo(sender.id, text)
      onSaved(saved.memo)
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
      setBusy(false)
    }
  }
  return (
    <Dialog title={t('senderMemo.title', { name: sender.name })} onClose={onClose}>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          if (!busy) void save()
        }}
      >
        <p className="-mt-2 mb-3 text-sm text-ink-2">{t('senderMemo.text')}</p>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          maxLength={MEMO_MAX}
          rows={5}
          placeholder={t('senderMemo.placeholder')}
          aria-label={t('senderMemo.label')}
          className="input min-h-28 py-2"
          data-autofocus
        />
        <p className="mt-1 text-right text-xs text-muted tabular-nums">{t('senderMemo.count', { count: text.length, max: MEMO_MAX })}</p>
        {problem && <p className="mt-2 text-sm text-bad">{errorText(problem)}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" type="submit" disabled={busy}>
            {t('common.save')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

/** The line under the sender at the document: the note, and the pencil for whoever may change it. */
export function MemoLine({ sender, memo, canEdit, onSaved }: { sender: { id: number; name: string } | null; memo: string | null | undefined; canEdit: boolean; onSaved: (memo: string) => void }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  // Nothing for somebody who sees the document through a share alone (`null`), nor without a sender.
  if (!sender || memo === null || memo === undefined) return null
  if (!memo && !canEdit) return null
  return (
    <div className="flex items-start gap-2 rounded-xl bg-sheet-2/70 px-3 py-2 text-sm" data-testid="sender-memo">
      <NotebookPen size={15} className="mt-0.5 shrink-0 text-muted" aria-hidden />
      {memo ? (
        <p className="min-w-0 flex-1 whitespace-pre-line text-ink-2">
          <span className="sr-only">{t('senderMemo.label')}: </span>
          <bdi>{memo}</bdi>
        </p>
      ) : (
        <button type="button" onClick={() => setEditing(true)} className="min-w-0 flex-1 text-left text-xs font-semibold text-accent hover:underline">
          {t('senderMemo.add')}
        </button>
      )}
      {canEdit && memo && (
        <button type="button" onClick={() => setEditing(true)} className="shrink-0 rounded-full p-1 text-muted hover:bg-sheet hover:text-ink" aria-label={t('senderMemo.editFor', { name: sender.name })} title={t('senderMemo.edit')}>
          <Pencil size={13} aria-hidden />
        </button>
      )}
      {editing && (
        <MemoDialog
          sender={sender}
          memo={memo}
          onClose={() => setEditing(false)}
          onSaved={(saved) => {
            setEditing(false)
            onSaved(saved)
          }}
        />
      )}
    </div>
  )
}
