/**
 * The lines of the history when a link of another document shows a document too, and no longer (N2): the other
 * document by its title only when the server gave it, else "another document".
 */
import type { TFunction } from 'i18next'

import type { DocumentEvent } from '../api/client'
import i18n, { changeLanguage } from '../i18n'
import { plain } from '../test/harness'
import { eventWhat } from './events'

const context = { people: new Map(), vaults: new Map(), sourceText: (s: string) => s }
const line = (action: string, detail: Record<string, unknown>) =>
  plain(eventWhat({ id: 1, at: '2026-11-12T08:00:00Z', action, by: null, by_link: '', detail } as DocumentEvent, i18n.t.bind(i18n) as TFunction, context))

beforeEach(async () => {
  await changeLanguage('de', false)
})

describe('the history of a document a link shows too', () => {
  it('names the other document only when the server gave its title', () => {
    expect(line('link_also_shown', { document: 5, title: 'Rechnung Oktober', days: 7 })).toBe('hat es über einen Link an Rechnung Oktober mitgezeigt')
    expect(line('link_also_shown', { document: null, days: 7 })).toBe('hat es über den Link eines anderen Dokuments mitgezeigt')
  })

  it('says why it left the link', () => {
    expect(line('link_also_left', { document: 5, title: 'Rechnung', reason: 'taken_out' })).toBe('hat es aus dem Link an Rechnung genommen')
    expect(line('link_also_left', { document: 5, title: 'Rechnung', reason: 'unlinked' })).toBe('hat die Verknüpfung gelöst, der Link an Rechnung zeigt es nicht mehr')
    expect(line('link_also_left', { document: null, reason: 'revoked' })).toBe('hat den Link eines anderen Dokuments zurückgezogen, der es mitzeigte')
    expect(line('link_also_gone', { document: 8, title: 'Lieferschein', reason: 'taken_out' })).toBe('hat Lieferschein aus einem Link genommen')
    expect(line('link_also_gone', { document: null, reason: 'purged' })).toBe('hat ein mitgezeigtes Dokument aus einem Link genommen, es wurde endgültig gelöscht')
    // A reason this page does not know is still a sentence.
    expect(line('link_also_left', { document: null, reason: 'odd' })).toBe('hat es aus dem Link eines anderen Dokuments genommen')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    expect(line('link_also_shown', { document: 5, title: 'Invoice', days: 7 })).toBe('showed it with a link of Invoice')
  })
})
