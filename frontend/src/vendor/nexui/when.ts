/**
 * Since 1.1.2 (E65): one form of dates and moments for every app and module. A day: "24.02.2027" in German,
 * "24/02/2027" in English and French, two digits each (an expiry, a day of a request). A moment: "heute, 14:05",
 * "gestern, 14:05", else "24.02.2027, 14:05" (last use, connected since, created; the forms of sicherung's E62, which a
 * sentence takes in brackets). In the browser's time zone; an app with a clock and zone of its own per account passes
 * its own format to the parts as before (`when`). Something that is no date stays as it came.
 */
import { NEXUI_TEXTS, languageOf, type NexuiLanguageCode } from './texts'

const LOCALES: Record<NexuiLanguageCode, string> = { de: 'de-DE', en: 'en-GB', fr: 'fr-FR' }

function momentOf(value: string | Date): Date | null {
  const found = value instanceof Date ? value : new Date(value)
  return Number.isNaN(found.getTime()) ? null : found
}

function sameDay(one: Date, other: Date): boolean {
  return one.getFullYear() === other.getFullYear() && one.getMonth() === other.getMonth() && one.getDate() === other.getDate()
}

/** "24.02.2027" (de), "24/02/2027" (en, fr). */
export function formatDay(value: string | Date, language: string): string {
  const found = momentOf(value)
  if (!found) return String(value)
  return found.toLocaleDateString(LOCALES[languageOf(language)], { day: '2-digit', month: '2-digit', year: 'numeric' })
}

/** "14:05" in every language (24 hours). */
export function formatTime(value: string | Date, language: string): string {
  const found = momentOf(value)
  if (!found) return String(value)
  return found.toLocaleTimeString(LOCALES[languageOf(language)], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
}

/** "heute, 14:05", "gestern, 14:05", else "24.02.2027, 14:05"; `now` for tests. */
export function formatMoment(value: string | Date, language: string, now: Date = new Date()): string {
  const found = momentOf(value)
  if (!found) return String(value)
  const code = languageOf(language)
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1)
  const day = sameDay(found, now) ? NEXUI_TEXTS[code].today : sameDay(found, yesterday) ? NEXUI_TEXTS[code].yesterday : formatDay(found, code)
  return `${day}, ${formatTime(found, code)}`
}

/** M-19 (1.1.2): an app's word that also serves as a heading ("Address books"), as it stands inside an English or
 * French sentence ("All address books, including later ones"); German keeps its capital (a noun), and so does a word
 * that starts with two capitals (an abbreviation, "IMAP folders"). */
export function inSentence(word: string, language: string): string {
  if (languageOf(language) === 'de' || word.length < 2) return word
  const [first, second] = [word[0]!, word[1]!]
  if (second !== second.toLowerCase()) return word
  return first.toLowerCase() + word.slice(1)
}
