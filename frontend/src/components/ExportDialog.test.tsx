/**
 * The export dialog against a stand-in of the server: the words of the dialog, the period and the vaults it starts with,
 * the server's count (with the person's rights) replacing the archive's, the tree of the ZIP, what goes in, the ZIP and
 * the link for the tax adviser, the operator's switch for links, refusals, and the person's exports below.
 */
import type { ExportInfo, ExportPreview } from '../api/client'
import { changeLanguage } from '../i18n'
import { treeOf } from '../lib/tree'
import { Page, Server } from '../test/harness'
import { ExportDialog } from './ExportDialog'

const auth = { status: 'signedIn', me: { id: 1, name: 'jule' }, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('../state/auth', () => ({ useAuth: () => auth, safeNext: (next: string | null) => next ?? '/' }))

const server = new Server()
const page = new Page()
const say = vi.fn()
const close = vi.fn()

const vault = (id: number, name: string, personal: number | null, icon = 'folder') => ({ id, name, icon, personal_of: personal, my_right: 'manage', documents: 3, size: 0, members: [] })
const VAULTS = [vault(1, 'jule', 1, 'user'), vault(7, 'Ferienwohnung', null, 'home')]
const PREVIEW: ExportPreview = {
  documents: 341, total: 1841260, totals: { EUR: 1841260 }, size: 1_900_000_000, too_many: false, max_documents: 20000, max_bytes: 20 * 1024 ** 3,
  sample: [
    'Ferienwohnung/2026/Elektro Brandt GmbH/2026-10-06 Rechnung Heizungswartung.pdf',
    'Ferienwohnung/2026/Elektro Brandt GmbH/2026-10-06 Rechnung Heizungswartung.xml',
    'Ferienwohnung/2026/Glanzwerk Reinigungsservice/2026-09-30 Endreinigung September.pdf',
    'liste.csv',
  ],
}
const PREVIEW_URL = '/api/v1/exports/preview?vault_ids=7&date_from=2026-01-01&date_to=2026-12-31&pdf=true&original=false&csv=true&xml=true'
const BOTH_URL = '/api/v1/exports/preview?vault_ids=7&vault_ids=1&date_from=2026-01-01&date_to=2026-12-31&pdf=true&original=false&csv=true&xml=true'

function made(over: Partial<ExportInfo> = {}): ExportInfo {
  return {
    id: 4, state: 'ready', documents: 341, size: 1_900_000_000, total: 1841260, error: '', date_from: '2026-01-01', date_to: '2026-12-31', vault_ids: [7],
    content: { pdf: true, original: false, csv: true, xml: true }, created_at: '2026-10-09T10:00:00Z', finished_at: '2026-10-09T10:02:00Z',
    expires_at: '2026-10-16T10:02:00Z', links: [], ...over,
  }
}

function open(filters = { vault_id: 7 }) {
  return page.show(<ExportDialog onClose={close} filters={filters} count={12} sum={4500} say={say} today={new Date('2026-10-10T12:00:00Z')} previewDelay={0} />)
}

/** The text of the page with the narrow spaces of number formats as plain ones. */
function plain(): string {
  return page.text.replace(/[\u00a0\u202f]/g, ' ')
}

/** The count is asked for after a turn of the timer (no wait in the tests): one turn, then every answer. */
async function settle() {
  await page.click(document.body)
  await page.click(document.body)
}

beforeEach(async () => {
  await changeLanguage('de', false)
  say.mockClear()
  close.mockClear()
  server.answers = {
    'GET /api/v1/vaults': VAULTS,
    'GET /api/v1/sharing': { links_allowed: true, link_max_days: 30 },
    'GET /api/v1/exports': [],
    [`GET ${PREVIEW_URL}`]: PREVIEW,
    [`GET ${BOTH_URL}`]: { ...PREVIEW, documents: 400 },
    'POST /api/v1/exports': { ...made({ state: 'queued' }), link: null },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the export dialog', () => {
  it('shows its words and starts from the archive', async () => {
    await open()
    for (const words of [
      'Exportieren', 'Ein ZIP für den Steuerberater oder fürs eigene Archiv. Die Ordner darin heißen wie in nexpaper: Tresor, Jahr, Absender.',
      'Von', 'Bis', 'Tresore', 'Mein Tresor', 'Ferienwohnung', 'Inhalt', 'Durchsuchbare PDFs', 'mit Textschicht, so wie in nexpaper',
      'Originale dazu', 'die Dateien genau so, wie sie hereinkamen', 'Liste als CSV', 'Datum, Titel, Absender, Art, Betrag, Währung, Rechnungsnummer, Tresor, Datei',
      'E-Rechnungen als XML', 'E-Rechnungen, die als XML hereinkamen, für die Buchhaltung', 'Im ZIP', 'Als Link freigeben statt herunterladen',
      'Der Steuerberater lädt das ZIP selbst, ohne Konto. Gilt 30 Tage, du siehst, wann er es geöffnet hat.', 'Abbrechen', 'ZIP erstellen',
    ]) {
      expect(page.text, words).toContain(words)
    }
    const dates = [...document.querySelectorAll<HTMLInputElement>('input[type="date"]')].map((i) => i.value)
    expect(dates).toEqual(['2026-01-01', '2026-12-31'])
    const pressed = [...document.querySelectorAll<HTMLButtonElement>('button[aria-pressed]')].map((b) => [b.textContent?.trim(), b.getAttribute('aria-pressed')])
    expect(pressed).toEqual([['Mein Tresor', 'false'], ['Ferienwohnung', 'true']])
  })

  it('shows the archive count first, then the server count, the sum, the size and the tree', async () => {
    // Before the server has counted: the archive's number and sum.
    await page.show(<ExportDialog onClose={close} filters={{ vault_id: 7 }} count={12} sum={4500} today={new Date('2026-10-10T12:00:00Z')} previewDelay={600_000} />)
    expect(page.text).toContain('12 Dokumente')
    expect(plain()).toContain('Summe der Beträge 45,00 €')
    page.close()
    await open()
    await settle()
    expect(page.text).toContain('341 Dokumente')
    expect(plain()).toContain('etwa 1,9 GB · Summe der Beträge 18.412,60 €')
    expect(document.querySelector('pre')!.textContent).toBe(treeOf(PREVIEW.sample))
    expect(document.querySelector('pre')!.textContent).toContain('Ferienwohnung/\n  2026/\n    Elektro Brandt GmbH/\n      2026-10-06 Rechnung Heizungswartung.pdf')
  })

  it('sums each currency on its own', async () => {
    server.answers[`GET ${PREVIEW_URL}`] = { ...PREVIEW, totals: { CHF: 12000, EUR: 1841260 }, total: 1853260 }
    await open()
    await settle()
    expect(plain()).toMatch(/Summe der Beträge (CHF 120,00|120,00 CHF) \+ 18\.412,60 €/)
  })

  it('counts again when a vault is added', async () => {
    await open()
    await settle()
    await page.click(page.button('Mein Tresor'))
    await settle()
    expect(server.called('GET', BOTH_URL)).toBeTruthy()
    expect(page.text).toContain('400 Dokumente')
  })

  it('makes the ZIP with what was chosen and says so', async () => {
    server.answers[`GET /api/v1/exports/preview?vault_ids=7&date_from=2026-01-01&date_to=2026-12-31&q=wartung&sender=Elektro+Brandt+GmbH&pdf=true&original=false&csv=true&xml=true`] = PREVIEW
    await open({ vault_id: 7, sender: 'Elektro Brandt GmbH', q: 'wartung' } as never)
    await settle()
    expect(page.text).toContain('Dazu gelten die Filter des Archivs.')
    await page.click(document.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[1])
    await page.click(page.button('ZIP erstellen'))
    expect(server.called('POST', '/api/v1/exports')!.body).toEqual({
      sender: 'Elektro Brandt GmbH', q: 'wartung', date_from: '2026-01-01', date_to: '2026-12-31', vault_ids: [7],
      content: { pdf: true, original: true, csv: true, xml: true },
    })
    expect(say).toHaveBeenCalledWith('Das ZIP wird gepackt. Du bekommst Bescheid, wenn es fertig ist.')
    expect(close).toHaveBeenCalled()
  })

  it('makes a link for the tax adviser and copies it', async () => {
    const copied: string[] = []
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: async (text: string) => void copied.push(text) }, configurable: true })
    server.answers['POST /api/v1/exports'] = { ...made({ state: 'queued' }), link: { id: 2, recipient: 'Steuerbüro Lindenau', token: 'lnx_made', url: 'https://paper.example.com/x/lnx_made', until: '2026-11-09T10:00:00Z', opened_count: 0, last_opened_at: null, created_at: '2026-10-10T10:00:00Z', revoked_at: null, status: 'active' } }
    await open()
    await settle()
    const asLink = [...document.querySelectorAll<HTMLLabelElement>('label')].find((l) => l.textContent?.startsWith('Als Link freigeben'))!.querySelector('input')
    await page.click(asLink)
    const recipient = [...document.querySelectorAll<HTMLLabelElement>('label')].find((l) => l.textContent?.startsWith('Für wen'))!.querySelector('input')!
    expect(recipient.value).toBe('Steuerberater')
    await page.type(recipient, 'Steuerbüro Lindenau')
    await page.click(page.button('Link anlegen'))
    expect(server.called('POST', '/api/v1/exports')!.body!.link).toEqual({ recipient: 'Steuerbüro Lindenau', days: 30 })
    expect(copied).toEqual(['https://paper.example.com/x/lnx_made'])
    expect(say).toHaveBeenCalledWith('Link angelegt und kopiert. Das ZIP wird im Hintergrund gepackt.')
  })

  it('offers no link while the operator has links switched off', async () => {
    server.answers['GET /api/v1/sharing'] = { links_allowed: false, link_max_days: 30 }
    await open()
    expect(page.text).not.toContain('Als Link freigeben statt herunterladen')
    expect(page.text).toContain('Links nach außen sind auf diesem Server abgeschaltet.')
  })

  it('says a refusal and stays open', async () => {
    server.fails['POST /api/v1/exports'] = { status: 409, code: 'export_busy', values: { max: 3 } }
    await open()
    await settle()
    await page.click(page.button('ZIP erstellen'))
    expect(page.text).toContain('Warte, bis deine Exporte gepackt sind.')
    expect(close).not.toHaveBeenCalled()
  })

  it('cannot make a ZIP without a vault or over the limit', async () => {
    server.answers[`GET ${PREVIEW_URL}`] = { ...PREVIEW, too_many: true }
    await open()
    await settle()
    expect(page.text).toContain('Zu viel für ein ZIP: höchstens 20.000 Dokumente und 20 GB.')
    expect(page.button('ZIP erstellen')!.disabled).toBe(true)
    await page.click(page.button('Ferienwohnung'))
    expect(page.button('ZIP erstellen')!.disabled).toBe(true)
  })

  it('lists the exports with download, the link and how often it was opened', async () => {
    server.answers['GET /api/v1/exports'] = [
      made({ links: [{ id: 2, recipient: 'Steuerbüro', until: '2026-11-09T10:00:00Z', opened_count: 2, last_opened_at: '2026-10-09T15:00:00Z', created_at: '2026-10-09T10:00:00Z', revoked_at: null, status: 'active' }] }),
      made({ id: 5, state: 'failed', error: 'nothing_found', documents: 0, size: 0 }),
    ]
    server.answers['POST /api/v1/exports/4/links/2/address'] = { url: 'https://paper.example.com/x/lnx_again' }
    server.answers['DELETE /api/v1/exports/5'] = 204
    await open()
    expect(page.text).toContain('Deine Exporte')
    expect(page.text).toContain('09.10.2026 · 341 Dokumente · 1,9 GB · liegt bis 16.10.2026')
    expect(page.text).toContain('Steuerbüro: 2× geöffnet, zuletzt 09.10.2026')
    expect(page.text).toContain('fehlgeschlagen')
    expect(page.text).toContain('keine passenden Dokumente')
    expect(document.querySelector<HTMLAnchorElement>('a[href="/api/v1/exports/4/file"]')).toBeTruthy()
    await page.click(page.button('Link kopieren'))
    expect(server.called('POST', '/api/v1/exports/4/links/2/address')).toBeTruthy()
    // A link to an export is withdrawn after asking, too.
    server.answers['DELETE /api/v1/exports/4/links/2'] = 204
    await page.click(page.button('Link zurückziehen'))
    expect(server.called('DELETE', '/api/v1/exports/4/links/2')).toBeUndefined()
    await page.inDialog('Abbrechen')
    expect(server.called('DELETE', '/api/v1/exports/4/links/2')).toBeUndefined()
    await page.click(page.button('Link zurückziehen'))
    await page.inDialog('Link zurückziehen')
    expect(server.called('DELETE', '/api/v1/exports/4/links/2')).toBeTruthy()
    await page.click(document.querySelectorAll<HTMLButtonElement>('button[aria-label="Export löschen"]')[1])
    expect(server.called('DELETE', '/api/v1/exports/5')).toBeUndefined()
    await page.inDialog('Export löschen')
    expect(server.called('DELETE', '/api/v1/exports/5')).toBeTruthy()
  })
})

describe('the tree of the ZIP', () => {
  it('names every folder once', () => {
    expect(treeOf(['a/2026/x/1.pdf', 'a/2026/x/2.pdf', 'a/2026/y/3.pdf', 'b/2025/z/4.pdf', 'liste.csv'])).toBe(
      'a/\n  2026/\n    x/\n      1.pdf\n      2.pdf\n    y/\n      3.pdf\nb/\n  2025/\n    z/\n      4.pdf\nliste.csv',
    )
  })
})
