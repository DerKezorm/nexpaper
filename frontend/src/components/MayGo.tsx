/**
 * "Darf weg" (the mock's `MayGo` on the deadlines page): the filed documents whose keeping time is over, in the vaults
 * where the person may change things. Nothing goes by itself: pick, then "In den Papierkorb", after the question (30
 * days in the trash, as always). `useMayGo` (`lib/mayGo.ts`) fetches them (`GET /api/v1/keeping`), `MayGoChip` is the filter of the
 * page, `MayGo` the section. The deadlines page puts the three in its place.
 */
import { Archive, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { keepingApi, type DocumentInfo, type Vault } from '../api/client'
import { shortDate } from '../lib/dates'
import { keptOf } from '../lib/keeping'
import { inboxChanged, useSay } from '../lib/say'
import { vaultLabel } from '../lib/vaultLabel'
import { Button } from './Button'
import { Chip, KindPill } from './docs'
import { useConfirm } from './useConfirm'
import { VaultIcon } from './VaultIcon'

/** How many the section shows before "Alle N zeigen". */
const FIRST = 8
/** The filter chip "Darf weg 12"; only while something may go. */
export function MayGoChip({ count, active, onClick }: { count: number; active: boolean; onClick: () => void }) {
  const { t, i18n } = useTranslation()
  if (count <= 0) return null
  return (
    <Chip active={active} onClick={onClick}>
      {t('keeping.mayGo')} <span className="tabular-nums opacity-80">{count.toLocaleString(i18n.language)}</span>
    </Chip>
  )
}

export function MayGo({ items, total, vaults, mineId, onChanged }: { items: DocumentInfo[]; total: number; vaults: Vault[]; mineId: number; onChanged: () => void }) {
  const { t, i18n } = useTranslation()
  const say = useSay()
  const { ask, dialog } = useConfirm()
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [all, setAll] = useState(false)
  const n = (value: number) => value.toLocaleString(i18n.language)
  const shownItems = all ? items : items.slice(0, FIRST)
  const toggle = (id: number) =>
    setPicked((had) => {
      const next = new Set(had)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const allPicked = items.length > 0 && items.every((d) => picked.has(d.id))
  const vaultOf = (id: number) => vaults.find((v) => v.id === id)

  /** Asks, then puts the picked ones in the trash, each checked on its own by the server. */
  const trash = () => {
    const ids = items.filter((d) => picked.has(d.id)).map((d) => d.id)
    if (!ids.length) return
    ask({
      title: t('keeping.askTitle', { count: ids.length, n: n(ids.length) }),
      text: t('keeping.askText', { count: ids.length }),
      confirm: t('keeping.toTrash'),
      danger: false,
      run: async () => {
        const done = await keepingApi.trashMany(ids)
        setPicked(new Set())
        inboxChanged()
        onChanged()
        const gone = done.trashed.length
        const notice = t('keeping.done', { count: gone, n: n(gone) })
        say(done.failed.length ? `${notice} ${t('keeping.failed', { count: done.failed.length, n: n(done.failed.length) })}` : notice, undefined, {
          to: '/papierkorb',
          label: t('docs.inbox.trashLink'),
        })
      },
    })
  }

  return (
    <section aria-label={t('keeping.mayGo')}>
      <h2 className="mb-1 flex items-center gap-2 text-sm font-bold tracking-wide text-muted uppercase">
        {t('keeping.mayGo')} <span className="rounded-full bg-sheet-2 px-1.5 text-xs">{n(total)}</span>
      </h2>
      <p className="mb-3 max-w-2xl text-sm text-muted">{t('keeping.mayGoIntro')}</p>
      {items.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-line px-5 py-4 text-sm text-muted">{t('keeping.mayGoEmpty')}</p>
      ) : (
        <div className="card overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-line bg-sheet-2/50 px-4 py-2.5 sm:px-5">
            <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-semibold">
              <input type="checkbox" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(items.map((d) => d.id)))} className="h-4 w-4 accent-[var(--accent)]" />
              {t('keeping.pickAll', { n: n(items.length) })}
            </label>
            <span className="ml-auto" />
            <Button size="sm" variant={picked.size ? 'primary' : 'line'} disabled={!picked.size} onClick={trash}>
              <Trash2 size={15} aria-hidden /> {picked.size > 0 ? t('keeping.toTrashCount', { n: n(picked.size) }) : t('keeping.toTrash')}
            </Button>
          </div>
          <ul className="divide-y divide-line">
            {shownItems.map((d) => {
              const kept = keptOf(d)
              const vault = vaultOf(d.vault_id)
              return (
                <li key={d.id} className="flex items-center gap-3 px-4 py-3 sm:px-5">
                  <input type="checkbox" checked={picked.has(d.id)} onChange={() => toggle(d.id)} className="h-4 w-4 shrink-0 accent-[var(--accent)]" aria-label={t('keeping.pick', { title: d.title })} />
                  <div className="min-w-0 flex-1">
                    <Link to={`/dokument/${d.id}`} className="block truncate font-semibold hover:text-accent">
                      <bdi>{d.title}</bdi>
                    </Link>
                    <p className="flex flex-wrap items-center gap-x-2 text-sm text-muted">
                      {d.sender && (
                        <>
                          <bdi>{d.sender.name}</bdi>
                          <span aria-hidden>·</span>
                        </>
                      )}
                      {d.date && (
                        <>
                          <span>{shortDate(d.date, i18n.language)}</span>
                          <span aria-hidden>·</span>
                        </>
                      )}
                      {vault && (
                        <span className="inline-flex items-center gap-1">
                          <VaultIcon icon={vault.icon} size={13} /> {vaultLabel(vault, mineId, t('vaults.mine'))}
                        </span>
                      )}
                    </p>
                  </div>
                  {d.kind && (
                    <span className="hidden sm:inline-flex">
                      <KindPill kind={d.kind} small />
                    </span>
                  )}
                  {kept && (
                    <span className="shrink-0 text-right text-sm text-ink-2">
                      <span className="inline-flex items-center gap-1">
                        <Archive size={13} className="text-muted" aria-hidden /> {t('keeping.until', { date: shortDate(kept.date, i18n.language) })}
                      </span>
                      <span className="block text-xs text-muted">{kept.from === 'kind' ? t('keeping.fromKindShort', { years: t('keeping.years', { count: kept.years ?? 0 }) }) : t('keeping.byHandShort')}</span>
                    </span>
                  )}
                </li>
              )
            })}
            {!all && items.length > shownItems.length && (
              <li>
                <button type="button" onClick={() => setAll(true)} className="w-full px-5 py-3 text-sm font-semibold text-accent hover:bg-sheet-2">
                  {t('keeping.showAll', { n: n(items.length) })}
                </button>
              </li>
            )}
          </ul>
        </div>
      )}
      {dialog}
    </section>
  )
}
