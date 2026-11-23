/**
 * The sidebar of a large screen, built like nexnotes' (`components/Sidebar.tsx` and the sections registered there):
 * the name at the top; "Hochladen" as the one accent button, the search field below it with Ctrl/⌘ K (as "Neue Notiz"
 * and "Suchen"), "Fotografieren" as a quiet row; the places as rows with their numbers quietly on the right; the
 * sections "Tresore" (each vault, to its documents in the archive; "+" for the operator, who makes shared ones) and
 * "Gemerkt" (the saved searches) with their titles in capitals; "Tresore verwalten", "Ordnung" and "Papierkorb" below
 * a line, as the trash stands in nexnotes; and at the foot the account with the gear, the way into the settings.
 * nexpaper keeps its own colours; how they behave (the chosen row, the accent only on the button) follows nexnotes.
 */
import { Archive, CalendarClock, Camera, FolderCog, Inbox, ListTree, Plus, Search, Settings, Trash2, Upload } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, useLocation } from 'react-router-dom'

import { vaultsApi, type Vault } from '../api/client'
import { usesDeadlines } from '../lib/deadlines'
import { INBOX_CHANGED } from '../lib/say'
import { vaultLabel } from '../lib/vaultLabel'
import { useAuth } from '../state/auth'
import { Avatar } from './Avatar'
import { Wordmark } from './Logo'
import { SavedNav } from './SavedNav'
import { useUploads } from '../state/uploads'
import { VaultIcon } from './VaultIcon'

export type MenuCounts = { inbox: number; trash: number; deadlines: number; overdue: boolean }

const ROW = 'flex h-8 items-center gap-2 rounded-lg px-2.5 text-[13.5px] pointer-coarse:h-11 '
const QUIET_ROW = 'text-ink hover:bg-sheet-2'

function isMac(): boolean {
  return typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
}

/** A place of the sidebar: its symbol, its name, and its number quietly on the right (none at 0). */
function Place({ to, icon: Icon, label, count, warn = false, end = false, testId, title }: { to: string; icon: typeof Inbox; label: string; count?: number; warn?: boolean; end?: boolean; testId?: string; title?: string }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => ROW + (isActive ? 'chosen font-semibold' : QUIET_ROW)}>
      <Icon className="h-3.5 w-3.5 shrink-0" strokeWidth={2} aria-hidden />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {count !== undefined && count > 0 && (
        <span className={`shrink-0 text-xs tabular-nums ${warn ? 'font-semibold text-warn' : 'text-muted'}`} title={title} data-testid={testId}>
          {count}
        </span>
      )}
    </NavLink>
  )
}

/** A section's title in capitals, with "+" on the right where something can be made there. */
function SectionHead({ title, add }: { title: string; add?: ReactNode }) {
  return (
    <div className="flex items-center justify-between pr-1">
      <h2 className="px-2.5 pt-3.5 pb-1 text-[11px] font-semibold tracking-[0.06em] text-muted uppercase">{title}</h2>
      {add}
    </div>
  )
}

/** The vaults the person sees, for the section "Tresore": asked again on every page and after the app changed documents. */
function useVaults(): Vault[] {
  const { pathname } = useLocation()
  const [vaults, setVaults] = useState<Vault[]>([])
  useEffect(() => {
    let alive = true
    const ask = () => void vaultsApi.list().then((list) => alive && setVaults(Array.isArray(list) ? list : []), () => undefined)
    ask()
    window.addEventListener(INBOX_CHANGED, ask)
    return () => {
      alive = false
      window.removeEventListener(INBOX_CHANGED, ask)
    }
  }, [pathname])
  return vaults
}

function VaultSection() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const vaults = useVaults()
  const { pathname, search } = useLocation()
  const chosen = pathname === '/' ? new URLSearchParams(search).get('vault') : null
  if (!vaults.length) return null
  // Your own first, then the shared ones in the server's order.
  const sorted = [...vaults].sort((a, b) => Number(b.personal_of === me?.id) - Number(a.personal_of === me?.id))
  return (
    <section aria-label={t('vaults.title')} className="pb-1" data-testid="sidebar-vaults">
      <SectionHead
        title={t('vaults.title')}
        add={
          me?.role === 'operator' && (
            <Link
              to="/tresore"
              state={{ create: true }}
              aria-label={t('vaults.create')}
              title={t('vaults.create')}
              className="mt-2.5 flex items-center justify-center rounded-md p-1 text-muted hover:bg-sheet-2 hover:text-ink"
              data-testid="sidebar-vault-new"
            >
              <Plus className="h-3.5 w-3.5" strokeWidth={2.2} aria-hidden />
            </Link>
          )
        }
      />
      <ul className="flex flex-col">
        {sorted.map((vault) => {
          const name = vaultLabel(vault, me?.id, t('vaults.mine'))
          const here = chosen === String(vault.id)
          return (
            <li key={vault.id}>
              <Link to={`/?vault=${vault.id}`} title={name} aria-current={here ? 'page' : undefined} className={ROW + (here ? 'chosen font-semibold' : QUIET_ROW)} data-testid="sidebar-vault">
                <span className="shrink-0">
                  <VaultIcon icon={vault.icon} size={14} />
                </span>
                <span className="min-w-0 flex-1 truncate">{name}</span>
                {vault.documents > 0 && <span className="shrink-0 text-xs tabular-nums text-muted">{vault.documents}</span>}
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/** The search field of the sidebar, as nexnotes': it opens the archive with its search field in focus; Ctrl/⌘ K too. */
function SearchEntry() {
  const { t } = useTranslation()
  return (
    <Link
      to="/"
      state={{ search: true }}
      data-testid="sidebar-search"
      aria-keyshortcuts={isMac() ? 'Meta+K' : 'Control+K'}
      className="mb-1 flex h-9 items-center gap-2 rounded-[9px] border border-line px-2.5 text-[13.5px] text-muted hover:bg-sheet-2 hover:text-ink"
    >
      <Search className="h-[15px] w-[15px]" strokeWidth={2} aria-hidden />
      <span className="flex-1">{t('nav.search')}</span>
      <kbd data-testid="search-key">{isMac() ? '⌘ K' : t('nav.searchKey')}</kbd>
    </Link>
  )
}

export function Sidebar({ counts }: { counts: MenuCounts }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const { pick } = useUploads()
  const deadlines = usesDeadlines(me)
  const shown = me?.display_name || me?.name || ''
  return (
    <aside className="sticky top-0 hidden h-dvh w-[260px] shrink-0 flex-col border-r border-line bg-sheet lg:flex">
      <div className="px-4 pt-4 pb-3">
        <Link to="/" aria-label={t('app.archive')} className="inline-flex">
          <Wordmark size={30} />
        </Link>
      </div>
      <nav aria-label={t('app.mainMenu')} className="soft-scroll min-h-0 flex-1 overflow-y-auto px-2" data-testid="sidebar-places">
        <div className="flex flex-col gap-1 pb-2">
          <button type="button" onClick={pick} className="btn btn-accent w-full" data-testid="sidebar-upload">
            <Upload className="h-4 w-4" strokeWidth={2.4} aria-hidden />
            {t('upload.button')}
          </button>
        </div>
        <SearchEntry />
        <Link to="/kamera" className={ROW + 'text-ink-2 hover:bg-sheet-2 hover:text-ink'} data-testid="sidebar-camera">
          <Camera className="h-3.5 w-3.5 shrink-0" strokeWidth={2} aria-hidden />
          {t('phone.quick.photo')}
        </Link>
        <div className="mt-2 flex flex-col">
          <Place to="/eingang" icon={Inbox} label={t('app.inbox')} count={counts.inbox} testId="inbox-count" />
          <Place to="/" end icon={Archive} label={t('app.archive')} />
          {deadlines && <Place to="/fristen" icon={CalendarClock} label={t('deadlines.menu')} count={counts.deadlines} warn={counts.overdue} title={t(counts.overdue ? 'deadlines.badgeOverdue' : 'deadlines.badgeSoon')} testId="deadline-count" />}
        </div>
        <VaultSection />
        <SavedNav />
        <div className="mt-3 flex flex-col border-t border-line pt-2 pb-2">
          <Place to="/tresore" icon={FolderCog} label={t('nav.manageVaults')} />
          <Place to="/ordnung" icon={ListTree} label={t('order.menu')} />
          <Place to="/papierkorb" icon={Trash2} label={t('app.trash')} count={counts.trash} testId="trash-count" />
        </div>
      </nav>
      <div className="border-t border-line p-2">
        <NavLink
          to="/settings"
          aria-label={`${shown} · ${t('settings.title')}`}
          title={`${shown} · ${t('settings.title')}`}
          className={({ isActive }) => 'flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-sm transition-colors ' + (isActive ? 'chosen' : 'text-ink-2 hover:bg-sheet-2 hover:text-ink')}
          data-testid="sidebar-account"
        >
          {me && <Avatar person={me} size={28} />}
          {/* The gear says "settings"; the word stays only for screen readers and the tooltip. */}
          <span className="min-w-0 flex-1 truncate">{shown}</span>
          <Settings className="h-4 w-4 shrink-0" strokeWidth={1.8} aria-hidden />
        </NavLink>
      </div>
    </aside>
  )
}
