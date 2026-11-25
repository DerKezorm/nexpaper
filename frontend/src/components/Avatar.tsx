import { avatarUrl } from '../api/client'
import { avatarPlaceholder } from '../vendor/nexkonten/konten'

/** A person as their picture, or the stand-in as the account module draws it everywhere (server, iPhone, the
 * operator's list): the first letter of the shown name on a hue from that name, saturation, lightness and the letter's
 * colour from the kit's variables. */
export function Avatar({ person, size = 32 }: { person: { id: number; name: string; display_name?: string; avatar: string | null }; size?: number }) {
  const shown = person.display_name || person.name
  const url = avatarUrl(person)
  const box = { width: size, height: size }
  if (url) return <img src={url} alt="" title={shown} style={box} className="shrink-0 rounded-full object-cover" />
  const { letter, hue } = avatarPlaceholder(shown)
  return (
    <span
      title={shown}
      className="inline-flex shrink-0 items-center justify-center rounded-full font-bold"
      style={{
        ...box,
        fontSize: size * 0.42,
        background: `hsl(${hue} var(--nexui-avatar-saturation) var(--nexui-avatar-lightness))`,
        color: 'var(--nexui-avatar-text)',
      }}
    >
      {letter}
    </span>
  )
}
