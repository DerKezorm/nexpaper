/**
 * The symbols the kit knows by name (``BUTTONS`` of the module ``konten`` names them as strings). A button given a name
 * draws this icon and says the name in ``data-icon``; a name missing here is a mistake the vitest of the app finds.
 */
import {
  ArrowLeft,
  ArrowRight,
  ArrowRightLeft,
  Ban,
  Check,
  CircleCheck,
  Copy,
  Crown,
  Download,
  ExternalLink,
  Fingerprint,
  HardDrive,
  KeyRound,
  Link,
  LogIn,
  LogOut,
  Mail,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldCheck,
  ShieldOff,
  Trash2,
  Undo2,
  Unlink,
  Unplug,
  Upload,
  UserCog,
  UserPen,
  UserPlus,
  UserRound,
  UserX,
  X,
  type LucideIcon,
} from 'lucide-react'

export const ICONS = {
  ArrowLeft,
  ArrowRight,
  ArrowRightLeft,
  Ban,
  Check,
  CircleCheck,
  Copy,
  Crown,
  Download,
  ExternalLink,
  Fingerprint,
  HardDrive,
  KeyRound,
  Link,
  LogIn,
  LogOut,
  Mail,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldCheck,
  ShieldOff,
  Trash2,
  Undo2,
  Unlink,
  Unplug,
  Upload,
  UserCog,
  UserPen,
  UserPlus,
  UserRound,
  UserX,
  X,
} as const satisfies Record<string, LucideIcon>

export type IconName = keyof typeof ICONS

/** A symbol: a name the kit knows, or an app's own lucide icon (its name then comes from the icon itself). */
export type IconLike = IconName | LucideIcon

export function iconOf(icon: IconLike): { Icon: LucideIcon; name: string } {
  if (typeof icon === 'string') {
    const Icon = ICONS[icon]
    if (!Icon) throw new Error(`nexui: unknown icon ${icon}`)
    return { Icon, name: icon }
  }
  return { Icon: icon, name: icon.displayName ?? 'icon' }
}
