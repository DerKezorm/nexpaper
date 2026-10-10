/**
 * Kinds of document by name: the same name in two vaults is one kind to look at (the archive filters by it), and
 * somebody typing a new kind is shown the ones that already sound like it, so that "Rechnnung" does not become a second
 * "Rechnung".
 */
import type { DocumentKind } from '../api/client'

/** A name as it compares: case, accents and spacing aside ("Behörde" and "behorde" are one). */
export function foldName(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .replace(/ß/g, 'ss')
    .toLocaleLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

function distance(a: string, b: string): number {
  const row = Array.from({ length: b.length + 1 }, (_, i) => i)
  for (let i = 1; i <= a.length; i += 1) {
    let diagonal = row[0]
    row[0] = i
    for (let j = 1; j <= b.length; j += 1) {
      const above = row[j]
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, diagonal + (a[i - 1] === b[j - 1] ? 0 : 1))
      diagonal = above
    }
  }
  return row[b.length]
}

/** One kind per name (the first), in the order they come. The server counts the others in when one is asked for. */
export function oneOfEachName(kinds: DocumentKind[]): DocumentKind[] {
  const seen = new Set<string>()
  return kinds.filter((kind) => {
    const key = foldName(kind.name)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** The id that stands for a kind in a list with one entry per name (a namesake in another vault maps to it). */
export function representative(kinds: DocumentKind[], id: string): string {
  const own = kinds.find((k) => String(k.id) === id)
  if (!own) return id
  const first = kinds.find((k) => foldName(k.name) === foldName(own.name))
  return String(first?.id ?? id)
}

export type Likeness = { same: DocumentKind | null; like: DocumentKind[] }

/** The kind that has the typed name (case and accents aside), and up to three that sound like it: one contains the
 * other, or they differ by a letter or two. */
export function likeness(typed: string, kinds: DocumentKind[]): Likeness {
  const word = foldName(typed)
  if (!word) return { same: null, like: [] }
  let same: DocumentKind | null = null
  const like: DocumentKind[] = []
  for (const kind of kinds) {
    const other = foldName(kind.name)
    if (other === word) {
      same = kind
    } else if ((word.length >= 3 && (other.includes(word) || word.includes(other))) || (Math.min(word.length, other.length) >= 4 && distance(word, other) <= 2)) {
      like.push(kind)
    }
  }
  return { same, like: like.slice(0, 3) }
}
