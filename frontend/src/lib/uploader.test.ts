/**
 * The queue of uploads against a stand-in of the server's routes: small files travel together, a large one in pieces with
 * the checksum first; a file the person has is not sent; a broken connection is tried again from where the server stands;
 * what cannot go on is paused and resumes; cancelling drops what arrived.
 */
import { randomBytes, concat, same, sha256Hex } from '../test/bytes'
import { ApiError, uploadsApi, type DocumentInfo, type UploadResult, type UploadState } from '../api/client'
import { canRetry, Uploader, type Entry, type Summary } from './uploader'

vi.mock('../api/client', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api/client')>()
  return {
    ...original,
    uploadsApi: { send: vi.fn(), start: vi.fn(), state: vi.fn(), piece: vi.fn(), finish: vi.fn(), cancel: vi.fn() },
  }
})

const api = vi.mocked(uploadsApi)
const KB = 1024
const config = { small: 100 * KB, piece: 40 * KB, batchFiles: 3, batchBytes: 250 * KB, waits: [1, 1, 1], sleep: async () => undefined }

function file(name: string, size: number): File {
  return new File([randomBytes(size)], name)
}

function document_(id: number, title: string): DocumentInfo {
  return { id, title, vault_id: 7 } as DocumentInfo
}

function accepted(name: string, id: number, duplicate: UploadResult['duplicate'] = null): UploadResult {
  return { filename: name, status: 'accepted', document: document_(id, name.replace(/\.\w+$/, '')), error: null, http_status: null, duplicate }
}

function state(received: number, size: number, extra: Partial<UploadState> = {}): UploadState {
  return { id: 'u'.repeat(32), state: 'open', size, received, chunk_size: 8 * 1024 * KB, max_piece: 64 * 1024 * KB, expires_at: '2026-10-10T00:00:00Z', document_id: null, ...extra }
}

async function settle(uploader: Uploader): Promise<readonly Entry[]> {
  for (let i = 0; i < 200 && uploader.busy; i++) await new Promise((resolve) => setTimeout(resolve, 5))
  await new Promise((resolve) => setTimeout(resolve, 10))
  return uploader.getSnapshot()
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset()
  api.cancel.mockResolvedValue(undefined)
})

describe('small files', () => {
  it('travel together, as many as one request takes, in the order they were added', async () => {
    const uploader = new Uploader(config)
    const sent: string[][] = []
    api.send.mockImplementation(async (files) => {
      sent.push(files.map((f) => f.name))
      return { items: files.map((f, i) => accepted(f.name, sent.length * 10 + i)) }
    })
    uploader.add([file('a.pdf', 10 * KB), file('b.pdf', 20 * KB), file('c.pdf', 30 * KB), file('d.pdf', 40 * KB), file('e.pdf', 50 * KB)])
    const entries = await settle(uploader)
    expect(sent).toEqual([['a.pdf', 'b.pdf', 'c.pdf'], ['d.pdf', 'e.pdf']])
    expect(entries.map((e) => [e.name, e.phase, e.document?.id])).toEqual([
      ['a.pdf', 'done', 10], ['b.pdf', 'done', 11], ['c.pdf', 'done', 12], ['d.pdf', 'done', 20], ['e.pdf', 'done', 21],
    ])
  })

  it('stay in one request only up to the bytes a request takes', async () => {
    const uploader = new Uploader({ ...config, batchBytes: 120 * KB })
    const sent: string[][] = []
    api.send.mockImplementation(async (files) => {
      sent.push(files.map((f) => f.name))
      return { items: files.map((f) => accepted(f.name, 1)) }
    })
    uploader.add([file('a.pdf', 60 * KB), file('b.pdf', 60 * KB), file('c.pdf', 10 * KB)])
    await settle(uploader)
    expect(sent).toEqual([['a.pdf', 'b.pdf'], ['c.pdf']])
  })

  it('show what became of each: taken, taken but repeating a document, refused with the reason', async () => {
    const uploader = new Uploader(config)
    api.send.mockResolvedValue({
      items: [
        accepted('a.pdf', 1),
        accepted('b.pdf', 2, { document_id: 1, title: 'Strom', kind: 'same' }),
        { filename: 'c.exe', status: 'rejected', document: null, error: { code: 'unsupported_type', message: 'x' }, http_status: 415, duplicate: null },
      ],
    })
    uploader.add([file('a.pdf', 5 * KB), file('b.pdf', 5 * KB), file('c.exe', 5 * KB)])
    const entries = await settle(uploader)
    expect(entries.map((e) => e.phase)).toEqual(['done', 'done', 'failed'])
    expect(entries[1].duplicate).toEqual({ title: 'Strom', kind: 'same' })
    expect(entries[2].error?.code).toBe('unsupported_type')
  })

  it('all refused: the error carries the result of each', async () => {
    const uploader = new Uploader(config)
    api.send.mockRejectedValue(new ApiError(413, 'too_large', {
      items: [
        { filename: 'a.pdf', status: 'rejected', error: { code: 'too_large', message: 'x', max_mb: 5 }, http_status: 413 },
        { filename: 'b.xml', status: 'rejected', error: { code: 'xml_not_invoice', message: 'x' }, http_status: 415 },
      ],
    }))
    uploader.add([file('a.pdf', 5 * KB), file('b.xml', 5 * KB)])
    const entries = await settle(uploader)
    expect(entries.map((e) => [e.phase, e.error?.code, e.error?.values])).toEqual([
      ['failed', 'too_large', { max_mb: 5 }],
      ['failed', 'xml_not_invoice', {}],
    ])
  })

  it('failed because the server cannot be reached: the whole group fails, and trying again sends it anew', async () => {
    const uploader = new Uploader(config)
    api.send.mockRejectedValueOnce(new ApiError(0, 'network'))
    uploader.add([file('a.pdf', 5 * KB), file('b.pdf', 5 * KB)])
    let entries = await settle(uploader)
    expect(entries.map((e) => [e.phase, e.error?.code])).toEqual([['failed', 'network'], ['failed', 'network']])
    api.send.mockImplementation(async (files) => ({ items: files.map((f, i) => accepted(f.name, i + 1)) }))
    uploader.retry(entries[0].id)
    uploader.retry(entries[1].id)
    entries = await settle(uploader)
    expect(entries.map((e) => e.phase)).toEqual(['done', 'done'])
  })

  it('tell the page when the queue is through, with the count of each outcome', async () => {
    const uploader = new Uploader(config)
    const summaries: Summary[] = []
    uploader.whenIdle((s) => summaries.push(s))
    api.send.mockResolvedValue({
      items: [accepted('a.pdf', 1, { document_id: 9, title: 'Alt', kind: 'similar' }), { filename: 'b.png', status: 'rejected', document: null, error: { code: 'empty_file', message: 'x' }, http_status: 422, duplicate: null }],
    })
    uploader.add([file('a.pdf', 5 * KB), file('b.png', 5 * KB)])
    await settle(uploader)
    expect(summaries).toEqual([{ done: 1, exists: 0, failed: 1, duplicates: 1, vaults: [7], failures: [{ name: 'b.png', code: 'empty_file', values: {} }] }])
  })
})

describe('a large file', () => {
  const size = 130 * KB

  function serve(data: Uint8Array) {
    const received: { offset: number; length: number; bytes: Uint8Array }[] = []
    let have = 0
    api.start.mockImplementation(async (_file, sha) => {
      expect(sha).toBe(await sha256Hex(data))
      return { exists: false, upload: state(0, data.length), document: null }
    })
    api.state.mockImplementation(async () => state(have, data.length))
    api.piece.mockImplementation(async (_id, offset, blob) => {
      const bytes = new Uint8Array(await blob.arrayBuffer())
      received.push({ offset, length: bytes.length, bytes })
      if (offset !== have) throw new ApiError(409, 'offset_mismatch', { received: have })
      have += bytes.length
      return state(have, data.length)
    })
    api.finish.mockImplementation(async () => ({ document: document_(77, 'Scan'), duplicate: null, created: true }))
    return { received, have: () => have, rewind: (to: number) => void (have = to) }
  }

  async function big(): Promise<{ data: Uint8Array; big: File }> {
    const data = randomBytes(size)
    return { data, big: new File([data], 'scan.pdf') }
  }

  it('goes in pieces in order after the checksum, and ends with finish', async () => {
    const { data, big: scan } = await big()
    const server = serve(data)
    const uploader = new Uploader(config)
    const seen: Entry[] = []
    uploader.subscribe(() => seen.push(...uploader.getSnapshot()))
    uploader.add([scan])
    const entries = await settle(uploader)
    expect(server.received.map((p) => [p.offset, p.length])).toEqual([[0, 40 * KB], [40 * KB, 40 * KB], [80 * KB, 40 * KB], [120 * KB, 10 * KB]])
    expect(same(concat(server.received.map((p) => p.bytes)), data)).toBe(true)
    expect(api.finish).toHaveBeenCalledTimes(1)
    expect(entries[0]).toMatchObject({ phase: 'done', sent: size, document: { id: 77, title: 'Scan' } })
    // The phases went hashing, sending, finishing, and the progress only grew.
    const phases = [...new Set(seen.map((e) => e.phase))]
    expect(phases.filter((p) => ['hashing', 'sending', 'finishing', 'done'].includes(p))).toEqual(['hashing', 'sending', 'finishing', 'done'])
    const sent = seen.filter((e) => e.phase === 'sending').map((e) => e.sent)
    expect(sent).toEqual([...sent].sort((a, b) => a - b))
  })

  it('is not sent at all when the person has the file already', async () => {
    const { big: scan } = await big()
    api.start.mockResolvedValue({ exists: true, upload: null, document: { id: 5, title: 'Strom', status: 'inbox' } })
    const uploader = new Uploader(config)
    const summaries: Summary[] = []
    uploader.whenIdle((s) => summaries.push(s))
    uploader.add([scan])
    const entries = await settle(uploader)
    expect(entries[0]).toMatchObject({ phase: 'exists', document: { id: 5, title: 'Strom' } })
    expect(api.piece).not.toHaveBeenCalled()
    expect(api.finish).not.toHaveBeenCalled()
    expect(summaries).toEqual([{ done: 0, exists: 1, failed: 0, duplicates: 0, vaults: [], failures: [] }])
  })

  it('goes on from where the server stands after a break, and asks it first', async () => {
    const { data, big: scan } = await big()
    const server = serve(data)
    let broken = false
    const forward = api.piece.getMockImplementation()!
    api.piece.mockImplementation(async (id, offset, blob, signal) => {
      if (offset === 40 * KB && !broken) {
        broken = true
        // The piece reached the server but the answer was lost on the way.
        await forward(id, offset, blob, signal)
        throw new ApiError(0, 'network')
      }
      return forward(id, offset, blob, signal)
    })
    const uploader = new Uploader(config)
    uploader.add([scan])
    const entries = await settle(uploader)
    expect(entries[0].phase).toBe('done')
    // After the break it asked for the state, found 80 KB there, and sent the next piece from 80 KB, not the old one again.
    expect(api.state).toHaveBeenCalled()
    expect(server.received.map((p) => p.offset)).toEqual([0, 40 * KB, 80 * KB, 120 * KB])
    expect(server.have()).toBe(size)
  })

  it('takes the offset the server names when a piece is in the wrong place', async () => {
    const { data, big: scan } = await big()
    const server = serve(data)
    let first = true
    const forward = api.piece.getMockImplementation()!
    api.piece.mockImplementation(async (id, offset, blob, signal) => {
      if (first && offset === 40 * KB) {
        first = false
        throw new ApiError(409, 'offset_mismatch', { received: 40 * KB })
      }
      return forward(id, offset, blob, signal)
    })
    const uploader = new Uploader(config)
    uploader.add([scan])
    expect((await settle(uploader))[0].phase).toBe('done')
    expect(server.received.map((p) => p.offset)).toEqual([0, 40 * KB, 80 * KB, 120 * KB])
  })

  it('takes the offset the server names even when it is behind where the client thought it was', async () => {
    const { data, big: scan } = await big()
    const server = serve(data)
    const forward = api.piece.getMockImplementation()!
    let named = false
    api.piece.mockImplementation(async (id, offset, blob, signal) => {
      if (offset === 40 * KB && !named) {
        named = true
        // The server only has 20 KB of it (it lost the end of the first piece): it says so, behind the client's idea.
        server.received.length = 0
        server.rewind(20 * KB)
        throw new ApiError(409, 'offset_mismatch', { received: 20 * KB })
      }
      return forward(id, offset, blob, signal)
    })
    const uploader = new Uploader(config)
    uploader.add([scan])
    expect((await settle(uploader))[0].phase).toBe('done')
    expect(server.received.map((p) => p.offset)).toEqual([20 * KB, 60 * KB, 100 * KB])
  })

  it('goes on with an upload that was open already when the server says so, from where it stands', async () => {
    const { data, big: scan } = await big()
    const server = serve(data)
    server.rewind(40 * KB)
    api.start.mockImplementation(async () => ({ exists: false, upload: state(40 * KB, data.length), document: null }))
    const uploader = new Uploader(config)
    uploader.add([scan])
    expect((await settle(uploader))[0].phase).toBe('done')
    // Nothing from the start again: the first piece begins at 40 KB.
    expect(server.received.map((p) => p.offset)).toEqual([40 * KB, 80 * KB, 120 * KB])
    expect(api.finish).toHaveBeenCalledTimes(1)
  })

  it('is paused when the connection does not come back, and resumes from the server on a press', async () => {
    const { data, big: scan } = await big()
    const server = serve(data)
    const forward = api.piece.getMockImplementation()!
    let down = false
    api.piece.mockImplementation(async (id, offset, blob, signal) => {
      if (down && offset >= 40 * KB) throw new ApiError(0, 'network')
      return forward(id, offset, blob, signal)
    })
    api.state.mockImplementation(async () => {
      if (down) throw new ApiError(0, 'network')
      return state(server.have(), size)
    })
    const uploader = new Uploader(config)
    down = true
    uploader.add([scan])
    let entries = await settle(uploader)
    expect(entries[0]).toMatchObject({ phase: 'paused', error: { code: 'network' } })
    expect(entries[0].sent).toBeLessThan(size)
    expect(api.finish).not.toHaveBeenCalled()
    // The connection is back; "Resume" asks the server where it stands and goes on from there.
    down = false
    uploader.resume(entries[0].id)
    entries = await settle(uploader)
    expect(entries[0].phase).toBe('done')
    expect(server.have()).toBe(size)
    expect(api.start).toHaveBeenCalledTimes(1)
    // After the resume nothing was sent from the start again: the offset came from the server, not from a guess.
    expect(server.received.filter((p) => p.offset === 0)).toHaveLength(1)
    expect(same(concat(server.received.filter((p, i, all) => all.findIndex((q) => q.offset === p.offset) === i).map((p) => p.bytes)), data)).toBe(true)
  })

  it('fails for a reason a new try will not mend, and trying again starts a new upload', async () => {
    const { data, big: scan } = await big()
    serve(data)
    api.piece.mockRejectedValueOnce(new ApiError(413, 'upload_space'))
    const uploader = new Uploader(config)
    uploader.add([scan])
    let entries = await settle(uploader)
    expect(entries[0]).toMatchObject({ phase: 'failed', error: { code: 'upload_space' } })
    serve(data)
    uploader.retry(entries[0].id)
    entries = await settle(uploader)
    expect(entries[0].phase).toBe('done')
    expect(api.start).toHaveBeenCalledTimes(2)
  })

  it('starts over when the server has dropped the upload (it ran out)', async () => {
    const { data, big: scan } = await big()
    serve(data)
    const forward = api.piece.getMockImplementation()!
    api.piece.mockImplementation(async (id, offset, blob, signal) => {
      if (offset === 40 * KB) throw new ApiError(410, 'upload_expired')
      return forward(id, offset, blob, signal)
    })
    const uploader = new Uploader(config)
    uploader.add([scan])
    const entries = await settle(uploader)
    expect(entries[0]).toMatchObject({ phase: 'failed', error: { code: 'upload_expired' } })
  })

  it('finishing is tried again after a break; the server answers the same document', async () => {
    const { data, big: scan } = await big()
    serve(data)
    api.finish.mockRejectedValueOnce(new ApiError(0, 'network')).mockResolvedValue({ document: document_(77, 'Scan'), duplicate: { document_id: 3, title: 'Alt', kind: 'same' }, created: false })
    const uploader = new Uploader(config)
    uploader.add([scan])
    const entries = await settle(uploader)
    expect(api.finish).toHaveBeenCalledTimes(2)
    expect(entries[0]).toMatchObject({ phase: 'done', duplicate: { title: 'Alt', kind: 'same' } })
  })

  it('a refused file at the end (wrong checksum) is a failure with its reason', async () => {
    const { data, big: scan } = await big()
    serve(data)
    api.finish.mockRejectedValue(new ApiError(422, 'checksum_mismatch'))
    const uploader = new Uploader(config)
    uploader.add([scan])
    expect((await settle(uploader))[0]).toMatchObject({ phase: 'failed', error: { code: 'checksum_mismatch' } })
  })

  it('cancelling stops the pieces and asks the server to drop what arrived', async () => {
    const { data, big: scan } = await big()
    serve(data)
    const forward = api.piece.getMockImplementation()!
    const uploader = new Uploader(config)
    let id = 0
    api.piece.mockImplementation(async (uploadId, offset, blob, signal) => {
      const result = await forward(uploadId, offset, blob, signal)
      if (offset === 40 * KB) uploader.cancel(id)
      return result
    })
    uploader.add([scan])
    id = uploader.getSnapshot()[0].id
    const entries = await settle(uploader)
    expect(entries[0].phase).toBe('cancelled')
    expect(api.cancel).toHaveBeenCalledWith('u'.repeat(32))
    expect(api.finish).not.toHaveBeenCalled()
    expect(api.piece.mock.calls.length).toBeLessThanOrEqual(3)
  })

  it('a small file waiting behind it is sent after it, in order', async () => {
    const { data, big: scan } = await big()
    serve(data)
    const order: string[] = []
    api.finish.mockImplementation(async () => {
      order.push('large done')
      return { document: document_(77, 'Scan'), duplicate: null, created: true }
    })
    api.send.mockImplementation(async (files) => {
      order.push('small sent')
      return { items: files.map((f) => accepted(f.name, 5)) }
    })
    const uploader = new Uploader(config)
    uploader.add([scan, file('note.pdf', 5 * KB)])
    await settle(uploader)
    expect(order).toEqual(['large done', 'small sent'])
  })
})

describe('trying again', () => {
  it.each([['unsupported_type', false], ['xml_not_invoice', false], ['empty_file', false], ['too_large', false], ['invalid_input', false], ['network', true], ['busy', true], ['checksum_mismatch', true], ['upload_expired', true]])(
    'is offered for %s: %s',
    async (code, offered) => {
      expect(canRetry(code)).toBe(offered)
      const uploader = new Uploader(config)
      api.send.mockRejectedValueOnce(new ApiError(415, code))
      uploader.add([file('a.pdf', 5 * KB)])
      let entries = await settle(uploader)
      expect(entries[0].phase).toBe('failed')
      api.send.mockResolvedValue({ items: [accepted('a.pdf', 1)] })
      uploader.retry(entries[0].id)
      entries = await settle(uploader)
      // Where it is not offered, asking changes nothing.
      expect(entries[0].phase).toBe(offered ? 'done' : 'failed')
    },
  )
})

describe('the list', () => {
  it('forgets the finished ones and keeps those still on their way', async () => {
    const uploader = new Uploader(config)
    api.send.mockResolvedValueOnce({ items: [accepted('a.pdf', 1)] })
    uploader.add([file('a.pdf', 5 * KB)])
    await settle(uploader)
    expect(uploader.getSnapshot()).toHaveLength(1)
    uploader.clear()
    expect(uploader.getSnapshot()).toHaveLength(0)
  })

  it('cancelling a file that has not started takes it out of the queue: it is never sent', async () => {
    const uploader = new Uploader(config)
    let release: (() => void) | undefined
    api.start.mockImplementation(async () => {
      await new Promise<void>((resolve) => (release = resolve))
      return { exists: true, upload: null, document: { id: 5, title: 'Strom', status: 'inbox' } }
    })
    uploader.add([file('large.pdf', 130 * KB)])
    uploader.add([file('later.pdf', 5 * KB)])
    const later = uploader.getSnapshot().find((e) => e.name === 'later.pdf')!
    uploader.cancel(later.id)
    // Nothing waits in the way of the first one any more; release it.
    for (let i = 0; i < 100 && !release; i++) await new Promise((resolve) => setTimeout(resolve, 5))
    release?.()
    const entries = await settle(uploader)
    expect(entries.map((e) => [e.name, e.phase])).toEqual([['large.pdf', 'exists'], ['later.pdf', 'cancelled']])
    expect(api.send).not.toHaveBeenCalled()
  })
})

describe('where files go and where they came from', () => {
  it('names the vault and the source, and never mixes two places in one request', async () => {
    const uploader = new Uploader(config)
    let release: () => void = () => undefined
    const held = new Promise<void>((resolve) => (release = resolve))
    api.send.mockImplementation(async (files: File[]) => {
      if (files[0].name === 'first.pdf') await held
      return { items: files.map((item, index) => accepted(item.name, index + 1)) }
    })
    // While the first request is on its way, three files wait: two for one vault, one from the camera.
    uploader.add([file('first.pdf', 10 * KB)])
    uploader.add([file('a.pdf', 10 * KB), file('b.pdf', 10 * KB)], { vaultId: 9 })
    uploader.add([file('scan.pdf', 10 * KB)], { source: 'camera' })
    release()
    await settle(uploader)
    expect(api.send.mock.calls.map((call) => call[0].map((item: File) => item.name))).toEqual([['first.pdf'], ['a.pdf', 'b.pdf'], ['scan.pdf']])
    expect(api.send.mock.calls[1][2]).toEqual({ vaultId: 9 })
    expect(api.send.mock.calls[2][2]).toEqual({ source: 'camera' })
  })

  it('carries them into an upload in pieces', async () => {
    const uploader = new Uploader(config)
    const big = file('gross.pdf', 150 * KB)
    api.start.mockResolvedValue({ exists: true, upload: null, document: { id: 4, title: 'gross', status: 'inbox' } })
    uploader.add([big], { vaultId: 9, source: 'share' })
    await settle(uploader)
    expect(api.start.mock.calls[0][3]).toEqual({ vaultId: 9, source: 'share' })
  })
})
