/**
 * What the tests of the pages share: a stand-in of the server (`Server`, answers by `METHOD /path`), a page shown in a
 * router, and the few things a test does to it (find a button, click, type).
 */
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

import '../i18n'
import { idle } from './wait'

export type Call = { method: string; url: string; body: Record<string, unknown> | undefined }

/** A text without the isolating marks around a person's text (U+2068, U+2069). */
export function plain(text: string | null | undefined): string {
  return (text ?? '').split(String.fromCharCode(0x2068)).join('').split(String.fromCharCode(0x2069)).join('')
}

/** The first page of the inbox, as the page asks for it, and the answer for some documents (the server's counting done here). */
export const INBOX = 'GET /api/v1/inbox?sort=new&limit=50'
export function inboxOf<T extends { vault_id: number; status: string }>(items: T[]): { items: T[]; total: number; counts: Record<string, number>; all: number; reading: number } {
  const counts: Record<string, number> = {}
  for (const d of items) counts[String(d.vault_id)] = (counts[String(d.vault_id)] ?? 0) + 1
  return { items, total: items.length, counts, all: items.length, reading: items.filter((d) => d.status === 'processing').length }
}

export class Server {
  calls: Call[] = []
  answers: Record<string, unknown> = {}
  fails: Record<string, { status: number; code: string; values?: Record<string, unknown> }> = {}

  install(): void {
    this.calls = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET'
        const body = init?.body ? JSON.parse(String(init.body)) : undefined
        this.calls.push({ method, url, body })
        const failed = this.fails[`${method} ${url}`]
        if (failed) return new Response(JSON.stringify({ detail: { code: failed.code, ...failed.values } }), { status: failed.status, headers: { 'Content-Type': 'application/json' } })
        const found = this.answers[`${method} ${url}`]
        if (found === 204) return new Response(null, { status: 204 })
        return new Response(JSON.stringify(found ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
      }),
    )
  }

  /** The calls that changed something, as `METHOD url`. */
  changes(): string[] {
    return this.calls.filter((c) => c.method !== 'GET').map((c) => `${c.method} ${c.url}`)
  }

  called(method: string, url: string): Call | undefined {
    return this.calls.find((c) => c.method === method && c.url === url)
  }
}

export class Page {
  root!: Root
  box!: HTMLDivElement

  async show(element: ReactNode, at = '/'): Promise<void> {
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    this.box = document.createElement('div')
    document.body.appendChild(this.box)
    this.root = createRoot(this.box)
    await act(async () => this.root.render(<MemoryRouter initialEntries={[at]}>{element}</MemoryRouter>))
    await idle()
  }

  close(): void {
    act(() => this.root.unmount())
    this.box.remove()
  }

  /** The text of the page as a person reads it: without the invisible marks that keep a person's text apart from the
   * sentence around it (`lib/say.ts`, `iso`). */
  get text(): string {
    return plain(document.body.textContent ?? '')
  }

  button(text: string, within: ParentNode = document.body): HTMLButtonElement | undefined {
    return [...within.querySelectorAll<HTMLButtonElement>('button')].find((item) => item.textContent?.trim() === text || item.getAttribute('aria-label') === text)
  }

  async click(target: HTMLElement | undefined | null): Promise<void> {
    expect(target).toBeTruthy()
    await act(async () => target!.click())
    await idle()
  }

  async type(input: HTMLInputElement | HTMLTextAreaElement | null | undefined, value: string): Promise<void> {
    expect(input).toBeTruthy()
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value')!.set!
    await act(async () => {
      setter.call(input, value)
      input!.dispatchEvent(new Event('input', { bubbles: true }))
      input!.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await idle()
  }

  async check(input: HTMLInputElement | null | undefined): Promise<void> {
    await this.click(input)
  }

  /** The dialog that stands on top (the last one drawn). */
  get dialog(): HTMLElement | null {
    const all = document.body.querySelectorAll<HTMLElement>('[role="dialog"]')
    return all.length ? all[all.length - 1] : null
  }

  /** Presses a button of the dialog on top. */
  async inDialog(text: string): Promise<void> {
    const dialog = this.dialog
    expect(dialog).toBeTruthy()
    await this.click(this.button(text, dialog!))
  }

  select(label: string): HTMLSelectElement | null {
    return document.body.querySelector<HTMLSelectElement>(`select[aria-label="${label}"]`)
  }

  async choose(select: HTMLSelectElement | null, value: string): Promise<void> {
    expect(select).toBeTruthy()
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
    await act(async () => {
      setter.call(select, value)
      select!.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await idle()
  }
}
