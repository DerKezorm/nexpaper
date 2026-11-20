/**
 * "Regeln erneut anwenden" (issue #11): after a rule was made or changed, the documents already waiting in the inbox are
 * worked out again. First a look that changes nothing (`POST /inbox/sort-again/preview`, a hundred documents an answer,
 * asked for until all were looked at), with every document whose proposals would change, its fields before and after,
 * and a tick; the ones a rule would move to another vault come first, because those are the ones that cost work when
 * they are wrong. Then the ticked ones are sorted again (`POST /inbox/sort-again`, worked out anew on the server).
 */
import { ArrowRight, FolderInput, Wand2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, inboxApi, type DocumentInfo, type SortAgainItem, type Vault } from '../api/client'
import { shortDate } from '../lib/dates'
import { errorText } from '../lib/errors'
import { money } from '../lib/money'
import { inboxChanged, useSay } from '../lib/say'
import { vaultLabel } from '../lib/vaultLabel'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { WhyBadge } from './docs'

/** The most the server sorts again in one call; more go in several. */
const APPLY_STEP = 100
/** The order the fields are shown in. */
const ORDER = ['vault', 'title', 'sender', 'kind', 'date', 'amount', 'dates', 'tags']

const moves = (item: SortAgainItem) => item.fields.includes('vault')

export function SortAgainDialog({ ids, vaults, mineId, onClose }: { ids?: number[]; vaults: Vault[]; mineId: number; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const say = useSay()
  const [items, setItems] = useState<SortAgainItem[]>([])
  const [ticked, setTicked] = useState<Set<number>>(new Set())
  const [looked, setLooked] = useState(0)
  const [total, setTotal] = useState<number | null>(null)
  const [looking, setLooking] = useState(true)
  const [applied, setApplied] = useState<number | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const stopped = useRef(false)
  const key = ids ? ids.join(',') : ''

  useEffect(() => {
    stopped.current = false
    const named = key ? key.split(',').map(Number) : undefined
    const run = async () => {
      let after = 0
      try {
        for (;;) {
          const answer = await inboxApi.lookAgain({ ...(named ? { ids: named } : {}), ...(after ? { after } : {}) })
          if (stopped.current) return
          const found = Array.isArray(answer.items) ? answer.items : []
          setItems((had) => [...had, ...found])
          setTicked((had) => new Set([...had, ...found.map((i) => i.before.id)]))
          setLooked((n) => n + (answer.looked_at ?? 0))
          setTotal(answer.total ?? 0)
          if (answer.next === null || answer.next === undefined) break
          after = answer.next
        }
      } catch (error) {
        if (!stopped.current) setProblem(error instanceof ApiError ? error.code : 'internal_error')
      }
      if (!stopped.current) setLooking(false)
    }
    void run()
    return () => {
      stopped.current = true
    }
  }, [key])

  // Moves first, then by title: those are the ones to look at.
  const shown = useMemo(() => [...items].sort((a, b) => Number(moves(b)) - Number(moves(a)) || a.before.title.localeCompare(b.before.title, i18n.language)), [items, i18n.language])
  const moving = items.filter(moves).length
  const chosen = items.filter((i) => ticked.has(i.before.id)).map((i) => i.before.id)
  const busy = applied !== null

  const close = () => {
    stopped.current = true
    onClose()
  }

  const apply = async () => {
    if (busy || chosen.length === 0) return
    setProblem(null)
    setApplied(0)
    let changed = 0
    let moved = 0
    let skipped = 0
    try {
      for (let at = 0; at < chosen.length; at += APPLY_STEP) {
        const answer = await inboxApi.sortAgain({ ids: chosen.slice(at, at + APPLY_STEP) })
        changed += answer.changed.length
        moved += answer.moved
        skipped += answer.skipped
        setApplied(Math.min(chosen.length, at + APPLY_STEP))
      }
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
      setApplied(null)
      if (changed > 0) inboxChanged()
      return
    }
    inboxChanged()
    const parts = [changed > 0 ? t('sorting.again.done', { count: changed }) : t('sorting.again.doneNone')]
    if (moved > 0) parts.push(t('sorting.again.doneMoved', { count: moved }))
    if (skipped > 0) parts.push(t('sorting.again.doneSkipped', { count: skipped }))
    say(parts.join(' '))
    onClose()
  }

  const vaultName = (id: number) => {
    const vault = vaults.find((v) => v.id === id)
    return vault ? vaultLabel(vault, mineId, t('vaults.mine')) : '…'
  }
  const value = (d: DocumentInfo, field: string): string => {
    switch (field) {
      case 'vault':
        return vaultName(d.vault_id)
      case 'title':
        return d.title
      case 'sender':
        return d.sender?.name ?? ''
      case 'kind':
        return d.kind?.name ?? ''
      case 'date':
        return d.date ? shortDate(d.date, i18n.language) : ''
      case 'amount':
        return money(d.amount, i18n.language, d.currency || 'EUR')
      case 'dates':
        return d.dates.map((x) => `${t(`docs.dateKinds.${x.kind}`)} ${shortDate(x.date, i18n.language)}`).join(', ')
      case 'tags':
        return d.tags.join(', ')
      default:
        return ''
    }
  }

  return (
    <Dialog title={t('sorting.again.title')} onClose={close} wide>
      <p className="text-sm text-ink-2">{ids ? t('sorting.again.introSelected', { count: ids.length }) : t('sorting.again.intro')}</p>

      {looking && (
        <div className="mt-4" role="status">
          <p className="text-sm text-muted">{t('sorting.again.looking', { looked: looked.toLocaleString(i18n.language), total: (total ?? 0).toLocaleString(i18n.language) })}</p>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sheet-2">
            <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${total ? Math.round((100 * looked) / total) : 0}%` }} />
          </div>
        </div>
      )}
      {problem && (
        <p role="alert" className="mt-4 text-sm text-bad">
          {errorText(problem)}
        </p>
      )}

      {!looking && items.length === 0 && !problem && <p className="mt-4 rounded-xl bg-sheet-2 p-3 text-sm" data-testid="sort-again-nothing">{t('sorting.again.nothing')}</p>}

      {items.length > 0 && (
        <div className="mt-4 space-y-3">
          {!looking && (
            <div className="space-y-1 text-sm" data-testid="sort-again-summary">
              <p className="font-semibold">{t('sorting.again.changes', { count: items.length })}</p>
              {moving > 0 && <p className="text-warn">{t('sorting.again.moves', { count: moving })}</p>}
              <p className="text-muted">{t('sorting.again.untick')}</p>
            </div>
          )}
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => setTicked(new Set(items.map((i) => i.before.id)))}>
              {t('sorting.again.all')}
            </Button>
            <Button variant="ghost" size="sm" disabled={busy} onClick={() => setTicked(new Set())}>
              {t('sorting.again.none')}
            </Button>
          </div>
          <ul className="space-y-2" aria-label={t('sorting.again.title')}>
            {shown.map((item) => {
              const d = item.before
              const fields = ORDER.filter((f) => item.fields.includes(f))
              return (
                <li key={d.id} className={`rounded-xl border p-3 ${moves(item) ? 'border-warn/50' : 'border-line'}`}>
                  <label className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      checked={ticked.has(d.id)}
                      disabled={busy}
                      onChange={(event) =>
                        setTicked((had) => {
                          const next = new Set(had)
                          if (event.target.checked) next.add(d.id)
                          else next.delete(d.id)
                          return next
                        })
                      }
                      aria-label={t('sorting.again.pick', { title: d.title })}
                      className="mt-1 h-4 w-4 shrink-0 accent-[var(--accent)]"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold">
                        {moves(item) && <FolderInput size={14} className="mr-1 inline text-warn" aria-hidden />}
                        <bdi>{d.title}</bdi>
                      </span>
                      <span className="mt-1 block space-y-0.5 text-sm">
                        {item.after === null ? (
                          <span className="block text-warn">
                            {t('docs.fields.vault')}: {vaultName(d.vault_id)} <ArrowRight size={12} className="inline" aria-hidden /> {t('sorting.again.outOfSight')}
                          </span>
                        ) : (
                          fields.map((field) => (
                            <span key={field} className="flex flex-wrap items-center gap-x-1.5" data-field={field}>
                              <span className="text-muted">{t(`docs.fields.${field}`)}:</span>
                              <span className="text-muted line-through decoration-1"><bdi>{value(d, field) || t('sorting.again.empty')}</bdi></span>
                              <ArrowRight size={12} className="text-muted" aria-hidden />
                              <span className="font-medium"><bdi>{value(item.after!, field) || t('sorting.again.empty')}</bdi></span>
                              <WhyBadge why={item.origins[field]} />
                            </span>
                          ))
                        )}
                      </span>
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {/* The buttons stay in view under a long list (the dialog scrolls, its foot does not). */}
      <div className="sticky -bottom-6 -mx-6 -mb-6 mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-line bg-[var(--sheet)] px-6 py-4">
        {busy && (
          <p className="mr-auto text-sm text-muted" role="status">
            {t('sorting.again.applying', { done: applied, total: chosen.length })}
          </p>
        )}
        <Button variant="ghost" onClick={close}>
          {looking ? t('sorting.again.stop') : t('common.cancel')}
        </Button>
        {!looking && items.length > 0 && (
          <Button variant="primary" disabled={busy || chosen.length === 0} onClick={() => void apply()}>
            <Wand2 size={16} aria-hidden /> {t('sorting.again.apply', { count: chosen.length })}
          </Button>
        )}
      </div>
    </Dialog>
  )
}
