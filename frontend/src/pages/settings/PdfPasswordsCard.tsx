/**
 * "Gemerkte PDF-Passwörter" under My account › Upload (P1): the passwords the person kept when opening a protected PDF,
 * by their own names, with when they were kept and when one last fitted. A password is never shown again: an entry is
 * only renamed or deleted (with a question first). An entry the server can no longer unseal (its secret changed) says
 * so. Nobody else's entries are ever here.
 */
import { KeyRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { pdfPasswordApi, type PdfPassword } from '../../api/client'
import { iso } from '../../lib/say'
import { errorText } from '../../lib/errors'
import { Button, Card, ConfirmDialog, Field, Row, Rows } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'
import { useAsk } from './useAsk'

export function PdfPasswordsCard() {
  const { t, i18n } = useTranslation()
  const [entries, setEntries] = useState<PdfPassword[] | null>(null)
  const [editing, setEditing] = useState<{ id: number; name: string } | null>(null)
  const action = useAction()
  const { ask, dialog } = useAsk()
  const load = () => pdfPasswordApi.list().then((found) => setEntries(Array.isArray(found) ? found : []), () => setEntries(null))
  useEffect(() => {
    void load()
  }, [])
  const day = (value: string) => new Date(value).toLocaleDateString(i18n.language)
  if (entries === null) return null
  return (
    <Card id="pdf-passwords" icon={KeyRound} title={t('pdfPassword.listTitle')} subtitle={t('pdfPassword.listText')}>
      {entries.length === 0 ? (
        <p className="m-0 text-sm text-[var(--nexui-text-muted)]" data-testid="pdf-passwords-empty">
          {t('pdfPassword.listEmpty')}
        </p>
      ) : (
        <Rows label={t('pdfPassword.listTitle')}>
          {entries.map((entry) => (
            <Row
              key={entry.id}
              icon={KeyRound}
              testId="pdf-password"
              name={<bdi>{entry.name}</bdi>}
              sub={
                <>
                  {t('pdfPassword.keptOn', { day: day(entry.created_at) })} · {entry.last_matched_at ? t('pdfPassword.lastFitted', { day: day(entry.last_matched_at) }) : t('pdfPassword.neverFitted')}
                  {!entry.readable && (
                    <span className="mt-1 block font-semibold text-[var(--nexui-warn)]" data-testid="pdf-password-lost">
                      {t('pdfPassword.lost')}
                    </span>
                  )}
                </>
              }
              action={
                <span className="flex flex-wrap items-center gap-2">
                  <Button kind="secondary" size="sm" icon="Pencil" onClick={() => setEditing({ id: entry.id, name: entry.name })} aria-label={t('pdfPassword.renameNamed', { name: entry.name })}>
                    {t('pdfPassword.rename')}
                  </Button>
                  <Button
                    kind="danger"
                    size="sm"
                    icon="Trash2"
                    aria-label={t('pdfPassword.deleteNamed', { name: entry.name })}
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
                  >
                    {t('common.delete')}
                  </Button>
                </span>
              }
            />
          ))}
        </Rows>
      )}
      <p className="m-0 text-xs text-[var(--nexui-text-muted)]">{t('pdfPassword.listNote')}</p>
      <Outcome problem={action.problem} values={action.values} />
      {editing && (
        <ConfirmDialog
          title={t('pdfPassword.renameNamed', { name: entries.find((entry) => entry.id === editing.id)?.name ?? '' })}
          confirm={{ label: t('pdfPassword.saveName'), kind: 'primary', icon: 'Check' }}
          cancel={t('common.cancel')}
          closeLabel={t('common.close')}
          busy={action.busy}
          confirmDisabled={!editing.name.trim()}
          error={action.problem ? errorText(action.problem, action.values) : undefined}
          onCancel={() => setEditing(null)}
          onConfirm={() =>
            void action.run(async () => {
              await pdfPasswordApi.rename(editing.id, editing.name)
              setEditing(null)
              await load()
            })
          }
        >
          <Field label={t('pdfPassword.nameLabel')} value={editing.name} maxLength={60} autoFocus onChange={(event) => setEditing({ ...editing, name: event.target.value })} />
        </ConfirmDialog>
      )}
      {dialog}
    </Card>
  )
}
