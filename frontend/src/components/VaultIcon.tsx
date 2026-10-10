import { Briefcase, Car, Folder, Home, Sun, User, type LucideIcon } from 'lucide-react'

const ICONS: Record<string, LucideIcon> = { user: User, home: Home, car: Car, sun: Sun, folder: Folder, briefcase: Briefcase }

/** The symbol of a vault; one the interface does not know is a folder. */
export function VaultIcon({ icon, size = 16 }: { icon: string; size?: number }) {
  const Icon = ICONS[icon] ?? Folder
  return <Icon size={size} aria-hidden />
}
