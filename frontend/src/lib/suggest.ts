/**
 * Names that fit what a person types: the senders under a field. Case and accents do not count (`muller` finds
 * `Müller`), a name that starts with the typing comes before one that only contains it, and each hit carries the span
 * to mark, in the positions of the name as it is written.
 */

/** A name without case and accents, with for each of its letters the span of the original it came from. */
function folded(text: string): { text: string; from: number[]; to: number[] } {
  let out = ''
  const from: number[] = []
  const to: number[] = []
  let at = 0
  for (const char of text) {
    const start = at
    at += char.length
    const plain = char.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase()
    for (const unit of plain) {
      for (let i = 0; i < unit.length; i += 1) {
        from.push(start)
        to.push(at)
      }
      out += unit
    }
  }
  return { text: out, from, to }
}

export function fold(text: string): string {
  return folded(text).text
}

export type Suggestion = { name: string; marks: [number, number][] }

/** The names that contain `query`, best first, at most `limit` of them; `more` counts the ones left out. */
export function suggest(names: string[], query: string, limit = 8): { shown: Suggestion[]; more: number } {
  const wanted = fold(query.trim())
  if (!wanted) return { shown: [], more: 0 }
  const hits: { name: string; at: number; marks: [number, number][] }[] = []
  for (const name of names) {
    const map = folded(name)
    const at = map.text.indexOf(wanted)
    if (at < 0) continue
    hits.push({ name, at, marks: [[map.from[at], map.to[at + wanted.length - 1]]] })
  }
  hits.sort((a, b) => Number(a.at !== 0) - Number(b.at !== 0) || a.name.localeCompare(b.name))
  return { shown: hits.slice(0, limit).map(({ name, marks }) => ({ name, marks })), more: Math.max(0, hits.length - limit) }
}

/** Every name that contains `query` (all of them for an empty one), in order, for the overlay with the whole list. */
export function filterNames(names: string[], query: string): Suggestion[] {
  const wanted = fold(query.trim())
  const sorted = [...names].sort((a, b) => a.localeCompare(b))
  if (!wanted) return sorted.map((name) => ({ name, marks: [] }))
  return suggest(sorted, query, Number.MAX_SAFE_INTEGER).shown
}

function distance(a: string, b: string): number {
  if (a === b) return 0
  let row = Array.from({ length: b.length + 1 }, (_, i) => i)
  for (let i = 1; i <= a.length; i += 1) {
    const next = [i]
    for (let j = 1; j <= b.length; j += 1) next.push(Math.min(row[j] + 1, next[j - 1] + 1, row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)))
    row = next
  }
  return row[b.length]
}

/**
 * The names that look like what is typed without containing it: a name that the typing contains whole (`Strom` in
 * `Stromvertrag`, three letters and more), or one a slip of the finger away (`Stromm`, `Versicherrung`: one letter
 * wrong for a word of four to seven, two for longer). The closest first, at most `limit`.
 */
export function similar(names: string[], query: string, limit = 3): string[] {
  const wanted = fold(query.trim())
  if (wanted.length < 3) return []
  const found: { name: string; rank: number }[] = []
  for (const name of names) {
    const plain = fold(name)
    if (!plain || plain === wanted || plain.includes(wanted)) continue
    if (wanted.includes(plain) && plain.length >= 3) {
      found.push({ name, rank: -plain.length })
      continue
    }
    const allowed = wanted.length >= 8 ? 2 : wanted.length >= 4 ? 1 : 0
    if (allowed === 0 || Math.abs(plain.length - wanted.length) > allowed) continue
    const far = distance(plain, wanted)
    if (far <= allowed) found.push({ name, rank: far })
  }
  found.sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name))
  return found.slice(0, limit).map((hit) => hit.name)
}
