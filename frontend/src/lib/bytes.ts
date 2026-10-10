/** "1,2 GB", "340 MB": a size in bytes as a person reads it, with the separator of the language. `base` 1024 counts a GB
 * as 1024 MB (a limit the operator sets); 1000 counts as a disk and a file manager do (the size of files, as the mock
 * shows it: 1.2e9 bytes are "1,2 GB"). */
export function formatBytes(bytes: number, language: string, base: 1000 | 1024 = 1024): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = Math.max(0, bytes)
  let unit = 0
  while (value >= base && unit < units.length - 1) {
    value /= base
    unit += 1
  }
  // One decimal from GB up ("1,2 GB"), none for a round number ("5 GB").
  const digits = unit >= 3 && value < 100 && !Number.isInteger(Math.round(value * 10) / 10) ? 1 : 0
  return `${new Intl.NumberFormat(language, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value)} ${units[unit]}`
}
