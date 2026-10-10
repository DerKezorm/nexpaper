/**
 * The queue of page pictures: at most two asked for at once (as many as the server draws for one person), a busy answer
 * asked again after exactly the time `Retry-After` names, a document still being read asked again later, a picture
 * that is not there given up at once, and a fetched one kept for the tab.
 */
import { AT_ONCE, PictureError, forgetPictures, loadPicture, retryAfterMs, timing } from './pictures'

type Held = { url: string; answer: (response: Response) => void }

let held: Held[] = []
let waits: number[] = []

function hold(): void {
  held = []
  vi.stubGlobal('fetch', vi.fn((url: string) => new Promise<Response>((resolve) => held.push({ url, answer: resolve }))))
}

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i++) await Promise.resolve()
  await new Promise((resolve) => setTimeout(resolve, 0))
}

beforeEach(() => {
  forgetPictures()
  waits = []
  vi.spyOn(timing, 'sleep').mockImplementation(async (ms: number) => {
    waits.push(ms)
  })
  hold()
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('the pictures of pages', () => {
  it('are asked for two at a time, the next when one is done', async () => {
    const all = [1, 2, 3, 4].map((n) => loadPicture(`/p/${n}`))
    await settle()
    expect(held.map((h) => h.url)).toEqual(['/p/1', '/p/2'])
    expect(AT_ONCE).toBe(2)
    held[0].answer(new Response('a', { status: 200 }))
    await settle()
    expect(held.map((h) => h.url)).toEqual(['/p/1', '/p/2', '/p/3'])
    for (const h of held.slice(1)) h.answer(new Response('b', { status: 200 }))
    await settle()
    held[3].answer(new Response('c', { status: 200 }))
    await Promise.all(all)
    expect(held).toHaveLength(4)
  })

  it('wait as long as the server says when it is busy, and then come', async () => {
    const one = loadPicture('/p/busy')
    await settle()
    held[0].answer(new Response(JSON.stringify({ detail: { code: 'busy' } }), { status: 503, headers: { 'Retry-After': '5' } }))
    await settle()
    expect(waits).toEqual([5000])
    expect(held).toHaveLength(2)
    held[1].answer(new Response('img', { status: 200 }))
    await expect(one).resolves.toBeTruthy()
  })

  it('wait while the document is still being read, and give up at once on one that is not there', async () => {
    const reading = loadPicture('/p/reading')
    await settle()
    held[0].answer(new Response('{}', { status: 409 }))
    await settle()
    expect(waits).toEqual([4000])
    held[1].answer(new Response('img', { status: 200 }))
    await reading
    const missing = loadPicture('/p/missing')
    await settle()
    held[2].answer(new Response('{}', { status: 404 }))
    await expect(missing).rejects.toEqual(new PictureError(404))
    expect(waits).toEqual([4000])
  })

  it('stop after a few tries of a server that stays busy', async () => {
    const never = loadPicture('/p/never')
    for (let n = 0; n < 8; n++) {
      await settle()
      held[n].answer(new Response('{}', { status: 503 }))
    }
    await expect(never).rejects.toEqual(new PictureError(503))
    expect(waits).toHaveLength(7)
  })

  it('are kept for the tab: the same address is not asked again', async () => {
    const first = loadPicture('/p/kept')
    await settle()
    held[0].answer(new Response('img', { status: 200 }))
    const made = await first
    await expect(loadPicture('/p/kept')).resolves.toBe(made)
    expect(held).toHaveLength(1)
  })

  it('read Retry-After in seconds, within half a second and half a minute', () => {
    expect(retryAfterMs('5', 1000)).toBe(5000)
    expect(retryAfterMs('0', 1000)).toBe(500)
    expect(retryAfterMs('3600', 1000)).toBe(30000)
    expect(retryAfterMs(null, 1500)).toBe(1500)
    expect(retryAfterMs('soon', 2000)).toBe(2000)
  })
})
