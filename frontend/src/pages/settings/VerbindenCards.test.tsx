/**
 * verbinden 0.1.13: nexpaper shows a card for nexfolk under My account › Connections (nexfolk asks how many documents
 * are from a contact, `documents.about`), and the card says what nexfolk sends for it (V53).
 */
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { VERBINDEN_TEXTS } from '../../vendor/nexverbinden'
import { OtherApps } from './VerbindenCards'

const server = new Server()
const page = new Page()

const nexfolk = {
  partner: 'nexfolk', state: 'none', address: 'https://folk.example.com', address_from_operator: true, set_up: true,
  host: 'folk.example.com', uses: [], grants: ['documents.about'], uses_levels: {}, grants_levels: { 'documents.about': 'read' },
  account: null, since: null, ok_at: null, used_at: null, stale_since: null, problem: null, areas_used: null,
  areas_granted: null, legacy: null, areas_choice: [{ id: 1, name: 'Kim' }], version: null, sends_person: false,
  receives_person: true,
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/connect/partners': [nexfolk] }
  server.install()
})

afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

it('shows a card for nexfolk that says what nexfolk sends about a contact', async () => {
  await page.show(<OtherApps operator={false} />)
  expect(page.text).toContain('nexfolk')
  // The card stands closed; its head names nexfolk and opens it.
  await page.click([...document.querySelectorAll<HTMLButtonElement>('button[aria-expanded]')].find((b) => b.textContent?.includes('nexfolk')))
  const said = document.querySelector('[data-testid="connection-receives-person"]')
  expect(said?.textContent).toBe(VERBINDEN_TEXTS.de.card.receivesPerson.replaceAll('{partner}', 'nexfolk').replaceAll('{app}', 'nexpaper'))
  expect(page.text).toContain(VERBINDEN_TEXTS.de.purposes.nexpaper['documents.about'])
})
