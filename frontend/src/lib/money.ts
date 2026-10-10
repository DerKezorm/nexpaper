/**
 * Amounts: the server keeps cents (a whole number), the page shows euros in the language's way ("1.284,17 €",
 * "€1,284.17") and takes what a person types, with a comma or a point.
 */

/** "86,40 €" in German, "€86.40" in English; empty without an amount. */
export function money(cents: number | null | undefined, language: string, currency = 'EUR'): string {
  if (cents === null || cents === undefined) return ''
  try {
    return new Intl.NumberFormat(language, { style: 'currency', currency }).format(cents / 100)
  } catch {
    return (cents / 100).toFixed(2)
  }
}

/** What an amount field shows: "224,91" in German, "224.91" in English; empty without one. */
export function amountText(cents: number | null | undefined, language: string): string {
  if (cents === null || cents === undefined) return ''
  return new Intl.NumberFormat(language, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(cents / 100)
}

/** What a person typed as cents: `null` for nothing, `'invalid'` for what is no amount. Either sign may separate the
 * cents; "1.234,56", "1,234.56", "12,5", "12.50" and "1.234" (thousands) all work. */
export function parseAmount(typed: string): number | null | 'invalid' {
  let text = typed.replace(/[\s €]/g, '').replace(/eur$/i, '')
  if (!text) return null
  const negative = text.startsWith('-')
  if (negative) text = text.slice(1)
  if (!/^[\d.,]+$/.test(text)) return 'invalid'
  const comma = text.lastIndexOf(',')
  const point = text.lastIndexOf('.')
  let whole = text
  let cents = ''
  if (comma >= 0 && point >= 0) {
    const decimal = Math.max(comma, point)
    const thousands = decimal === comma ? '.' : ','
    const before = text.slice(0, decimal)
    // The other sign groups thousands only: "1.234,56", never "1.2.3,45,6".
    if (before.includes(text[decimal]) || !new RegExp(`^\\d{1,3}(\\${thousands}\\d{3})*$`).test(before)) return 'invalid'
    whole = before.split(thousands).join('')
    cents = text.slice(decimal + 1)
  } else if (comma >= 0 || point >= 0) {
    const sign = comma >= 0 ? ',' : '.'
    const parts = text.split(sign)
    // "1.234", "1,234" and "1.234.567" are thousands; "12.5" and "12,50" are cents.
    if (parts.length > 2 || (parts.length === 2 && parts[1].length === 3)) whole = parts.join('')
    else [whole, cents] = [parts[0], parts[1] ?? '']
  }
  if (!/^\d*$/.test(whole) || !/^\d{0,2}$/.test(cents) || (whole === '' && cents === '')) return 'invalid'
  const value = Number(whole || '0') * 100 + Number(cents.padEnd(2, '0') || '0')
  if (!Number.isSafeInteger(value) || value > 1e12) return 'invalid'
  return negative ? -value : value
}
