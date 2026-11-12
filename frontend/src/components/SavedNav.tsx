/**
 * "Gemerkt" in the side bar: the person's saved searches, each with its number of hits (counted by the server's search,
 * with its rights). A menu per entry renames, moves and deletes; deleting asks, like every delete in nexpaper. An entry
 * whose vault the person cannot see (any more) shows a hint instead of a number.
 */
import { AlertTriangle, ArrowDown, ArrowUp, Bookmark, MoreHorizontal, Pencil, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'

import { ApiError, savedApi, type SavedSearch } from '../api/client'
import { errorText } from '../lib/errors'
import { INBOX_CHANGED, useSay } from '../lib/say'
import { isSearch, SAVED_NAME_MAX, savedHint, setSaved, useSaved } from '../lib/saved'
import { useConfirm } from './useConfirm'

export function SavedNav() {
  const { t } = useTranslation()
  const { list, reload } = useSaved()
  const { pathname, search } = useLocation()
  const say = useSay()
  const { ask, dialog } = useConfirm()
  // The numbers follow the archive: asked again whenever it is opened, and after documents changed.
  useEffect(() => {
    if (pathname === '/') void reload()
  }, [pathname, reload])
  useEffect(() => {
    const again = () => void reload()
    window.addEventListener(INBOX_CHANGED, again)
    return () => window.removeEventListener(INBOX_CHANGED, again)
  }, [reload])
  if (!list.length) return null
  const here = pathname === '/' ? new URLSearchParams(search) : null
  const failed = (error: unknown) => say(errorText(error instanceof ApiError ? error.code : 'internal_error'))
  const move = (entry: SavedSearch, way: 'up' | 'down') =>
    void (way === 'up' ? savedApi.up(entry.id) : savedApi.down(entry.id)).then((next) => setSaved(Array.isArray(next) ? next : []), failed)
  const rename = (entry: SavedSearch, name: string) =>
    void savedApi.rename(entry.id, name).then(() => reload(), failed)
  const remove = (entry: SavedSearch) =>
    ask({
      title: t('saved.deleteTitle'),
      text: t('saved.deleteText', { name: entry.name }),
      confirm: t('saved.delete'),
      danger: false,
      run: async () => {
        await savedApi.remove(entry.id)
        await reload()
        say(t('saved.deleted'))
      },
    })
  return (
    <div className="mt-6" data-testid="saved-nav">
      <p className="px-3 pb-1.5 text-xs font-bold tracking-wide text-muted uppercase">{t('saved.title')}</p>
      <ul className="space-y-0.5">
        {list.map((entry, index) => (
          <Entry
            key={entry.id}
            entry={entry}
            active={here !== null && isSearch(entry, here)}
            first={index === 0}
            last={index === list.length - 1}
            above={list.length > 3 && index >= list.length - 2}
            onUp={() => move(entry, 'up')}
            onDown={() => move(entry, 'down')}
            onRename={(name) => rename(entry, name)}
            onDelete={() => remove(entry)}
          />
        ))}
      </ul>
      {dialog}
    </div>
  )
}

/** The number of an entry, or the hint that stands for it. */
export function SavedCount({ entry, className = '' }: { entry: SavedSearch; className?: string }) {
  const { t, i18n } = useTranslation()
  if (entry.state === 'no_access')
    return <AlertTriangle size={14} className={`shrink-0 text-warn ${className}`} aria-label={t('saved.noAccess')} data-testid="saved-hint" />
  if (entry.state !== 'ok' || entry.count === null) return <span className={`text-xs text-muted ${className}`} aria-label={t('saved.failed')}>–</span>
  return <span className={`text-xs tabular-nums text-muted ${className}`}>{entry.count.toLocaleString(i18n.language)}</span>
}

type EntryProps = {
  entry: SavedSearch
  active: boolean
  first: boolean
  last: boolean
  /** The menu opens above the entry (the last ones of a long list, near the account below). */
  above: boolean
  onUp: () => void
  onDown: () => void
  onRename: (name: string) => void
  onDelete: () => void
}

function Entry({ entry, active, first, last, above, onUp, onDown, onRename, onDelete }: EntryProps) {
  const { t } = useTranslation()
  const [menu, setMenu] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(entry.name)
  const box = useRef<HTMLLIElement>(null)
  useEffect(() => {
    if (!menu) return
    const close = (event: MouseEvent) => box.current && !box.current.contains(event.target as Node) && setMenu(false)
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [menu])
  const item = 'flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm font-semibold text-ink-2 hover:bg-sheet-2 hover:text-ink disabled:pointer-events-none disabled:opacity-40'
  const hint = savedHint(entry, t)

  if (renaming)
    return (
      <li className="px-1 py-0.5">
        <form
          onSubmit={(event) => {
            event.preventDefault()
            const next = name.trim()
            if (next && next !== entry.name) onRename(next)
            setRenaming(false)
          }}
        >
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            onBlur={() => setRenaming(false)}
            onKeyDown={(event) => event.key === 'Escape' && setRenaming(false)}
            maxLength={SAVED_NAME_MAX}
            autoFocus
            aria-label={t('saved.newName')}
            className="input h-9 text-sm"
          />
        </form>
      </li>
    )

  return (
    <li ref={box} className="group relative" data-testid="saved-entry">
      <Link
        to={`/?${entry.query}`}
        title={hint || undefined}
        aria-current={active ? 'page' : undefined}
        className={`flex items-center gap-3 rounded-xl py-2 pr-3 pl-3 text-sm font-semibold transition ${active ? 'bg-accent-soft text-accent' : 'text-ink-2 hover:bg-sheet-2'}`}
      >
        <Bookmark size={16} className={`shrink-0 ${active ? 'fill-current' : ''}`} aria-hidden />
        <bdi className="line-clamp-2 min-w-0 flex-1 break-words">{entry.name}</bdi>
        <SavedCount entry={entry} className="group-hover:opacity-0 group-focus-within:opacity-0" />
      </Link>
      <button
        type="button"
        onClick={() => setMenu(!menu)}
        aria-label={t('saved.more', { name: entry.name })}
        aria-expanded={menu}
        className={`absolute top-1/2 right-1.5 -translate-y-1/2 rounded-full p-1 text-muted hover:bg-sheet hover:text-ink ${menu ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus:opacity-100'}`}
      >
        <MoreHorizontal size={16} aria-hidden />
      </button>
      {menu && (
        <div className={`card rise absolute left-2 z-50 w-52 p-1.5 ${above ? 'bottom-full mb-1' : 'top-full mt-1'}`} role="menu">
          <button type="button" role="menuitem" className={item} onClick={() => (setMenu(false), setName(entry.name), setRenaming(true))}>
            <Pencil size={15} aria-hidden /> {t('saved.rename')}
          </button>
          <button type="button" role="menuitem" className={item} disabled={first} onClick={() => (setMenu(false), onUp())}>
            <ArrowUp size={15} aria-hidden /> {t('saved.up')}
          </button>
          <button type="button" role="menuitem" className={item} disabled={last} onClick={() => (setMenu(false), onDown())}>
            <ArrowDown size={15} aria-hidden /> {t('saved.down')}
          </button>
          <div className="my-1 h-px bg-line" />
          <button type="button" role="menuitem" className={item} onClick={() => (setMenu(false), onDelete())}>
            <Trash2 size={15} aria-hidden /> {t('saved.delete')}
          </button>
        </div>
      )}
    </li>
  )
}
