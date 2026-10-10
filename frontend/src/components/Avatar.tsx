import { avatarUrl } from '../api/client'

/** A hue from the name, so a person keeps the colour of their circle everywhere. */
function hueOf(name: string): number {
  let hash = 0
  for (const char of name) hash = (hash * 31 + char.codePointAt(0)!) % 360
  return hash
}

/** A person as their picture, or a round letter in their colour, as the mock shows accounts. */
export function Avatar({ person, size = 32 }: { person: { id: number; name: string; display_name?: string; avatar: string | null }; size?: number }) {
  const shown = person.display_name || person.name
  const url = avatarUrl(person)
  const box = { width: size, height: size }
  if (url) return <img src={url} alt="" title={shown} style={box} className="shrink-0 rounded-full object-cover" />
  return (
    <span
      title={shown}
      className="inline-flex shrink-0 items-center justify-center rounded-full font-bold text-white"
      style={{ ...box, fontSize: size * 0.42, background: `hsl(${hueOf(person.name)} 38% 52%)` }}
    >
      {(shown.trim()[0] ?? '?').toUpperCase()}
    </span>
  )
}
