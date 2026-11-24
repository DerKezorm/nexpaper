/** The two shipped languages have the same keys, the same placeholders, and no dashes as pauses. */

import de from './de.json'
import en from './en.json'
import fr from './fr.json'
import oidcFr from './oidc.fr.json'
import oidcEn from '../vendor/nexoidc/oidc.en.json'
import whatsNewDe from './whatsnew/de.json'
import whatsNewEn from './whatsnew/en.json'

function flat(tree: Record<string, unknown>, prefix = ''): Map<string, string> {
  const out = new Map<string, string>()
  for (const [key, value] of Object.entries(tree)) {
    if (value && typeof value === 'object') for (const [k, v] of flat(value as Record<string, unknown>, `${prefix}${key}.`)) out.set(k, v)
    else out.set(prefix + key, String(value))
  }
  return out
}

const german = flat(de)
const english = flat(en)

describe('shipped languages', () => {
  it('have exactly the same keys', () => {
    expect([...german.keys()].filter((key) => !english.has(key))).toEqual([])
    expect([...english.keys()].filter((key) => !german.has(key))).toEqual([])
  })

  it('use the same placeholders for each key', () => {
    const holes = (text: string) => [...text.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort()
    const different = [...german].filter(([key, text]) => JSON.stringify(holes(text)) !== JSON.stringify(holes(english.get(key) ?? '')))
    expect(different.map(([key]) => key)).toEqual([])
  })

  it('never pause with a dash', () => {
    const dashed = [...german, ...english].filter(([, text]) => /[–—]/.test(text))
    expect(dashed.map(([key]) => key)).toEqual([])
  })

  it('say trash in English, never bin', () => {
    expect([...english].filter(([, text]) => /\bbins?\b/i.test(text)).map(([key, text]) => `${key}: ${text}`)).toEqual([])
    // Floor: the English texts are read at all.
    expect(english.size).toBeGreaterThan(300)
  })

  it('count with figures throughout the backup line, never a figure next to a word', () => {
    for (const key of ['server.countAccounts_one']) {
      expect(german.get(key), key).toContain('{{count}}')
      expect(english.get(key), key).toContain('{{count}}')
    }
  })

  it('call the program version Version in German', () => {
    const about = [...german].filter(([key]) => key.startsWith('about.'))
    expect(about.filter(([, text]) => /Fassung/.test(text)).map(([key, text]) => `${key}: ${text}`)).toEqual([])
    expect(german.get('about.version')).toBe('Version')
    expect(german.get('about.updates.current')).toBe('Das ist die neueste Version.')
  })
})

/**
 * French ships too, translated by a person who speaks it. It holds every key of the English file, so nothing falls back to
 * English unseen; the words of the sign-in module come in `oidc.fr.json` beside it, in the shape of the module's own files.
 */
describe('French', () => {
  const french = flat(fr)
  const holes = (text: string) => [...text.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort()
  const tags = (text: string) => [...text.matchAll(/<\/?(\w+)>/g)].map((m) => m[0]).sort()

  it('has exactly the keys of English', () => {
    expect([...english.keys()].filter((key) => !french.has(key))).toEqual([])
    expect([...french.keys()].filter((key) => !english.has(key))).toEqual([])
  })

  it('uses the placeholders and the markup of English for each key', () => {
    const differ = (pick: (text: string) => string[]) =>
      [...french].filter(([key, text]) => JSON.stringify(pick(text)) !== JSON.stringify(pick(english.get(key) ?? ''))).map(([key]) => key)
    expect(differ(holes)).toEqual([])
    expect(differ(tags)).toEqual([])
  })

  it('never pauses with a dash', () => {
    expect([...french].filter(([, text]) => /[–—]/.test(text)).map(([key]) => key)).toEqual([])
  })

  it('has every word of the sign-in module, with its placeholders', () => {
    const module = flat(oidcEn)
    const words = flat(oidcFr)
    expect([...module.keys()].filter((key) => !words.has(key))).toEqual([])
    expect([...words.keys()].filter((key) => !module.has(key))).toEqual([])
    expect([...words].filter(([key, text]) => JSON.stringify(holes(text)) !== JSON.stringify(holes(module.get(key) ?? ''))).map(([key]) => key)).toEqual([])
  })
})

/** Every text in a tree of entries, however deep, arrays included. */
function strings(tree: unknown): string[] {
  if (typeof tree === 'string') return [tree]
  if (tree && typeof tree === 'object') return Object.values(tree).flatMap(strings)
  return []
}

/**
 * The program version in German, as a phrase: "Fassung 1.2", "Fassung von nexpaper", "eine neue Fassung", "die erste
 * Fassung", "je Fassung", "Alle Fassungen und was sich geändert hat". What belongs to content may keep the word: "eine
 * neue Fassung einer Notiz", "Welche Fassung bleibt".
 */
const PROGRAM_FASSUNG =
  /Fassung\s+(?:\d|von\s+nex)|\b(?:neue|neuen|neuere|neueren|neueste|neuesten|erste|ersten|diese|dieser|jede|jeder|je|nächste|nächsten)\s+Fassung(?!en)(?!\s+(?:einer|eines|der|des|deiner|deines)\b)|Fassungen\s+und\s+was/

// The entries are empty until the text of the first release is written; the checks hold for every entry that comes.
describe('what is new', () => {
  const german = strings(whatsNewDe)
  const english = strings(whatsNewEn)

  it('call the program version Version in German, in released entries too', () => {
    expect(german.filter((text) => PROGRAM_FASSUNG.test(text))).toEqual([])
  })

  it('say trash in English', () => {
    expect(english.filter((text) => /\bbins?\b/i.test(text))).toEqual([])
  })

  it('know the program version when they see it, and leave the versions of content alone', () => {
    for (const text of ['Fassung 1.4.0 ist da.', 'eine neuere Fassung von nexlore', 'Die erste Fassung von nexpaper:', 'kommt einmal je Fassung', 'Vor dieser Fassung ging es', 'Alle Fassungen und was sich geändert hat']) {
      expect(PROGRAM_FASSUNG.test(text), text).toBe(true)
    }
    for (const text of ['Jede gespeicherte Fassung einer Notiz', 'eine neue Fassung einer Notiz', 'Welche Fassung bleibt', 'bekommen eine WebP-Fassung']) {
      expect(PROGRAM_FASSUNG.test(text), text).toBe(false)
    }
  })
})
