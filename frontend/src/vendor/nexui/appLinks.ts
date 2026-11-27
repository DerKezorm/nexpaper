/**
 * Since 1.2.2 (decision W24 of the module wasneu): where a text of "What's new" names another nex app, the name is a
 * link to that app's public repository. The texts stay as they are (frozen once released); the links come only when
 * they are shown (`WhatsNewDialog`, in `lead`, each section's `body` and the lines of `small`, never in a title or in
 * `where`). An app never links itself in its own text.
 */

/**
 * The public repository of every nex app that has one, by the app's name. nexfolk is not public yet (it lives on
 * Forgejo): once it is on GitHub, its line goes here, and every text that names it links it.
 */
export const APP_REPOS: Readonly<Record<string, string>> = {
  nexdiary: 'https://github.com/DerKezorm/nexdiary',
  nexlore: 'https://github.com/DerKezorm/nexlore',
  nexmail: 'https://github.com/DerKezorm/nexmail',
  nexnotes: 'https://github.com/DerKezorm/nexnotes',
  nexpaper: 'https://github.com/DerKezorm/nexpaper',
  nextasks: 'https://github.com/DerKezorm/nextasks',
  nextime: 'https://github.com/DerKezorm/nextime',
}

/** A piece of a text: words as they are, or an app's name with the address of its repository (`href`). */
export type AppLinkPart = { text: string; href?: string }

/** What may touch a name without making it part of a longer word: a letter, a digit or `_` on either side; before it
 * also `-`, `.`, `/`, `@`, `#` (`nexapps-nexnotes`, `github.com/DerKezorm/nexnotes`); after it `-`, `/`, `@`
 * (`nexnotes-ios`), and `.` or `:` followed by a letter or digit (`nexnotes.app`). A full stop, comma, colon,
 * apostrophe, bracket or quotation mark after it ends the word. */
const WORD = String.raw`\p{L}\p{N}_`
const patterns = new Map<string, RegExp>()
/** An app's name: letters and digits only (so it goes into a pattern as it is). */
const NAME = /^[\p{L}\p{N}]+$/u

function pattern(names: readonly string[]): RegExp {
  const key = names.join('|')
  let found = patterns.get(key)
  if (!found) {
    const alternatives = [...names].sort((a, b) => b.length - a.length)
    found = new RegExp(String.raw`(?<![${WORD}./@#-])(?:${alternatives.join('|')})(?![${WORD}/@-])(?![.:][${WORD}])`, 'gu')
    patterns.set(key, found)
  }
  return found
}

/**
 * `text` in pieces: each whole-word mention of another app in `repos` (`APP_REPOS` unless given) becomes a piece with
 * its `href`, all else stays as it is; joined, the pieces give `text` back. `app` (the app showing the text, any case)
 * is never linked; nor is a name whose address does not start with `https://`, nor one with other signs than letters
 * and digits. Names are matched as written (the apps' names are lower case).
 */
export function appLinkParts(text: string, app: string, repos: Readonly<Record<string, string>> = APP_REPOS): AppLinkPart[] {
  if (!text) return []
  const own = app.trim().toLowerCase()
  const names = Object.keys(repos).filter((name) => NAME.test(name) && name !== own && (repos[name] ?? '').startsWith('https://'))
  if (names.length === 0) return [{ text }]
  const parts: AppLinkPart[] = []
  let at = 0
  for (const found of text.matchAll(pattern(names))) {
    const start = found.index ?? 0
    if (start > at) parts.push({ text: text.slice(at, start) })
    parts.push({ text: found[0], href: repos[found[0]] })
    at = start + found[0].length
  }
  if (at < text.length) parts.push({ text: text.slice(at) })
  return parts
}
