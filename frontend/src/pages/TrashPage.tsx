/**
 * The trash (`/papierkorb`, linked from the bottom of the archive): what was deleted in the vaults the person sees, 30
 * days long. Whoever may change a document brings it back; the managers of its vault and the person it belongs to may
 * delete it for good before then (the server checks it, `POST /documents/{id}/purge`).
 */
import { ArrowLeft, RotateCcw, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, documentApi, documentsApi, type DocumentInfo } from '../api/client'
import { Button } from '../components/Button'
import { useConfirm } from '../components/useConfirm'
import { DocThumb } from '../components/docs'
import { shortDate } from '../lib/dates'
import { errorText } from '../lib/errors'
import { inboxChanged, iso, listOf, useSay } from '../lib/say'
import { useAuth } from '../state/auth'

async function trashed(): Promise<DocumentInfo[]> {
  const found: DocumentInfo[] = []
  let after = 0
  for (let page = 0; page < 20; page++) {
    const answer = await documentsApi.list({ status: 'trash', after, limit: 500 })
    found.push(...listOf<DocumentInfo>(answer.items))
    if (!answer.next) break
    after = answer.next
  }
  return found.sort((a, b) => (b.trashed_at ?? '').localeCompare(a.trashed_at ?? '') || b.id - a.id)
}

export function TrashPage() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const say = useSay()
  const [list, setList] = useState<DocumentInfo[] | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const { ask, dialog } = useConfirm()
  const load = useCallback(() => trashed().then(setList, (error: unknown) => setProblem(error instanceof ApiError ? error.code : 'internal_error')), [])
  useEffect(() => {
    void load()
  }, [load])

  const run = async (work: () => Promise<unknown>, notice: string) => {
    setProblem(null)
    try {
      await work()
      inboxChanged()
      say(notice)
      await load()
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    }
  }
  if (!me) return null
  const canEdit = (d: DocumentInfo) => d.my_right === 'edit' || d.my_right === 'manage'
  const canPurge = (d: DocumentInfo) => d.my_right === 'manage' || (canEdit(d) && d.owner?.id === me.id)

  return (
    <div className="page space-y-5 pt-6 pb-28 lg:pt-8 lg:pb-12">
      <div>
        <Link to="/" className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold text-ink-2">
          <ArrowLeft size={16} aria-hidden /> {t('docs.archive.title')}
        </Link>
        <h1 className="font-display text-3xl font-semibold tracking-tight">{t('docs.trash.title')}</h1>
        <p className="text-sm text-muted">{t('docs.trash.sub')}</p>
      </div>
      {problem && (
        <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {errorText(problem)}
        </p>
      )}
      {!list && !problem && <p className="text-sm text-muted">{t('docs.loading')}</p>}
      {list && list.length === 0 && (
        <div className="card p-10 text-center">
          <Trash2 size={28} className="mx-auto text-muted" aria-hidden />
          <p className="mt-3 font-semibold">{t('docs.trash.empty')}</p>
        </div>
      )}
      {list && list.length > 0 && (
        <ul className="card divide-y divide-line overflow-hidden p-0">
          {list.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-4 px-4 py-3">
              <DocThumb document={d} className="w-10 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold">
                  <bdi>{d.title}</bdi>
                </p>
                <p className="truncate text-sm text-ink-2">
                  {d.sender ? <><bdi>{d.sender.name}</bdi> · </> : ''}
                  {d.trash_ends_at ? t('docs.trash.until', { date: shortDate(d.trash_ends_at, i18n.language) }) : ''}
                </p>
              </div>
              {canEdit(d) && (
                <Button size="sm" variant="line" onClick={() => void run(() => documentApi.restore(d.id), t('docs.trash.restored', { title: iso(d.title) }))}>
                  <RotateCcw size={14} aria-hidden /> {t('docs.trash.restore')}
                </Button>
              )}
              {canPurge(d) && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    ask({
                      title: t('confirm.purge.title'),
                      text: t('confirm.purge.text', { title: iso(d.title) }),
                      confirm: t('confirm.purge.confirm'),
                      run: async () => {
                        await documentApi.purge(d.id)
                        inboxChanged()
                        say(t('docs.trash.purged', { title: iso(d.title) }))
                        await load()
                      },
                    })
                  }
                >
                  <Trash2 size={14} aria-hidden /> {t('docs.trash.purge')}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {dialog}
    </div>
  )
}
