/**
 * The bar over the archive's table while documents are selected ("Auswählen", A1): a tag added or taken away, a kind,
 * another vault, the trash, for all of them in one request each (`POST /api/v1/documents/bulk`, 500 at most; more go
 * in turns). The server checks every document on its own and says what it did; the bar says it in one line ("12
 * geändert, 2 nicht (nur Lesen)"). Moving asks who sees the documents afterwards; the trash asks too (rule 13), with
 * the 30 days and how many are still within their keeping time. More actions can join `ACTIONS`. "Miteinander
 * verknüpfen" sets two to ten of them to go with each other (N1), without a question: each pair can be taken apart
 * again.
 */
import { Archive, FolderInput, Paperclip, Tag, Tags, Trash2, X } from 'lucide-react'
import { useState, type ComponentType } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, bulkApi, type BulkAction, type BulkResult, type DocumentInfo, type DocumentKind, type Vault } from '../api/client'
import { BULK_MOST, LINK_MOST } from '../lib/bulk'
import { dayInDays } from '../lib/dates'
import { errorText } from '../lib/errors'
import { keptOf } from '../lib/keeping'
import { oneOfEachName } from '../lib/kinds'
import { personName } from '../lib/people'
import { iso, listOf } from '../lib/say'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { useConfirm } from './useConfirm'

/** What a person may do with the selected documents, in the order of the bar. */
type Step = 'add_tag' | 'remove_tag' | 'kind' | 'move' | 'trash'
const ACTIONS: { step: Step; label: string; icon: ComponentType<{ size?: number; 'aria-hidden'?: boolean }> }[] = [
  { step: 'add_tag', label: 'archiveBulk.addTag', icon: Tag },
  { step: 'remove_tag', label: 'archiveBulk.removeTag', icon: Tags },
  { step: 'kind', label: 'archiveBulk.kind', icon: Archive },
  { step: 'move', label: 'archiveBulk.vault', icon: FolderInput },
  { step: 'trash', label: 'archiveBulk.trash', icon: Trash2 },
]

type Props = {
  selected: DocumentInfo[]
  vaults: Vault[]
  kinds: DocumentKind[]
  /** The names of the tags the person's vaults have (to choose from while typing). */
  tags: string[]
  meId: number
  onClear: () => void
  /** After a request: what it did (the page says it and asks for the table again). */
  onDone: (result: BulkResult, action: BulkAction) => void
}

export function BulkBar({ selected, vaults, kinds, tags, meId, onClear, onDone }: Props) {
  const { t, i18n } = useTranslation()
  const n = (value: number) => value.toLocaleString(i18n.language)
  const { ask, dialog } = useConfirm()
  const [open, setOpen] = useState<Step | null>(null)
  const [tag, setTag] = useState('')
  const [kindId, setKindId] = useState('')
  const [vaultId, setVaultId] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const ids = selected.map((d) => d.id)
  const count = ids.length

  /** One request per 500; what each did, added up. */
  const run = async (action: BulkAction, extra: { tag?: string; kind_id?: number; vault_id?: number }) => {
    const all: BulkResult = { changed: [], skipped: [], reasons: {} }
    for (let at = 0; at < ids.length; at += BULK_MOST) {
      const answer = await bulkApi.change({ ids: ids.slice(at, at + BULK_MOST), action, ...extra })
      all.changed.push(...listOf<number>(answer.changed))
      all.skipped.push(...listOf<{ id: number; reason: string }>(answer.skipped))
      for (const [reason, value] of Object.entries(answer.reasons ?? {})) all.reasons[reason] = (all.reasons[reason] ?? 0) + value
    }
    onDone(all, action)
  }
  const apply = async (action: BulkAction, extra: { tag?: string; kind_id?: number; vault_id?: number }) => {
    if (busy) return
    setBusy(true)
    setProblem(null)
    try {
      await run(action, extra)
      setOpen(null)
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    }
    setBusy(false)
  }

  const askTrash = () => {
    const today = dayInDays(0)
    const running = selected.filter((d) => {
      const kept = keptOf(d)
      return kept !== null && kept.date >= today
    }).length
    ask({
      title: t('keeping.askTitle', { count, n: n(count) }),
      text: (
        <>
          <p>{t('keeping.askText', { count })}</p>
          {running > 0 && (
            <p className="mt-3 rounded-xl bg-warn-soft px-4 py-3 text-sm font-semibold text-warn" data-testid="bulk-keep-running">
              {t('archiveBulk.keepRunning', { count: running, n: n(running) })}
            </p>
          )}
        </>
      ),
      confirm: running > 0 ? t('keeping.trashAnyway') : t('keeping.toTrash'),
      danger: false,
      run: () => run('trash', {}),
    })
  }

  const askMove = () => {
    const target = vaults.find((v) => String(v.id) === vaultId)
    if (!target) return
    const name = target.personal_of === meId ? t('vaults.mine') : target.name
    const people = listOf<Vault['members'][number]>(target.members).map((m) => personName({ name: m.name, display_name: m.display_name }))
    const who =
      people.length === 1
        ? t('archiveBulk.moveAskOnly', { person: iso(people[0]) })
        : people.length > 1
          ? t('archiveBulk.moveAskPeople', { vault: iso(name), people: people.map(iso).join(', ') })
          : ''
    setOpen(null)
    ask({
      title: t('archiveBulk.moveAskTitle', { count, n: n(count), vault: iso(name) }),
      text: (
        <>
          {who && <p data-testid="bulk-move-who">{who}</p>}
          <p className={who ? 'mt-2' : ''}>{t('archiveBulk.moveAskTerms')}</p>
        </>
      ),
      confirm: t('archiveBulk.moveConfirm'),
      danger: false,
      run: () => run('move', { vault_id: target.id }),
    })
  }

  const start = (step: Step) => {
    setProblem(null)
    if (step === 'trash') askTrash()
    else setOpen(step)
  }

  const writable = vaults.filter((v) => v.my_right === 'edit' || v.my_right === 'manage')
  const inVaults = new Set(selected.map((d) => d.vault_id))
  // The server's kinds, and those of the vaults the documents lie in (a vault's own kind is only for its documents).
  const choices = oneOfEachName(kinds.filter((k) => !k.vault_id || inVaults.has(k.vault_id)))
  const title = open === 'add_tag' ? 'archiveBulk.addTagTitle' : open === 'remove_tag' ? 'archiveBulk.removeTagTitle' : open === 'kind' ? 'archiveBulk.kindTitle' : 'archiveBulk.vaultTitle'

  return (
    <div className="card rise space-y-3 p-4" role="region" aria-label={t('docs.inbox.selected', { count })} data-testid="bulk-bar">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">{t('docs.inbox.selected', { count })}</p>
        <Button variant="ghost" size="sm" onClick={onClear}>
          <X size={14} aria-hidden /> {t('docs.inbox.clearSelection')}
        </Button>
      </div>
      <div className="flex flex-wrap gap-2" role="group" aria-label={t('archiveBulk.actions')}>
        {ACTIONS.map(({ step, label, icon: Icon }) => (
          <Button key={step} variant="line" size="sm" onClick={() => start(step)} disabled={busy}>
            <Icon size={15} aria-hidden /> {t(label)}
          </Button>
        ))}
        <Button
          variant="line"
          size="sm"
          onClick={() => void apply('link', {})}
          disabled={busy || count < 2 || count > LINK_MOST}
          title={count < 2 || count > LINK_MOST ? t('archiveBulk.linkHint', { most: LINK_MOST }) : undefined}
        >
          <Paperclip size={15} aria-hidden /> {t('archiveBulk.link')}
        </Button>
      </div>
      {problem && !open && (
        <p role="alert" className="text-sm text-bad">
          {errorText(problem)}
        </p>
      )}
      {open && (
        <Dialog title={t(title, { count, n: n(count) })} onClose={() => setOpen(null)}>
          <form
            className="space-y-4 text-sm"
            onSubmit={(event) => {
              event.preventDefault()
              if (open === 'add_tag' || open === 'remove_tag') {
                if (tag.trim()) void apply(open, { tag: tag.trim() })
              } else if (open === 'kind') {
                if (kindId) void apply('kind', { kind_id: Number(kindId) })
              } else if (vaultId) askMove()
            }}
          >
            {(open === 'add_tag' || open === 'remove_tag') && (
              <label className="block">
                <span className="font-semibold">{t('archiveBulk.tagLabel')}</span>
                <input value={tag} onChange={(event) => setTag(event.target.value)} list="bulk-tags" maxLength={40} data-autofocus className="input mt-1 h-11" />
                <datalist id="bulk-tags">
                  {(open === 'remove_tag' ? [...new Set(selected.flatMap((d) => listOf<string>(d.tags)))] : tags).map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
              </label>
            )}
            {open === 'kind' && (
              <>
                <label className="block">
                  <span className="font-semibold">{t('archiveBulk.kind')}</span>
                  <select value={kindId} onChange={(event) => setKindId(event.target.value)} data-autofocus className="input mt-1 h-11">
                    <option value="" />
                    {choices.map((k) => (
                      <option key={k.id} value={k.id}>
                        {k.name}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="text-ink-2">{t('archiveBulk.kindHint')}</p>
              </>
            )}
            {open === 'move' && (
              <label className="block">
                <span className="font-semibold">{t('archiveBulk.vaultLabel')}</span>
                <select value={vaultId} onChange={(event) => setVaultId(event.target.value)} data-autofocus className="input mt-1 h-11">
                  <option value="" />
                  {writable.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.personal_of === meId ? t('vaults.mine') : v.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {problem && (
              <p role="alert" className="text-bad">
                {errorText(problem)}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setOpen(null)}>
                {t('saved.cancel')}
              </Button>
              <Button
                type="submit"
                variant="primary"
                disabled={busy || ((open === 'add_tag' || open === 'remove_tag') && !tag.trim()) || (open === 'kind' && !kindId) || (open === 'move' && !vaultId)}
              >
                {open === 'move' ? t('archiveBulk.next') : t('archiveBulk.apply')}
              </Button>
            </div>
          </form>
        </Dialog>
      )}
      {dialog}
    </div>
  )
}
