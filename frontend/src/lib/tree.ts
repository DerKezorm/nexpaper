/** The sample paths as the tree the mock shows: each folder once, indented. */
export function treeOf(paths: string[]): string {
  const lines: string[] = []
  const open: string[] = []
  for (const path of paths) {
    const parts = path.split('/')
    const folders = parts.slice(0, -1)
    let same = 0
    while (same < folders.length && same < open.length && open[same] === folders[same]) same += 1
    open.length = same
    for (let depth = same; depth < folders.length; depth += 1) {
      lines.push(`${'  '.repeat(depth)}${folders[depth]}/`)
      open.push(folders[depth])
    }
    lines.push(`${'  '.repeat(folders.length)}${parts[parts.length - 1]}`)
  }
  return lines.join('\n')
}
