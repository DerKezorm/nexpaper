/**
 * Settings, Storage, the card "Text recognition": the six languages of the server with the chosen ones marked, a change
 * saved at once (in the order of the offer, never the last language off), the two switches, the queue with the pace, and
 * an honest line when the server has no recognition.
 */
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { OcrCard } from './OcrCard'

const server = new Server()
const page = new Page()

const state = {
  languages: ['deu', 'eng'], offered: ['deu', 'eng', 'fra', 'nld', 'pol', 'tur'], straighten: true, blank_pages: true, jobs: 1,
  available: true, running: 1, waiting: 0, seconds_per_page: 4, max_seconds: 3600, long_document_pages: 300,
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/settings/ocr': state }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

function chip(name: string): HTMLButtonElement {
  const found = [...document.querySelectorAll<HTMLButtonElement>('button[aria-pressed]')].find((b) => b.textContent === name)
  expect(found, name).toBeTruthy()
  return found!
}

describe('the card of the text recognition', () => {
  it('shows the words of the mock, the six languages and the queue', async () => {
    await page.show(<OcrCard />)
    expect(page.text).toContain('Texterkennung')
    expect(page.text).toContain('Damit die Suche auch in Fotos und Scans findet. PDFs, die schon Text haben, bleiben, wie sie sind.')
    expect([...document.querySelectorAll('button[aria-pressed]')].map((b) => b.textContent)).toEqual(['Deutsch', 'Englisch', 'Französisch', 'Niederländisch', 'Polnisch', 'Türkisch'])
    expect(chip('Deutsch').getAttribute('aria-pressed')).toBe('true')
    expect(chip('Polnisch').getAttribute('aria-pressed')).toBe('false')
    // Nothing is loaded later: the hint says so instead of the mock's promise.
    expect(page.text).toContain('Diese sechs bringt nexpaper mit, nachgeladen wird nichts.')
    expect(page.text).not.toContain('beim ersten Gebrauch')
    expect(document.querySelector('[data-testid="queue-line"]')!.textContent).toBe(
      '1 Dokument in Arbeit, 0 wartend. Im Schnitt 4 Sekunden je Seite auf diesem Server. Immer nur ein Dokument auf einmal, damit der Rest flüssig bleibt.',
    )
    expect(page.text).not.toContain('Auf diesem Server fehlt die Texterkennung')
  })

  it('saves a language at once, in the order of the offer', async () => {
    server.answers['PUT /api/v1/settings/ocr'] = { ...state, languages: ['deu', 'eng', 'pol'] }
    await page.show(<OcrCard />)
    await page.click(chip('Polnisch'))
    expect(server.called('PUT', '/api/v1/settings/ocr')!.body).toEqual({ languages: ['deu', 'eng', 'pol'] })
    expect(chip('Polnisch').getAttribute('aria-pressed')).toBe('true')
  })

  it('never switches the last language off', async () => {
    server.answers['GET /api/v1/settings/ocr'] = { ...state, languages: ['eng'] }
    await page.show(<OcrCard />)
    await page.click(chip('Englisch'))
    expect(server.called('PUT', '/api/v1/settings/ocr')).toBeUndefined()
    expect(chip('Englisch').getAttribute('aria-pressed')).toBe('true')
  })

  it('saves the switches, and says what the separator pages do', async () => {
    server.answers['PUT /api/v1/settings/ocr'] = { ...state, straighten: false }
    await page.show(<OcrCard />)
    expect(page.text).toContain('Ein Stapelscan wird im Eingang zum Aufteilen vorgeschlagen.')
    const straighten = document.querySelector<HTMLButtonElement>('button[role="switch"][aria-label="Schiefe Seiten gerade richten und drehen"]')
    await page.click(straighten)
    expect(server.called('PUT', '/api/v1/settings/ocr')!.body).toEqual({ straighten: false })
    expect(straighten!.getAttribute('aria-checked')).toBe('false')
  })

  it('goes back to what the server has when saving fails', async () => {
    server.fails['PUT /api/v1/settings/ocr'] = { status: 422, code: 'invalid_input' }
    await page.show(<OcrCard />)
    await page.click(chip('Türkisch'))
    expect(chip('Türkisch').getAttribute('aria-pressed')).toBe('false')
    expect(document.querySelector('[role="alert"]')).toBeTruthy()
  })

  it('says plainly when the server has no recognition, and leaves out the pace before anything was read', async () => {
    server.answers['GET /api/v1/settings/ocr'] = { ...state, available: false, running: 0, waiting: 2, seconds_per_page: null }
    await page.show(<OcrCard />)
    expect(page.text).toContain('Auf diesem Server fehlt die Texterkennung (ocrmypdf und Tesseract).')
    expect(document.querySelector('[data-testid="queue-line"]')!.textContent).toBe('0 Dokumente in Arbeit, 2 wartend. Immer nur ein Dokument auf einmal, damit der Rest flüssig bleibt.')
  })

  it('speaks English too', async () => {
    await changeLanguage('en', false)
    server.answers['GET /api/v1/settings/ocr'] = { ...state, seconds_per_page: 3.5 }
    await page.show(<OcrCard />)
    expect(page.text).toContain('Text recognition')
    expect(chip('Turkish')).toBeTruthy()
    expect(document.querySelector('[data-testid="queue-line"]')!.textContent).toContain('1 document in progress, 0 waiting. On average 3.5 seconds per page')
  })

  it('shows the longest time for a document in minutes and saves it in seconds', async () => {
    server.answers['PUT /api/v1/settings/ocr'] = { ...state, max_seconds: 5400 }
    await page.show(<OcrCard />)
    const field = [...document.querySelectorAll<HTMLLabelElement>('label')].find((l) => l.textContent?.startsWith('Zeit je Dokument (Minuten)'))!.querySelector('input')!
    expect(field.value).toBe('60')
    expect(page.text).toContain('Eine Seite darf höchstens das Zehnfache des Schnitts dauern.')
    await page.type(field, '90')
    await page.click(page.button('Speichern'))
    expect(server.called('PUT', '/api/v1/settings/ocr')!.body).toEqual({ max_seconds: 5400 })
    expect(field.value).toBe('90')
  })

  it('refuses a time out of range on the page and sends nothing', async () => {
    await page.show(<OcrCard />)
    const field = [...document.querySelectorAll<HTMLLabelElement>('label')].find((l) => l.textContent?.startsWith('Zeit je Dokument (Minuten)'))!.querySelector('input')!
    for (const wrong of ['0', '1441', '1,5', 'x']) {
      await page.type(field, wrong)
      await page.click(page.button('Speichern'))
      expect(page.text).toContain('Gib eine ganze Zahl von 1 bis 1440 Minuten an.')
    }
    expect(server.called('PUT', '/api/v1/settings/ocr')).toBeUndefined()
  })
})
