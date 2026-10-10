/** Where a stack is cut in the split panel (`components/SplitPanel`). Pages are counted from 0 here. */

/** The parts the pages make: a cut before a page starts a new part, a dropped page belongs to none. */
export function partsOf(pages: number, cuts: Set<number>, dropped: Set<number>): number[][] {
  const parts: number[][] = []
  let current: number[] = []
  for (let i = 0; i < pages; i++) {
    if (cuts.has(i) && current.length) {
      parts.push(current)
      current = []
    }
    if (dropped.has(i)) continue
    current.push(i)
  }
  if (current.length) parts.push(current)
  return parts
}
