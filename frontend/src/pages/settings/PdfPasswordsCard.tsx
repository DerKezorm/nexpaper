/**
 * "Gemerkte PDF-Passwörter" under My account, Upload (P1): the passwords the person kept when opening a protected PDF,
 * by their own names, with when they were kept and when one last fitted. A password is never shown again: an entry is
 * only renamed or deleted (with a question first). An entry the server can no longer unseal (its secret changed) says
 * so. Nobody else's entries are ever here.
 */
import { Check, KeyRound, Pencil, Trash2, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { pdfPasswordApi, type PdfPassword } from '../../api/client'
import { useConfirm } from '../../components/useConfirm'
import { iso } from '../../lib/say'
import { Card, Feedback, useAction } from './ui'

export function PdfPasswordsCard() {
  const { t, i18n } = useTranslation()
  const [entries, setEntries] = useState<PdfPassword[] | null>(null)
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null)
  const action = useAction()
  const { ask, dialog } = useConfirm()
  const load = () => pdfPasswordApi.list().then((found) => setEntries(Array.isArray(found) ? found : []), () => setEntries(null))
  useEffect(() => {
    void load()
  }, [])
  const day = (value: string) => new Date(value).toLocaleDateString(i18n.language)
  if (entries === null) return null
  return (
    <Card id="pdf-passwords" icon={KeyRound} title={t('pdfPassword.listTitle')} text={t('pdfPassword.listText')}>
      {entries.length === 0 ? (
        <p className="text-sm text-muted" data-testid="pdf-passwords-empty">
          {t('pdfPassword.listEmpty')}
        </p>
      ) : (
        <ul className="space-y-2">
          {entries.map((entry) => (
            <li key={entry.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-3 text-sm" data-testid="pdf-password">
              <KeyRound size={17} className="shrink-0 text-accent" aria-hidden />
              {editing?.id === entry.id ? (
                <form
                  className="flex min-w-0 flex-1 items-center gap-2"
                  onSubmit={(event) => {
                    event.preventDefault()
                    void action.run(async () => {
                      await pdfPasswordApi.rename(entry.id, editing.name)
                      setEditing(null)
                      await load()
                    })
                  }}
                >
                  <input value={editing.name} maxLength={60} autoFocus onChange={(event) => setEditing({ id: entry.id, name: event.target.value })} className="input min-w-0 flex-1" aria-label={t('pdfPassword.nameLabel')} />
                  <button type="submit" className="rounded-full p-1.5 text-accent hover:bg-sheet" aria-label={t('pdfPassword.saveName')} disabled={!editing.name.trim()}>
                    <Check size={16} />
                  </button>
                  <button type="button" onClick={() => setEditing(null)} className="rounded-full p-1.5 text-muted hover:bg-sheet hover:text-ink" aria-label={t('common.cancel')}>
                    <X size={16} />
                  </button>
                </form>
              ) : (
                <span className="min-w-0 flex-1">
                  <span className="font-semibold">
                    <bdi>{entry.name}</bdi>
                  </span>
                  <span className="block text-xs text-muted">
                    {t('pdfPassword.keptOn', { day: day(entry.created_at) })} ·{' '}
                    {entry.last_matched_at ? t('pdfPassword.lastFitted', { day: day(entry.last_matched_at) }) : t('pdfPassword.neverFitted')}
                  </span>
                  {!entry.readable && (
                    <span className="mt-1 block text-xs font-semibold text-warn" data-testid="pdf-password-lost">
                      {t('pdfPassword.lost')}
                    </span>
                  )}
                </span>
              )}
              {editing?.id !== entry.id && (
                <>
                  <button type="button" onClick={() => setEditing({ id: entry.id, name: entry.name })} className="rounded-full p-1.5 text-muted hover:bg-sheet hover:text-ink" aria-label={t('pdfPassword.renameNamed', { name: entry.name })}>
                    <Pencil size={15} />
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      ask({
                        title: t('pdfPassword.deleteTitle'),
                        text: t('pdfPassword.deleteText', { name: iso(entry.name) }),
                        confirm: t('pdfPassword.deleteConfirm'),
                        run: async () => {
                          await pdfPasswordApi.remove(entry.id)
                          await load()
                        },
                      })
                    }
                    className="rounded-full p-1.5 text-muted hover:bg-sheet hover:text-ink"
                    aria-label={t('pdfPassword.deleteNamed', { name: entry.name })}
                  >
                    <Trash2 size={15} />
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted">{t('pdfPassword.listNote')}</p>
      <Feedback problem={action.problem} values={action.values} />
      {dialog}
    </Card>
  )
}
