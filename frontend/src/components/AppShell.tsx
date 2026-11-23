import { Archive, CalendarClock, FolderLock, Inbox, ListTree, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { inboxApi } from '../api/client'
import { usesDeadlines } from '../lib/deadlines'
import { INBOX_CHANGED, type NoticeLink } from '../lib/say'
import { useAuth } from '../state/auth'
import { Avatar } from './Avatar'
import { Wordmark } from './Logo'
import { Sidebar, type MenuCounts } from './Sidebar'
import { DropSheet, UploadPanel, UploadRound } from './UploadPanel'
import { WhatsNewBanner } from './WhatsNew'

/** A short sentence after something was done ("Gespeichert."), handed over by the page that did it as `notice` in the
 * navigation state; shown for a moment, then gone, and not again after a reload. */
function Toast() {
  const location = useLocation()
  const navigate = useNavigate()
  const [shown, setShown] = useState<{ text: string; link?: NoticeLink } | null>(null)
  const state = location.state as { notice?: unknown; link?: unknown } | null
  const notice = state?.notice
  const link = state?.link as NoticeLink | undefined
  useEffect(() => {
    if (typeof notice !== 'string') return
    setShown({ text: notice, ...(link && typeof link.to === 'string' && typeof link.label === 'string' ? { link } : {}) })
    navigate(location.pathname + location.search, { replace: true, state: null })
  }, [notice, link, navigate, location.pathname, location.search])
  useEffect(() => {
    if (!shown) return
    // A sentence with a way on stays longer: there is something to press.
    const timer = window.setTimeout(() => setShown(null), shown.link ? 8000 : 3500)
    return () => window.clearTimeout(timer)
  }, [shown])
  if (!shown) return null
  return (
    <div role="status" className="rise fixed inset-x-0 bottom-24 z-40 flex justify-center px-4 lg:bottom-8">
      <p className="rounded-[12px] border border-line bg-sheet-2 px-4 py-2.5 text-[13.5px] text-ink shadow-xl shadow-black/20">
        {shown.text}
        {shown.link && (
          <>
            {' '}
            <Link to={shown.link.to} className="underline underline-offset-2" onClick={() => setShown(null)}>
              {shown.link.label}
            </Link>
          </>
        )}
      </p>
    </div>
  )
}

/** The menu items, with "Fristen" after the archive. On the phone the bottom bar has room for five: "Ordnung"
 * moves into the account menu there (`phone: false`). Whoever switched deadlines off has no "Fristen", and "Ordnung"
 * takes its place in the bar (`menuFor`). */
const NAV = [
  { to: '/eingang', label: 'app.inbox', icon: Inbox, phone: true },
  { to: '/', label: 'app.archive', icon: Archive, phone: true },
  { to: '/fristen', label: 'deadlines.menu', icon: CalendarClock, phone: true },
  { to: '/tresore', label: 'app.vaults', icon: FolderLock, phone: true },
  { to: '/ordnung', label: 'order.menu', icon: ListTree, phone: false },
  { to: '/papierkorb', label: 'app.trash', icon: Trash2, phone: true },
]
/** The menu of a person: without deadlines no "Fristen", and the bar of the phone shows "Ordnung" again. */
function menuFor(deadlines: boolean) {
  return deadlines ? NAV : NAV.filter((item) => item.to !== '/fristen').map((item) => (item.to === '/ordnung' ? { ...item, phone: true } : item))
}
/** How often the menu asks again how much waits in the inbox (besides after every change the app makes itself). */
const COUNT_EVERY_MS = 60_000

/** How many documents wait in the inbox or are being read, how many deadlines are overdue or come in the next 14 days
 * (and whether one is overdue), and how many are in the trash, for the badges of the menu. */
function useMenuCounts(): MenuCounts {
  const { pathname } = useLocation()
  const [count, setCount] = useState({ inbox: 0, trash: 0, deadlines: 0, overdue: false })
  useEffect(() => {
    let alive = true
    const ask = () =>
      void inboxApi.counts().then(
        (found) =>
          alive &&
          setCount({
            inbox: (Number(found.inbox) || 0) + (Number(found.reading) || 0),
            trash: Number(found.trash) || 0,
            deadlines: Number(found.deadlines) || 0,
            overdue: (Number(found.deadlines_overdue) || 0) > 0,
          }),
        () => undefined,
      )
    ask()
    const timer = window.setInterval(ask, COUNT_EVERY_MS)
    window.addEventListener(INBOX_CHANGED, ask)
    return () => {
      alive = false
      window.clearInterval(timer)
      window.removeEventListener(INBOX_CHANGED, ask)
    }
  }, [pathname])
  return count
}

/** Ctrl/⌘ K anywhere: the archive with its search field in focus, as the search of nexnotes. */
function useSearchKey() {
  const navigate = useNavigate()
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey || event.key.toLowerCase() !== 'k') return
      event.preventDefault()
      navigate('/', { state: { search: true } })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navigate])
}

/**
 * The frame: the sidebar on a large screen (`Sidebar.tsx`, as nexnotes'), a header on a phone, a header on a phone, the menu below on a phone (inbox with the number of what waits there, archive, vaults, order, trash).
 */
export function AppShell() {
  const { t } = useTranslation()
  // The queue of uploads is the whole signed-in app's (`App.tsx`): the phone's pages share it.
  return <Frame t={t} />
}

function Frame({ t }: { t: (key: string) => string }) {
  const counts = useMenuCounts()
  const { me } = useAuth()
  const items = menuFor(usesDeadlines(me))
  useSearchKey()
  const badge = (to: string) => (to === '/eingang' ? counts.inbox : to === '/papierkorb' ? counts.trash : to === '/fristen' ? counts.deadlines : 0)
  const deadlineBadge = counts.overdue ? 'bg-warn text-paper' : 'bg-accent text-accent-ink'
  return (
    <div className="lg:flex">
      <Sidebar counts={counts} />

      <main className="min-w-0 flex-1">
        <div className="flex items-center justify-between px-4 pt-4 lg:hidden">
          <Wordmark size={30} />
          <div className="flex items-center gap-2">
            <UploadRound />
            {/* On the phone the bottom bar has room for five: "Ordnung" waits here, unless it took the place of
               "Fristen" there. The picture leads to the settings, as the account's row in the sidebar. */}
            {usesDeadlines(me) && (
              <Link to="/ordnung" className="rounded-full p-2 text-ink-2 hover:bg-sheet-2" aria-label={t('order.menu')} title={t('order.menu')}>
                <ListTree size={18} aria-hidden />
              </Link>
            )}
            {me && (
              <Link to="/settings" aria-label={`${me.display_name || me.name} · ${t('settings.title')}`} data-testid="phone-account">
                <Avatar person={me} size={34} />
              </Link>
            )}
          </div>
        </div>
        <WhatsNewBanner />
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-sheet/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden" aria-label={t('app.mainMenu')}>
        {items.filter((n) => n.phone).map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `relative flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[0.7rem] font-bold ${isActive ? 'text-accent' : 'text-muted'}`}>
            <Icon size={21} aria-hidden /> {t(label)}
            {to === '/eingang' && badge(to) > 0 && <span className="absolute top-1.5 left-1/2 ml-2 rounded-full bg-accent px-1 text-[0.6rem] text-accent-ink">{badge(to)}</span>}
            {to === '/fristen' && badge(to) > 0 && <span className={`absolute top-1.5 left-1/2 ml-2 rounded-full px-1 text-[0.6rem] ${deadlineBadge}`}>{badge(to)}</span>}
          </NavLink>
        ))}
      </nav>

      <Toast />
      <UploadPanel />
      <DropSheet />
    </div>
  )
}
