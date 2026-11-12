/**
 * The inbox and upload requests (U1): a document that came through a request says so in the list, not "von dir" (the
 * person it belongs to did not bring it), and the inbox offers "Um ein Dokument bitten".
 */
import { Route, Routes } from 'react-router-dom'

import { changeLanguage } from '../i18n'
import { forgetPictures } from '../lib/pictures'
import { INBOX, Page, Server, inboxOf } from '../test/harness'
import { InboxPage } from './InboxPage'

const auth = { me: { id: 1, name: 'jule', role: 'member' } }
vi.mock('../state/auth', () => ({ useAuth: () => auth }))

const server = new Server()
const page = new Page()

function doc(id: number, title: string, source: string) {
  return {
    id, vault_id: 7, owner: { id: 1, name: 'jule', display_name: 'Jule' }, title, sender: null, kind: null, date: null, amount: null,
    currency: 'EUR', tags: [], dates: [], pages: 1, source, status: 'inbox', added_at: '2026-11-12T08:00:00Z', trashed_at: null,
    trash_ends_at: null, change_seq: id, current_version: 1, my_right: 'manage', via_share: false, can_share: true, notes: 0,
    process_error: '', duplicate: null, suggest: {},
  }
}

beforeEach(async () => {
  forgetPictures()
  await changeLanguage('de', false)
  server.answers = {
    [INBOX]: inboxOf([doc(21, 'Jahresabschluss', 'request'), doc(22, 'Strom', 'upload')]),
    'GET /api/v1/vaults': [{ id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 2, size: 1, members: [] }],
    'GET /api/v1/kinds': [],
    'GET /api/v1/senders': [],
    'GET /api/v1/people': [],
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('upload requests in the inbox', () => {
  it('names a document of a request as such, and one the person brought as theirs', async () => {
    await page.show(<Routes><Route path="eingang" element={<InboxPage />} /></Routes>, '/eingang')
    const rows = [...page.box.querySelectorAll('a[href^="/eingang/"]')].map((a) => a.textContent ?? '')
    const request = rows.find((r) => r.includes('Jahresabschluss'))!
    const own = rows.find((r) => r.includes('Strom'))!
    expect(request).toContain('über eine Upload-Bitte')
    expect(request).not.toContain('von dir')
    expect(own).toContain('von dir')
    expect(page.button('Um ein Dokument bitten')).toBeTruthy()
  })
})
