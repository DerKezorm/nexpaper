/**
 * The cards of the other nex apps (verbinden 0.1.1): one per partner nexpaper has a use with; none for a partner of the
 * catalog without one yet (Bauplan V20: nextasks, nexpaper as its guest is not built).
 */
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { OtherApps, WITHOUT_USE } from './VerbindenCards'

const server = new Server()
const page = new Page()

const view = (partner: string) => ({
  partner, state: 'none', address: '', address_from_operator: false, host: '', uses: [], grants: [], areas_choice: [],
})

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/connect/partners': [view('nexmail'), view('nextasks'), view('nextime')] }
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

it('shows a card for each partner with a use, none for one without (V20)', async () => {
  expect(WITHOUT_USE).toEqual(['nextasks'])
  await page.show(<OtherApps />)
  expect(document.querySelector('[data-testid="connection-nextime"]')).toBeTruthy()
  expect(document.querySelector('[data-testid="connection-nexmail"]')).toBeTruthy()
  expect(document.querySelector('[data-testid="connection-nextasks"]')).toBeNull()
})
