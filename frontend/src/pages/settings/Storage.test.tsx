/**
 * Settings, Storage: the limits on what comes in are shown with their values, changed with one Save (only what changed is
 * sent), refused on the page when a number is out of its range; the disk card shows how the files lie (the queue is on
 * the card of the text recognition, `Ocr.test.tsx`).
 */
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { DiskCard, LimitsCard } from './StorageCards'

const server = new Server()
const page = new Page()

const settings = {
  public_url: '', password_login: true, two_factor_required: true, oidc_second_factor_by_provider: false, backup_schedule: 'daily', backup_keep: 7,
  smtp_host: '', smtp_port: 587, smtp_security: 'starttls', smtp_user: '', smtp_password_set: false, smtp_from: '', api_keys_allowed: false, update_check: true,
  links_allowed: true, link_max_days: 30, upload_max_mb: 200, upload_max_pages: 2000, upload_max_megapixels: 100, upload_open_count: 10, upload_open_mb: 4096,
  process_timeout_seconds: 300, process_memory_mb: 2048, cache_max_mb: 1024,
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/settings': settings }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

function field(label: string): HTMLInputElement {
  const input = [...document.querySelectorAll<HTMLLabelElement>('label')].find((l) => l.textContent?.startsWith(label))?.querySelector('input')
  expect(input, label).toBeTruthy()
  return input!
}

describe('the limits', () => {
  it('show the numbers the server has, with the words of the card', async () => {
    await page.show(<LimitsCard />)
    expect(page.text).toContain('Hochladen und Grenzen')
    expect(field('Größe einer Datei (MB)').value).toBe('200')
    expect(field('Seiten je Dokument').value).toBe('2000')
    expect(field('Bildpunkte je Bild (Millionen)').value).toBe('100')
    expect(field('Offene Uploads je Konto').value).toBe('10')
    expect(field('Offene Bytes je Konto (MB)').value).toBe('4096')
    expect(field('Zeit je Dokument (Sekunden)').value).toBe('300')
    expect(field('Arbeitsspeicher je Dokument (MB)').value).toBe('2048')
    expect(field('Zwischenspeicher für Seitenbilder (MB)').value).toBe('1024')
    expect(page.text).toContain('0 heißt: keine Grenze, sonst mindestens 256.')
  })

  it('send only what was changed, on Save', async () => {
    server.answers['PUT /api/v1/settings'] = { ...settings, upload_max_mb: 50, process_timeout_seconds: 120 }
    await page.show(<LimitsCard />)
    await page.type(field('Größe einer Datei (MB)'), '50')
    await page.type(field('Zeit je Dokument (Sekunden)'), '120')
    // Typed, but the same as it was: not sent.
    await page.type(field('Seiten je Dokument'), '2001')
    await page.type(field('Seiten je Dokument'), '2000')
    await page.click(page.button('Speichern'))
    expect(server.called('PUT', '/api/v1/settings')!.body).toEqual({ upload_max_mb: 50, process_timeout_seconds: 120 })
    expect(page.text).toContain('Gespeichert.')
    expect(field('Größe einer Datei (MB)').value).toBe('50')
  })

  it('send nothing when nothing changed', async () => {
    await page.show(<LimitsCard />)
    await page.click(page.button('Speichern'))
    expect(server.changes()).toEqual([])
  })

  it.each([['Größe einer Datei (MB)', '0'], ['Größe einer Datei (MB)', '10241'], ['Seiten je Dokument', 'viele'], ['Offene Uploads je Konto', '2,5'], ['Zeit je Dokument (Sekunden)', '4'], ['Arbeitsspeicher je Dokument (MB)', '-1'], ['Arbeitsspeicher je Dokument (MB)', '100'], ['Zwischenspeicher für Seitenbilder (MB)', '63']])(
    'refuse %s = %s on the page, without asking the server',
    async (label, value) => {
      await page.show(<LimitsCard />)
      await page.type(field(label), value)
      await page.click(page.button('Speichern'))
      expect(page.text).toContain('Die Zahlen müssen in den erlaubten Bereich fallen.')
      expect(server.changes()).toEqual([])
    },
  )

  it('take 0 for the memory (no limit)', async () => {
    server.answers['PUT /api/v1/settings'] = { ...settings, process_memory_mb: 0 }
    await page.show(<LimitsCard />)
    await page.type(field('Arbeitsspeicher je Dokument (MB)'), '0')
    await page.click(page.button('Speichern'))
    expect(server.called('PUT', '/api/v1/settings')!.body).toEqual({ process_memory_mb: 0 })
  })

  it('show the answer of the server when it refuses', async () => {
    server.fails['PUT /api/v1/settings'] = { status: 422, code: 'invalid_input' }
    await page.show(<LimitsCard />)
    await page.type(field('Größe einer Datei (MB)'), '50')
    await page.click(page.button('Speichern'))
    expect(document.querySelector('[role="alert"]')!.textContent).toContain('Die Eingabe ist nicht gültig')
    expect(field('Größe einer Datei (MB)').value).toBe('200')
  })

  it('are in English too', async () => {
    await changeLanguage('en', false)
    await page.show(<LimitsCard />)
    expect(page.text).toContain('Uploading and limits')
    expect(field('Size of one file (MB)').value).toBe('200')
    expect(page.button('Save')).toBeTruthy()
  })
})

describe('the disk', () => {
  it('shows how the files lie on the disk, readable without nexpaper', async () => {
    await page.show(<DiskCard />)
    expect(page.text).toContain('Lesbar, auch ohne nexpaper.')
    expect(page.text).toContain('/data/dokumente/Haushalt/2026/Stadtwerke Lindenau/2026-10-01 Rechnung.jpg')
    expect(page.text).toContain('Originale werden nie verändert')
  })
})
