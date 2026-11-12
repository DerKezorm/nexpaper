/**
 * Asking for a document (U1), the person's side: the dialog makes an address and copies it, says what is missing when
 * the operator has requests off or the server no public address, lists the own requests, and withdraws one only after
 * asking.
 */
import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { UploadRequestButton } from './UploadRequests'

const server = new Server()
const page = new Page()

const rules = { allowed: true, public_url_set: true, max_days: 30, max_files: 50, default_files: 10, max_open: 20 }
const one = { id: 7, name: 'Kanzlei Weber', until: '2026-11-19T09:00:00Z', max_files: 10, received: 3, last_used_at: '2026-11-12T10:00:00Z', created_at: '2026-11-12T09:00:00Z', status: 'active' }

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/upload-requests/rules': rules, 'GET /api/v1/upload-requests': [one] }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

async function openDialog() {
  await page.show(<UploadRequestButton />)
  await page.click(page.button('Um ein Dokument bitten'))
}

describe('asking for a document', () => {
  it('makes an address with the name, the days and the number of files', async () => {
    server.answers['POST /api/v1/upload-requests'] = { ...one, id: 8, name: 'Hausverwaltung', received: 0, url: 'https://paper.example.com/u/upr_made' }
    await openDialog()
    expect(page.text).toContain('3 von 10 Dateien angekommen')
    await page.type(document.querySelector<HTMLInputElement>('input[placeholder="zum Beispiel Kanzlei Weber"]'), 'Hausverwaltung')
    await page.click(page.button('Adresse erstellen'))
    const made = server.called('POST', '/api/v1/upload-requests')!
    expect(made.body).toMatchObject({ name: 'Hausverwaltung', max_files: 10 })
    expect(Number(made.body!.days)).toBeGreaterThanOrEqual(6)
    expect(document.querySelector<HTMLInputElement>('[data-testid="request-made"] input')!.value).toBe('https://paper.example.com/u/upr_made')
  })

  it('says why no request can be made while they are off or the server has no public address', async () => {
    server.answers['GET /api/v1/upload-requests/rules'] = { ...rules, allowed: false }
    await openDialog()
    expect(document.querySelector('[data-testid="request-blocked"]')!.textContent).toContain('ausgeschaltet')
    expect(page.button('Adresse erstellen')).toBeUndefined()
    page.close()
    server.answers['GET /api/v1/upload-requests/rules'] = { ...rules, public_url_set: false }
    await openDialog()
    expect(document.querySelector('[data-testid="request-blocked"]')!.textContent).toContain('öffentliche Adresse')
  })

  it('withdraws a request only after asking', async () => {
    await openDialog()
    await page.click(document.querySelector<HTMLButtonElement>('button[aria-label="Bitte an Kanzlei Weber zurückziehen"]'))
    expect(server.changes()).toEqual([])
    const dialogs = document.querySelectorAll('[role="dialog"]')
    const asked = dialogs[dialogs.length - 1] as HTMLElement
    expect(asked.textContent).toContain('Zurückholen lässt sich die Bitte nicht')
    await page.click(page.button('Zurückziehen', asked))
    expect(server.changes()).toEqual(['DELETE /api/v1/upload-requests/7'])
  })

  it('copies the address of an open request again', async () => {
    server.answers['POST /api/v1/upload-requests/7/address'] = { url: 'https://paper.example.com/u/upr_again' }
    await openDialog()
    await page.click(document.querySelector<HTMLButtonElement>('button[aria-label="Adresse für Kanzlei Weber kopieren"]'))
    expect(server.changes()).toEqual(['POST /api/v1/upload-requests/7/address'])
  })
})
