/**
 * A page picture loads when it comes near the screen and, while it is not there yet, gives its place in the queue up
 * when it is scrolled away (a strip of ninety pages): asked for again when it comes back.
 */
import { act } from 'react'

import { forgetPictures } from '../lib/pictures'
import { Page } from '../test/harness'
import { PagePicture } from './PagePicture'

const page = new Page()
let notify: (seen: boolean) => void = () => undefined

class Watcher {
  constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
    notify = (seen) => callback([{ isIntersecting: seen }])
  }
  observe() {}
  disconnect() {}
}

beforeEach(() => {
  forgetPictures()
  vi.stubGlobal('IntersectionObserver', Watcher)
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('a page picture', () => {
  it('is fetched when it comes near, let go when it is scrolled away before it came, and fetched again', async () => {
    const signals: AbortSignal[] = []
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => {
      signals.push(init!.signal!)
      return new Promise<Response>(() => undefined)
    }))
    await page.show(<PagePicture src="/api/v1/documents/5/versions/1/pages/40?size=small" alt="" />)
    expect(signals).toHaveLength(0)
    await act(async () => notify(true))
    expect(signals).toHaveLength(1)
    await act(async () => notify(false))
    expect(signals[0].aborted).toBe(true)
    await act(async () => notify(true))
    expect(signals).toHaveLength(2)
  })
})
