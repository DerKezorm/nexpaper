/**
 * Dates as the pages show them: a moment from the server (an ISO time) as the day it falls on in the person's time
 * zone, and the time zone of the browser to tell the server.
 */

/** The browser's own time zone, as the server wants it ("Europe/Berlin"); empty when the browser does not say. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || ''
  } catch {
    return ''
  }
}

/** "2. Oktober": the day of a moment in the person's time zone, without the year. */
export function dayOfMoment(moment: string, language: string, timeZone?: string): string {
  const options: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'long' }
  try {
    return new Intl.DateTimeFormat(language, { ...options, timeZone: timeZone || undefined }).format(new Date(moment))
  } catch {
    return new Intl.DateTimeFormat(language, options).format(new Date(moment))
  }
}

/** "08.10.2026": a day, as a whole date with the order of the language. Takes a day (`2026-10-08`) or a moment. */
export function shortDate(value: string, language: string): string {
  const stamp = /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00` : value
  try {
    return new Intl.DateTimeFormat(language, { day: '2-digit', month: '2-digit', year: 'numeric' }).format(new Date(stamp))
  } catch {
    return value
  }
}

/** The day `days` days from `from`, as `2026-10-08` in the browser's own calendar (what a date field wants). */
export function dayInDays(days: number, from: Date = new Date()): string {
  const day = new Date(from.getFullYear(), from.getMonth(), from.getDate() + days)
  const two = (n: number) => String(n).padStart(2, '0')
  return `${day.getFullYear()}-${two(day.getMonth() + 1)}-${two(day.getDate())}`
}

/** How many days from `from` (today) a day `2026-10-08` lies; at least 0. */
export function daysUntil(day: string, from: Date = new Date()): number {
  const [year, month, date] = day.split('-').map(Number)
  const start = new Date(from.getFullYear(), from.getMonth(), from.getDate()).getTime()
  const end = new Date(year, month - 1, date).getTime()
  return Math.max(0, Math.round((end - start) / 86_400_000))
}
