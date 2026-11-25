/**
 * Since 1.1.0: the frame of the settings, as nexnotes' (`SettingsPage`, `SettingsNav`, `areas.ts`). Where the place is
 * wide enough (700 px of its own; beside an app's sidebar a laptop is narrow too) the navigation stands left: the
 * account at the top, then the group "My account", at most one group of the app's own (nexmail's "Mail"), "Server"
 * (the operator's), and set apart at the end "About <app>"; the entry of the area shown is marked (`aria-current`).
 * Narrower, a phone goes from the list to an area: `/settings` shows the list (`list`), an area shows a way back to it
 * above its title.
 *
 * `SettingsPage` is one area: its title (`h1`), one line under it, and below nothing but cards. The titles and lines of
 * the shared areas come from the kit's words (`areaText`); an app's own area brings its own.
 *
 * The kit knows no router: an app hands over its link (`link={Link}` of react-router), else a plain `a` is used.
 */
import type { ComponentType, ReactNode } from 'react'

import { iconOf, type IconLike } from './icons'
import { BUTTON_BASE, BUTTON_ICON_SIZE, BUTTON_KIND, BUTTON_SIZE, FOCUS, MUTED, PLAIN } from './styles'
import { areaText, fill, useNexuiTexts } from './texts'

/** The link an app hands over; react-router's `Link` fits. */
export type SettingsLink = ComponentType<{
  to: string
  className?: string
  children?: ReactNode
  'aria-current'?: 'page'
  'data-testid'?: string
}>

export type SettingsArea = {
  slug: string
  /** Its title in the navigation; for a shared area the kit's own when left out. */
  title?: string
  icon: IconLike
  href: string
}

export type SettingsGroup = {
  /** `account` ("My account", first), `server` ("Server", last), any other: the app's own group (between them). */
  id: string
  /** The group's heading; for `account` and `server` the kit's own when left out. */
  title?: string
  areas: readonly SettingsArea[]
}

function PlainLink({ to, className, children, ...rest }: { to: string; className?: string; children?: ReactNode; 'aria-current'?: 'page'; 'data-testid'?: string }) {
  return (
    <a href={to} className={className} {...rest}>
      {children}
    </a>
  )
}

const ENTRY = `flex min-w-0 items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-sm leading-5 tracking-normal no-underline transition-colors ${FOCUS}`
const ENTRY_HERE = 'bg-[color-mix(in_srgb,var(--nexui-accent)_14%,transparent)] font-medium text-[var(--nexui-accent-text)]'
const ENTRY_QUIET = 'text-[var(--nexui-text-muted)] hover:bg-[var(--nexui-surface-hover)] hover:text-[var(--nexui-text)]'

/** account first, the app's own group in between, server last; the order inside a group is the caller's. */
function ordered(groups: readonly SettingsGroup[]): SettingsGroup[] {
  const rank = (group: SettingsGroup) => (group.id === 'account' ? 0 : group.id === 'server' ? 2 : 1)
  return groups.filter((group) => group.areas.length > 0).sort((a, b) => rank(a) - rank(b))
}

export function SettingsNav({
  app,
  things,
  groups,
  about,
  current,
  account,
  link: Link = PlainLink,
  testId = 'settings-nav',
}: {
  /** The app's name ("nexnotes"), for "About nexnotes". */
  app: string
  /** The app's word for its things, for the lines of the shared areas (`areaText`). */
  things?: string
  groups: readonly SettingsGroup[]
  /** "About <app>", set apart at the end. */
  about: { href: string; title?: string; slug?: string }
  /** The slug of the area shown; none on the phone's list. */
  current?: string
  /** The account at the top: its picture (an `Avatar`), name and role. */
  account?: { name: string; role?: string; picture?: ReactNode }
  link?: SettingsLink
  testId?: string
}) {
  const texts = useNexuiTexts()
  const groupTitle = (group: SettingsGroup) => group.title ?? (group.id === 'account' ? texts.groupAccount : group.id === 'server' ? texts.groupServer : group.id)
  const aboutSlug = about.slug ?? 'about'
  const entry = (slug: string, title: string, icon: IconLike, href: string) => {
    const here = slug === current
    const { Icon } = iconOf(icon)
    return (
      <Link to={href} aria-current={here ? 'page' : undefined} className={`${ENTRY} ${here ? ENTRY_HERE : ENTRY_QUIET}`} data-testid={`settings-nav-${slug}`}>
        <Icon aria-hidden className="h-4 w-4 shrink-0" strokeWidth={1.8} />
        <span className="min-w-0 truncate">{title}</span>
      </Link>
    )
  }
  return (
    <nav aria-label={texts.settings} className="w-full min-w-0 tracking-normal" data-testid={testId}>
      {account && (
        <div className="mb-4 flex items-center gap-3 px-2.5" data-part="settings-account">
          {account.picture}
          <div className="min-w-0">
            <p className={`${PLAIN} truncate text-sm leading-5 font-semibold text-[var(--nexui-text)]`} title={account.name}>
              {account.name}
            </p>
            {account.role && <p className={`${PLAIN} text-xs leading-4 ${MUTED}`}>{account.role}</p>}
          </div>
        </div>
      )}
      {ordered(groups).map((group) => (
        <div key={group.id} className="mb-4" data-group={group.id}>
          <p id={`settings-group-${group.id}`} className={`${PLAIN} px-2.5 pb-1.5 text-[11px] leading-4 font-semibold tracking-wider uppercase ${MUTED}`}>
            {groupTitle(group)}
          </p>
          <ul aria-labelledby={`settings-group-${group.id}`} className="m-0 flex list-none flex-col gap-0.5 p-0">
            {group.areas.map((area) => (
              <li key={area.slug}>{entry(area.slug, area.title ?? areaText(texts, area.slug, { app, things })?.title ?? area.slug, area.icon, area.href)}</li>
            ))}
          </ul>
        </div>
      ))}
      <div className="border-0 border-t border-solid border-[var(--nexui-line)] pt-2" data-part="settings-about">
        {entry(aboutSlug, about.title ?? fill(texts.aboutApp, { app }), 'Info', about.href)}
      </div>
    </nav>
  )
}

/**
 * The navigation and the area side by side; on a phone either the list (`list`) or the area with a way back. `back` is
 * the address of the list (`/settings`).
 */
export function SettingsLayout({
  nav,
  list = false,
  back,
  link: Link = PlainLink,
  children,
  testId = 'settings',
}: {
  /** The navigation (`SettingsNav`). */
  nav: ReactNode
  /** On a phone show the list instead of the area (the address without an area). */
  list?: boolean
  back: string
  link?: SettingsLink
  children?: ReactNode
  testId?: string
}) {
  const texts = useNexuiTexts()
  const { Icon } = iconOf('ArrowLeft')
  return (
    <div className="@container mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8" data-testid={testId} data-list={list || undefined}>
      <div className="flex flex-col gap-5 @min-[700px]:flex-row @min-[700px]:items-start @min-[700px]:gap-8">
        <div className={`${list ? 'block' : 'hidden'} min-w-0 @min-[700px]:sticky @min-[700px]:top-6 @min-[700px]:block @min-[700px]:w-56 @min-[700px]:shrink-0`} data-part="settings-side">
          {nav}
        </div>
        <div className={`${list ? 'hidden' : 'flex'} min-w-0 flex-1 flex-col gap-5 @min-[700px]:flex`} data-part="settings-main">
          <div className="@min-[700px]:hidden" data-part="settings-back">
            <Link to={back} className={`${BUTTON_BASE} ${BUTTON_SIZE.sm} ${BUTTON_KIND.secondary}`} data-testid="settings-back">
              <Icon aria-hidden className={BUTTON_ICON_SIZE.sm} strokeWidth={2} />
              <span className="min-w-0">{texts.backToList}</span>
            </Link>
          </div>
          {children}
        </div>
      </div>
    </div>
  )
}

/** One area: its title, one line, then the cards (nothing else). */
export function SettingsPage({
  slug,
  title,
  subtitle,
  app,
  things,
  children,
}: {
  slug: string
  /** For a shared area the kit's title when left out. */
  title?: string
  subtitle?: ReactNode
  /** The app's name and word for its things, for a shared area's title and line. */
  app?: string
  things?: string
  children?: ReactNode
}) {
  const texts = useNexuiTexts()
  const shared = areaText(texts, slug, { app: app ?? '', things })
  const line = subtitle ?? (shared?.text || null)
  return (
    <div className="flex min-w-0 flex-col gap-5" data-testid={`settings-area-${slug}`} data-area={slug}>
      <div>
        <h1 className={`${PLAIN} text-2xl leading-8 font-bold tracking-tight text-[var(--nexui-text)]`}>{title ?? shared?.title ?? slug}</h1>
        {line && <p className={`${PLAIN} mt-1 text-sm leading-5 ${MUTED}`}>{line}</p>}
      </div>
      <div className="flex min-w-0 flex-col gap-6" data-part="settings-cards">
        {children}
      </div>
    </div>
  )
}
