/**
 * "Aufgabe in nextasks" on a document's page (Bauplan V19, nexpaper the guest of nextasks; a draft in its smallest
 * form). The button stands only while a connection made by a click under Mein Konto › Verbindungen holds; the window
 * asks for the list in nextasks (the one used last chosen first) and makes the task with the document's title and a
 * link back to this page. The same document again finds the task made first.
 */
import { ExternalLink, ListChecks } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, nextasksApi, type NextasksList, type NextasksTask } from '../api/client'
import { errorText } from '../lib/errors'
import { Button } from './Button'
import { Dialog } from './Dialog'

export function NextasksTaskButton({ documentId }: { documentId: number }) {
  const { t } = useTranslation()
  const [usable, setUsable] = useState(false)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    let live = true
    nextasksApi.state().then(
      (found) => live && setUsable(found.usable === true),
      () => live && setUsable(false),
    )
    return () => {
      live = false
    }
  }, [])
  if (!usable) return null
  return (
    <>
      <Button variant="line" size="sm" onClick={() => setOpen(true)} data-testid="nextasks-task">
        <ListChecks size={15} aria-hidden /> {t('nextasksTask.button')}
      </Button>
      {open && <NextasksTaskDialog documentId={documentId} onClose={() => setOpen(false)} />}
    </>
  )
}

function NextasksTaskDialog({ documentId, onClose }: { documentId: number; onClose: () => void }) {
  const { t } = useTranslation()
  const [lists, setLists] = useState<NextasksList[] | null>(null)
  const [chosen, setChosen] = useState('')
  const [problem, setProblem] = useState<{ code: string; values?: Record<string, unknown> } | null>(null)
  const [busy, setBusy] = useState(false)
  const [made, setMade] = useState<NextasksTask | null>(null)
  useEffect(() => {
    nextasksApi.lists().then(
      (found) => {
        setLists(found.lists)
        setChosen(found.last_list_id ?? found.lists[0]?.id ?? '')
      },
      (error) => {
        setLists([])
        setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
      },
    )
  }, [])
  const make = async () => {
    setBusy(true)
    setProblem(null)
    try {
      setMade(await nextasksApi.make(documentId, chosen))
    } catch (error) {
      setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
    }
    setBusy(false)
  }
  return (
    <Dialog title={t('nextasksTask.title')} onClose={onClose}>
      {made ? (
        <div data-testid="nextasks-made">
          <p className="text-sm text-ink-2">{t(made.created ? 'nextasksTask.made' : 'nextasksTask.there')}</p>
          {made.link && (
            <a href={made.link} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-accent hover:underline">
              <ExternalLink size={14} aria-hidden /> {t('nextasksTask.open')}
            </a>
          )}
          <div className="mt-5 flex justify-end">
            <Button variant="primary" onClick={onClose}>
              {t('common.close')}
            </Button>
          </div>
        </div>
      ) : (
        <>
          <p className="-mt-2 mb-3 text-sm text-ink-2">{t('nextasksTask.text')}</p>
          {lists === null ? (
            <p className="text-sm text-muted">{t('docs.loading')}</p>
          ) : lists.length === 0 ? (
            !problem && <p className="text-sm text-ink-2">{t('nextasksTask.noList')}</p>
          ) : (
            <select value={chosen} onChange={(event) => setChosen(event.target.value)} aria-label={t('nextasksTask.list')} className="input">
              {lists.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.space_name ? `${item.space_name} · ${item.name}` : item.name}
                </option>
              ))}
            </select>
          )}
          {problem && (
            <p role="alert" className="mt-3 text-sm text-bad">
              {errorText(problem.code, problem.values)}
            </p>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <Button variant="line" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            {lists !== null && lists.length > 0 && (
              <Button variant="primary" onClick={() => void make()} disabled={busy || !chosen}>
                <ListChecks size={16} aria-hidden /> {t('nextasksTask.make')}
              </Button>
            )}
          </div>
        </>
      )}
    </Dialog>
  )
}
