/**
 * The page behind an upload request, for somebody without an account: who asks and for whom, how many files still go,
 * each file "angekommen" or why not, the same gentle word for every address that does not work, never anything of
 * what came before, and no call to anything but the request's own routes.
 */
import { act } from 'react'
import { Route, Routes } from 'react-router-dom'

import { changeLanguage } from '../i18n'
import { Page } from '../test/harness'
import { UploadRequestPage } from './UploadRequestPage'

const page = new Page()

// Made at run time: a token written out here would look like a secret to the scanners.
const TOKEN = 'upr_' + Array.from({ length: 16 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
const shown = { requested_by: 'Jule Beispiel', name: 'Kanzlei Weber', until: '2026-11-19T09:00:00Z', remaining: 2, max_mb: 200 }

type Answer = { status: number; body: unknown }
let calls: { method: string; url: string; file?: string }[] = []
let answers: ((url: string, method: string) => Answer)[] = []

function serve(next: (url: string, method: string) => Answer) {
  answers.push(next)
}

beforeEach(async () => {
  await changeLanguage('de', false)
  calls = []
  answers = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const url = String(input)
      const file = init?.body instanceof FormData ? (init.body.get('file') as File).name : undefined
      calls.push({ method, url, file })
      const found = method === 'GET' ? { status: 200, body: shown } : (answers.shift()?.(url, method) ?? { status: 500, body: {} })
      return new Response(JSON.stringify(found.body), { status: found.status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

function open() {
  return page.show(<Routes><Route path="u/:token" element={<UploadRequestPage />} /></Routes>, `/u/${TOKEN}`)
}

async function drop(...names: string[]) {
  const input = page.box.querySelector<HTMLInputElement>('input[type="file"]')!
  const files = names.map((name) => new File(['%PDF-1.4'], name, { type: 'application/pdf' }))
  Object.defineProperty(input, 'files', { value: files, configurable: true })
  await act(async () => {
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0))
  })
}

describe('the page behind an upload request', () => {
  it('says who asks, for whom, how many still go, what is taken, and asks the server for nothing else', async () => {
    await open()
    expect(page.text).toContain('Jule Beispiel bittet dich um Dokumente')
    // The name stands isolated (a name in another direction cannot turn the sentence around).
    expect(page.box.querySelector('h1')!.textContent).toBe('Dateien für ⁨Jule Beispiel⁩')
    expect(page.text).toContain('Diese Bitte ist für Kanzlei Weber.')
    expect(page.text).toContain('Noch 2 Dateien möglich.')
    expect(page.text).toContain('je Datei bis 200 MB')
    expect(page.text).toContain('Gültig bis 19.11.2026')
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([`GET /api/v1/u/${TOKEN}`])
  })

  it('sends the files one by one and says for each that it arrived or why not', async () => {
    serve(() => ({ status: 201, body: { status: 'arrived', remaining: 1 } }))
    serve(() => ({ status: 415, body: { detail: { code: 'unsupported_type', message: 'x' } } }))
    await open()
    await drop('rechnung.pdf', 'programm.exe')
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(calls.filter((c) => c.method === 'POST').map((c) => [c.url, c.file])).toEqual([
      [`/api/v1/u/${TOKEN}/files`, 'rechnung.pdf'],
      [`/api/v1/u/${TOKEN}/files`, 'programm.exe'],
    ])
    const rows = [...page.box.querySelectorAll('[data-testid="request-sent"] li')]
    expect(rows.map((r) => r.getAttribute('data-state'))).toEqual(['arrived', 'refused'])
    expect(page.text).toContain('angekommen')
    expect(page.text).toContain('Diese Art Datei wird nicht angenommen.')
    expect(page.text).toContain('Noch 1 Datei möglich.')
  })

  it('sends no more than the request takes', async () => {
    serve(() => ({ status: 201, body: { status: 'arrived', remaining: 1 } }))
    serve(() => ({ status: 201, body: { status: 'arrived', remaining: 0 } }))
    await open()
    await drop('a.pdf', 'b.pdf', 'c.pdf')
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(2)
    expect(page.text).toContain('Es gehen keine weiteren Dateien mehr.')
    expect(page.box.querySelector('input[type="file"]')).toBeNull()
  })

  it('has the same gentle word for every address that does not work', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: { code: 'not_found', message: 'Not found.' } }), { status: 404, headers: { 'Content-Type': 'application/json' } })))
    await open()
    expect(page.text).toContain('Diese Adresse nimmt nichts an')
    expect(page.box.querySelector('input[type="file"]')).toBeNull()
    expect(page.text).not.toContain('Kanzlei')
  })

  it('speaks English', async () => {
    await changeLanguage('en', false)
    await open()
    expect(page.text).toContain('Jule Beispiel asks you for documents')
    expect(page.text).toContain('2 more files possible.')
  })

  it('shows names as text, never as markup (the review’s probe)', async () => {
    const hostile = { ...shown, requested_by: '<strong>Jule</strong><img src=x onerror=alert(1)>', name: '<0>Kanzlei</0><name>Weber</name><a href="https://example.com">x</a>' }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(hostile), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    await open()
    expect(page.box.querySelector('strong, img, a, name')).toBeNull()
    expect(page.text).toContain('<strong>Jule</strong><img src=x onerror=alert(1)> bittet dich um Dokumente')
    expect(page.text).toContain('Diese Bitte ist für <0>Kanzlei</0><name>Weber</name><a href="https://example.com">x</a>.')
    // The stress is one span around the whole name, nothing inside it but text.
    const stressed = [...page.box.querySelectorAll('span.font-semibold')]
    expect(stressed.every((s) => s.children.length === 0)).toBe(true)
  })
})
