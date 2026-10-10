/** Every call names its browser tab: the server refuses a change without it (the wall against other sites). */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, tabId, uploadsApi } from './client'

function answer(status = 200, body: unknown = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function seen(mock: ReturnType<typeof vi.fn>): Record<string, string> {
  return mock.mock.calls[mock.mock.calls.length - 1][1].headers as Record<string, string>
}

afterEach(() => vi.unstubAllGlobals())

describe('the header of the tab', () => {
  it('goes with every kind of call, changes and reads alike', async () => {
    const fetchMock = vi.fn(async () => answer())
    vi.stubGlobal('fetch', fetchMock)
    for (const method of ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const) {
      await api('/api/v1/probe', { method })
      expect(seen(fetchMock)['X-Nexpaper-Client'], method).toBe(tabId())
    }
    await api('/api/v1/probe', { method: 'POST', raw: new Blob(['x']) })
    expect(seen(fetchMock)['X-Nexpaper-Client']).toBe(tabId())
  })

  it('is one id per tab, in the shape the server accepts, and a caller cannot replace it', async () => {
    const fetchMock = vi.fn(async () => answer())
    vi.stubGlobal('fetch', fetchMock)
    expect(tabId()).toMatch(/^tab-[0-9a-f]{24}$/)
    expect(tabId()).toBe(tabId())
    await api('/api/v1/probe', { method: 'POST', headers: { 'X-Nexpaper-Client': 'tab-other' } })
    expect(seen(fetchMock)['X-Nexpaper-Client']).toBe(tabId())
  })
})

describe('the answers', () => {
  it('turn the code of the server into an error and a lost session into the event', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => answer(401, { detail: { code: 'sign_in_required', message: 'x' } })))
    const gone = vi.fn()
    window.addEventListener('nexpaper:signed-out', gone)
    await expect(api('/api/v1/probe')).rejects.toMatchObject({ status: 401, code: 'sign_in_required' })
    expect(gone).toHaveBeenCalledTimes(1)
    window.removeEventListener('nexpaper:signed-out', gone)
    vi.stubGlobal('fetch', vi.fn(async () => answer(403, { detail: { code: 'browser_only', message: 'x' } })))
    const error: unknown = await api('/api/v1/probe').catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('browser_only')
  })
})

describe('where an upload goes', () => {
  it('names the vault and the source in the address of a form, and in the body of an upload in pieces', async () => {
    const fetchMock = vi.fn(async () => answer(200, { items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await uploadsApi.send([new File(['x'], 'a.pdf')], undefined, { vaultId: 9, source: 'camera' })
    expect((fetchMock.mock.calls[0] as unknown[])[0]).toBe('/api/v1/documents?vault_id=9&source=camera')
    await uploadsApi.send([new File(['x'], 'a.pdf')])
    expect((fetchMock.mock.calls[1] as unknown[])[0]).toBe('/api/v1/documents')
    await uploadsApi.start({ name: 'a.pdf', size: 1 }, 'a'.repeat(64), undefined, { vaultId: 9, source: 'share' })
    const init = (fetchMock.mock.calls[2] as unknown[])[1] as RequestInit
    expect(JSON.parse(String(init.body))).toEqual({ filename: 'a.pdf', size: 1, sha256: 'a'.repeat(64), vault_id: 9, source: 'share' })
  })
})
