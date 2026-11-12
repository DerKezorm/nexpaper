/** The history of a document from an upload request names the request, never the person it belongs to (U1). */
import type { TFunction } from 'i18next'

import type { DocumentEvent } from '../api/client'
import i18n, { changeLanguage } from '../i18n'
import { plain } from '../test/harness'
import { eventWhat, eventWho } from './events'

const context = { people: new Map(), vaults: new Map(), sourceText: (s: string) => (s === 'request' ? 'Upload-Link' : s) }
const created = { id: 1, at: '2026-11-12T08:00:00Z', action: 'created', by: null, by_link: 'Kanzlei Weber', detail: { source: 'request', from: 'Kanzlei Weber' } } as DocumentEvent
const line = () => plain(`${eventWho(created, i18n.t.bind(i18n) as TFunction)} ${eventWhat(created, i18n.t.bind(i18n) as TFunction, context)}`)

describe('a document from an upload request in the history', () => {
  it('says it came through the request', async () => {
    await changeLanguage('de', false)
    expect(line()).toBe('Jemand über die Upload-Bitte „Kanzlei Weber“ hat es angelegt: upload-Link')
  })

  it('a link to a document stays a link', async () => {
    await changeLanguage('de', false)
    const opened = { ...created, action: 'link_opened', detail: null } as DocumentEvent
    expect(plain(eventWho(opened, i18n.t.bind(i18n) as TFunction))).toBe('Jemand über den Link für „Kanzlei Weber“')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    expect(line()).toContain('Somebody through the upload request “Kanzlei Weber”')
  })
})
