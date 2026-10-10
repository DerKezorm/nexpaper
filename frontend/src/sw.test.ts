/**
 * The service worker itself (`public/sw.js`), run against a stand-in of its surroundings: a push shows as a
 * notification, and a tap opens a path of nexpaper and never another site, whatever the message says. Browsers drop
 * tabs and line breaks from an address before they read it; those tricks are among the cases.
 */
import source from '../public/sw.js?raw'

const ORIGIN = 'https://paper.example.com'

type Handler = (event: unknown) => void

async function tap(url: unknown, agent = 'Mozilla/5.0 (iPhone)'): Promise<{ data: { url: string }; opened: string[] }> {
  const handlers: Record<string, Handler> = {}
  const shown: { title: string; options: { data: { url: string } } }[] = []
  const opened: string[] = []
  const self = {
    addEventListener: (type: string, handler: Handler) => (handlers[type] = handler),
    skipWaiting() {},
    clients: { claim() {}, matchAll: async () => [], openWindow: async (address: string) => opened.push(address) },
    registration: { showNotification: async (title: string, options: { data: { url: string } }) => shown.push({ title, options }) },
    navigator: { userAgent: agent },
    location: { origin: ORIGIN },
  }
  new Function('self', 'URL', source)(self, URL)
  let pending: Promise<unknown> = Promise.resolve()
  handlers.push({ data: { json: () => ({ title: 'nexpaper', body: 'Wie war dein Tag?', url, desk: url, tag: 'x' }) }, waitUntil: (work: Promise<unknown>) => (pending = work) })
  await pending
  handlers.notificationclick({ notification: { data: shown[0].options.data, close() {} }, waitUntil: (work: Promise<unknown>) => (pending = work) })
  await pending
  return { data: shown[0].options.data, opened }
}

describe('the service worker', () => {
  it('opens a path of nexpaper where a tap leads', async () => {
    const { opened } = await tap('/schnell?x=1')
    expect(opened).toEqual([ORIGIN + '/schnell?x=1'])
  })

  it.each([
    'https://evil.example.org/x',
    '//evil.example.org',
    '/\t/evil.example.org/x',
    '/\n/evil.example.org',
    '/\r/evil.example.org',
    '/\\evil.example.org',
    'javascript:alert(1)',
    '/\u007f/evil.example.org',
    42,
  ])('never leads elsewhere: %j', async (url) => {
    const { data, opened } = await tap(url)
    expect(data.url).toBe('/')
    expect(opened).toEqual([ORIGIN + '/'])
  })
})

/** A stand-in of the worker's `Response`: what it holds, its headers, and the redirect (the runtime's own would want
 * the runtime's own kind of file, which jsdom's is not under every Node). */
class FakeResponse {
  headers: Headers
  status: number
  constructor(public body: unknown, init: { headers?: Record<string, string>; status?: number } = {}) {
    this.headers = new Headers(init.headers)
    this.status = init.status ?? 200
  }
  static redirect(url: string, status: number) {
    return new FakeResponse(null, { status, headers: { location: url } })
  }
}

type Shared = { location: string | null; status: number; stored: { url: string; name: string; type: string }[]; handled: boolean }

async function share(method: string, url: string, files: File[], extra: Record<string, unknown> = {}): Promise<Shared> {
  const handlers: Record<string, Handler> = {}
  const stored: { url: string; name: string; type: string }[] = []
  const cache = {
    keys: async () => [new Request(ORIGIN + '/teilen/old/0?at=1')],
    delete: async () => true,
    put: async (key: string, response: FakeResponse) =>
      stored.push({ url: key, name: decodeURIComponent(response.headers.get('X-Name') ?? ''), type: response.headers.get('Content-Type') ?? '' }),
  }
  const self = {
    addEventListener: (type: string, handler: Handler) => (handlers[type] = handler),
    skipWaiting() {},
    clients: { claim() {} },
    caches: { open: async () => cache },
    crypto: globalThis.crypto,
    location: { origin: ORIGIN },
    navigator: { userAgent: 'Android' },
    ...extra,
  }
  new Function('self', 'URL', 'Response', source)(self, URL, FakeResponse)
  const form = { getAll: (name: string) => (name === 'files' ? files : []) }
  let answer: Promise<FakeResponse> | null = null
  handlers.fetch({ request: { method, url, formData: async () => form }, respondWith: (work: Promise<FakeResponse>) => (answer = work) })
  if (!answer) return { location: null, status: 0, stored, handled: false }
  const response = await (answer as Promise<FakeResponse>)
  return { location: response.headers.get('location'), status: response.status, stored, handled: true }
}

describe('files shared from another app', () => {
  it('are kept on the phone and the page is opened to upload them', async () => {
    const found = await share('POST', ORIGIN + '/teilen', [new File(['%PDF'], 'Rechnung März.pdf', { type: 'application/pdf' }), new File(['x'], 'Beleg.jpg', { type: 'image/jpeg' })])
    expect(found.status).toBe(303)
    const id = /share=([0-9a-f]{32})$/.exec(found.location ?? '')![1]
    expect(found.location).toBe(`${ORIGIN}/teilen?share=${id}`)
    expect(found.stored.map((item) => [new URL(item.url).pathname, item.name, item.type])).toEqual([
      [`/teilen/${id}/0`, 'Rechnung März.pdf', 'application/pdf'],
      [`/teilen/${id}/1`, 'Beleg.jpg', 'image/jpeg'],
    ])
  })

  it('without a file the page says so', async () => {
    const found = await share('POST', ORIGIN + '/teilen', [])
    expect(found.location).toBe(`${ORIGIN}/teilen?missed=1`)
  })

  it('leaves every other request alone', async () => {
    expect((await share('GET', ORIGIN + '/teilen', [])).handled).toBe(false)
    expect((await share('POST', ORIGIN + '/api/v1/documents', [])).handled).toBe(false)
    expect((await share('POST', 'https://evil.example.org/teilen', [])).handled).toBe(false)
  })

  it('takes at most twenty files', async () => {
    const many = Array.from({ length: 25 }, (_, index) => new File(['x'], `${index}.pdf`, { type: 'application/pdf' }))
    expect((await share('POST', ORIGIN + '/teilen', many)).stored).toHaveLength(20)
  })
})
