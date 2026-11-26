/**
 * Server › General, the card "Grenzen": the limits on what comes in are shown with their values; the size of one file
 * has its own field with its own Save (`Field action`) as in nexnotes, the card's line on where one account's limit is
 * set (E48), the further limits one Save below (each sends only what changed in its part),
 * refused on the page when a number is out of its range. Settings, Storage: the disk card shows how the files lie (the
 * queue is on the card of the text recognition, `Ocr.test.tsx`).
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

/** The Save of the row of one file, and the Save of the further limits. */
function save(part: 'file' | 'more', name = 'Speichern'): HTMLButtonElement | undefined {
  return page.button(name, document.querySelector(`[data-testid="limit-${part}"]`)!)
}

/** A field of the kit by its label (joined by `for`). */
function field(label: string): HTMLInputElement {
  const named = [...document.querySelectorAll<HTMLLabelElement>('label')].find((l) => l.textContent?.startsWith(label))
  const input = named ? (document.getElementById(named.htmlFor) as HTMLInputElement | null) : null
  expect(input, label).toBeTruthy()
  return input!
}

describe('the limits', () => {
  it('show the numbers the server has, with the words of the card', async () => {
    await page.show(<LimitsCard />)
    expect(page.text).toContain('Grenzen')
    // The size of one file stands in the row of its own, as in nexnotes; the others below it.
    expect(document.querySelector('[data-testid="limit-file"]')!.contains(field('Größe einer Datei (MB)'))).toBe(true)
    expect(document.querySelector('[data-testid="limit-more"]')!.contains(field('Seiten je Dokument'))).toBe(true)
    expect(field('Größe einer Datei (MB)').value).toBe('200')
    expect(field('Seiten je Dokument').value).toBe('2000')
    expect(field('Bildpunkte je Bild (Millionen)').value).toBe('100')
    expect(field('Offene Uploads je Konto').value).toBe('10')
    expect(field('Offene Bytes je Konto (MB)').value).toBe('4096')
    expect(field('Zeit je Dokument (Sekunden)').value).toBe('300')
    expect(field('Arbeitsspeicher je Dokument (MB)').value).toBe('2048')
    expect(field('Zwischenspeicher für Seitenbilder (MB)').value).toBe('1024')
    expect(page.text).toContain('0 heißt: keine Grenze, sonst mindestens 256.')
    // The card of the kit, and the Save of one file level with its field (plan "Einstellungen", Allgemein 1).
    expect(document.querySelector('[data-card="limits"]')).toBeTruthy()
    expect(save('file')!.closest('[data-part="field-action"]')!.contains(field('Größe einer Datei (MB)'))).toBe(true)
    expect([save('file')!.dataset.kind, save('more')!.dataset.kind]).toEqual(['secondary', 'secondary'])
    // E48: the card's line says what nexpaper takes in, then where the limit of one account is set, once.
    expect(document.querySelector('[data-card="limits"] h2 + p')!.textContent).toBe(
      'Was nexpaper annimmt. Gilt für Browser, Handy und Apps, ab der nächsten Datei. Die Grenze eines Kontos setzt du unter Server › Konten › Verwalten.',
    )
    expect(document.querySelector('[data-card="limits"]')!.textContent!.split('Server › Konten › Verwalten').length).toBe(2)
  })

  it('send only what was changed, each Save its own part', async () => {
    server.answers['PUT /api/v1/settings'] = { ...settings, process_timeout_seconds: 120, upload_open_count: 12 }
    await page.show(<LimitsCard />)
    await page.type(field('Zeit je Dokument (Sekunden)'), '120')
    await page.type(field('Offene Uploads je Konto'), '12')
    // Typed, but the same as it was: not sent.
    await page.type(field('Seiten je Dokument'), '2001')
    await page.type(field('Seiten je Dokument'), '2000')
    // Typed in the row of one file, but saved with the other button: not sent by this one.
    await page.type(field('Größe einer Datei (MB)'), '50')
    await page.click(save('more'))
    expect(server.called('PUT', '/api/v1/settings')!.body).toEqual({ process_timeout_seconds: 120, upload_open_count: 12 })
    expect(page.text).toContain('Gespeichert.')
    expect(field('Zeit je Dokument (Sekunden)').value).toBe('120')
    // The size of one file waits for its own button, and goes alone.
    expect(field('Größe einer Datei (MB)').value).toBe('50')
    server.answers['PUT /api/v1/settings'] = { ...settings, process_timeout_seconds: 120, upload_open_count: 12, upload_max_mb: 50 }
    await page.click(save('file'))
    expect(server.calls.filter((c) => c.method === 'PUT').at(-1)!.body).toEqual({ upload_max_mb: 50 })
    expect(field('Größe einer Datei (MB)').value).toBe('50')
  })

  it('send nothing when nothing changed', async () => {
    await page.show(<LimitsCard />)
    await page.click(save('file'))
    await page.click(save('more'))
    expect(server.changes()).toEqual([])
  })

  it.each([['Größe einer Datei (MB)', '0'], ['Größe einer Datei (MB)', '10241'], ['Seiten je Dokument', 'viele'], ['Offene Uploads je Konto', '2,5'], ['Zeit je Dokument (Sekunden)', '4'], ['Arbeitsspeicher je Dokument (MB)', '-1'], ['Arbeitsspeicher je Dokument (MB)', '100'], ['Zwischenspeicher für Seitenbilder (MB)', '63']])(
    'refuse %s = %s on the page, without asking the server',
    async (label, value) => {
      await page.show(<LimitsCard />)
      await page.type(field(label), value)
      await page.click(save(label.startsWith('Größe einer Datei') ? 'file' : 'more'))
      expect(page.text).toContain('Die Zahlen müssen in den erlaubten Bereich fallen.')
      expect(server.changes()).toEqual([])
    },
  )

  it('take 0 for the memory (no limit)', async () => {
    server.answers['PUT /api/v1/settings'] = { ...settings, process_memory_mb: 0 }
    await page.show(<LimitsCard />)
    await page.type(field('Arbeitsspeicher je Dokument (MB)'), '0')
    await page.click(save('more'))
    expect(server.called('PUT', '/api/v1/settings')!.body).toEqual({ process_memory_mb: 0 })
  })

  it('show the answer of the server when it refuses', async () => {
    server.fails['PUT /api/v1/settings'] = { status: 422, code: 'invalid_input' }
    await page.show(<LimitsCard />)
    await page.type(field('Größe einer Datei (MB)'), '50')
    await page.click(save('file'))
    expect(document.querySelector('[role="alert"]')!.textContent).toContain('Die Eingabe ist nicht gültig')
    expect(field('Größe einer Datei (MB)').value).toBe('200')
  })

  it('are in English too', async () => {
    await changeLanguage('en', false)
    await page.show(<LimitsCard />)
    expect(page.text).toContain('Limits')
    expect(field('Size of one file (MB)').value).toBe('200')
    expect(save('file', 'Save')).toBeTruthy()
    expect(save('more', 'Save')).toBeTruthy()
  })
})

describe('the storage for new accounts (Bauplan E44)', () => {
  const GB = 1024 ** 3
  const own = () => page.button('Speichern', document.querySelector('[data-testid="limit-new-accounts"]')!)!

  it('stands in "Grenzen" in GB with its own Save level with it, the place of one account\'s limit in the card\'s line', async () => {
    server.answers['GET /api/v1/settings'] = { ...settings, new_account_storage_limit: 5 * GB }
    await page.show(<LimitsCard />)
    const input = field('Speicher für neue Konten (GB)')
    expect(input.value).toBe('5')
    expect(document.querySelector('[data-testid="limit-new-accounts"]')!.contains(input)).toBe(true)
    expect(own().closest('[data-part="field-action"]')!.contains(input)).toBe(true)
    expect([own().dataset.kind, own().dataset.size, own().dataset.icon]).toEqual(['secondary', 'md', 'Check'])
    const hint = document.getElementById((input.getAttribute('aria-describedby') ?? '').split(' ')[0]!)!
    // The place of one account's limit stands once, in the card's line (E48), not again under the field.
    expect(hint.textContent).toBe('Leer heißt ohne Grenze. Gilt für Konten, die ab jetzt dazukommen.')
  })

  it('sends the GB as bytes, alone, and empty as null', async () => {
    server.answers['PUT /api/v1/settings'] = { ...settings, new_account_storage_limit: Math.round(2.5 * GB) }
    await page.show(<LimitsCard />)
    expect(field('Speicher für neue Konten (GB)').value).toBe('')
    await page.type(field('Größe einer Datei (MB)'), '50')
    await page.type(field('Speicher für neue Konten (GB)'), '2.5')
    await page.click(own())
    expect(server.called('PUT', '/api/v1/settings')!.body).toEqual({ new_account_storage_limit: Math.round(2.5 * GB) })
    expect(field('Speicher für neue Konten (GB)').value).toBe('2.5')
    server.answers['PUT /api/v1/settings'] = { ...settings, new_account_storage_limit: null }
    await page.type(field('Speicher für neue Konten (GB)'), '')
    await page.click(own())
    expect(server.calls.filter((c) => c.method === 'PUT').at(-1)!.body).toEqual({ new_account_storage_limit: null })
    expect(field('Speicher für neue Konten (GB)').value).toBe('')
  })

  it.each(['0', '-1', '20000', '1e9'])('refuses %s on the page, without asking the server', async (value) => {
    await page.show(<LimitsCard />)
    await page.type(field('Speicher für neue Konten (GB)'), value)
    await page.click(own())
    expect(page.text).toContain('Die Zahlen müssen in den erlaubten Bereich fallen.')
    expect(server.changes()).toEqual([])
  })

  it('sends nothing when nothing changed, and is in English and French too', async () => {
    await page.show(<LimitsCard />)
    await page.click(own())
    expect(server.changes()).toEqual([])
    page.close()
    await changeLanguage('en', false)
    await page.show(<LimitsCard />)
    expect(field('Storage for new accounts (GB)')).toBeTruthy()
    expect(page.text).toContain('The limit of one account is set under Server › Accounts › Manage.')
    page.close()
    await changeLanguage('fr', false)
    await page.show(<LimitsCard />)
    expect(field('Espace pour les nouveaux comptes (Go)')).toBeTruthy()
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
