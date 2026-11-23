/**
 * The areas of the settings, as in nexnotes, each with its own address (`/settings/<slug>`): "My account" for every
 * account, "Server" for the operator only, and "About nexpaper" (`/settings/about`) for everyone at the end of the
 * navigation, outside the groups. `/settings` is the profile.
 *
 * What nexnotes has too stands where it stands there and is called the same (Profile, Security, Appearance,
 * Connections; General, Sign-in, Mail, Storage and backups, Text recognition, Accounts, Log). nexpaper's own areas come
 * after the shared ones of their group (Upload, Reminders, AI under My account; Filing, AI, Inputs, Import, API before
 * Accounts and Log under Server), so the shared ones keep their order.
 *
 * The addresses of before (`/konto?tab=…`, `/einstellungen?tab=…`, `/ueber`) lead to their area: the server's
 * notices and mails, the providers' answers and saved links still point there (`formerAddress`).
 */
import {
  Bell,
  FolderInput,
  FolderTree,
  HardDrive,
  Inbox,
  Info,
  KeyRound,
  Mail,
  Palette,
  Plug,
  ScanText,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Upload,
  UserRound,
  Users,
  Webhook,
  type LucideIcon,
} from 'lucide-react'

import type { Me } from '../../api/client'

type Role = Me['role']

export type AreaSlug =
  | 'profile'
  | 'security'
  | 'appearance'
  | 'connections'
  | 'upload'
  | 'reminders'
  | 'ai'
  | 'general'
  | 'sign-in'
  | 'mail'
  | 'storage'
  | 'ocr'
  | 'filing'
  | 'ai-setup'
  | 'inputs'
  | 'import'
  | 'api'
  | 'accounts'
  | 'log'
  | 'about'
export type AreaGroup = 'account' | 'server'

export type Area = { slug: AreaSlug; group: AreaGroup; icon: LucideIcon; key: string }

/** In the order of the navigation; `key` names the texts `settings.areas.<key>.title` and `.text`. */
export const AREAS: Area[] = [
  { slug: 'profile', group: 'account', icon: UserRound, key: 'profile' },
  { slug: 'security', group: 'account', icon: ShieldCheck, key: 'security' },
  { slug: 'appearance', group: 'account', icon: Palette, key: 'appearance' },
  { slug: 'connections', group: 'account', icon: Plug, key: 'connections' },
  { slug: 'upload', group: 'account', icon: Upload, key: 'upload' },
  { slug: 'reminders', group: 'account', icon: Bell, key: 'reminders' },
  { slug: 'ai', group: 'account', icon: Sparkles, key: 'myAi' },
  { slug: 'general', group: 'server', icon: SlidersHorizontal, key: 'general' },
  { slug: 'sign-in', group: 'server', icon: KeyRound, key: 'signIn' },
  { slug: 'mail', group: 'server', icon: Mail, key: 'mail' },
  { slug: 'storage', group: 'server', icon: HardDrive, key: 'storage' },
  { slug: 'ocr', group: 'server', icon: ScanText, key: 'ocr' },
  { slug: 'filing', group: 'server', icon: FolderTree, key: 'filing' },
  { slug: 'ai-setup', group: 'server', icon: Sparkles, key: 'aiSetup' },
  { slug: 'inputs', group: 'server', icon: FolderInput, key: 'inputs' },
  { slug: 'import', group: 'server', icon: Inbox, key: 'import' },
  { slug: 'api', group: 'server', icon: Webhook, key: 'api' },
  { slug: 'accounts', group: 'server', icon: Users, key: 'accounts' },
  { slug: 'log', group: 'server', icon: ScrollText, key: 'log' },
]

export const GROUPS: AreaGroup[] = ['account', 'server']

/** "About nexpaper": an area of every account, below the groups. */
export const ABOUT_AREA: Area = { slug: 'about', group: 'account', icon: Info, key: 'about' }

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
 * Where an address of the settings leads: the area itself, or the address to go to instead (an area the account may
 * not open goes to the profile). The answer of a provider after linking (`?linked=`, `?error=`) belongs to Security,
 * where the providers are.
 */
export function resolveArea(asked: string | undefined, role: Role | undefined, search: string): { area: AreaSlug } | { redirect: string } {
  const allowed = areasFor(role)
  if (asked === undefined) {
    const params = new URLSearchParams(search)
    if (params.has('linked') || params.has('error')) return { redirect: areaPath('security') + search }
    return { area: 'profile' }
  }
  if (asked === ABOUT_AREA.slug || allowed.some((area) => area.slug === asked)) return { area: asked as AreaSlug }
  return { redirect: '/settings' }
}

/** The tabs of "Mein Konto" before the areas (`/konto?tab=…`). */
const FORMER_ACCOUNT: Record<string, AreaSlug> = {
  profile: 'profile',
  security: 'security',
  sicherheit: 'security',
  devices: 'connections',
  upload: 'upload',
  erinnerungen: 'reminders',
  ai: 'ai',
  looks: 'appearance',
}

/** The tabs of the settings before the areas (`/einstellungen?tab=…`). */
const FORMER_SERVER: Record<string, AreaSlug> = {
  accounts: 'accounts',
  signin: 'sign-in',
  mail: 'mail',
  ai: 'ai-setup',
  storage: 'filing',
  inputs: 'inputs',
  sharing: 'general',
  push: 'general',
  backups: 'storage',
  languages: 'general',
  import: 'import',
  log: 'log',
  api: 'api',
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
