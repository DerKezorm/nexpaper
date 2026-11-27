/**
 * The areas of the settings (plan "Einstellungen"), each with its own address (`/settings/<slug>`): "Mein Konto" for
 * every account (Profile, Security, Appearance, nexpaper's own Upload and AI, Notifications, Connections), "Server" for
 * the operator only (General, Connections, Sign-in, Mail, Storage and backups, then nexpaper's own Text recognition, AI
 * provider, Filing, Inputs, Import, then Accounts and Log), and "Über nexpaper" (`/settings/about`) for everyone, set
 * apart at the end. Titles and lines of the shared areas come from the ui kit (`areaText`); nexpaper's own keep theirs
 * (`settings.areas.<key>`), "KI-Anbieter" takes the kit's title and keeps nexpaper's line.
 *
 * `/settings` alone is the list on a phone and the profile beside it on a wider page. Every address of before leads on
 * for good: the slugs of before (`reminders`, `ai-setup`, `api`) and the pages of before (`/konto?tab=…`,
 * `/einstellungen?tab=…`, `/ueber`), which the server's notices and mails, the providers' answers and saved links still
 * name (`resolveArea`, `formerAddress`).
 *
 * Server › Connections (`server-connections`, plan E67, ui 1.2.1) holds "Andere nex-Apps" and "Schnittstellen", which
 * stood under General before: `/settings/general#nex-apps` and `#interfaces` lead there with their anchor, and so do the
 * addresses of the area "API" of before.
 */
import { FolderInput, FolderTree, Inbox } from 'lucide-react'

import type { GeneralPart, IconLike } from '../../vendor/nexui'
import type { Me } from '../../api/client'

type Role = Me['role']

export type AreaSlug =
  | 'profile'
  | 'security'
  | 'appearance'
  | 'upload'
  | 'ai'
  | 'notifications'
  | 'connections'
  | 'general'
  | 'server-connections'
  | 'sign-in'
  | 'mail'
  | 'storage'
  | 'ocr'
  | 'ai-provider'
  | 'filing'
  | 'inputs'
  | 'import'
  | 'accounts'
  | 'log'
  | 'about'
export type AreaGroup = 'account' | 'server'

/**
 * `own`: an area of nexpaper alone, its title and line under `settings.areas.<key>` of nexpaper's words; `line`: a shared
 * title (the kit's) with nexpaper's own line (`settings.areas.<key>.text`).
 */
export type Area = { slug: AreaSlug; group: AreaGroup; icon: IconLike; key?: string; own?: boolean; line?: boolean }

/** In the order of the navigation (plan "Einstellungen", "Reihenfolge Mein Konto" and "Reihenfolge Server"). */
export const AREAS: Area[] = [
  { slug: 'profile', group: 'account', icon: 'UserRound' },
  { slug: 'security', group: 'account', icon: 'ShieldCheck' },
  { slug: 'appearance', group: 'account', icon: 'Palette' },
  { slug: 'upload', group: 'account', icon: 'Upload', key: 'upload', own: true },
  { slug: 'ai', group: 'account', icon: 'Sparkles', key: 'myAi', own: true },
  { slug: 'notifications', group: 'account', icon: 'Bell' },
  { slug: 'connections', group: 'account', icon: 'Plug' },
  { slug: 'general', group: 'server', icon: 'SlidersHorizontal' },
  { slug: 'server-connections', group: 'server', icon: 'Plug' },
  { slug: 'sign-in', group: 'server', icon: 'KeyRound' },
  { slug: 'mail', group: 'server', icon: 'Mail' },
  { slug: 'storage', group: 'server', icon: 'HardDrive' },
  { slug: 'ocr', group: 'server', icon: 'ScanText', key: 'ocr', own: true },
  { slug: 'ai-provider', group: 'server', icon: 'Sparkles', key: 'aiProvider', line: true },
  { slug: 'filing', group: 'server', icon: FolderTree, key: 'filing', own: true },
  { slug: 'inputs', group: 'server', icon: FolderInput, key: 'inputs', own: true },
  { slug: 'import', group: 'server', icon: Inbox, key: 'import', own: true },
  { slug: 'accounts', group: 'server', icon: 'Users' },
  { slug: 'log', group: 'server', icon: 'ScrollText' },
]

export const GROUPS: AreaGroup[] = ['account', 'server']

/** The cards of Server › General in their order (``SettingsAreas.tsx``): the line under the title names these (ui 1.1.3,
 * U-3). "Andere nex-Apps" and "Schnittstellen" stand under Server › Connections (E67). */
export const GENERAL_PARTS: readonly GeneralPart[] = ['limits', 'features', 'webPush', 'languages']

/** "Über nexpaper": an area of every account, below the groups (its `group` only says who may open it). */
export const ABOUT_AREA: Area = { slug: 'about', group: 'account', icon: 'Info' }

/** The area of an address, the groups' and "Über nexpaper". */
export function findArea(slug: AreaSlug): Area | undefined {
  return slug === ABOUT_AREA.slug ? ABOUT_AREA : AREAS.find((area) => area.slug === slug)
}

/** The areas an account may open: the operator all, a member those of its own account. */
export function areasFor(role: Role | undefined): Area[] {
  return role === 'operator' ? AREAS : AREAS.filter((area) => area.group === 'account')
}

export function areaPath(slug: AreaSlug): string {
  return `/settings/${slug}`
}

/**
 * The slugs of before the plan "Einstellungen": "Erinnerungen" is "Benachrichtigungen" now (E1), the server's "KI" is
 * "KI-Anbieter" (E10), and the area "API" went apart (the interface is a card under Server › Connections since E67, the
 * shortcut one under My account › Connections); its address leads to Server › Connections.
 */
export const FORMER_SLUGS: Record<string, AreaSlug> = { reminders: 'notifications', 'ai-setup': 'ai-provider', api: 'server-connections' }

/** The cards that left Server › General for Server › Connections (E67), by their anchor. */
const MOVED_FROM_GENERAL = new Set(['#nex-apps', '#interfaces'])

/**
 * Where an address of the settings leads: the area itself, or the address to go to instead (a slug of before, an area
 * the account may not open, which goes to the settings' start). `/settings` alone shows the profile (and on a phone the
 * list). The answer of a provider after linking (`?linked=`, `?error=`) comes to `/settings` and belongs to Security,
 * where the providers are.
 */
export function resolveArea(asked: string | undefined, role: Role | undefined, search: string, hash = ''): { area: AreaSlug } | { redirect: string } {
  const allowed = areasFor(role)
  // E67: a link to a card that moved (the cards' "Einrichten" of before, a partner's link, saved links) lands at its new
  // place, the anchor kept.
  if (asked === 'general' && MOVED_FROM_GENERAL.has(hash) && allowed.some((area) => area.slug === 'server-connections')) {
    return { redirect: areaPath('server-connections') + search + hash }
  }
  if (asked === undefined) {
    const params = new URLSearchParams(search)
    if (params.has('linked') || params.has('error')) return { redirect: areaPath('security') + search }
    return { area: 'profile' }
  }
  if (asked === ABOUT_AREA.slug || allowed.some((area) => area.slug === asked)) return { area: asked as AreaSlug }
  const former = FORMER_SLUGS[asked]
  if (former && allowed.some((area) => area.slug === former)) return { redirect: areaPath(former) + search + hash }
  return { redirect: '/settings' }
}

/** The tabs of "Mein Konto" before the areas (`/konto?tab=…`). */
const FORMER_ACCOUNT: Record<string, AreaSlug> = {
  profile: 'profile',
  security: 'security',
  sicherheit: 'security',
  devices: 'connections',
  upload: 'upload',
  erinnerungen: 'notifications',
  ai: 'ai',
  looks: 'appearance',
}

/** The tabs of the settings before the areas (`/einstellungen?tab=…`). */
const FORMER_SERVER: Record<string, AreaSlug> = {
  accounts: 'accounts',
  signin: 'sign-in',
  mail: 'mail',
  ai: 'ai-provider',
  storage: 'filing',
  inputs: 'inputs',
  sharing: 'general',
  push: 'general',
  backups: 'storage',
  languages: 'general',
  import: 'import',
  log: 'log',
  api: 'server-connections',
}

/**
 * The address of the area an address of before meant, with what else it carried (a provider's answer, `?linked=`).
 * `page`: `konto`, `einstellungen` or `ueber`.
 */
export function formerAddress(page: 'konto' | 'einstellungen' | 'ueber', search: string): string {
  if (page === 'ueber') return areaPath('about')
  const params = new URLSearchParams(search)
  const tab = params.get('tab') ?? ''
  params.delete('tab')
  const rest = params.toString() ? `?${params.toString()}` : ''
  if (page === 'einstellungen') return areaPath(FORMER_SERVER[tab] ?? 'general') + rest
  // The provider's answer after linking stands on Security, whichever tab the address named.
  if (!tab && (params.has('linked') || params.has('error'))) return areaPath('security') + rest
  return areaPath(FORMER_ACCOUNT[tab] ?? 'profile') + rest
}
