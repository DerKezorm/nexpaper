/**
 * The lines of the history when a link of another document shows a document too, and no longer (N2): the other
 * document by its title only when the server gave it, else "another document".
 */
import type { TFunction } from 'i18next'

import type { DocumentEvent } from '../api/client'
import i18n, { changeLanguage } from '../i18n'
import { plain } from '../test/harness'
import { eventWhat, eventWho, standsAlone } from './events'

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
    // A reason this page does not know is still a sentence.
    expect(line('link_also_left', { document: null, reason: 'odd' })).toBe('hat es aus dem Link eines anderen Dokuments genommen')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    expect(line('link_also_shown', { document: 5, title: 'Invoice', days: 7 })).toBe('showed it with a link of Invoice')
  })
})

describe('a further document deleted for good', () => {
  /** The whole line as the history shows it: the name in front only when the line does not stand alone. */
  const whole = (detail: Record<string, unknown>, by: DocumentEvent['by'] = null) => {
    const event = { id: 1, at: '2026-11-12T08:00:00Z', action: 'link_also_gone', by, by_link: '', detail } as DocumentEvent
    const t = i18n.t.bind(i18n) as TFunction
    return plain(standsAlone(event) ? eventWhat(event, t, context) : `${eventWho(event, t)} ${eventWhat(event, t, context)}`)
  }

  it('is a sentence of its own, without "nexpaper" in front', () => {
    expect(whole({ document: null, reason: 'purged' })).toBe('Ein mitgezeigtes Dokument wurde endgültig gelöscht und wird über den Link nicht mehr gezeigt.')
    // Taken out by a person, the person stays in front.
    expect(whole({ document: 8, title: 'Lieferschein', reason: 'taken_out' }, { id: 1, name: 'jule', display_name: 'Jule' })).toBe('Jule hat Lieferschein aus einem Link genommen')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    expect(whole({ document: null, reason: 'purged' })).toBe('A document shown through a link was deleted for good and is no longer shown through it.')
  })
})