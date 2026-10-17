/**
 * "Exportieren" in the archive: period, vaults, what goes in, and what the ZIP will hold (the
 * server counts it, with the person's rights, while the choice changes). The ZIP is packed in the background; the
 * person gets a notice when it is ready, or hands it out at once as a link for somebody without an account (the tax
 * adviser), whose address is copied right away. Below, the person's exports: state, download, links, delete.
 *
 * The archive passes its current filters (the search and the filters of `GET /search`), the number of documents it
 * shows and the sum of their amounts (cents); the dialog starts from them and shows the server's count once it has it.
 */
import { Download, Link2, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, exportsApi, sharingApi, vaultsApi, type ExportFilters, type ExportInfo, type ExportPreview, type SearchFilters, type SharingRules, type Vault } from '../api/client'
import { formatBytes } from '../lib/bytes'
import { copyText } from '../lib/copy'
import { shortDate } from '../lib/dates'
import { errorText } from '../lib/errors'
import { iso } from '../lib/say'
import { treeOf } from '../lib/tree'
import { useAuth } from '../state/auth'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { useConfirm } from './useConfirm'
import { VaultIcon } from './VaultIcon'

export type ExportDialogProps = {
  onClose: () => void
  /** The archive's current filters (as `GET /search` takes them); `date_from`/`date_to` start the period, `vault_id`
   * the vaults chosen. What an export cannot follow (only the shared ones, the trash, a page) is left out. */
  filters?: ExportFilters | SearchFilters
  /** The archive's search, when it is not in `filters`. */
  q?: string
  /** How many documents the archive shows and the sum of their amounts in cents: shown until the server has counted. */
  count: number
  sum: number
  /** What was done, in a sentence, for the page to show (a toast). */
  say?: (text: string) => void
  /** Today, for the period of the current year when the archive has none (the tests set it). */
  today?: Date
  /** How long the dialog waits after a change before it asks the server to count (the tests set 0). */
  previewDelay?: number
}

const PREVIEW_DELAY_MS = 300

/** The filters of the archive as an export takes them. */
function exportFiltersOf(given: ExportFilters | SearchFilters, q?: string): ExportFilters {
  const out: ExportFilters = {}
  const from = given as ExportFilters & SearchFilters
  if (q || from.q) out.q = q || from.q
  for (const key of ['vault_id', 'kind_id', 'owner_id'] as const) if (typeof from[key] === 'number') out[key] = from[key]
  for (const key of ['sender', 'tag', 'date_from', 'date_to'] as const) if (from[key]) out[key] = from[key]
  if (from.status === 'inbox' || from.status === 'filed') out.status = from.status
  return out
}
const POLL_MS = 3000

function useExportText() {
  const { t, i18n } = useTranslation()
  return useCallback(
    (code: string, values: Record<string, unknown> = {}) => {
      const own = `exports.errors.${code}`
      return i18n.exists(own) ? t(own, values) : errorText(code, values)
    },
    [t, i18n],
  )
}

export function ExportDialog({ onClose, filters: given = {}, q, count, sum, say, today = new Date(), previewDelay = PREVIEW_DELAY_MS }: ExportDialogProps) {
  const filters = exportFiltersOf(given, q)
  const { t, i18n } = useTranslation()
  const words = useExportText()
  const { me } = useAuth()
  const year = today.getFullYear()
  const [from, setFrom] = useState(filters.date_from ?? `${year}-01-01`)
  const [to, setTo] = useState(filters.date_to ?? `${year}-12-31`)
  const [vaults, setVaults] = useState<Vault[]>([])
  const [chosen, setChosen] = useState<number[]>(filters.vault_id ? [filters.vault_id] : [])
  const [what, setWhat] = useState({ pdf: true, original: false, csv: true, xml: true })
  const [asLink, setAsLink] = useState(false)
  const [recipient, setRecipient] = useState(() => t('exports.recipientDefault'))
  const [rules, setRules] = useState<SharingRules | null>(null)
  const [preview, setPreview] = useState<ExportPreview | null>(null)
  const [mine, setMine] = useState<ExportInfo[]>([])
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<{ code: string; values: Record<string, unknown> } | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const fail = (error: unknown) => setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error', values: {} })

  useEffect(() => {
    let alive = true
    Promise.all([vaultsApi.list(), sharingApi.rules(), exportsApi.list()]).then(
      ([found, ruleSet, exports]) => {
        if (!alive) return
        setVaults(found)
        setRules(ruleSet)
        setMine(exports)
        setChosen((before) => (before.length ? before : found.map((v) => v.id)))
      },
      (error: unknown) => alive && fail(error),
    )
    return () => {
      alive = false
    }
  }, [])

  // The filters as a text: a new object with the same filters (each render of the archive makes one) asks nothing again.
  const filterKey = JSON.stringify(filters)
  const request = useMemo(() => {
    const archive = JSON.parse(filterKey) as ExportFilters
    return { ...archive, vault_id: undefined, date_from: from || undefined, date_to: to || undefined, vault_ids: chosen, content: what }
  }, [filterKey, from, to, chosen, what])

  useEffect(() => {
    if (!chosen.length) {
      setPreview(null)
      return
    }
    const stop = new AbortController()
    const timer = window.setTimeout(() => {
      exportsApi.preview(request, stop.signal).then(setPreview, (error: unknown) => {
        if (!(error instanceof ApiError && error.code === 'cancelled')) fail(error)
      })
    }, previewDelay)
    return () => {
      window.clearTimeout(timer)
      stop.abort()
    }
  }, [request, chosen.length, previewDelay])

  const waiting = mine.some((e) => e.state === 'queued' || e.state === 'packing')
  useEffect(() => {
    if (!waiting) return
    const timer = window.setInterval(() => {
      exportsApi.list().then(setMine, () => undefined)
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [waiting])

  const money = (cents: number, currency = 'EUR') => {
    try {
      return (cents / 100).toLocaleString(i18n.language, { style: 'currency', currency })
    } catch {
      return `${(cents / 100).toLocaleString(i18n.language, { minimumFractionDigits: 2 })} ${currency}`
    }
  }
  const shownCount = preview?.documents ?? count
  // The server sums per currency: one sum for each, never euros and francs added up.
  const totals = Object.entries(preview?.totals ?? {})
  const shownSum = totals.length ? totals.map(([currency, cents]) => money(cents, currency)).join(' + ') : money(preview?.total ?? sum)
  const linksOn = rules?.links_allowed !== false
  const days = rules?.link_max_days ?? 30
  // The archive always asks for what was filed: only filters a person set are worth a word.
  const hasFilters = Boolean(filters.q || filters.kind_id || filters.owner_id || filters.sender || filters.tag)

  const create = async () => {
    setBusy(true)
    setProblem(null)
    try {
      const made = await exportsApi.create({ ...request, ...(asLink ? { link: { recipient: recipient.trim(), days } } : {}) })
      let sentence = t('exports.made')
      if (asLink && made.link) sentence = (await copyText(made.link.url)) ? t('exports.madeLink') : t('exports.madeLinkNotCopied')
      say?.(sentence)
      onClose()
    } catch (error) {
      fail(error)
    } finally {
      setBusy(false)
    }
  }

  const vaultName = (vault: Vault) => (vault.personal_of !== null && vault.personal_of === me?.id ? t('exports.myVault') : vault.name)

  return (
    <Dialog title={t('exports.title')} onClose={onClose} wide>
      <p className="-mt-2 mb-5 text-sm text-ink-2">{t('exports.intro')}</p>
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="space-y-4">
          <div className="flex gap-3">
            <label className="flex-1 text-sm">
              <span className="font-semibold">{t('exports.from')}</span>
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="mt-1 block h-10 w-full rounded-xl border border-line bg-sheet px-3" />
            </label>
            <label className="flex-1 text-sm">
              <span className="font-semibold">{t('exports.to')}</span>
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="mt-1 block h-10 w-full rounded-xl border border-line bg-sheet px-3" />
            </label>
          </div>
          <div>
            <p className="text-sm font-semibold">{t('exports.vaults')}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {vaults.map((vault) => {
                const active = chosen.includes(vault.id)
                return (
                  <button
                    key={vault.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setChosen(active ? chosen.filter((id) => id !== vault.id) : [...chosen, vault.id])}
                    className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm font-semibold transition ${
                      active ? 'border-transparent bg-accent text-accent-ink' : 'border-line bg-sheet text-ink-2 hover:border-accent'
                    }`}
                  >
                    <VaultIcon icon={vault.icon} size={14} /> {vaultName(vault)}
                  </button>
                )
              })}
            </div>
          </div>
          <div className="space-y-2 text-sm">
            <p className="font-semibold">{t('exports.content')}</p>
            {(['pdf', 'original', 'csv', 'xml'] as const).map((key) => (
              <label key={key} className="flex items-start gap-3">
                <input type="checkbox" checked={what[key]} onChange={(e) => setWhat({ ...what, [key]: e.target.checked })} className="mt-0.5 h-5 w-5 accent-[var(--accent)]" />
                <span>
                  <span className="font-semibold">{t(`exports.${key}`)}</span>
                  <span className="block text-xs text-muted">{t(`exports.${key}Hint`)}</span>
                </span>
              </label>
            ))}
          </div>
        </div>
        <div className="space-y-4">
          <div className="rounded-2xl bg-sheet-2 p-4 text-sm" aria-live="polite">
            <p className="text-xs font-bold tracking-wide text-muted uppercase">{t('exports.inZip')}</p>
            <p className="mt-2 font-display text-2xl font-semibold">{t('exports.documents', { n: shownCount.toLocaleString(i18n.language) })}</p>
            <p className="text-ink-2">{t('exports.sizeSum', { size: formatBytes(preview?.size ?? 0, i18n.language, 1000), sum: shownSum })}</p>
            {preview && preview.sample?.length > 0 && (
              <pre className="mt-3 overflow-x-auto rounded-xl bg-sheet p-3 font-mono text-[0.7rem] leading-relaxed text-ink-2">{treeOf(preview.sample)}</pre>
            )}
            {preview?.too_many && (
              <p className="mt-2 text-xs font-semibold text-bad">
                {t('exports.tooMany', { max: preview.max_documents.toLocaleString(i18n.language), size: formatBytes(preview.max_bytes, i18n.language, 1024) })}
              </p>
            )}
            {hasFilters && <p className="mt-2 text-xs text-muted">{t('exports.filters')}</p>}
          </div>
          {linksOn ? (
            <div className="space-y-2">
              <label className="flex items-start gap-3 text-sm">
                <input type="checkbox" checked={asLink} onChange={(e) => setAsLink(e.target.checked)} className="mt-0.5 h-5 w-5 accent-[var(--accent)]" />
                <span>
                  <span className="font-semibold">{t('exports.asLink')}</span>
                  <span className="block text-xs text-muted">{t('exports.asLinkHint', { days })}</span>
                </span>
              </label>
              {asLink && (
                <label className="block pl-8 text-sm">
                  <span className="font-semibold">{t('exports.recipient')}</span>
                  <input value={recipient} maxLength={100} onChange={(e) => setRecipient(e.target.value)} className="mt-1 block h-10 w-full rounded-xl border border-line bg-sheet px-3" />
                </label>
              )}
            </div>
          ) : (
            <p className="text-xs text-muted">{t('exports.linksOff')}</p>
          )}
        </div>
      </div>
      {problem && (
        <p role="alert" className="mt-4 rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {words(problem.code, problem.values)}
        </p>
      )}
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          {t('exports.cancel')}
        </Button>
        <Button variant="primary" onClick={() => void create()} disabled={busy || !chosen.length || preview?.too_many === true || (asLink && !recipient.trim())}>
          <Download size={16} aria-hidden /> {asLink ? t('exports.createLink') : t('exports.createZip')}
        </Button>
      </div>
      {mine.length > 0 && (
        <ExportList
          exports={mine}
          days={days}
          linksOn={linksOn}
          recipient={t('exports.recipientDefault')}
          onChange={() => exportsApi.list().then(setMine, fail)}
          onNote={setNote}
          onFail={fail}
        />
      )}
      {note && (
        <p role="status" className="mt-2 text-sm font-semibold text-accent">
          ✓ {note}
        </p>
      )}
    </Dialog>
  )
}

/** The person's exports under the dialog: state, size, until when, download, the link (copy, revoke), delete. */
function ExportList({
  exports,
  days,
  linksOn,
  recipient,
  onChange,
  onNote,
  onFail,
}: {
  exports: ExportInfo[]
  days: number
  linksOn: boolean
  recipient: string
  onChange: () => void
  onNote: (text: string) => void
  onFail: (error: unknown) => void
}) {
  const { t, i18n } = useTranslation()
  const words = useExportText()
  const { ask, dialog } = useConfirm()
  const run = async (work: () => Promise<unknown>, done?: string) => {
    try {
      await work()
      if (done) onNote(done)
      onChange()
    } catch (error) {
      onFail(error)
    }
  }
  const copy = async (url: string) => onNote((await copyText(url)) ? t('exports.copied') : url)
  return (
    <section className="mt-6 border-t border-line pt-4" aria-label={t('exports.recent')}>
      <h3 className="text-sm font-semibold">{t('exports.recent')}</h3>
      <ul className="mt-2 divide-y divide-line">
        {exports.map((item) => {
          const link = item.links.find((l) => l.status === 'active')
          return (
            <li key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
              <span className="min-w-0 flex-1">
                <span className="font-semibold">{t(`exports.state.${item.state}`)}</span>
                <span className="block text-xs text-muted">
                  {t('exports.line', { date: shortDate(item.created_at, i18n.language), n: item.documents.toLocaleString(i18n.language), size: formatBytes(item.size, i18n.language, 1000) })}
                  {item.state === 'ready' && ` · ${t('exports.keptUntil', { date: shortDate(item.expires_at, i18n.language) })}`}
                  {item.state === 'failed' && ` · ${words(item.error || 'failed')}`}
                </span>
                {item.links
                  .filter((l) => l.status !== 'revoked')
                  .slice(0, 2)
                  .map((l) => (
                    <span key={l.id} className="block text-xs text-muted">
                      {l.status !== 'active'
                        ? t('exports.linkEnded', { recipient: l.recipient })
                        : l.opened_count > 0 && l.last_opened_at
                          ? t('exports.opened', { recipient: l.recipient, n: l.opened_count, date: shortDate(l.last_opened_at, i18n.language) })
                          : t('exports.notOpened', { recipient: l.recipient })}
                    </span>
                  ))}
              </span>
              <span className="flex flex-wrap gap-1">
                {item.state === 'ready' && (
                  <a href={exportsApi.fileUrl(item.id)} download className="inline-flex h-8 items-center gap-1.5 rounded-full bg-accent-soft px-3.5 text-sm font-semibold text-accent">
                    <Download size={14} aria-hidden /> {t('exports.download')}
                  </a>
                )}
                {link && (
                  <Button size="sm" variant="line" onClick={() => void run(async () => copy((await exportsApi.address(item.id, link.id)).url))}>
                    <Link2 size={14} aria-hidden /> {t('exports.copyLink')}
                  </Button>
                )}
                {link && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      ask({
                        title: t('confirm.exportLink.title'),
                        text: t('confirm.exportLink.text', { name: iso(link.recipient) }),
                        confirm: t('confirm.exportLink.confirm'),
                        run: async () => {
                          await exportsApi.revokeLink(item.id, link.id)
                          onChange()
                        },
                      })
                    }
                  >
                    {t('exports.revoke')}
                  </Button>
                )}
                {!link && linksOn && item.state !== 'failed' && (
                  <Button size="sm" variant="line" onClick={() => void run(async () => copy((await exportsApi.makeLink(item.id, recipient, days)).url))}>
                    <Link2 size={14} aria-hidden /> {t('exports.makeLink')}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={t('exports.delete')}
                  onClick={() =>
                    ask({
                      title: t('confirm.export.title'),
                      text: t('confirm.export.text'),
                      confirm: t('confirm.export.confirm'),
                      run: async () => {
                        await exportsApi.remove(item.id)
                        onChange()
                      },
                    })
                  }
                >
                  <Trash2 size={14} aria-hidden />
                </Button>
              </span>
            </li>
          )
        })}
      </ul>
      {dialog}
    </section>
  )
}
