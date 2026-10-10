/** The places of the page tools: the proposal to split shows itself only for a document that has one. */
import type { DocumentInfo } from '../api/client'
import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { SplitPanelSlot } from './pageToolSlots'

const server = new Server()
const page = new Page()
const stack = { id: 5, title: 'Stapelscan', pages: 3, current_version: 1, source: 'folder', split_suggested: false } as DocumentInfo

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/documents/5/separators': { version: 1, checked: true, blank_pages: [2], parts: [[1], [3]], duplex: false, dismissed: false, suggested: true } }
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the place of the split panel', () => {
  it('stays empty for a document without a proposal and shows the panel for one with', async () => {
    await page.show(<SplitPanelSlot document={stack} onDone={vi.fn()} />)
    expect(page.text).toBe('')
    expect(server.calls).toHaveLength(0)
    page.close()
    await page.show(<SplitPanelSlot document={{ ...stack, split_suggested: true }} onDone={vi.fn()} />)
    expect(page.text).toContain('Stapelscan aufteilen?')
  })
})
