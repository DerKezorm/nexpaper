/**
 * The notice at a document that a link of another document shows too (N2): to whom, until when, through which document
 * (or "another document"), and taking it out only after asking.
 */
import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { ShownThroughNotice } from './ShownThrough'

const server = new Server()
const page = new Page()
const say = vi.fn()

const entry = (over: Record<string, unknown> = {}) => ({
  id: 31, recipient: 'Steuerbüro', until: '2026-11-30T10:00:00Z', created_by: null, document_id: 5, document_title: 'Rechnung Oktober', ...over,
})

function open(canShare = true) {
  return page.show(<ShownThroughNotice document={{ id: 8, title: 'Lieferschein', can_share: canShare }} say={say} />)
}

beforeEach(async () => {
  await changeLanguage('de', false)
  say.mockClear()
  server.answers = { 'GET /api/v1/documents/8/shown-through': [entry(), entry({ id: 32, recipient: 'Bank', document_id: null, document_title: null })] }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('shown through the link of another document', () => {
  it('names to whom, until when and through which document, or another one', async () => {
    await open()
    expect(page.text).toContain('Auch über einen anderen Link sichtbar')
    expect(page.text).toContain('Für Steuerbüro über den Link an „Rechnung Oktober“, bis 30.11.2026')
    expect(page.text).toContain('Für Bank über den Link an einem anderen Dokument, bis 30.11.2026')
  })

  it('takes it out only after asking, and says that only a new link shows it again', async () => {
    server.answers['DELETE /api/v1/documents/8/shown-through/31'] = 204
    await open()
    await page.click(page.button('Aus dem Link für Steuerbüro herausnehmen'))
    expect(server.changes()).toEqual([])
    expect(page.dialog!.textContent).toContain('Wieder zeigen lässt es sich nur über einen neuen Link.')
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Aus dem Link für Steuerbüro herausnehmen'))
    server.answers['GET /api/v1/documents/8/shown-through'] = [entry({ id: 32, recipient: 'Bank', document_id: null, document_title: null })]
    await page.inDialog('Herausnehmen')
    expect(server.changes()).toEqual(['DELETE /api/v1/documents/8/shown-through/31'])
    expect(say).toHaveBeenCalledWith('Aus dem Link genommen.')
    expect(page.text).not.toContain('Steuerbüro')
  })

  it('shows nothing and asks nothing for who may not see the links', async () => {
    await open(false)
    expect(page.text).toBe('')
    expect(server.calls).toEqual([])
  })

  it('shows nothing when no other link shows it', async () => {
    server.answers['GET /api/v1/documents/8/shown-through'] = []
    await open()
    expect(document.querySelector('[data-testid="shown-through"]')).toBeNull()
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    await open()
    expect(page.text).toContain('For Steuerbüro through the link of “Rechnung Oktober”, until')
  })
})
