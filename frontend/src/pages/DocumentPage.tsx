/**
 * One document (`/dokument/<id>`), as the mock draws it: the pages on the left (pdf.js, the pictures of the pages first
 * because they are quicker, the strip of pages below), on the right details, the recognised text, notes, versions and
 * the history. Sharing with people and by link, downloading the searchable PDF or the original, copying the text,
 * moving it and putting it in the trash. What the person may change follows their right (`my_right`); the server
 * refuses the rest anyway. The page tools, joining and new versions come from block B5 through `slots`.
 */
import {
  ArrowLeft,
  ChevronDown,
  Copy,
  Download,
  FileCode2,
  FileStack,
  FolderInput,
  Lock,
  MessageSquare,
  MoreHorizontal,
  Pencil,
  RotateCw,
  Share2,
  Trash2,
  Upload,
  Users,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'

import {
  ApiError,
  catalogApi,
  deadlinesApi,
  documentApi,
  TRASH_DAYS,
  documentsApi,
  einvoiceApi,
  fileUrls,
  searchApi,
  sharingApi,
  vaultsApi,
  type DocumentEvent,
  type DocumentInfo,
  type DocumentKind,
  type DocumentLink,
  type DocumentNote,
  type DocumentPatch,
  type DocumentShare,
  type DocumentVersion,
  type Person,
  type Vault,
  type VersionText,
} from '../api/client'
import { Avatar } from '../components/Avatar'
import { Button } from '../components/Button'
import { Dialog } from '../components/Dialog'
import { TagPicker } from '../components/TagPicker'
import { AmountInput, DateInput, Dates, type DateEntry } from '../components/DocumentFields'
import { SenderPicker } from '../components/SenderPicker'
import { FileNotice, KindPill, Menu, MenuItem } from '../components/docs'
import { EInvoiceBox, useEInvoice } from '../components/EInvoice'
import { PagePicture } from '../components/PagePicture'
import { NewKindForm } from '../components/NewKind'
import { PdfView } from '../components/PdfView'
import { useConfirm } from '../components/useConfirm'
import { ShareDialog } from '../components/ShareDialog'
import { VaultIcon } from '../components/VaultIcon'
import { formatBytes } from '../lib/bytes'
import { copyText } from '../lib/copy'
import { shortDate } from '../lib/dates'
import { useVaultTags } from '../lib/tags'
import { dateEntry, datesChanged } from '../lib/inbox'
import { problemOf, refusedOf, refusedValue, shownAtField } from '../lib/dateInput'
import { errorText } from '../lib/errors'
import { eventWhat, eventWho, standsAlone } from '../lib/events'
import { money } from '../lib/money'
import { readablePath } from '../lib/paths'
import { asAvatarPerson, personName } from '../lib/people'
import { inboxChanged, iso, listOf, moment, useSay, useSourceText } from '../lib/say'
import { useAuth } from '../state/auth'
import { slots as appSlots, type Slots } from '../slots'

type Tab = 'details' | 'text' | 'notes' | 'versions' | 'history'

export function DocumentPage({ slots = appSlots }: { slots?: Slots }) {
  const { t } = useTranslation()
  const { id = '' } = useParams()
  const [document, setDocument] = useState<DocumentInfo | null>(null)
  const [gone, setGone] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const load = useCallback(async () => {
    try {
      setDocument(await documentsApi.read(Number(id)))
      setProblem(null)
    } catch (error) {
      if (error instanceof ApiError && (error.code === 'not_found' || error.status === 422)) setGone(true)
      else setProblem(error instanceof ApiError ? error.code : 'internal_error')
    }
  }, [id])
  useEffect(() => {
    setDocument(null)
    setGone(false)
    void load()
  }, [load])

  if (gone)
    return (
      <div className="page pt-10">
        <p>{t('docs.document.gone')}</p>
        <Link to="/" className="text-accent">
          {t('docs.document.toArchive')}
        </Link>
      </div>
    )
  if (problem)
    return (
      <div className="page pt-10">
        <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {errorText(problem)}
        </p>
      </div>
    )
  if (!document) return <div className="page pt-10 text-sm text-muted">{t('docs.loading')}</div>
  return <Doc key={document.id} document={document} setDocument={setDocument} reload={load} slots={slots} />
}

function Doc({ document: d, setDocument, reload, slots }: { document: DocumentInfo; setDocument: (d: DocumentInfo) => void; reload: () => Promise<void>; slots: Slots }) {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const navigate = useNavigate()
  const say = useSay()
  const canEdit = d.my_right === 'edit' || d.my_right === 'manage'
  const [tab, setTab] = useState<Tab>('details')
  const [page, setPage] = useState(1)
  const [pdfPages, setPdfPages] = useState(0)
  const [pdfFailed, setPdfFailed] = useState(false)
  const [menu, setMenu] = useState<'download' | 'more' | null>(null)
  const [sharing, setSharing] = useState(false)
  const [moving, setMoving] = useState(false)
  const [editingPages, setEditingPages] = useState(false)
  const [merging, setMerging] = useState(false)
  const [newVersion, setNewVersion] = useState(false)
  const [vaults, setVaults] = useState<Vault[]>([])
  const [versions, setVersions] = useState<DocumentVersion[]>([])
  const [problem, setProblem] = useState<{ code: string; values?: Record<string, unknown> } | null>(null)
  const [title, setTitle] = useState(d.title)
  const { ask, dialog } = useConfirm()
  useEffect(() => setTitle(d.title), [d.title])

  useEffect(() => {
    void vaultsApi.list().then((list) => setVaults(listOf(list)), () => undefined)
  }, [])
  const loadVersions = useCallback(() => documentApi.versions(d.id).then((list) => setVersions(listOf(list)), () => undefined), [d.id])
  useEffect(() => {
    void loadVersions()
  }, [loadVersions, d.current_version])

  const vault = vaults.find((v) => v.id === d.vault_id)
  const vaultName = (v: Vault) => (me && v.personal_of === me.id ? t('vaults.mine') : v.name)
  const current = versions.find((v) => v.current)
  const pdfUrl = current?.has_archive ? fileUrls.archive(d.id, d.current_version) : current?.kind === 'pdf' ? fileUrls.file(d.id, d.current_version) : null

  const change = async (patch: DocumentPatch) => {
    setProblem(null)
    try {
      setDocument(await documentApi.patch(d.id, patch))
      return true
    } catch (error) {
      setProblem(problemOf(error, patch))
      return false
    }
  }
  // Escape puts the old title back; the blur that follows must not save what was typed before it.
  const leaving = useRef(false)
  const saveTitle = async () => {
    if (leaving.current) {
      leaving.current = false
      return
    }
    const wanted = title.trim()
    if (!wanted) {
      // A title cannot be empty: the field goes back to the one there was, and the page says why.
      setTitle(d.title)
      setProblem({ code: 'invalid_title' })
      return
    }
    if (wanted !== d.title) await change({ title: wanted })
  }
  /** Into the trash, after asking: it stays {{days}} days there and can be brought back. */
  const trash = () =>
    ask({
      title: t('confirm.trash.title'),
      text: t('confirm.trash.text', { title: iso(d.title), days: TRASH_DAYS }),
      confirm: t('confirm.trash.confirm'),
      danger: false,
      run: async () => {
        await documentApi.trash(d.id)
        inboxChanged()
        say(t('docs.document.trashed'), '/', { to: '/papierkorb', label: t('docs.inbox.trashLink') })
      },
    })
  const copyAll = async () => {
    try {
      const text = await searchApi.text(d.id, d.current_version)
      const all = text.pages.join('\n\n').trim()
      if (!all) {
        say(t('docs.document.noTextToCopy'))
        return
      }
      say((await copyText(all)) ? t('docs.document.textCopied') : t('docs.document.copyFailed'))
    } catch (error) {
      setProblem(error instanceof ApiError ? { code: error.code } : { code: 'internal_error' })
    }
  }
  const sourceHint = d.source === 'camera' ? t('docs.document.originalCamera') : t('docs.document.originalAsCame')
  const invoice = useEInvoice(d)
  const pages = d.pages
  const PageEditor = slots.PageEditor
  const MergeDialog = slots.MergeDialog
  const NewVersion = slots.NewVersion

  return (
    <div className="page space-y-5 pt-6 pb-28 lg:pt-8 lg:pb-12">
      <div className="flex flex-wrap items-start gap-3">
        <button type="button" onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/'))} className="mt-1 rounded-full p-2 text-ink-2 hover:bg-sheet-2" aria-label={t('docs.document.back')}>
          <ArrowLeft size={19} aria-hidden />
        </button>
        <div className="min-w-0 flex-1">
          {canEdit ? (
            <input
              value={title}
              maxLength={200}
              onChange={(event) => setTitle(event.target.value)}
              onBlur={() => void saveTitle()}
              onKeyDown={(event) => {
                if (event.key === 'Enter') (event.target as HTMLInputElement).blur()
                else if (event.key === 'Escape') {
                  leaving.current = true
                  setTitle(d.title)
                  setProblem(null)
                  ;(event.target as HTMLInputElement).blur()
                }
              }}
              className="w-full rounded-lg bg-transparent font-display text-2xl font-semibold tracking-tight outline-none hover:bg-sheet-2/60 focus:bg-sheet sm:text-3xl"
              aria-label={t('docs.fields.title')}
            />
          ) : (
            <h1 className="font-display text-2xl font-semibold tracking-tight sm:text-3xl">
              <bdi>{d.title}</bdi>
            </h1>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-ink-2">
            {d.sender && <bdi>{d.sender.name}</bdi>}
            {d.date && <span>{shortDate(d.date, i18n.language)}</span>}
            <KindPill kind={d.kind} small />
            {vault && !d.via_share ? (
              <span className="inline-flex items-center gap-1.5">
                <VaultIcon icon={vault.icon} size={14} /> {vaultName(vault)}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5">
                <Users size={14} aria-hidden /> {t('docs.archive.sharedLower')}
              </span>
            )}
            {d.owner && (
              <span className="inline-flex items-center gap-1.5">
                <Avatar person={asAvatarPerson(d.owner)} size={20} /> {t('docs.document.belongsTo', { name: iso(personName(d.owner)) })}
              </span>
            )}
            {!canEdit && (
              <span className="inline-flex items-center gap-1 rounded-full bg-sheet-2 px-2 py-0.5 text-xs font-semibold" data-testid="read-only">
                <Lock size={12} aria-hidden /> {t('docs.document.readOnly')}
              </span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Button variant="line" size="sm" onClick={() => setMenu(menu === 'download' ? null : 'download')} aria-expanded={menu === 'download'}>
              <Download size={15} aria-hidden /> {t('docs.document.download')} <ChevronDown size={14} aria-hidden />
            </Button>
            {menu === 'download' && (
              <Menu onClose={() => setMenu(null)} label={t('docs.document.download')}>
                {current?.has_archive && <MenuItem icon={Download} text={t('docs.document.searchablePdf')} hint={t('docs.document.searchableHint')} href={fileUrls.archive(d.id, d.current_version)} download />}
                <MenuItem icon={FileStack} text={t('docs.document.original')} hint={sourceHint} href={fileUrls.file(d.id, d.current_version)} download />
                {invoice && <MenuItem icon={FileCode2} text={t('sorting.einvoice.download')} hint={invoice.format} href={einvoiceApi.xmlUrl(d.id, invoice.version)} download />}
              </Menu>
            )}
          </div>
          {d.can_share && (
            <Button variant="line" size="sm" onClick={() => setSharing(true)}>
              <Share2 size={15} aria-hidden /> {t('docs.document.share')}
            </Button>
          )}
          <div className="relative">
            <Button variant="ghost" size="sm" onClick={() => setMenu(menu === 'more' ? null : 'more')} aria-label={t('docs.document.more')} aria-expanded={menu === 'more'}>
              <MoreHorizontal size={18} aria-hidden />
            </Button>
            {menu === 'more' && (
              <Menu onClose={() => setMenu(null)} right label={t('docs.document.more')}>
                {canEdit && NewVersion && <MenuItem icon={Upload} text={t('docs.document.newVersion')} hint={t('docs.document.newVersionHint')} onClick={() => setNewVersion(true)} />}
                {canEdit && MergeDialog && <MenuItem icon={FileStack} text={t('docs.document.merge')} hint={t('docs.document.mergeHint')} onClick={() => setMerging(true)} />}
                <MenuItem icon={Copy} text={t('docs.document.copyText')} onClick={() => void copyAll()} />
                {canEdit && <MenuItem icon={FolderInput} text={t('docs.document.move')} hint={t('docs.document.moveHint')} onClick={() => setMoving(true)} />}
                {canEdit && (
                  <>
                    <div className="my-1 h-px bg-line" />
                    <MenuItem icon={Trash2} text={t('docs.document.trash')} hint={t('docs.document.trashHint')} onClick={() => trash()} />
                  </>
                )}
              </Menu>
            )}
          </div>
        </div>
      </div>

      {problem && !shownAtField(problem) && (
        <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {errorText(problem.code, problem.values)}
        </p>
      )}

      <FileNotice state={d.files_state} documentId={d.id} onChecked={() => void reload()} />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_26rem]">
        <section className="card p-4 sm:p-5" aria-label={t('docs.pagesLabel')}>
          {editingPages && PageEditor ? (
            <PageEditor
              key={d.current_version}
              document={d}
              onDone={(changed) => {
                setEditingPages(false)
                if (changed) {
                  void reload()
                  say(t('docs.document.savedAsVersion'))
                }
              }}
            />
          ) : (
            <>
              <div className="relative mx-auto aspect-[210/297] w-full max-w-xl">
                {pages > 0 ? (
                  <>
                    {/* The picture of the page from the server stands until pdf.js has the PDF (and where it cannot). */}
                    {(pdfPages === 0 || !pdfUrl || pdfFailed) && (
                      <PagePicture key={page} src={fileUrls.page(d.id, d.current_version, page, 'small')} better={fileUrls.page(d.id, d.current_version, page, 'large')} alt={t('docs.page', { n: page })} eager className="absolute inset-0 z-10" />
                    )}
                    {pdfUrl && !pdfFailed && (
                      <PdfView url={pdfUrl} page={page} title={d.title} onPage={setPage} onLoaded={setPdfPages} onFailed={() => setPdfFailed(true)} />
                    )}
                  </>
                ) : (
                  <div className="flex h-full w-full flex-col items-center justify-center gap-2 rounded-[3px] bg-white text-muted shadow-[0_1px_3px_rgb(0_0_0/0.18)]">
                    <FileStack size={28} aria-hidden />
                    <span className="text-xs">{d.status === 'processing' ? t('docs.inbox.reading') : t('docs.noPages')}</span>
                  </div>
                )}
              </div>
              {pages > 1 && (
                <div className="scroll-x mx-auto mt-4 flex w-max max-w-full gap-2 overflow-x-auto pb-1" aria-label={t('docs.pagesStrip')}>
                  {Array.from({ length: pages }, (_, i) => (
                    <button key={i} type="button" onClick={() => setPage(i + 1)} className={`w-11 shrink-0 rounded-[4px] ring-2 ${page === i + 1 ? 'ring-accent' : 'ring-transparent'}`} aria-label={t('docs.page', { n: i + 1 })} aria-pressed={page === i + 1}>
                      <PagePicture src={fileUrls.page(d.id, d.current_version, i + 1, 'small')} alt="" margin="200px" />
                    </button>
                  ))}
                </div>
              )}
              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-sm text-muted">
                <span>{t('docs.document.pageOf', { page, count: Math.max(pages, 1) })}</span>
                {canEdit && PageEditor && pages > 0 && (
                  <Button variant="soft" size="sm" onClick={() => setEditingPages(true)}>
                    <RotateCw size={14} aria-hidden /> {t('docs.document.editPages')}
                  </Button>
                )}
              </div>
            </>
          )}
        </section>

        <section className="card overflow-hidden p-0">
          <div role="tablist" aria-label={t('docs.document.tabs')} className="scroll-x flex gap-1 overflow-x-auto border-b border-line px-3 pt-3">
            {(
              [
                ['details', t('docs.tab.details')],
                ['text', t('docs.tab.text')],
                ['notes', d.notes ? t('docs.tab.notesCount', { count: d.notes }) : t('docs.tab.notes')],
                ['versions', t('docs.tab.versions')],
                ['history', t('docs.tab.history')],
              ] as [Tab, string][]
            ).map(([key, label]) => (
              <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)} className={`shrink-0 border-b-2 px-3 pb-2.5 text-sm font-semibold ${tab === key ? 'border-accent text-accent' : 'border-transparent text-muted hover:text-ink'}`}>
                {label}
              </button>
            ))}
          </div>
          <div className="p-5" role="tabpanel">
            {tab === 'details' && <Details document={d} canEdit={canEdit} vaults={vaults} path={d.status === 'filed' ? (current?.path ?? '') : ''} change={change} problem={problem} onShare={() => setSharing(true)} onMoved={setDocument} onProblem={setProblem} />}
            {tab === 'text' && <TextTab document={d} />}
            {tab === 'notes' && <Notes document={d} onCount={(count) => count !== d.notes && setDocument({ ...d, notes: count })} />}
            {tab === 'versions' && <Versions document={d} versions={versions} canEdit={canEdit} slots={slots} onChanged={() => void reload().then(loadVersions)} />}
            {tab === 'history' && <History document={d} vaults={vaults} vaultName={vaultName} />}
          </div>
        </section>
      </div>

      {sharing && <ShareDialog document={d} onClose={() => setSharing(false)} say={(text) => say(text)} />}
      {moving && (
        <MoveDialog
          document={d}
          vaults={vaults.filter((v) => (v.my_right === 'edit' || v.my_right === 'manage') && v.id !== d.vault_id)}
          vaultName={vaultName}
          onClose={() => setMoving(false)}
          onMoved={(moved, name) => {
            setMoving(false)
            setDocument(moved)
            say(t('docs.document.moved', { vault: iso(name) }))
          }}
        />
      )}
      {merging && MergeDialog && <MergeDialog document={d} onClose={() => setMerging(false)} onDone={() => {
        setMerging(false)
        void reload()
      }} />}
      {newVersion && NewVersion && <NewVersion document={d} onClose={() => setNewVersion(false)} onDone={() => {
        setNewVersion(false)
        void reload().then(loadVersions)
      }} />}
      {dialog}
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] items-center gap-3 text-sm">
      <span className="text-muted">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

type DetailsProps = {
  document: DocumentInfo
  canEdit: boolean
  vaults: Vault[]
  /** Where the original lies, from the folder for documents on (vault, year, sender, file). */
  path: string
  change: (patch: DocumentPatch) => Promise<boolean>
  onShare: () => void
  onMoved: (d: DocumentInfo) => void
  /** What went wrong with the last change, for the date fields to mark the one the server refused. */
  problem: { code: string; values?: Record<string, unknown> } | null
  onProblem: (problem: { code: string; values?: Record<string, unknown> } | null) => void
}

/** The last choice of the kinds: not a kind, the field to make one. */
const NEW_KIND = '__new'

function Details({ document: d, canEdit, vaults, path, change, problem, onShare, onMoved, onProblem }: DetailsProps) {
  const { t, i18n } = useTranslation()
  const invoice = useEInvoice(d)
  const { me } = useAuth()
  const sourceText = useSourceText()
  const [kinds, setKinds] = useState<DocumentKind[]>([])
  const [makingKind, setMakingKind] = useState(false)
  const [senders, setSenders] = useState<string[]>([])
  const [sender, setSender] = useState(d.sender?.name ?? '')
  const [shares, setShares] = useState<DocumentShare[]>([])
  const [links, setLinks] = useState<DocumentLink[]>([])
  // The tags of the document's vault, to choose from (only those; not the names of other vaults).
  const vaultTags = useVaultTags(canEdit ? [d.vault_id] : [])
  useEffect(() => setSender(d.sender?.name ?? ''), [d.sender?.name])
  useEffect(() => {
    void catalogApi.kinds(d.vault_id).then((list) => setKinds(listOf(list)), () => undefined)
    if (canEdit) void catalogApi.senders().then((groups) => setSenders(listOf<{ name: string }>(groups).map((g) => g.name)), () => undefined)
    // Whom a document is shared with is told only to who may share it; the server answers others with 403.
    setShares([])
    setLinks([])
    if (!d.can_share) return
    void sharingApi.shares(d.id).then((list) => setShares(listOf(list)), () => undefined)
    void sharingApi.links(d.id).then((all) => setLinks(listOf<DocumentLink>(all).filter((l) => l.status === 'active')), () => undefined)
  }, [d.id, d.vault_id, d.can_share, canEdit])

  const writable = vaults.filter((v) => v.my_right === 'edit' || v.my_right === 'manage')
  const vaultLabel = (v: Vault) => (v.personal_of !== null ? t('docs.inbox.personalVault', { name: me && v.personal_of === me.id ? t('vaults.mine') : v.name }) : v.name)
  const move = async (target: number) => {
    onProblem(null)
    try {
      onMoved(await documentApi.move(d.id, target))
    } catch (error) {
      onProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
    }
  }
  const dates = d.dates.map(dateEntry)
  const done = Object.fromEntries(d.dates.map((x) => [x.kind, x.done ?? null]))
  const markDone = async (kind: DateEntry['kind'], on: boolean) => {
    if (kind === 'keep_until') return
    onProblem(null)
    try {
      onMoved(await (on ? deadlinesApi.done(d.id, kind) : deadlinesApi.reopen(d.id, kind)))
    } catch (error) {
      onProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
    }
  }
  const addTag = (name: string) => {
    const word = name.trim().replace(/^#/, '')
    if (word && !d.tags.some((had) => had.toLocaleLowerCase() === word.toLocaleLowerCase())) void change({ tags: [...d.tags, word] })
  }
  return (
    <div className="space-y-3">
      <Row label={t('docs.fields.sender')}>
        {canEdit ? (
          <SenderPicker value={sender} onChange={setSender} onCommit={(name) => name.trim() !== (d.sender?.name ?? '') && void change({ sender: name.trim() || null })} names={senders} label={t('docs.fields.sender')} className="input h-9" iconOnly />
        ) : (
          d.sender ? <bdi>{d.sender.name}</bdi> : <span className="text-muted">{t('docs.fields.none')}</span>
        )}
      </Row>
      <Row label={t('docs.fields.kind')}>
        {canEdit ? (
          <div className="min-w-0 flex-1">
            <select
              value={d.kind?.id ?? ''}
              aria-label={t('docs.fields.kind')}
              onChange={(event) => {
                if (event.target.value === NEW_KIND) {
                  setMakingKind(true)
                  return
                }
                setMakingKind(false)
                void change({ kind_id: event.target.value ? Number(event.target.value) : null })
              }}
              className="input h-9"
            >
              <option value="">{t('docs.fields.noKind')}</option>
              {/* A kind the document has from another vault (seen through a share) stays in the list. */}
              {d.kind && !kinds.some((k) => k.id === d.kind!.id) && <option value={d.kind.id}>{d.kind.name}</option>}
              {kinds.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
              {!d.via_share && <option value={NEW_KIND}>{t('kinds.new.option')}</option>}
            </select>
            {makingKind && (
              <NewKindForm
                vaultId={d.vault_id}
                kinds={kinds}
                onClose={() => setMakingKind(false)}
                onMade={(made) => {
                  setKinds((had) => (had.some((k) => k.id === made.id) ? had : [...had, made]))
                  setMakingKind(false)
                  void change({ kind_id: made.id })
                }}
              />
            )}
          </div>
        ) : (
          <KindPill kind={d.kind} small />
        )}
      </Row>
      <Row label={t('docs.fields.date')}>
        {canEdit ? (
          <DateInput value={d.date ?? ''} label={t('docs.fields.date')} refused={refusedValue(problem, 'date')} onCommit={(date) => void change({ date: date || null })} className="input h-9" />
        ) : d.date ? (
          shortDate(d.date, i18n.language)
        ) : (
          <span className="text-muted">{t('docs.fields.none')}</span>
        )}
      </Row>
      <Row label={t('docs.fields.amount')}>
        {canEdit ? (
          <AmountInput cents={d.amount} onChange={(amount) => void change({ amount })} label={t('docs.fields.amount')} className="input h-9" language={i18n.language} />
        ) : (
          money(d.amount, i18n.language, d.currency) || <span className="text-muted">{t('docs.fields.noAmount')}</span>
        )}
      </Row>
      <Row label={t('docs.fields.vault')}>
        {canEdit && !d.via_share ? (
          <select value={d.vault_id} aria-label={t('docs.fields.vault')} onChange={(event) => void move(Number(event.target.value))} className="input h-9">
            {(writable.some((v) => v.id === d.vault_id) ? writable : [...writable, ...vaults.filter((v) => v.id === d.vault_id)]).map((v) => (
              <option key={v.id} value={v.id}>
                {vaultLabel(v)}
              </option>
            ))}
          </select>
        ) : (
          (vaults.find((v) => v.id === d.vault_id)?.name ?? t('docs.archive.sharedLower'))
        )}
      </Row>
      <Row label={t('docs.fields.owner')}>{d.owner ? personName(d.owner) : <span className="text-muted">{t('docs.fields.none')}</span>}</Row>
      <Row label={t('docs.fields.tags')}>
        <div className="flex flex-wrap items-center gap-1.5">
          {d.tags.map((name) => (
            <span key={name} className="inline-flex items-center rounded-full bg-sheet-2 text-xs font-semibold">
              <Link to={`/?q=${encodeURIComponent(`tag:${name.includes(' ') ? `"${name}"` : name}`)}`} className="py-0.5 pl-2.5 hover:text-accent">
                <bdi>{name}</bdi>
              </Link>
              {canEdit ? (
                <button type="button" onClick={() => void change({ tags: d.tags.filter((had) => had !== name) })} aria-label={t('docs.fields.removeTag', { tag: name })} className="rounded-full p-0.5 pr-1.5 text-muted hover:text-ink">
                  <X size={12} aria-hidden />
                </button>
              ) : (
                <span className="pr-2.5" />
              )}
            </span>
          ))}
          {!d.tags.length && !canEdit && <span className="text-muted">{t('docs.fields.noTags')}</span>}
          {canEdit && <TagPicker known={vaultTags} taken={d.tags} onAdd={addTag} placeholder={t('docs.fields.addTag')} label={t('docs.fields.addTagLabel')} />}
        </div>
      </Row>
      {canEdit ? (
        <Dates dates={dates} onChange={(next) => void change(datesChanged(dates, next))} start={d.date} refused={refusedOf(problem)} done={done} onDone={(kind, on) => void markDone(kind, on)} />
      ) : dates.length ? (
        <Row label={t('docs.fields.dates')}>{dates.map((x) => `${t(`docs.dateKinds.${x.kind}`)} ${shortDate(x.date, i18n.language)}`).join(', ')}</Row>
      ) : null}

      <EInvoiceBox invoice={invoice} />

      {(shares.length > 0 || links.length > 0) && (
        <button type="button" onClick={onShare} disabled={!d.can_share} className="mt-2 w-full rounded-2xl border border-line p-4 text-left text-sm hover:border-accent/50 disabled:pointer-events-none" data-testid="shared-box">
          <p className="font-semibold">{t('docs.document.shared')}</p>
          {shares.map((share) => (
            <p key={share.user.id} className="mt-1 flex items-center gap-2 text-ink-2">
              <Users size={14} aria-hidden /> {t('docs.document.sharedWith', { name: iso(personName(share.user)), right: t(`rights.${share.right}.name`).toLocaleLowerCase(i18n.language) })}
            </p>
          ))}
          {links.map((link) => (
            <p key={link.id} className="mt-1 flex items-center gap-2 text-ink-2">
              <Share2 size={14} aria-hidden /> {t('docs.document.linkFor', { to: iso(link.recipient), until: shortDate(link.until, i18n.language), count: link.opened_count })}
            </p>
          ))}
        </button>
      )}
      <p className="pt-2 text-xs text-muted">
        {t('docs.document.footer', { source: sourceText(d.source), when: moment(d.added_at, i18n.language), pages: t('docs.pages', { count: d.pages }) })}
        {path && (
          <span data-testid="stored-at" title={iso(path)}>
            {' '}
            · {t('docs.document.storedAt', { path: iso(readablePath(path, t)) })}
          </span>
        )}
      </p>
    </div>
  )
}

function TextTab({ document: d }: { document: DocumentInfo }) {
  const { t } = useTranslation()
  const [text, setText] = useState<VersionText | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  useEffect(() => {
    searchApi.text(d.id, d.current_version).then(setText, (error: unknown) => setProblem(error instanceof ApiError ? error.code : 'internal_error'))
  }, [d.id, d.current_version])
  if (problem) return <p className="text-sm text-bad">{errorText(problem)}</p>
  if (!text) return <p className="text-sm text-muted">{t('docs.loading')}</p>
  if (text.state === 'pending') return <p className="text-sm text-muted">{t('docs.text.pending')}</p>
  if (text.state === 'none') return <p className="text-sm text-muted">{t('docs.text.none')}</p>
  const languages = text.languages
    .split('+')
    .filter(Boolean)
    .map((code) => t(`ocr.language.${code}`, { defaultValue: code }))
  const filled = text.pages.some((p) => p.trim())
  return (
    <div>
      <p className="mb-3 text-xs text-muted">
        {text.ocr_pages > 0 ? t('docs.text.recognised', { languages: languages.join(', ') }) : t('docs.text.fromFile')} {t('docs.text.searchable')}
      </p>
      {!filled && <p className="text-sm text-muted">{t('docs.text.empty')}</p>}
      {filled &&
        text.pages.map((pageText, index) => (
          <div key={index} className="mb-3">
            {text.pages.length > 1 && <p className="mb-1 text-xs font-bold tracking-wide text-muted uppercase">{t('docs.page', { n: index + 1 })}</p>}
            <p className="rounded-2xl bg-sheet-2/60 p-4 text-sm leading-relaxed whitespace-pre-line text-ink-2">{pageText.trim() || t('docs.text.emptyPage')}</p>
          </div>
        ))}
    </div>
  )
}

function Notes({ document: d, onCount }: { document: DocumentInfo; onCount: (count: number) => void }) {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [notes, setNotes] = useState<DocumentNote[] | null>(null)
  const [text, setText] = useState('')
  const [editing, setEditing] = useState<{ id: number; text: string } | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const { ask, dialog } = useConfirm()
  const load = useCallback(() => documentApi.notes(d.id).then((answer) => {
    const list = listOf<DocumentNote>(answer)
    setNotes(list)
    onCount(list.length)
  }, (error: unknown) => setProblem(error instanceof ApiError ? error.code : 'internal_error')), [d.id, onCount])
  useEffect(() => {
    void load()
    // `onCount` changes with every render of the page; the notes are loaded once per document.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d.id])
  const run = async (work: () => Promise<unknown>) => {
    setProblem(null)
    try {
      await work()
      await load()
      return true
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
      return false
    }
  }
  return (
    <div className="space-y-3">
      {(notes ?? []).map((note) => (
        <div key={note.id} className="flex gap-3">
          {note.author ? <Avatar person={asAvatarPerson(note.author)} size={28} /> : <span className="h-7 w-7 shrink-0 rounded-full bg-sheet-2" />}
          <div className="min-w-0 flex-1 rounded-2xl bg-sheet-2/60 px-3.5 py-2.5 text-sm">
            <p className="flex items-center gap-2 text-xs text-muted">
              <span className="flex-1">
                {note.author ? personName(note.author) : t('docs.notes.someone')} · {moment(note.updated_at ?? note.created_at, i18n.language)}
                {note.updated_at && ` · ${t('docs.notes.edited')}`}
              </span>
              {note.mine && editing?.id !== note.id && (
                <>
                  {me && note.author?.id === me.id && (
                    <button type="button" onClick={() => setEditing({ id: note.id, text: note.text })} aria-label={t('docs.notes.edit')} className="rounded-full p-1 hover:text-ink">
                      <Pencil size={12} aria-hidden />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() =>
                      ask({
                        title: t('confirm.note.title'),
                        text: t('confirm.note.text'),
                        confirm: t('confirm.note.confirm'),
                        run: async () => {
                          await documentApi.deleteNote(d.id, note.id)
                          await load()
                        },
                      })
                    }
                    aria-label={t('docs.notes.delete')}
                    className="rounded-full p-1 hover:text-ink"
                  >
                    <Trash2 size={12} aria-hidden />
                  </button>
                </>
              )}
            </p>
            {editing?.id === note.id ? (
              <form
                className="mt-1 flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (editing.text.trim()) void run(() => documentApi.editNote(d.id, note.id, editing.text.trim())).then((ok) => ok && setEditing(null))
                }}
              >
                <input value={editing.text} onChange={(event) => setEditing({ ...editing, text: event.target.value })} aria-label={t('docs.notes.edit')} maxLength={5000} className="input h-9" autoFocus />
                <Button size="sm" variant="soft" type="submit">
                  {t('common.save')}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                  {t('common.cancel')}
                </Button>
              </form>
            ) : (
              <p className="mt-0.5 whitespace-pre-line">
                <bdi>{note.text}</bdi>
              </p>
            )}
          </div>
        </div>
      ))}
      {notes && notes.length === 0 && <p className="text-sm text-muted">{t('docs.notes.none')}</p>}
      {problem && <p className="text-sm text-bad">{errorText(problem)}</p>}
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          if (text.trim()) void run(() => documentApi.addNote(d.id, text.trim())).then((ok) => ok && setText(''))
        }}
      >
        <input value={text} onChange={(event) => setText(event.target.value)} placeholder={t('docs.notes.placeholder')} aria-label={t('docs.notes.placeholder')} maxLength={5000} className="input" />
        <Button variant="soft" type="submit" aria-label={t('docs.notes.add')}>
          <MessageSquare size={15} aria-hidden />
        </Button>
      </form>
      <p className="text-xs text-muted">{t('docs.notes.everybody')}</p>
      {dialog}
    </div>
  )
}

/** How often the versions are asked for again while an uploaded one is being read. */
const READING_POLL_MS = 3000
/** What the first version's note says when it names where the file came from (the source, not a person's words). */
const SOURCE_NOTES = ['upload', 'camera', 'mail', 'folder', 'share', 'paperless', 'api']

function Versions({ document: d, versions, canEdit, slots, onChanged }: { document: DocumentInfo; versions: DocumentVersion[]; canEdit: boolean; slots: Slots; onChanged: () => void }) {
  const { t, i18n } = useTranslation()
  const sourceText = useSourceText()
  const VersionActions = slots.VersionActions
  // A version that was uploaded is read in the background: the list asks again until it is done (the page tools).
  const reading = versions.some((v) => v.state === 'processing')
  useEffect(() => {
    if (!reading) return
    const timer = window.setTimeout(onChanged, READING_POLL_MS)
    return () => window.clearTimeout(timer)
  }, [reading, versions, onChanged])
  // What a version is: what the person said about it, else how it came about, else where the file came from.
  const what = (v: DocumentVersion) => {
    if (v.note && !SOURCE_NOTES.includes(v.note)) return <bdi>{v.note}</bdi>
    if (v.origin) return t(`pagetools.versions.origin.${v.origin}`, { n: v.from_n ?? '' })
    return v.n === 1 ? sourceText(d.source) : t('docs.versions.version', { n: v.n })
  }
  return (
    <div className="space-y-2">
      {versions.map((v) => (
        <div key={v.n} className="flex items-center gap-3 rounded-2xl border border-line px-3 py-3 text-sm sm:px-4">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-sheet-2 text-xs font-bold">{v.n}</span>
          <div className="min-w-0 flex-1">
            <p className="font-semibold break-words">
              {what(v)}
              {v.current && <span className="ml-2 rounded-full bg-accent-soft px-2 py-0.5 text-xs text-accent">{t('docs.versions.current')}</span>}
              {v.state === 'processing' && <span className="ml-2 rounded-full bg-sheet-2 px-2 py-0.5 text-xs text-muted">{t('pagetools.versions.reading')}</span>}
              {v.state === 'failed' && <span className="ml-2 rounded-full bg-bad/10 px-2 py-0.5 text-xs text-bad">{t('pagetools.versions.failed')}</span>}
            </p>
            <p className="text-xs text-muted">
              {v.created_by ? `${personName(v.created_by)} · ` : ''}
              {moment(v.created_at, i18n.language)}
              {(v.state ?? 'ready') === 'ready' ? ` · ${t('docs.pages', { count: v.pages })}` : ''} · {formatBytes(v.size, i18n.language, 1000)}
            </p>
          </div>
          <a href={fileUrls.file(d.id, v.n)} download className="rounded-full p-2 text-muted hover:bg-sheet-2 hover:text-ink" aria-label={t('docs.versions.download', { n: v.n })} title={t('docs.versions.download', { n: v.n })}>
            <Download size={15} aria-hidden />
          </a>
          {VersionActions && <VersionActions document={d} version={v} canEdit={canEdit} onDone={onChanged} />}
        </div>
      ))}
      <p className="pt-1 text-xs text-muted">{t('docs.versions.hint')}</p>
    </div>
  )
}

function History({ document: d, vaults, vaultName }: { document: DocumentInfo; vaults: Vault[]; vaultName: (v: Vault) => string }) {
  const { t, i18n } = useTranslation()
  const sourceText = useSourceText()
  const [events, setEvents] = useState<DocumentEvent[] | null>(null)
  const [people, setPeople] = useState<Person[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  useEffect(() => {
    documentApi.events(d.id).then((list) => setEvents(listOf(list)), (error: unknown) => setProblem(error instanceof ApiError ? error.code : 'internal_error'))
    void vaultsApi.people().then((list) => setPeople(listOf(list)), () => undefined)
  }, [d.id])
  const context = useMemo(
    () => ({ people: new Map(people.map((p) => [p.id, p])), vaults: new Map(vaults.map((v) => [v.id, vaultName(v)])), sourceText }),
    [people, vaults, vaultName, sourceText],
  )
  if (problem) return <p className="text-sm text-bad">{errorText(problem)}</p>
  if (!events) return <p className="text-sm text-muted">{t('docs.loading')}</p>
  return (
    <ol className="relative space-y-4 border-l-2 border-line pl-5" data-testid="history">
      {events.map((event) => (
        <li key={event.id} className="relative text-sm">
          <span className="absolute top-1 -left-[1.6rem] h-2.5 w-2.5 rounded-full bg-accent" />
          <p>
            {!standsAlone(event) && <span className="font-semibold">{eventWho(event, t)} </span>}
            {eventWhat(event, t, context)}
          </p>
          <p className="text-xs text-muted">{moment(event.at, i18n.language)}</p>
        </li>
      ))}
    </ol>
  )
}

function MoveDialog({ document: d, vaults, vaultName, onClose, onMoved }: { document: DocumentInfo; vaults: Vault[]; vaultName: (v: Vault) => string; onClose: () => void; onMoved: (d: DocumentInfo, name: string) => void }) {
  const { t } = useTranslation()
  const [target, setTarget] = useState(vaults[0]?.id ?? 0)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const move = async () => {
    setBusy(true)
    setProblem(null)
    try {
      const moved = await documentApi.move(d.id, target)
      const vault = vaults.find((v) => v.id === target)
      onMoved(moved, vault ? vaultName(vault) : '')
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
      setBusy(false)
    }
  }
  return (
    <Dialog title={t('docs.document.moveTitle')} onClose={onClose}>
      {vaults.length === 0 ? (
        <p className="text-sm text-ink-2">{t('docs.document.moveNowhere')}</p>
      ) : (
        <>
          <p className="-mt-2 mb-3 text-sm text-ink-2">{t('docs.document.moveText')}</p>
          <select value={target} onChange={(event) => setTarget(Number(event.target.value))} aria-label={t('docs.fields.vault')} className="input">
            {vaults.map((v) => (
              <option key={v.id} value={v.id}>
                {vaultName(v)}
              </option>
            ))}
          </select>
        </>
      )}
      {problem && <p className="mt-3 text-sm text-bad">{errorText(problem)}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel')}
        </Button>
        {vaults.length > 0 && (
          <Button variant="primary" onClick={() => void move()} disabled={busy}>
            <FolderInput size={16} aria-hidden /> {t('docs.document.moveButton')}
          </Button>
        )}
      </div>
    </Dialog>
  )
}
