/**
 * The lines of the history about a link for who may not share the document (N2b): the server leaves out for whom the
 * link was made and for how long; the line still says that it was made or opened, through a link, by somebody.
 */
import type { TFunction } from 'i18next'

import type { DocumentEvent } from '../api/client'
import i18n, { changeLanguage } from '../i18n'
import { plain } from '../test/harness'
import { eventWhat, eventWho } from './events'

const context = { people: new Map(), vaults: new Map(), sourceText: (s: string) => s }
const jule = { id: 1, name: 'jule', display_name: 'Jule' }
const event = (over: Partial<DocumentEvent>) => ({ id: 1, at: '2026-11-12T08:00:00Z', action: 'link_opened', by: null, by_link: '', detail: null, ...over }) as DocumentEvent
const say = (e: DocumentEvent) => plain(`${eventWho(e, i18n.t.bind(i18n) as TFunction)} ${eventWhat(e, i18n.t.bind(i18n) as TFunction, context)}`)

beforeEach(async () => {
  await changeLanguage('de', false)
})

describe('a link in the history for who may not share', () => {
  it('says somebody opened it through a link, without a name', () => {
    expect(say(event({ via_link: true }))).toBe('Jemand hat es über einen Link geöffnet')
  })

  it('says a link was made, without the days', () => {
    expect(say(event({ action: 'link_created', by: jule, detail: {} }))).toBe('Jule hat einen Link angelegt')
  })

  it('shows who may share the name and the days as before', () => {
    expect(say(event({ by_link: 'Steuerbüro Kessler', via_link: true }))).toBe('Jemand über den Link für „Steuerbüro Kessler“ hat es geöffnet')
    expect(say(event({ action: 'link_created', by: jule, detail: { days: 7, also: 1 } }))).toBe('Jule hat einen Link für 7 Tage angelegt')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    expect(say(event({ via_link: true }))).toBe('Somebody opened it through a link')
    expect(say(event({ action: 'link_created', by: jule, detail: {} }))).toBe('Jule made a link')
  })
})
