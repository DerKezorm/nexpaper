/**
 * The guard over "What's new": every entry has its four fields in both languages, both languages name the same
 * versions with the same number of parts, and a feature version (patch 0) does not ship without its text.
 */
import { describe, expect, it } from 'vitest'

import pkg from '../../package.json'
import de from '../i18n/whatsnew/de.json'
import en from '../i18n/whatsnew/en.json'
import { entriesFor, fileFor, isEntry, type WhatsNewEntry } from './whatsNew'

const FILES: Record<string, Record<string, unknown>> = { en, de }

describe('the written texts', () => {
  it('have their four fields in every entry', () => {
    for (const [language, entries] of Object.entries(FILES)) {
      for (const [version, entry] of Object.entries(entries)) expect(isEntry(entry), `${language} ${version}`).toBe(true)
    }
  })

  it('name the same versions in both languages, built alike', () => {
    expect(Object.keys(de).sort()).toEqual(Object.keys(en).sort())
    for (const version of Object.keys(en)) {
      const a = (en as Record<string, WhatsNewEntry>)[version]
      const b = (de as Record<string, WhatsNewEntry>)[version]
      expect(b.sections.length, version).toBe(a.sections.length)
      expect(b.small.length, version).toBe(a.small.length)
    }
  })

  it('are there for a feature version before it ships', () => {
    const [major, minor, patch] = pkg.version.split('.').map(Number)
    if (patch !== 0) return
    expect(Object.keys(en), `${major}.${minor}.0`).toContain(pkg.version)
  })
})

describe('an entry', () => {
  const good: WhatsNewEntry = { lead: 'Lead.', sections: [{ title: 'T', where: 'W', body: 'B' }], smallTitle: 'Also', small: ['x'] }

  it('is left out when a field is missing or empty', () => {
    expect(isEntry(good)).toBe(true)
    expect(isEntry({ ...good, lead: '' })).toBe(false)
    expect(isEntry({ ...good, sections: [] })).toBe(false)
    expect(isEntry({ ...good, sections: [{ title: 'T', body: 'B' }] })).toBe(false)
    expect(isEntry({ ...good, sections: [{ title: 'T', where: 'W', body: '' }] })).toBe(false)
    expect(isEntry({ lead: 'L', sections: good.sections, small: [] })).toBe(false)
    expect(isEntry({ ...good, small: 'x' })).toBe(false)
    expect(isEntry({ ...good, small: [''] })).toBe(false)
    expect(isEntry(null)).toBe(false)
  })

  it('takes a link under a section only to https', () => {
    const linked = (link: unknown) => ({ ...good, sections: [{ ...good.sections[0], link }] })
    expect(isEntry(linked({ label: 'App Store', href: 'https://apps.apple.com/app/id1' }))).toBe(true)
    expect(isEntry(linked({ label: 'App Store', href: 'http://apps.apple.com/app/id1' }))).toBe(false)
    expect(isEntry(linked({ label: 'App Store', href: 'javascript:alert(1)' }))).toBe(false)
    expect(isEntry(linked({ label: '', href: 'https://apps.apple.com/app/id1' }))).toBe(false)
    expect(isEntry(linked('https://apps.apple.com/app/id1'))).toBe(false)
  })

  it('comes in German for German and in English for every other language', async () => {
    expect([fileFor('de'), fileFor('de-AT'), fileFor('en'), fileFor('es')]).toEqual(['de', 'de', 'en', 'en'])
    expect((await entriesFor('es'))[pkg.version]?.lead).toBe((en as Record<string, WhatsNewEntry>)[pkg.version]?.lead)
  })
})
