/**
 * Uploading as the person sees it: the button in the menu opens the dialog for files (PDF, pictures, XML), the whole page
 * takes dropped files and says so ("Loslassen zum Hochladen"), the list shows each upload with its
 * progress and what came of it, and one sentence says how the run ended.
 */
import { act } from 'react'
import { useLocation } from 'react-router-dom'

import { ApiError, uploadsApi, vaultsApi, type DocumentInfo, type UploadResult } from '../api/client'
import { changeLanguage } from '../i18n'
import { ACCEPT } from '../lib/formats'
import { INBOX_CHANGED } from '../lib/say'
import { Uploader } from '../lib/uploader'
import { Page } from '../test/harness'
import { idle } from '../test/wait'
import { UploadProvider } from '../state/uploads'
import { DropSheet, UploadButton, UploadPanel, UploadRound } from './UploadPanel'

vi.mock('../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/client')>()
  return { ...original, uploadsApi: { send: vi.fn(), start: vi.fn(), state: vi.fn(), piece: vi.fn(), finish: vi.fn(), cancel: vi.fn() }, vaultsApi: { list: vi.fn() } }
})
vi.mock('../state/auth', () => ({ useAuth: () => ({ status: 'signedIn', me: { id: 1, name: 'jule' } }) }))
const vaults = vi.mocked(vaultsApi)
const api = vi.mocked(uploadsApi)
const page = new Page()
const KB = 1024
const config = { small: 100 * KB, piece: 40 * KB, batchFiles: 10, batchBytes: 1024 * KB, waits: [1], sleep: async () => undefined }

function accepted(name: string, duplicate: UploadResult['duplicate'] = null): UploadResult {
  return { filename: name, status: 'accepted', document: { id: 1, vault_id: 7, title: name.replace(/\.\w+$/, '') } as DocumentInfo, error: null, http_status: null, duplicate }
}

function pdf(name: string, size = 5 * KB): File {
  return new File([new Uint8Array(size)], name, { type: 'application/pdf' })
}

function Screen({ uploader }: { uploader: Uploader }) {
  return (
    <UploadProvider uploader={uploader}>
      <UploadButton />
      <UploadRound />
      <DropSheet />
      <UploadPanel />
    </UploadProvider>
  )
}

function drag(type: string, files = true, related: EventTarget | null = null): Event {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: { types: files ? ['Files'] : ['text/plain'], files: [pdf('dropped.pdf')] } })
  Object.defineProperty(event, 'relatedTarget', { value: related })
  window.dispatchEvent(event)
  return event
}

async function show(uploader = new Uploader(config)): Promise<Uploader> {
  await page.show(<Screen uploader={uploader} />)
  return uploader
}

async function settle(uploader: Uploader): Promise<void> {
  for (let i = 0; i < 100 && uploader.busy; i++) await act(async () => new Promise((resolve) => setTimeout(resolve, 5)))
  await act(async () => new Promise((resolve) => setTimeout(resolve, 10)))
  await idle()
}

beforeEach(async () => {
  await changeLanguage('de', false)
  for (const fn of Object.values(api)) fn.mockReset()
  api.cancel.mockResolvedValue(undefined)
  vaults.list.mockReset()
  vaults.list.mockResolvedValue([{ id: 7, name: 'Jule', personal_of: 1 }, { id: 9, name: 'Haushalt', personal_of: null }] as never)
})
afterEach(() => {
  page.close()
})

describe('the buttons', () => {
  it('open the dialog for files, in the menu and in the header of the phone', async () => {
    await show()
    const input = document.querySelector<HTMLInputElement>('[data-testid="upload-input"]')!
    expect(input.multiple).toBe(true)
    expect(input.accept).toBe(ACCEPT)
    // Only what the server takes: not every picture (a GIF or a BMP is turned away), no "image/*".
    expect(input.accept).not.toContain('image/*')
    for (const taken of ['image/webp', 'image/avif', 'image/heic', '.webp', '.avif']) expect(input.accept).toContain(taken)
    const click = vi.spyOn(input, 'click')
    await page.click(page.button('Hochladen'))
    expect(click).toHaveBeenCalledTimes(1)
    // The round button of the phone has the same name and leads to the quick upload.
    const round = document.querySelector<HTMLAnchorElement>('a[aria-label="Hochladen"]')!
    expect(round.getAttribute('href')).toBe('/schnell')
  })

  it('are called Upload in English', async () => {
    await changeLanguage('en', false)
    await show()
    expect(page.button('Upload')).toBeTruthy()
  })

  it('send the chosen files to the queue and let the same file be chosen again', async () => {
    const uploader = await show()
    api.send.mockResolvedValue({ items: [accepted('a.pdf'), accepted('b.pdf')] })
    const input = document.querySelector<HTMLInputElement>('[data-testid="upload-input"]')!
    const files = [pdf('a.pdf'), pdf('b.pdf')]
    Object.defineProperty(input, 'files', { configurable: true, value: files })
    const forget = vi.fn()
    Object.defineProperty(input, 'value', { configurable: true, get: () => '', set: forget })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    await settle(uploader)
    expect(api.send).toHaveBeenCalledTimes(1)
    expect(api.send.mock.calls[0][0].map((f: File) => f.name)).toEqual(['a.pdf', 'b.pdf'])
    expect(forget).toHaveBeenCalledWith('')
  })
})

describe('the sheet for dropping', () => {
  it('appears while files are dragged over the page, with its words, and goes when they leave', async () => {
    await show()
    expect(page.text).not.toContain('Loslassen zum Hochladen')
    await act(async () => void drag('dragover'))
    expect(page.text).toContain('Loslassen zum Hochladen')
    expect(page.text).toContain('PDF, Bilder, E-Rechnungen als XML. Alles landet erst im Eingang.')
    await act(async () => void drag('dragleave'))
    expect(page.text).not.toContain('Loslassen zum Hochladen')
  })

  it('does not appear for something that is not a file (a selected text)', async () => {
    await show()
    const event = drag('dragover', false)
    await idle()
    expect(page.text).not.toContain('Loslassen zum Hochladen')
    expect(event.defaultPrevented).toBe(false)
  })

  it('takes the dropped files, wherever on the page, and shows them in the list', async () => {
    const uploader = await show()
    api.send.mockResolvedValue({ items: [accepted('dropped.pdf')] })
    await act(async () => void drag('dragover'))
    const dropped = drag('drop')
    await settle(uploader)
    expect(dropped.defaultPrevented).toBe(true)
    expect(page.text).not.toContain('Loslassen zum Hochladen')
    expect(api.send).toHaveBeenCalledTimes(1)
    expect(page.text).toContain('dropped.pdf')
  })
})

describe('the list', () => {
  it('shows a file that was taken and says it is read and then waits in the inbox', async () => {
    const uploader = await show()
    api.send.mockResolvedValue({ items: [accepted('Strom.pdf')] })
    act(() => uploader.add([pdf('Strom.pdf')]))
    await settle(uploader)
    const row = document.querySelector('[data-phase="done"]')!
    expect(row.textContent).toContain('Strom.pdf')
    // The row and the sentence name the vault it went to (the own one is "Mein Tresor", as on the Vaults page).
    expect(row.textContent).toContain('Hochgeladen in „Mein Tresor“. Wird eingelesen, danach liegt es im Eingang.')
    expect(document.querySelector('[role="status"]')!.textContent).toBe('Hochgeladen in „Mein Tresor“. Wird eingelesen, danach liegt es im Eingang.')
  })

  it('names a shared vault by its name, and says nothing of a vault when the files went to several', async () => {
    const uploader = await show()
    api.send.mockResolvedValue({ items: [{ ...accepted('a.pdf'), document: { id: 1, vault_id: 9, title: 'a' } as DocumentInfo }, { ...accepted('b.pdf'), document: { id: 2, vault_id: 9, title: 'b' } as DocumentInfo }] })
    act(() => uploader.add([pdf('a.pdf'), pdf('b.pdf')]))
    await settle(uploader)
    expect(document.querySelector('[role="status"]')!.textContent).toBe('2 Dateien hochgeladen in „Haushalt“. Sie werden eingelesen.')
    act(() => uploader.clear())
    api.send.mockResolvedValue({ items: [accepted('c.pdf'), { ...accepted('d.pdf'), document: { id: 2, vault_id: 9, title: 'd' } as DocumentInfo }] })
    act(() => uploader.add([pdf('c.pdf'), pdf('d.pdf')]))
    await settle(uploader)
    expect(document.querySelector('[role="status"]')!.textContent).toBe('2 Dateien hochgeladen. Sie werden eingelesen.')
  })

  it('names the document a file repeats, in both cases', async () => {
    const uploader = await show()
    api.send.mockResolvedValue({
      items: [accepted('a.pdf', { document_id: 3, title: 'Abschlag Strom', kind: 'same' }), accepted('b.pdf', { document_id: 4, title: 'Vertrag', kind: 'similar' })],
    })
    act(() => uploader.add([pdf('a.pdf'), pdf('b.pdf')]))
    await settle(uploader)
    expect(page.text).toContain('Hochgeladen, aber dieselbe Datei gibt es schon als „Abschlag Strom“.')
    expect(page.text).toContain('Sieht aus wie das vorhandene Dokument „Vertrag“.')
    expect(document.querySelector('[role="status"]')!.textContent).toBe('2 Dateien hochgeladen in „Mein Tresor“. Sie werden eingelesen.')
  })

  it('says why a file was not taken, in the language of the page', async () => {
    const uploader = await show()
    api.send.mockRejectedValue(new ApiError(415, 'unsupported_type', { items: [{ filename: 'x.exe', status: 'rejected', error: { code: 'unsupported_type', message: 'x' }, http_status: 415 }] }))
    act(() => uploader.add([pdf('x.exe')]))
    await settle(uploader)
    const row = document.querySelector('[data-phase="failed"]')!
    const reason = 'Diese Art Datei nimmt nexpaper nicht an. Erlaubt sind PDF, JPEG, PNG, TIFF, HEIC, WebP, AVIF und E-Rechnungen als XML.'
    expect(row.textContent).toContain(reason)
    // The notice itself names the file and the reason: it does not send the person to a list that may be out of sight.
    const notice = document.querySelector('[role="alert"]')!
    expect(notice.textContent).toContain('1 Datei konnte nicht hochgeladen werden:')
    expect(notice.textContent).toContain('x.exe')
    expect(notice.textContent).toContain(reason)
    expect(notice.textContent).not.toContain('Die Liste')
    // A kind of file that is not taken comes out the same each time: no button to try again.
    expect(page.button('Erneut versuchen')).toBeUndefined()
  })

  it('names each refused file with its reason next to what was taken, and keeps the notice until it is closed', async () => {
    const uploader = await show()
    const timers = vi.spyOn(window, 'setTimeout')
    api.send.mockResolvedValue({
      items: [
        accepted('gut.pdf'),
        { filename: 'a.gif', status: 'rejected', document: null, error: { code: 'unsupported_type', message: 'x' }, http_status: 415, duplicate: null },
        { filename: 'leer.png', status: 'rejected', document: null, error: { code: 'empty_file', message: 'x' }, http_status: 422, duplicate: null },
      ],
    })
    act(() => uploader.add([pdf('gut.pdf'), pdf('a.gif'), pdf('leer.png')]))
    await settle(uploader)
    const notice = document.querySelector('[role="alert"]')!
    expect(notice.textContent).toContain('Hochgeladen in „Mein Tresor“.')
    expect(notice.textContent).toContain('2 Dateien konnten nicht hochgeladen werden:')
    expect(notice.textContent).toContain('a.gif')
    expect(notice.textContent).toContain('Erlaubt sind PDF, JPEG, PNG, TIFF, HEIC, WebP, AVIF')
    expect(notice.textContent).toContain('leer.png')
    expect(notice.textContent).toContain('Die Datei ist leer.')
    // No timer takes it away by itself (a plain success notice has one of six seconds).
    expect(timers.mock.calls.some(([, delay]) => delay === 6000)).toBe(false)
    await page.click(page.button('Schließen'))
    expect(document.querySelector('[role="alert"]')).toBeNull()
  })

  it('offers to try again for what a second try can change, and only for that', async () => {
    const uploader = await show()
    api.send.mockRejectedValue(new ApiError(0, 'network'))
    act(() => uploader.add([pdf('a.pdf')]))
    await settle(uploader)
    expect(page.button('Erneut versuchen')).toBeTruthy()
  })

  it('names the limit when a file is too large', async () => {
    const uploader = await show()
    api.send.mockRejectedValue(new ApiError(413, 'too_large', { items: [{ filename: 'big.pdf', status: 'rejected', error: { code: 'too_large', message: 'x', max_mb: 200 }, http_status: 413 }] }))
    act(() => uploader.add([pdf('big.pdf')]))
    await settle(uploader)
    expect(document.querySelector('[data-phase="failed"]')!.textContent).toContain('höchstens 200 MB')
  })

  it('shows the progress of a large file and lets it be cancelled', async () => {
    const uploader = await show()
    let release: (() => void) | undefined
    api.start.mockResolvedValue({ exists: false, upload: { id: 'u'.repeat(32), state: 'open', size: 130 * KB, received: 0, chunk_size: 40 * KB, max_piece: 64 * KB, expires_at: '', document_id: null }, document: null })
    api.piece.mockImplementation(async (_id, offset, blob) => {
      if (offset === 40 * KB) await new Promise<void>((resolve) => (release = resolve))
      return { id: 'u'.repeat(32), state: 'open', size: 130 * KB, received: offset + blob.size, chunk_size: 40 * KB, max_piece: 64 * KB, expires_at: '', document_id: null }
    })
    act(() => uploader.add([pdf('Scan.pdf', 130 * KB)]))
    for (let i = 0; i < 100 && !release; i++) await act(async () => new Promise((resolve) => setTimeout(resolve, 5)))
    const bar = document.querySelector('[role="progressbar"]')!
    expect(bar.getAttribute('aria-valuenow')).toBe('30')
    expect(page.text).toContain('Wird hochgeladen, 30 %')
    await page.click(page.button('Abbrechen'))
    expect(api.cancel).toHaveBeenCalledWith('u'.repeat(32))
    expect(document.querySelector('[data-phase="cancelled"]')!.textContent).toContain('Abgebrochen')
    release?.()
    await settle(uploader)
  })

  it('never shows more than 100 percent, whatever the server says it has', async () => {
    const entry = { id: 1, name: 'Scan.pdf', size: 100 * KB, chunked: true, phase: 'sending' as const, sent: 250 * KB, document: null, vaultId: null, duplicate: null, error: null }
    const list = [entry]
    class Overfull extends Uploader {
      getSnapshot = () => list
    }
    await show(new Overfull(config))
    expect(document.querySelector('[role="progressbar"]')!.getAttribute('aria-valuenow')).toBe('100')
    expect(page.text).toContain('Wird hochgeladen, 100 %')
  })

  it('shows a file the person has already as not transferred', async () => {
    const uploader = await show()
    api.start.mockResolvedValue({ exists: true, upload: null, document: { id: 5, title: 'Abschlag Strom', status: 'inbox' } })
    act(() => uploader.add([pdf('Scan.pdf', 130 * KB)]))
    await settle(uploader)
    expect(document.querySelector('[data-phase="exists"]')!.textContent).toContain('Diese Datei liegt schon als „Abschlag Strom“ vor. Es wurde nichts übertragen.')
    expect(document.querySelector('[role="status"]')!.textContent).toBe('1 Datei war schon vorhanden und wurde nicht übertragen.')
  })

  it('offers to resume a paused upload and to start a failed one again', async () => {
    const uploader = await show()
    api.start.mockResolvedValue({ exists: false, upload: { id: 'u'.repeat(32), state: 'open', size: 130 * KB, received: 0, chunk_size: 40 * KB, max_piece: 64 * KB, expires_at: '', document_id: null }, document: null })
    api.piece.mockRejectedValue(new ApiError(0, 'network'))
    api.state.mockRejectedValue(new ApiError(0, 'network'))
    act(() => uploader.add([pdf('Scan.pdf', 130 * KB)]))
    await settle(uploader)
    const row = document.querySelector('[data-phase="paused"]')!
    expect(row.textContent).toContain('Unterbrochen, 0 % sind angekommen. Mit „Fortsetzen“ geht es von dort weiter.')
    expect(page.button('Fortsetzen')).toBeTruthy()
    // Back online: resumes and ends.
    api.state.mockResolvedValue({ id: 'u'.repeat(32), state: 'open', size: 130 * KB, received: 0, chunk_size: 40 * KB, max_piece: 64 * KB, expires_at: '', document_id: null })
    api.piece.mockImplementation(async (_id, offset, blob) => ({ id: 'u'.repeat(32), state: 'open', size: 130 * KB, received: offset + blob.size, chunk_size: 40 * KB, max_piece: 64 * KB, expires_at: '', document_id: null }))
    api.finish.mockResolvedValue({ document: { id: 8, title: 'Scan' } as DocumentInfo, duplicate: null, created: true })
    await page.click(page.button('Fortsetzen'))
    await settle(uploader)
    expect(document.querySelector('[data-phase="done"]')).toBeTruthy()
  })

  it('is cleared by the cross once nothing runs, and only then is the cross there', async () => {
    const uploader = await show()
    let release: (() => void) | undefined
    api.send.mockImplementation(async (files) => {
      await new Promise<void>((resolve) => (release = resolve))
      return { items: files.map((f) => accepted(f.name)) }
    })
    act(() => uploader.add([pdf('a.pdf')]))
    for (let i = 0; i < 100 && !release; i++) await act(async () => new Promise((resolve) => setTimeout(resolve, 5)))
    expect(document.querySelector('button[aria-label="Liste leeren"]')).toBeNull()
    release?.()
    await settle(uploader)
    await page.click(document.querySelector<HTMLButtonElement>('button[aria-label="Liste leeren"]'))
    expect(document.querySelector('section[aria-label="Uploads"]')).toBeNull()
  })

  it('has no list while nothing was uploaded', async () => {
    await show()
    expect(document.querySelector('section[aria-label="Uploads"]')).toBeNull()
  })
})

describe('after files were chosen or dropped', () => {
  function Where() {
    return <p data-testid="where">{useLocation().pathname}</p>
  }

  async function at(path: string, uploader = new Uploader(config)): Promise<Uploader> {
    await page.show(
      <UploadProvider uploader={uploader}>
        <Where />
      </UploadProvider>,
      path,
    )
    return uploader
  }
  const where = () => document.querySelector('[data-testid="where"]')!.textContent

  it('the inbox opens, and the app is told when the run is through', async () => {
    api.send.mockResolvedValue({ items: [accepted('a.pdf')] })
    const told = vi.fn()
    window.addEventListener(INBOX_CHANGED, told)
    try {
      const uploader = await at('/tresore')
      const input = document.querySelector<HTMLInputElement>('[data-testid="upload-input"]')!
      Object.defineProperty(input, 'files', { value: [pdf('a.pdf')], configurable: true })
      await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
      expect(where()).toBe('/eingang')
      await settle(uploader)
      expect(told).toHaveBeenCalled()
    } finally {
      window.removeEventListener(INBOX_CHANGED, told)
    }
  })

  it('a dropped file opens the inbox too, but not on the pages of the phone', async () => {
    api.send.mockResolvedValue({ items: [accepted('dropped.pdf')] })
    await at('/')
    await act(async () => void drag('drop'))
    expect(where()).toBe('/eingang')
    page.close()
    await at('/schnell')
    await act(async () => void drag('drop'))
    expect(where()).toBe('/schnell')
  })
})
