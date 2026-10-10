/**
 * The actions in a row of the list of versions against test data: restoring an older version (as a new one, for the
 * version the document stands at), putting away one that could not be read, nothing for the current one or a reader,
 * one request for two quick clicks; and uploading a new version with a note.
 */
import { act } from 'react'

import { changeLanguage } from '../i18n'
import { ACCEPT } from '../lib/formats'
import { Page, Server } from '../test/harness'
import { UploadVersionDialog, VersionRowActions } from './VersionActions'

const server = new Server()
const page = new Page()
const say = vi.fn()
const onDone = vi.fn()

function row(n: number, over: Record<string, unknown> = {}, canEdit = true) {
  const version = { n, current: false, state: 'ready' as const, ...over }
  return page.show(<VersionRowActions document={{ id: 5, current_version: 3 }} version={version} canEdit={canEdit} onDone={onDone} say={say} />)
}

beforeEach(async () => {
  await changeLanguage('de', false)
  say.mockClear()
  onDone.mockClear()
  server.answers = {
    'POST /api/v1/documents/5/versions/1/restore': { id: 5, current_version: 4 },
    'DELETE /api/v1/documents/5/versions/4': 204,
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('the actions of a version', () => {
  it('restores an older version for the version the document stands at, and says which one it became', async () => {
    await row(1)
    await page.click(page.button('Fassung 1 zurückholen'))
    expect(server.called('POST', '/api/v1/documents/5/versions/1/restore')!.body).toEqual({ base_version: 3 })
    expect(say).toHaveBeenCalledWith('Fassung 1 ist jetzt als Fassung 4 wiederhergestellt. Die anderen bleiben in der Liste.')
    expect(onDone).toHaveBeenCalledWith({ id: 5, current_version: 4 })
  })

  it('puts away a version that could not be read, and offers nothing else for it', async () => {
    await row(4, { state: 'failed' })
    expect(page.button('Fassung 4 zurückholen')).toBeUndefined()
    await page.click(page.button('Fassung 4 verwerfen'))
    expect(server.changes()).toEqual([])
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('Fassung 4 verwerfen'))
    await page.inDialog('Fassung verwerfen')
    expect(server.changes()).toEqual(['DELETE /api/v1/documents/5/versions/4'])
    expect(say).toHaveBeenCalledWith('Fassung 4 ist verworfen.')
    expect(onDone).toHaveBeenCalledWith(null)
  })

  it('offers nothing for the current version, one being read, or to a reader', async () => {
    await row(3, { current: true })
    expect(document.querySelectorAll('button')).toHaveLength(0)
    page.close()
    await row(4, { state: 'processing' })
    expect(document.querySelectorAll('button')).toHaveLength(0)
    page.close()
    await row(1, {}, false)
    expect(document.querySelectorAll('button')).toHaveLength(0)
  })

  it('says what the server refused', async () => {
    server.fails = { 'POST /api/v1/documents/5/versions/1/restore': { status: 409, code: 'version_changed' } }
    await row(1)
    await page.click(page.button('Fassung 1 zurückholen'))
    expect(say).toHaveBeenCalledWith('Das Dokument hat sich inzwischen geändert. Sieh es dir noch einmal an.')
    expect(onDone).not.toHaveBeenCalled()
  })

  it('sends one request for two quick clicks', async () => {
    await row(1)
    const button = page.button('Fassung 1 zurückholen')!
    await act(async () => {
      button.click()
      button.click()
    })
    expect(server.changes()).toEqual(['POST /api/v1/documents/5/versions/1/restore'])
  })
})

describe('uploading a new version', () => {
  it('sends the file and the note, and says the text is being read', async () => {
    const sent: { url: string; form: FormData }[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      sent.push({ url, form: init.body as FormData })
      return new Response(JSON.stringify({ n: 4, current: false, state: 'processing' }), { status: 202, headers: { 'Content-Type': 'application/json' } })
    }))
    const onUploaded = vi.fn()
    const onClose = vi.fn()
    await page.show(<UploadVersionDialog document={{ id: 5, title: 'Vertrag' }} onClose={onClose} onUploaded={onUploaded} say={say} />)
    const upload = () => [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Neue Fassung hochladen')!
    expect(upload().disabled).toBe(true)
    const input = document.querySelector<HTMLInputElement>('[data-testid="version-file"]')!
    const file = new File(['%PDF-1.4'], 'besser.pdf', { type: 'application/pdf' })
    await act(async () => {
      Object.defineProperty(input, 'files', { value: [file] })
      input.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await page.type(document.querySelector<HTMLInputElement>('input[aria-label="Was ist neu? (freiwillig)"]'), 'besserer Scan')
    await page.click(upload())
    expect(sent[0].url).toBe('/api/v1/documents/5/versions')
    expect((sent[0].form.get('file') as File).name).toBe('besser.pdf')
    expect(sent[0].form.get('note')).toBe('besserer Scan')
    expect(say).toHaveBeenCalledWith('Neue Fassung hochgeladen. Texterkennung läuft.')
    expect(onUploaded).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('offers only the kinds of file the server takes', async () => {
    await page.show(<UploadVersionDialog document={{ id: 5, title: 'Vertrag' }} onClose={vi.fn()} onUploaded={vi.fn()} />)
    expect(document.querySelector<HTMLInputElement>('[data-testid="version-file"]')!.accept).toBe(ACCEPT)
  })

  it('shows what the server refused', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: { code: 'same_file' } }), { status: 409, headers: { 'Content-Type': 'application/json' } })))
    await page.show(<UploadVersionDialog document={{ id: 5, title: 'Vertrag' }} onClose={vi.fn()} onUploaded={vi.fn()} />)
    const input = document.querySelector<HTMLInputElement>('[data-testid="version-file"]')!
    await act(async () => {
      Object.defineProperty(input, 'files', { value: [new File(['x'], 'a.pdf')] })
      input.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await page.click([...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === 'Neue Fassung hochladen'))
    expect(page.text).toContain('Diese Datei ist schon die aktuelle Fassung.')
  })
})
