/**
 * The inbox (`/eingang`, `/eingang/<id>`): everything new waits here, in the vaults the person may
 * add to, until somebody looks at it and files it. Above, a filter by vault with the numbers ("Alle 4 · Mein Tresor 1 ·
 * Haushalt 3"), a search and filters; on the left the list, a page of 50 at a time from `GET /api/v1/inbox`, each entry
 * with the vault it waits in and who brought it (what is still being read shimmers), with boxes to select many and file
 * them together; on the right one document with its pages and every field, where each proposal came from, the hint
 * when it looks like one the person has, and why reading it failed with a way to try again. "Ablegen" (Ctrl+Enter)
 * files it and goes on to the next; j and k step through the list. A phone shows the list, and one document on a page
 * of its own.
 */
import { AlertTriangle, ArrowLeft, Check, CheckSquare, Copy, FileCode2, FileText, FolderInput, Inbox, Mail, Maximize2, RotateCcw, RotateCw, Scissors, Search, Share2, SlidersHorizontal, Smartphone, Sparkles, Trash2, Upload, Wand2, X } from 'lucide-react'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import {
  ApiError,
  catalogApi,
  documentApi,
  documentsApi,
  fileUrls,
  inboxApi,
  intakeApi,
  rulesApi,
  searchApi,
  vaultsApi,
  type DocumentInfo,
  type DocumentKind,
  type DocumentOrigin,
  type DocumentVersion,
  type InboxPage as InboxView,
  type InboxQuery,
  type Person,
  type Vault,
  type VersionText,
} from '../api/client'
import { Button } from '../components/Button'
import { AmountInput, DateInput, Dates, Field, TagEditor } from '../components/DocumentFields'
import { SenderPicker } from '../components/SenderPicker'
import { Chip, DocThumb, FileNotice, FileSign, KindPill } from '../components/docs'
import { EInvoiceNotice, useEInvoice } from '../components/EInvoice'
import { NewKindButton, NewKindForm } from '../components/NewKind'
import { PagePicture } from '../components/PagePicture'
import { PdfView } from '../components/PdfView'
import { useConfirm } from '../components/useConfirm'
import { VaultFilter } from '../components/VaultFilter'
import { VaultIcon } from '../components/VaultIcon'
import { problemOf, refusedOf, refusedValue, shownAtField } from '../lib/dateInput'
import { errorText } from '../lib/errors'
import { useVaultTags } from '../lib/tags'
import { changesOf, draftOf, follow, type Draft } from '../lib/inbox'
import { oneOfEachName } from '../lib/kinds'
import { baseYear } from '../lib/keeping'
import { trashQuestion } from '../components/KeepTrash'
import { personName } from '../lib/people'
import { INBOX_CHANGED, inboxChanged, iso, listOf, moment, useSay, useSourceText, type NoticeLink } from '../lib/say'
import { vaultLabel } from '../lib/vaultLabel'
import { useAuth } from '../state/auth'
import { slots as appSlots, type Slots } from '../slots'

const SOURCE_ICON: Record<string, typeof Mail> = { upload: Upload, camera: Smartphone, mail: Mail, folder: FolderInput, share: Share2, paperless: Inbox, api: Smartphone }
/** While something is still being read, the list is asked for again this often. */
const POLL_MS = 4000
/** What the worker could not read at all; the rest of the codes (`ocr_*`) leave the pages and only the text is missing. */
const UNREADABLE = ['encrypted', 'broken', 'too_many_pages', 'too_large', 'timeout', 'failed']
/** From this width the list and one document stand side by side. */
const WIDE = 1024

function wide(): boolean {
  try {
    return window.matchMedia(`(min-width: ${WIDE}px)`).matches
  } catch {
    return window.innerWidth >= WIDE
  }
}

/** The value of the vault filter for what comes through a share of the document alone (it has no vault of its own). */
const SHARED = 'shared'
const SOURCES = ['upload', 'camera', 'mail', 'folder', 'share', 'paperless', 'api']
/** How many documents the list shows at first, and with every "Mehr laden". */
const PAGE = 50
/** The most the server files in one call. */
const BULK = 200
/** How long the search field waits after the last key. */
const TYPING_MS = 300
type Sort = 'new' | 'old' | 'date'

/** An answer with its lists in place, whatever came (a list that is not one counts as empty). */
const tidy = (answer: InboxView): InboxView => ({ ...answer, items: Array.isArray(answer.items) ? answer.items : [], counts: answer.counts ?? {}, shared: answer.shared ?? 0, all: answer.all ?? 0, total: answer.total ?? 0, reading: answer.reading ?? 0 })

const asNumber = (value: string | null): number | undefined => (value && /^\d+$/.test(value) ? Number(value) : undefined)

/** A key typed into a field of the page is meant for the field. */
function typingIn(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  return !!el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable || !!el.closest?.('[role="dialog"]'))
}

export function InboxPage({ slots = appSlots }: { slots?: Slots }) {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const { id } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const sourceText = useSourceText()
  const [view, setView] = useState<InboxView | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [vaults, setVaults] = useState<Vault[]>([])
  const [kinds, setKinds] = useState<DocumentKind[]>([])
  const [senders, setSenders] = useState<string[]>([])
  const [people, setPeople] = useState<Person[]>([])
  const [showFilters, setShowFilters] = useState(false)
  const [selected, setSelected] = useState<number[]>([])
  // The boxes to select many show only after "Auswählen" (or the key x); "Fertig" puts them away again.
  const [selecting, setSelecting] = useState(false)
  const [fetched, setFetched] = useState<DocumentInfo | null>(null)

  // Everything the list is filtered by stands in the address: a filtered inbox can be bookmarked, the back button works.
  const vault = params.get('vault') ?? ''
  const q = params.get('q') ?? ''
  const sender = params.get('sender') ?? ''
  const kind = params.get('kind') ?? ''
  const source = params.get('source') ?? ''
  const owner = params.get('owner') ?? ''
  const sort: Sort = params.get('sort') === 'old' ? 'old' : params.get('sort') === 'date' ? 'date' : 'new'
  const [typed, setTyped] = useState(q)
  const search = params.toString() ? `?${params.toString()}` : ''
  const active = [sender, kind, source, owner].filter(Boolean).length

  const change = useCallback(
    (patch: Record<string, string>) => {
      setSelected([])
      const next = new URLSearchParams(params)
      for (const [key, value] of Object.entries(patch)) {
        if (value) next.set(key, value)
        else next.delete(key)
      }
      setParams(next, { replace: true })
    },
    [params, setParams],
  )
  useEffect(() => {
    if (typed.trim() === q) return
    const timer = window.setTimeout(() => change({ q: typed.trim() }), TYPING_MS)
    return () => window.clearTimeout(timer)
  }, [typed, q, change])

  const key = JSON.stringify([vault, q, sender, kind, source, owner, sort])
  const loaded = useRef({ key: '', length: 0 })
  const reading = (view?.reading ?? 0) > 0
  useEffect(() => {
    let alive = true
    const query: InboxQuery = { vault_id: asNumber(vault), shared: vault === SHARED || undefined, q: q || undefined, sender: sender || undefined, kind_id: asNumber(kind), source: source || undefined, owner_id: asNumber(owner), sort }
    const run = () => {
      // The same list again keeps as many as were loaded; a new filter starts with the first page.
      const keep = loaded.current.key === key ? loaded.current.length : 0
      return inboxApi.list({ ...query, limit: Math.min(BULK, Math.max(PAGE, keep)) }).then(
        (answer) => {
          if (!alive) return
          const found = tidy(answer)
          loaded.current = { key, length: found.items.length }
          setView(found)
          setProblem(null)
        },
        (error: unknown) => alive && setProblem(error instanceof ApiError ? error.code : 'internal_error'),
      )
    }
    void run()
    // Uploads that finished meanwhile come into the list; what is still being read is asked for again.
    const again = () => void run()
    window.addEventListener(INBOX_CHANGED, again)
    const timer = reading ? window.setInterval(again, POLL_MS) : undefined
    return () => {
      alive = false
      window.removeEventListener(INBOX_CHANGED, again)
      if (timer) window.clearInterval(timer)
    }
  }, [key, reading, vault, q, sender, kind, source, owner, sort])

  useEffect(() => {
    void vaultsApi.list().then((list) => setVaults(listOf(list)), () => undefined)
    void vaultsApi.people().then((list) => setPeople(listOf(list)), () => undefined)
    void catalogApi.kinds().then((list) => setKinds(listOf(list)), () => undefined)
    void catalogApi.senders().then((groups) => setSenders(listOf<{ name: string }>(groups).map((g) => g.name)), () => undefined)
  }, [])

  /** The next page, below the ones shown. */
  const more = async () => {
    if (!view) return
    try {
      const answer = await inboxApi.list({ vault_id: asNumber(vault), shared: vault === SHARED || undefined, q: q || undefined, sender: sender || undefined, kind_id: asNumber(kind), source: source || undefined, owner_id: asNumber(owner), sort, limit: PAGE, offset: view.items.length })
      const found = tidy(answer)
      loaded.current = { key, length: view.items.length + found.items.length }
      setView({ ...found, items: [...view.items, ...found.items] })
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    }
  }

  const items = useMemo(() => view?.items ?? [], [view])
  const chosen = id ? Number(id) : null
  const inList = items.find((d) => d.id === chosen)
  // A document opened by its address that is not among those loaded (page 7 of a long list): fetched on its own.
  useEffect(() => {
    if (!view || chosen === null || view.items.some((d) => d.id === chosen)) return
    let alive = true
    documentsApi.read(chosen).then(
      (found) => {
        if (!alive) return
        if (found.status !== 'inbox' && found.status !== 'processing') navigate(`/dokument/${found.id}`, { replace: true })
        else setFetched(found)
      },
      () => undefined,
    )
    return () => {
      alive = false
    }
  }, [view, chosen, navigate])
  const current = inList ?? (fetched && fetched.id === chosen ? fetched : undefined) ?? (chosen === null && wide() ? items[0] : undefined)

  const after = (d: DocumentInfo) => {
    const at = items.findIndex((x) => x.id === d.id)
    const order = [...items.slice(at + 1), ...items.slice(0, Math.max(0, at))]
    return order.find((x) => x.id !== d.id && x.status !== 'processing')
  }
  const pick = useCallback((id: number, on: boolean) => setSelected((had) => (on ? [...had, id] : had.filter((n) => n !== id))), [])
  const go = (to?: number) => navigate(`/eingang${to ? `/${to}` : ''}${search}`)

  // j and k step through the list, x selects the one that is open.
  useEffect(() => {
    const press = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey || typingIn(event.target) || items.length === 0) return
      const at = items.findIndex((d) => d.id === current?.id)
      if (event.key === 'j' || event.key === 'k') {
        const to = items[Math.min(items.length - 1, Math.max(0, at + (event.key === 'j' ? 1 : -1)))]
        if (to && to.id !== current?.id) {
          event.preventDefault()
          navigate(`/eingang/${to.id}${search}`)
        }
      } else if (event.key === 'x' && current && current.status !== 'processing') {
        event.preventDefault()
        setSelecting(true)
        setSelected((had) => (had.includes(current.id) ? had.filter((n) => n !== current.id) : [...had, current.id]))
      }
    }
    window.addEventListener('keydown', press)
    return () => window.removeEventListener('keydown', press)
  }, [items, current, navigate, search])

  if (!me) return null
  const writable = vaults.filter((v) => v.my_right === 'edit' || v.my_right === 'manage')
  const vaultById = new Map(vaults.map((v) => [v.id, v]))
  const counts = Object.fromEntries(Object.entries(view?.counts ?? {}).map(([k, n]) => [Number(k), n]))
  const sharedCount = view?.shared ?? 0
  const readyItems = items.filter((d) => d.status !== 'processing')
  const empty = !!view && view.all === 0 && !q && !active
  const rest = view ? view.total - items.length : 0

  return (
    <div className="page pt-6 pb-28 lg:pt-8 lg:pb-12">
      <div className={`mb-5 ${chosen !== null ? 'hidden lg:block' : ''}`}>
        <h1 className="font-display text-3xl font-semibold tracking-tight">{t('docs.inbox.title')}</h1>
        <p className="text-sm text-muted">{empty ? t('home.sub') : t('docs.inbox.sub')}</p>
        {!empty && <p className="mt-1 max-w-3xl text-sm text-muted">{t('docs.inbox.explain')}</p>}
      </div>

      {problem && (
        <p role="alert" className="mb-4 rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {errorText(problem)}
        </p>
      )}
      {!view && !problem && <p className="text-sm text-muted">{t('docs.loading')}</p>}

      {empty ? (
        <div className="card p-12 text-center">
          <Check size={30} className="mx-auto text-ok" aria-hidden />
          <p className="mt-3 font-display text-xl font-semibold">{t('home.empty')}</p>
          <p className="mt-1 text-sm text-ink-2">{t('home.emptyText')}</p>
        </div>
      ) : (
        view && (
          <>
            <div className={`mb-4 space-y-3 ${chosen !== null ? 'hidden lg:block' : ''}`}>
              <VaultFilter vaults={writable} value={vault} onChange={(value) => change({ vault: value })} mineId={me.id} counts={counts} total={view.all} label={t('order.vault')} extra={sharedCount > 0 || vault === SHARED ? { value: SHARED, label: t('docs.inbox.sharedGroup', { count: sharedCount }) } : undefined} />
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="search"
                  value={typed}
                  onChange={(event) => setTyped(event.target.value)}
                  placeholder={t('docs.inbox.searchPlaceholder')}
                  aria-label={t('docs.inbox.searchPlaceholder')}
                  maxLength={100}
                  className="input h-10 min-w-48 flex-1"
                />
                <Chip active={showFilters || active > 0} onClick={() => setShowFilters(!showFilters)}>
                  <SlidersHorizontal size={14} aria-hidden /> {active > 0 ? t('docs.archive.filterCount', { count: active }) : t('docs.archive.filter')}
                </Chip>
                <select value={sort} onChange={(event) => change({ sort: event.target.value === 'new' ? '' : event.target.value })} aria-label={t('docs.inbox.sortLabel')} className="input h-10 w-auto">
                  <option value="new">{t('docs.inbox.sortNew')}</option>
                  <option value="old">{t('docs.inbox.sortOld')}</option>
                  <option value="date">{t('docs.inbox.sortDate')}</option>
                </select>
              </div>
              {showFilters && (
                <div className="card rise grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
                  <label className="text-sm">
                    <span className="text-xs font-semibold text-muted">{t('docs.archive.kind')}</span>
                    <select value={kind} onChange={(event) => change({ kind: event.target.value })} aria-label={t('docs.archive.kind')} className="input mt-1">
                      <option value="">{t('docs.archive.all')}</option>
                      {oneOfEachName(kinds).map((k) => (
                        <option key={k.id} value={k.id}>
                          {k.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="text-sm">
                    <span className="text-xs font-semibold text-muted">{t('docs.archive.sender')}</span>
                    <div className="mt-1">
                      <SenderPicker known value={sender} onChange={(value) => change({ sender: value })} names={senders} label={t('docs.archive.sender')} placeholder={t('docs.archive.all')} />
                    </div>
                  </div>
                  <label className="text-sm">
                    <span className="text-xs font-semibold text-muted">{t('docs.inbox.source')}</span>
                    <select value={source} onChange={(event) => change({ source: event.target.value })} aria-label={t('docs.inbox.source')} className="input mt-1">
                      <option value="">{t('docs.archive.all')}</option>
                      {SOURCES.map((s) => (
                        <option key={s} value={s}>
                          {sourceText(s)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm">
                    <span className="text-xs font-semibold text-muted">{t('docs.inbox.by')}</span>
                    <select value={owner} onChange={(event) => change({ owner: event.target.value })} aria-label={t('docs.inbox.by')} className="input mt-1">
                      <option value="">{t('docs.archive.all')}</option>
                      {people.map((p) => (
                        <option key={p.id} value={p.id}>
                          {personName(p)}
                        </option>
                      ))}
                    </select>
                  </label>
                  {active > 0 && (
                    <button type="button" onClick={() => change({ sender: '', kind: '', source: '', owner: '' })} className="text-left text-sm font-semibold text-accent sm:col-span-2 lg:col-span-4">
                      {t('docs.archive.reset')}
                    </button>
                  )}
                </div>
              )}
              {selected.length > 0 && (
                <BulkBar
                  ids={selected}
                  items={items}
                  writable={writable}
                  kinds={kinds}
                  vaults={vaults}
                  onClear={() => setSelected([])}
                  onDone={(filed) => {
                    setSelected((had) => had.filter((n) => !filed.includes(n)))
                    inboxChanged()
                    // The document that was open is gone from the inbox: the next one opens.
                    if (chosen !== null && filed.includes(chosen)) go(items.find((d) => !filed.includes(d.id) && d.status !== 'processing')?.id)
                  }}
                />
              )}
            </div>

            <div className="grid gap-5 lg:grid-cols-[19rem_minmax(0,1fr)]">
              {/* The list keeps its own scroll beside the details: an entry far down leaves preview and fields in view. */}
              <div className={`${chosen !== null ? 'hidden lg:block' : ''} lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:self-start lg:overflow-y-auto lg:pr-1`}>
                <div className="mb-2 flex items-center justify-between gap-2 px-1 text-xs text-muted">
                  {selecting ? (
                    <label className="inline-flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={readyItems.length > 0 && selected.length >= readyItems.length}
                        onChange={(event) => setSelected(event.target.checked ? readyItems.map((d) => d.id) : [])}
                        disabled={readyItems.length === 0}
                        aria-label={t('docs.inbox.selectAll', { count: readyItems.length })}
                        className="h-4 w-4 accent-[var(--accent)]"
                      />
                      <span data-testid="inbox-shown">{t('docs.inbox.showing', { shown: items.length.toLocaleString(i18n.language), total: view.total.toLocaleString(i18n.language) })}</span>
                    </label>
                  ) : (
                    <span data-testid="inbox-shown">{t('docs.inbox.showing', { shown: items.length.toLocaleString(i18n.language), total: view.total.toLocaleString(i18n.language) })}</span>
                  )}
                  {selecting ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setSelecting(false)
                        setSelected([])
                      }}
                    >
                      <Check size={14} aria-hidden /> {t('docs.inbox.chooseDone')}
                    </Button>
                  ) : (
                    <Button variant="ghost" size="sm" onClick={() => setSelecting(true)} disabled={readyItems.length === 0}>
                      <CheckSquare size={14} aria-hidden /> {t('docs.inbox.choose')}
                    </Button>
                  )}
                </div>
                {items.length === 0 ? (
                  <p className="card p-5 text-sm text-muted">{t('docs.inbox.noMatch')}</p>
                ) : (
                  <ul className="space-y-2" aria-label={t('docs.inbox.title')}>
                    {items.map((d) => (
                      <Entry
                        key={d.id}
                        document={d}
                        on={current?.id === d.id}
                        picked={selected.includes(d.id)}
                        selecting={selecting}
                        search={search}
                        vault={vaultById.get(d.vault_id)}
                        mineId={me.id}
                        splitHint={!!d.split_suggested && !!slots.SplitPanel}
                        onPick={pick}
                      />
                    ))}
                  </ul>
                )}
                {rest > 0 && (
                  <div className="mt-3 text-center">
                    <Button variant="line" size="sm" onClick={() => void more()}>
                      {t('docs.inbox.loadMore')}
                    </Button>
                  </div>
                )}
                <p className="mt-3 hidden px-1 text-xs text-muted lg:block">{t('docs.inbox.keys')}</p>
              </div>

              {current ? (
                <Detail
                  key={`${current.id}-${current.status}-${current.current_version}`}
                  document={current}
                  next={after(current)}
                  slots={slots}
                  search={search}
                  onChanged={inboxChanged}
                />
              ) : (
                <div className="hidden lg:block" />
              )}
            </div>
          </>
        )
      )}
    </div>
  )
}

/** One document in the list: a box to select it, its picture and fields, in which vault it waits and who brought it. */
const Entry = memo(function Entry({ document: d, on, picked, selecting, search, vault, mineId, splitHint, onPick }: { document: DocumentInfo; on: boolean; picked: boolean; selecting: boolean; search: string; vault: Vault | undefined; mineId: number; splitHint: boolean; onPick: (id: number, on: boolean) => void }) {
  const { t, i18n } = useTranslation()
  const sourceText = useSourceText()
  const Icon = SOURCE_ICON[d.source] ?? Upload
  const processing = d.status === 'processing'
  const shield = vault ? vaultLabel(vault, mineId, t('vaults.mine')) : ''
  return (
    <li className="inbox-entry flex items-start gap-2" data-testid="inbox-entry">
      {selecting && (
        <input
          type="checkbox"
          checked={picked}
          disabled={processing}
          onChange={(event) => onPick(d.id, event.target.checked)}
          aria-label={t('docs.inbox.select', { title: d.title })}
          className="mt-5 h-4 w-4 shrink-0 accent-[var(--accent)]"
        />
      )}
      <Link
        to={`/eingang/${d.id}${search}`}
        aria-current={on ? 'true' : undefined}
        className={`flex min-w-0 flex-1 items-center gap-3 rounded-2xl border p-3 transition ${on ? 'border-accent/50 bg-accent-soft/60' : 'border-line bg-sheet hover:border-accent/40'}`}
      >
        <div className="w-11 shrink-0">
          <DocThumb document={d} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{processing ? t('docs.inbox.reading') : <bdi>{d.title}</bdi>}</p>
          <p className="truncate text-xs text-muted">{d.sender?.name ? <bdi>{d.sender.name}</bdi> : d.pages > 0 ? t('docs.pages', { count: d.pages }) : sourceText(d.source)}</p>
          <p className="mt-1 flex items-center gap-1.5 text-xs text-muted">
            <Icon size={12} aria-hidden /> {moment(d.added_at, i18n.language)}
          </p>
          <p className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-muted" data-testid="inbox-shield">
            <span className="inline-flex min-w-0 items-center gap-1 rounded-full bg-sheet-2 px-2 py-0.5 font-semibold text-ink-2">
              {vault && <VaultIcon icon={vault.icon} size={11} />}
              <span className="truncate">{shield}</span>
            </span>
            <span className="truncate">{d.owner ? (d.owner.id === mineId ? t('docs.inbox.from_you') : t('docs.inbox.from_other', { name: personName(d.owner) })) : ''}</span>
          </p>
        </div>
        {splitHint && <Scissors size={15} className="shrink-0 text-accent" aria-label={t('pagetools.split.suggestedShort')} />}
        {d.duplicate && <Copy size={15} className="shrink-0 text-warn" aria-label={t('docs.inbox.looksLikeShort')} />}
        {d.process_error && <AlertTriangle size={15} className="shrink-0 text-bad" aria-label={t('docs.inbox.problemShort')} />}
        <FileSign state={d.files_state} size={15} />
        {d.einvoice && <FileCode2 size={15} className="shrink-0 text-accent" aria-label={t('sorting.einvoice.icon')} />}
      </Link>
    </li>
  )
})

/** Several selected at once: file them with what the proposals say, and a vault, a kind and a tag for all of them. One
 * call per 200 (the most the server takes); what could not be filed is named with the reason. */
function BulkBar({ ids, items, writable, kinds, vaults, onClear, onDone }: { ids: number[]; items: DocumentInfo[]; writable: Vault[]; kinds: DocumentKind[]; vaults: Vault[]; onClear: () => void; onDone: (filed: number[]) => void }) {
  const { t } = useTranslation()
  const say = useSay()
  const [vaultId, setVaultId] = useState('')
  const [kindId, setKindId] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<{ id: number; code: string }[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const inVaults = new Set(items.filter((d) => ids.includes(d.id)).map((d) => d.vault_id))
  // The kinds every one of them may have: the server's, and those of the vault they all end up in.
  const endVault = vaultId ? Number(vaultId) : inVaults.size === 1 ? [...inVaults][0] : null
  const choices = oneOfEachName(kinds.filter((k) => !k.vault_id || k.vault_id === endVault))
  const kindValue = choices.some((k) => String(k.id) === kindId) ? kindId : ''
  // The tags to choose from: those of the vault they all end up in; when they stay where they are, those every one of
  // their vaults has. Never a name from a vault they are not in.
  const vaultTags = useVaultTags(vaultId ? [Number(vaultId)] : [...inVaults])
  const titleOf = (id: number) => items.find((d) => d.id === id)?.title ?? String(id)

  const file = async () => {
    if (busy) return
    setBusy(true)
    setProblem(null)
    setFailed([])
    const filed: number[] = []
    const refused: { id: number; code: string }[] = []
    try {
      for (let at = 0; at < ids.length; at += BULK) {
        const answer = await inboxApi.file({
          ids: ids.slice(at, at + BULK),
          ...(vaultId ? { vault_id: Number(vaultId) } : {}),
          ...(kindValue ? { kind_id: Number(kindValue) } : {}),
          ...(tags.length ? { add_tags: tags } : {}),
        })
        filed.push(...answer.filed)
        refused.push(...answer.failed)
      }
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    }
    setBusy(false)
    setFailed(refused)
    if (filed.length > 0) {
      say(t('docs.inbox.bulkDone', { count: filed.length }))
      onDone(filed)
    }
  }
  return (
    <div className="card rise space-y-3 p-4" role="region" aria-label={t('docs.inbox.selected', { count: ids.length })}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">{t('docs.inbox.selected', { count: ids.length })}</p>
        <Button variant="ghost" size="sm" onClick={onClear}>
          <X size={14} aria-hidden /> {t('docs.inbox.clearSelection')}
        </Button>
      </div>
      <p className="text-xs text-muted">{t('docs.inbox.bulkHint')}</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">
          <span className="text-xs font-semibold text-muted">{t('docs.inbox.bulkVault')}</span>
          <select value={vaultId} onChange={(event) => setVaultId(event.target.value)} aria-label={t('docs.inbox.bulkVault')} className="input mt-1">
            <option value="">{t('docs.inbox.unchanged')}</option>
            {writable.map((v) => (
              <option key={v.id} value={v.id}>
                {v.personal_of !== null ? t('docs.inbox.personalVault', { name: v.name }) : v.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="text-xs font-semibold text-muted">{t('docs.inbox.bulkKind')}</span>
          <select value={kindValue} onChange={(event) => setKindId(event.target.value)} aria-label={t('docs.inbox.bulkKind')} className="input mt-1">
            <option value="">{t('docs.inbox.unchanged')}</option>
            {choices.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </select>
        </label>
        <div className="text-sm">
          <span className="text-xs font-semibold text-muted">{t('docs.inbox.bulkTag')}</span>
          <div className="mt-1">
            <TagEditor tags={tags} onChange={setTags} label={t('docs.inbox.bulkTag')} known={vaultTags} />
          </div>
        </div>
      </div>
      {problem && <p role="alert" className="text-sm text-bad">{errorText(problem)}</p>}
      {failed.length > 0 && (
        <div role="alert" className="rounded-xl border border-warn/40 bg-warn-soft p-3 text-sm">
          <p className="font-semibold text-warn">{t('docs.inbox.bulkFailed', { count: failed.length })}</p>
          <ul className="mt-1 list-disc pl-5 text-ink-2">
            {failed.slice(0, 10).map((f) => (
              <li key={f.id}>
                <bdi>{titleOf(f.id)}</bdi>: {errorText(f.code)}
              </li>
            ))}
          </ul>
        </div>
      )}
      <Button variant="primary" onClick={() => void file()} disabled={busy || vaults.length === 0}>
        <Check size={17} aria-hidden /> {t('docs.inbox.bulkFile', { count: ids.length })}
      </Button>
    </div>
  )
}

function BackLink() {
  const { t } = useTranslation()
  const { search } = useLocation()
  return (
    <Link to={`/eingang${search}`} className="mb-3 inline-flex items-center gap-1.5 text-sm font-semibold text-ink-2 lg:hidden">
      <ArrowLeft size={16} aria-hidden /> {t('docs.inbox.title')}
    </Link>
  )
}

function Detail({ document: d, next, slots, search, onChanged }: { document: DocumentInfo; next?: DocumentInfo; slots: Slots; search: string; onChanged: () => void }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const sourceText = useSourceText()
  const [f, setF] = useState<Draft>(() => draftOf(d))
  // The document as it was when the draft last agreed with it: the list is asked again now and then, and what the
  // server changed meanwhile (a proposal that came late) reaches the fields the person has not touched.
  const seen = useRef<Draft>(draftOf(d))
  useEffect(() => {
    const now = draftOf(d)
    const was = seen.current
    if (JSON.stringify(now) === JSON.stringify(was)) return
    seen.current = now
    setF((mine) => follow(was, now, mine))
  }, [d])
  const [page, setPage] = useState(1)
  // The PDF for the large view (pdf.js with zoom); the inbox itself shows the server's pictures of the pages.
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [editingPages, setEditingPages] = useState(false)
  // The document large over the page, at the page it opens with: to read what it is before filing it.
  const [large, setLarge] = useState<number | null>(null)
  const [vaults, setVaults] = useState<Vault[]>([])
  const [kinds, setKinds] = useState<DocumentKind[]>([])
  const [senders, setSenders] = useState<string[]>([])
  const [origin, setOrigin] = useState<DocumentOrigin | null>(null)
  const [text, setText] = useState<VersionText | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<{ code: string; values?: Record<string, unknown> } | null>(null)
  const invoice = useEInvoice(d)
  // The tags of the vault the document ends up in, to choose from.
  const vaultTags = useVaultTags([f.vault_id])
  // "Immer so?": what the person just chose for the kind or the vault, offered as a rule for this sender.
  const [offer, setOffer] = useState<{ kind_id?: number; vault_id?: number } | null>(null)
  const [remembered, setRemembered] = useState<string | null>(null)
  const [makingKind, setMakingKind] = useState(false)
  const { ask, dialog } = useConfirm()

  useEffect(() => {
    void vaultsApi.list().then((list) => setVaults(listOf(list)), () => undefined)
    void catalogApi.kinds(d.vault_id).then((list) => setKinds(listOf(list)), () => undefined)
    void catalogApi.senders().then((groups) => setSenders(listOf<{ name: string }>(groups).map((g) => g.name)), () => undefined)
    void intakeApi.origin(d.id).then(setOrigin, () => undefined)
    if (d.status !== 'processing' && d.pages > 0) void searchApi.text(d.id, d.current_version).then(setText, () => undefined)
    if (d.status !== 'processing' && d.pages > 0)
      void documentApi.versions(d.id).then((list) => {
        const current = listOf<DocumentVersion>(list).find((v) => v.current)
        setPdfUrl(current?.has_archive ? fileUrls.archive(d.id, d.current_version) : current?.kind === 'pdf' ? fileUrls.file(d.id, d.current_version) : null)
      }, () => undefined)
  }, [d.id, d.vault_id, d.status, d.pages, d.current_version])

  const vaultName = (v: Vault) => (v.personal_of !== null ? t('docs.inbox.personalVault', { name: iso(v.name) }) : v.name)
  const writable = vaults.filter((v) => v.my_right === 'edit' || v.my_right === 'manage')
  const goNext = useCallback(
    (notice: string, link?: NoticeLink) => navigate(`/eingang${next ? `/${next.id}` : ''}${search}`, { state: { notice, ...(link ? { link } : {}) } }),
    [navigate, next, search],
  )

  const file = useCallback(async () => {
    if (busy) return
    if (!f.title.trim()) {
      setProblem({ code: 'invalid_title' })
      return
    }
    setBusy(true)
    setProblem(null)
    const changed = changesOf(d, f)
    try {
      // A kind the vault made for itself is chosen by its number there: the fields go first, while the document is still
      // in that vault, and the move takes the kind along by its name. Any other change goes after the move.
      const ownKind = changed.kind_id != null && kinds.find((k) => k.id === changed.kind_id)?.vault_id != null
      if (f.vault_id !== d.vault_id && ownKind) {
        await documentApi.patch(d.id, changed)
        await documentApi.move(d.id, f.vault_id)
        await documentApi.patch(d.id, { status: 'filed' })
      } else {
        if (f.vault_id !== d.vault_id) await documentApi.move(d.id, f.vault_id)
        await documentApi.patch(d.id, { ...changed, status: 'filed' })
      }
      const vault = vaults.find((v) => v.id === f.vault_id)
      onChanged()
      goNext(vault ? t('docs.inbox.filedIn', { vault: vaultName(vault) }) : t('docs.inbox.filed'))
    } catch (error) {
      setProblem(problemOf(error, changed))
      setBusy(false)
    }
    // vaultName only reads `t`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, f, d, vaults, kinds, onChanged, goNext, t])

  /** "Als Regel merken": the sender as it stands in the field is saved first (the rule names it), then the rule. */
  const remember = async () => {
    if (!offer) return
    setBusy(true)
    setProblem(null)
    try {
      const sender = f.sender.trim()
      if (sender !== (d.sender?.name ?? '')) await documentApi.patch(d.id, { sender })
      await rulesApi.remember(d.id, offer)
      setOffer(null)
      setRemembered(t('sorting.remember.done'))
    } catch (error) {
      setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
    } finally {
      setBusy(false)
    }
  }

  /** Into the trash, after asking: it stays {{days}} days there and can be brought back. */
  const trash = (notice: string) =>
    ask({
      ...trashQuestion(d, t, i18n.language),
      danger: false,
      run: async () => {
        await documentApi.trash(d.id)
        onChanged()
        goNext(notice, { to: '/papierkorb', label: t('docs.inbox.trashLink') })
      },
    })
  const retry = async () => {
    setBusy(true)
    try {
      await documentsApi.retry(d.id)
      onChanged()
    } catch (error) {
      setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
      setBusy(false)
    }
  }

  // Ctrl+Enter (Cmd+Enter on a Mac) files the document, from any field.
  useEffect(() => {
    if (d.status === 'processing') return
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault()
        void file()
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [d.status, file])

  if (d.status === 'processing')
    return (
      <div className="card p-6" data-testid="inbox-reading">
        <BackLink />
        <p className="font-display text-xl font-semibold">{t('docs.inbox.readingTitle')}</p>
        <p className="mt-1 text-sm text-ink-2">{t('docs.inbox.readingText')}</p>
        <div className="mt-5 flex gap-3">
          {Array.from({ length: Math.min(Math.max(d.pages, 3), 6) }, (_, i) => (
            <div key={i} className="shimmer aspect-[210/297] w-24 rounded-[3px]" />
          ))}
        </div>
        <p className="mt-4 text-xs text-muted">
          {sourceText(d.source)} · {moment(d.added_at, i18n.language)}
        </p>
      </div>
    )

  const why = d.suggest ?? {}
  const unreadable = UNREADABLE.includes(d.process_error)
  const longPages = text?.long_document_pages ?? 0
  const SplitPanel = slots.SplitPanel
  const PageEditor = slots.PageEditor
  if (SplitPanel && d.split_suggested)
    // A batch scan with a proposal to split: the proposal takes the place of the details.
    return (
      <SplitPanel
        document={d}
        back={<BackLink />}
        onDone={(first) => {
          onChanged()
          navigate(`/eingang${first ? `/${first}` : ''}${search}`)
        }}
      />
    )
  return (
    <div className="card overflow-hidden p-0">
      <div className="grid xl:grid-cols-[minmax(0,1fr)_25rem]">
        <div className="border-b border-line bg-sheet-2/60 p-5 xl:border-r xl:border-b-0">
          <BackLink />
          {editingPages && PageEditor ? (
            <PageEditor
              document={d}
              onDone={(changed) => {
                setEditingPages(false)
                if (changed) onChanged()
              }}
            />
          ) : (
            <>
          <div className="mx-auto max-w-md">
            {d.pages > 0 ? (
              <button type="button" onClick={() => setLarge(page)} className="block w-full cursor-zoom-in" aria-label={t('docs.inbox.large')}>
                <PagePicture
                  key={page}
                  src={fileUrls.page(d.id, d.current_version, page, 'small')}
                  better={fileUrls.page(d.id, d.current_version, page, 'large')}
                  alt={t('docs.page', { n: page })}
                  eager
                />
              </button>
            ) : (
              <div className="flex aspect-[210/297] w-full flex-col items-center justify-center gap-2 rounded-[3px] bg-white text-muted shadow-[0_1px_3px_rgb(0_0_0/0.18)]">
                <FileText size={28} aria-hidden />
                <span className="text-xs">{t('docs.noPages')}</span>
              </div>
            )}
          </div>
          {d.pages > 1 && (
            <div className="scroll-x mx-auto mt-4 flex w-max max-w-full gap-2 overflow-x-auto pb-1" aria-label={t('docs.pagesLabel')}>
              {Array.from({ length: d.pages }, (_, i) => (
                <div key={i} className="relative w-12 shrink-0">
                  <button type="button" onClick={() => setPage(i + 1)} className={`block w-full rounded-[4px] ring-2 ${page === i + 1 ? 'ring-accent' : 'ring-transparent'}`} aria-label={t('docs.page', { n: i + 1 })} aria-pressed={page === i + 1}>
                    <PagePicture src={fileUrls.page(d.id, d.current_version, i + 1, 'small')} alt="" margin="200px" />
                  </button>
                  <button type="button" onClick={() => setLarge(i + 1)} className="absolute right-0.5 bottom-0.5 rounded-full bg-sheet/95 p-1 text-ink shadow-soft hover:text-accent" aria-label={t('docs.inbox.largePage', { n: i + 1 })} title={t('docs.inbox.largePage', { n: i + 1 })}>
                    <Search size={11} aria-hidden />
                  </button>
                </div>
              ))}
            </div>
          )}
          {d.pages > 0 && (
            <div className="mt-3 flex flex-wrap justify-center gap-2">
              <Button variant="soft" size="sm" onClick={() => setLarge(page)}>
                <Maximize2 size={14} aria-hidden /> {t('docs.inbox.large')}
              </Button>
              {PageEditor && (
                <Button variant="soft" size="sm" onClick={() => setEditingPages(true)}>
                  <RotateCw size={14} aria-hidden /> {t('docs.document.editPages')}
                </Button>
              )}
            </div>
          )}
          {large !== null && <LargeDocument document={d} pdfUrl={pdfUrl} page={large} onClose={() => setLarge(null)} />}
            </>
          )}
          <p className="mt-4 text-center text-xs text-muted" data-testid="origin">
            {sourceText(d.source)} · {moment(d.added_at, i18n.language)}
            {origin?.unknown && <span className="ml-2 rounded-full bg-warn-soft px-2 py-0.5 font-semibold text-warn">{t('intake.origin.unknown')}</span>}
          </p>
          {origin && (origin.sender || origin.subject || origin.file) && (
            <p className="mt-1 text-center text-xs text-muted">
              {origin.sender && t('docs.inbox.from', { sender: iso(origin.sender) })}
              {origin.subject && ` · ${t('docs.inbox.subject', { subject: iso(origin.subject) })}`}
              {origin.file && t('docs.inbox.fromFile', { file: iso(origin.folder ? `${origin.folder}/${origin.file}` : origin.file) })}
            </p>
          )}
        </div>

        <div className="space-y-4 p-5">
          <FileNotice state={d.files_state} documentId={d.id} onChecked={onChanged} />
          {d.process_error && (
            <div role="alert" className={`rounded-2xl border p-4 text-sm ${unreadable ? 'border-bad/40 bg-bad/10' : 'border-warn/40 bg-warn-soft'}`}>
              <p className={`flex items-center gap-2 font-semibold ${unreadable ? 'text-bad' : 'text-warn'}`}>
                <AlertTriangle size={15} aria-hidden /> {t(`docs.inbox.error.${d.process_error}`, { defaultValue: t('docs.inbox.error.failed') })}
              </p>
              <p className="mt-1 text-ink-2">{t(unreadable ? 'docs.inbox.errorUnreadable' : 'docs.inbox.errorText')}</p>
              <div className="mt-3">
                <Button size="sm" variant="line" onClick={() => void retry()} disabled={busy}>
                  <RotateCcw size={14} aria-hidden /> {t('docs.inbox.retry')}
                </Button>
              </div>
            </div>
          )}

          {text?.state === 'pending' && longPages > 0 && d.pages >= longPages && <p className="rounded-2xl bg-sheet-2 p-3 text-sm text-ink-2">{t('ocr.longDocument', { pages: d.pages })}</p>}

          <EInvoiceNotice invoice={invoice} />

          {d.duplicate && (
            <div className="rounded-2xl border border-warn/40 bg-warn-soft p-4 text-sm" data-testid="looks-like">
              <p className="flex items-center gap-2 font-semibold text-warn">
                <Copy size={15} aria-hidden /> {t('docs.inbox.looksLike')}
              </p>
              <p className="mt-1 text-ink-2">{t(d.duplicate.kind === 'same' ? 'docs.inbox.sameFile' : 'docs.inbox.similarFile', { title: iso(d.duplicate.title) })}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" variant="line" disabled={busy} onClick={() => trash(t('docs.inbox.discarded'))}>
                  {t('docs.inbox.discard')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => navigate(`/dokument/${d.duplicate!.document_id}`)}>
                  {t('docs.inbox.seeExisting')}
                </Button>
              </div>
            </div>
          )}

          <Field label={t('docs.fields.title')} why={why.title}>
            <input value={f.title} maxLength={200} aria-label={t('docs.fields.title')} onChange={(event) => setF({ ...f, title: event.target.value })} className="input" />
          </Field>
          <Field label={t('docs.fields.sender')} why={why.sender}>
            <SenderPicker value={f.sender} onChange={(sender) => setF({ ...f, sender })} names={senders} label={t('docs.fields.sender')} />
          </Field>
          <Field label={t('docs.fields.kind')} why={why.kind}>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t('docs.fields.kind')}>
              {kinds.map((k) => (
                <button
                  key={k.id}
                  type="button"
                  role="radio"
                  aria-checked={f.kind_id === k.id}
                  onClick={() => {
                    setF({ ...f, kind_id: f.kind_id === k.id ? null : k.id })
                    setOffer(f.kind_id === k.id ? null : { kind_id: k.id })
                  }}
                  className={`rounded-full ring-2 ${f.kind_id === k.id ? 'ring-accent' : 'ring-transparent opacity-70 hover:opacity-100'}`}
                >
                  <KindPill kind={k} small />
                </button>
              ))}
              {d.my_right !== 'read' && <NewKindButton onClick={() => setMakingKind(true)} />}
            </div>
            {makingKind && (
              <NewKindForm
                vaultId={d.vault_id}
                kinds={kinds}
                onClose={() => setMakingKind(false)}
                onMade={(made) => {
                  setKinds((had) => (had.some((k) => k.id === made.id) ? had : [...had, made]))
                  setF({ ...f, kind_id: made.id })
                  setOffer({ kind_id: made.id })
                  setMakingKind(false)
                }}
              />
            )}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('docs.fields.date')} why={why.date}>
              <DateInput value={f.date} label={t('docs.fields.date')} refused={refusedValue(problem, 'date')} onChange={(date) => setF((was) => ({ ...was, date }))} onCommit={(date) => setF((was) => ({ ...was, date }))} />
            </Field>
            <Field label={t('docs.fields.amount')} why={why.amount}>
              <AmountInput cents={f.amount} onChange={(amount) => setF({ ...f, amount })} label={t('docs.fields.amount')} language={i18n.language} />
            </Field>
          </div>
          <Field label={t('docs.fields.vault')} why={why.vault}>
            <select
              value={f.vault_id}
              aria-label={t('docs.fields.vault')}
              onChange={(event) => {
                setF({ ...f, vault_id: Number(event.target.value) })
                setOffer(Number(event.target.value) !== d.vault_id ? { vault_id: Number(event.target.value) } : null)
              }}
              className="input"
            >
              {(writable.some((v) => v.id === f.vault_id) ? writable : [...writable, ...vaults.filter((v) => v.id === f.vault_id)]).map((v) => (
                <option key={v.id} value={v.id}>
                  {vaultName(v)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('docs.fields.tags')} why={why.tags}>
            <TagEditor tags={f.tags} onChange={(tags) => setF((was) => ({ ...was, tags }))} label={t('docs.fields.addTagLabel')} known={vaultTags} />
          </Field>
          <Dates
            dates={f.dates}
            onChange={(dates) => setF((was) => ({ ...was, dates }))}
            onDraft={(dates) => setF((was) => ({ ...was, dates }))}
            start={f.date || null}
            why={why.dates}
            refused={refusedOf(problem)}
            keep={{
              kindName: kinds.find((k) => k.id === f.kind_id)?.name ?? null,
              years: kinds.find((k) => k.id === f.kind_id)?.keep_years ?? null,
              base: baseYear(f.date, d.added_at),
              fresh: f.kind_id === (d.kind?.id ?? null) && f.date === (d.date ?? '') && f.vault_id === d.vault_id,
              // Filing it with a time that is over puts it in the trash that night, when its kind has the switch on.
              auto: kinds.find((k) => k.id === f.kind_id)?.auto_trash ? { where: 'inbox' } : null,
            }}
          />

          {offer && f.sender.trim() && d.my_right === 'manage' && (
            <div className="rise flex items-start gap-3 rounded-2xl border border-dashed border-accent/50 p-3 text-sm" data-testid="remember">
              <Wand2 size={16} className="mt-0.5 shrink-0 text-accent" aria-hidden />
              <div className="flex-1">
                <p className="text-ink-2">
                  {t('sorting.remember.question', {
                    rule: offer.kind_id
                      ? t('sorting.remember.kind', { sender: iso(f.sender.trim()), kind: kinds.find((k) => k.id === offer.kind_id)?.name ?? '' })
                      : t('sorting.remember.vault', { sender: iso(f.sender.trim()), vault: (() => { const v = vaults.find((x) => x.id === offer.vault_id); return v ? vaultName(v) : '' })() }),
                  })}
                </p>
                <div className="mt-2 flex gap-2">
                  <Button size="sm" variant="soft" disabled={busy} onClick={() => void remember()}>
                    {t('sorting.remember.button')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setOffer(null)}>
                    {t('sorting.remember.once')}
                  </Button>
                </div>
              </div>
            </div>
          )}
          {remembered && (
            <p role="status" className="text-sm font-semibold text-accent">
              {remembered}
            </p>
          )}

          {problem && !shownAtField(problem) && (
            <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
              {errorText(problem.code, problem.values)}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
            <Button variant="primary" onClick={() => void file()} disabled={busy} title={t('docs.inbox.fileKey')}>
              <Check size={17} aria-hidden /> {t('docs.inbox.file')}
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => trash(t('docs.inbox.trashed'))}>
              <Trash2 size={16} aria-hidden /> {t('docs.inbox.delete')}
            </Button>
            <span className="ml-auto hidden text-xs text-muted sm:inline">
              {Object.values(why).includes('ai') && (
                <span className="inline-flex items-center gap-1">
                  <Sparkles size={12} aria-hidden /> {t('docs.inbox.partlyAi')}
                </span>
              )}
            </span>
          </div>
        </div>
      </div>
      {dialog}
    </div>
  )
}


/** The document over the whole page, as large as the window allows: pdf.js with its zoom, or the pictures of the pages.
 * Escape, the button or a click beside it closes it. */
function LargeDocument({ document: d, pdfUrl, page, onClose }: { document: DocumentInfo; pdfUrl: string | null; page: number; onClose: () => void }) {
  const { t } = useTranslation()
  const close = useRef<HTMLButtonElement>(null)
  const [failed, setFailed] = useState(false)
  const first = useRef<HTMLDivElement>(null)
  useEffect(() => first.current?.scrollIntoView?.({ block: 'start' }), [])
  useEffect(() => {
    close.current?.focus()
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    window.addEventListener('keydown', key, true)
    return () => window.removeEventListener('keydown', key, true)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-scrim p-3 sm:p-6" role="dialog" aria-modal="true" aria-label={d.title} onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="mx-auto mb-2 flex w-full max-w-5xl items-center justify-between gap-3">
        <p className="truncate font-semibold text-white">{iso(d.title)}</p>
        <button ref={close} type="button" onClick={onClose} className="rounded-full bg-sheet/95 p-2 text-ink shadow-soft" aria-label={t('common.close')}>
          <X size={18} />
        </button>
      </div>
      <div className="relative mx-auto min-h-0 w-full max-w-5xl flex-1" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
        {pdfUrl && !failed ? (
          <PdfView url={pdfUrl} page={page} title={d.title} onFailed={() => setFailed(true)} />
        ) : (
          <div className="h-full overflow-y-auto">
            {Array.from({ length: Math.max(d.pages, 1) }, (_, i) => (
              <div key={i} ref={i + 1 === page ? first : undefined} className="mx-auto mb-4 max-w-3xl">
                <PagePicture src={fileUrls.page(d.id, d.current_version, i + 1, 'large')} alt={t('docs.page', { n: i + 1 })} margin="400px" />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
