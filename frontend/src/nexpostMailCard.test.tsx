// @vitest-environment jsdom
/**
 * Since post 1.1.0: the card "Mail" of the module in the app (page Server › Mail): built from the ui kit, the fields,
 * words, kinds and symbols of the plan in German, English and French; the port follows the encryption, the password
 * stays unless typed, the warning without encryption, "Testmail an" with "Senden" level with the field, the lines
 * under it. Copied once by bauplaene/post/tools/sync.py to `frontend/src/nexpostMailCard.test.tsx`; then the app's
 * file. Fill in the places marked APP. Needs react-dom, both in every app.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { NexuiLanguage } from './vendor/nexui'
import { MailCard } from './vendor/nexpost/MailCard'
import type { MailView, PostRequest } from './vendor/nexpost/mailserver'

// APP: where the app mounts nexpost.api.router, its name, and its sentence under the title (German).
const BASE = '/api/server/mail'
const APP = 'nexapp'
const SUBTITLE = `Der Mailserver, über den ${APP} Einladungen, Links und Benachrichtigungen verschickt.`

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Call = { path: string; method: string; body: unknown }

let root: Root
let box: HTMLDivElement
let calls: Call[]
let view: MailView
let refuse: string

const request: PostRequest = async <T,>(path: string, init: { method?: string; body?: unknown } = {}) => {
  calls.push({ path, method: init.method ?? 'GET', body: init.body })
  if (refuse && init.method) throw Object.assign(new Error('refused'), { code: refuse })
  if (path === BASE && init.method === 'PUT') {
    const change = init.body as { password: string | null } & Record<string, unknown>
    view = { ...view, ...change, password_set: change.password === null ? view.password_set : change.password !== '', configured: true } as MailView
    return view as T
  }
  if (path === `${BASE}/test`) {
    view = { ...view, last_ok_at: '2026-11-25T10:00:00+00:00' }
    return undefined as T
  }
  return view as T
}

function show(language = 'de'): void {
  act(() =>
    root.render(
      <NexuiLanguage language={language}>
        <MailCard request={request} base={BASE} subtitle={SUBTITLE} when={(iso: string) => iso.slice(0, 10)} />
      </NexuiLanguage>,
    ),
  )
}

async function wait(ms = 20): Promise<void> {
  await act(async () => await new Promise((resolve) => setTimeout(resolve, ms)))
}

function type(input: HTMLInputElement, value: string): void {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function choose(select: HTMLSelectElement, value: string): void {
  act(() => {
    select.value = value
    select.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

const find = <T extends Element = HTMLElement>(selector: string) => box.querySelector<T>(selector)!
const label = (testId: string) => box.querySelector(`label[for="${find(`[data-testid="${testId}"]`).id}"]`)!.textContent

beforeEach(() => {
  calls = []
  refuse = ''
  view = {
    host: 'mail.example.com',
    port: 587,
    security: 'starttls',
    user: 'robot',
    password_set: true,
    sender: 'robot@example.com',
    sender_name: '',
    sender_name_default: APP,
    configured: true,
    warnings: [],
    last_ok_at: '2026-11-24T08:00:00+00:00',
    last_error: 'mail_unreachable',
    last_error_at: '2026-11-24T09:00:00+00:00',
    waiting: 2,
  }
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
})

describe('the card Mail', () => {
  it('has the fields of the plan in their order with the words of the plan', async () => {
    show()
    await wait()
    const card = find('[data-card="mail"]')
    expect(card.querySelector('h2')!.textContent).toBe('Mail')
    expect(card.textContent).toContain(SUBTITLE)
    const fields = ['mail-server', 'mail-port', 'mail-security', 'mail-user', 'mail-password', 'mail-sender', 'mail-sender-name'].map(label)
    expect(fields).toEqual(['Server', 'Port', 'Verschlüsselung', 'Benutzer', 'Passwort', 'Absender', 'Absendername'])
    expect([...find<HTMLSelectElement>('[data-testid="mail-security"]').options].map((option) => option.textContent)).toEqual(['STARTTLS', 'TLS', 'keine'])
    expect(find<HTMLInputElement>('[data-testid="mail-password"]').placeholder).toBe('Bleibt; nur zum Ändern tippen.')
    expect(find<HTMLInputElement>('[data-testid="mail-sender-name"]').placeholder).toBe(APP)
    const save = find('[data-testid="mail-save"]')
    expect([save.getAttribute('data-kind'), save.getAttribute('data-icon'), save.textContent]).toEqual(['primary', 'Check', 'Speichern'])
    expect(label('mail-test-to')).toBe('Testmail an')
    const send = find('[data-testid="mail-test"]')
    expect([send.getAttribute('data-kind'), send.getAttribute('data-icon'), send.textContent]).toEqual(['secondary', 'Send', 'Senden'])
    expect(send.closest('[data-part="field-action"]')).not.toBeNull()
  })

  it('shows the last mail sent, the last error and the mails waiting', async () => {
    show()
    await wait()
    expect([...find('[data-testid="mail-status"]').querySelectorAll('p')].map((line) => line.textContent)).toEqual([
      'Zuletzt verschickt: 2026-11-24',
      'Letzter Fehler (2026-11-24): Der Mailserver ist nicht erreichbar.',
      'Wartende Mails: 2',
    ])
  })

  it('lets the port follow the encryption until one is typed, and warns without encryption', async () => {
    show()
    await wait()
    const port = find<HTMLInputElement>('[data-testid="mail-port"]')
    choose(find<HTMLSelectElement>('[data-testid="mail-security"]'), 'tls')
    expect(port.value).toBe('465')
    expect(box.querySelector('[data-testid="mail-warning"]')).toBeNull()
    choose(find<HTMLSelectElement>('[data-testid="mail-security"]'), 'none')
    expect(port.value).toBe('25')
    expect(find('[data-testid="mail-warning"]').textContent).toContain('Ohne Verschlüsselung')
    type(port, '2525')
    choose(find<HTMLSelectElement>('[data-testid="mail-security"]'), 'starttls')
    expect(port.value).toBe('2525')
  })

  it('saves the password only when one is typed', async () => {
    show()
    await wait()
    type(find<HTMLInputElement>('[data-testid="mail-sender-name"]'), 'Robot')
    act(() => find<HTMLButtonElement>('[data-testid="mail-save"]').click())
    await wait()
    const first = calls.find((call) => call.method === 'PUT')!
    expect(first.body).toMatchObject({ host: 'mail.example.com', port: 587, security: 'starttls', sender_name: 'Robot', password: null })
    expect(find('[data-testid="mail-done"]').textContent).toBe('Gespeichert.')
    type(find<HTMLInputElement>('[data-testid="mail-password"]'), 'new-secret')
    act(() => find<HTMLButtonElement>('[data-testid="mail-save"]').click())
    await wait()
    expect(calls.filter((call) => call.method === 'PUT').at(-1)!.body).toMatchObject({ password: 'new-secret' })
    expect(find<HTMLInputElement>('[data-testid="mail-password"]').value).toBe('')
  })

  it('sends the test mail in the page language and says why when it fails', async () => {
    show()
    await wait()
    const send = find<HTMLButtonElement>('[data-testid="mail-test"]')
    expect(send.disabled).toBe(true)
    type(find<HTMLInputElement>('[data-testid="mail-test-to"]'), 'kim@example.org')
    act(() => send.click())
    await wait()
    expect(calls.find((call) => call.method === 'POST')).toEqual({ path: `${BASE}/test`, method: 'POST', body: { to: 'kim@example.org', language: 'de' } })
    expect(find('[data-testid="mail-done"]').textContent).toBe('Die Testmail ist an kim@example.org raus.')
    refuse = 'mail_auth_refused'
    act(() => send.click())
    await wait()
    expect(find('[data-testid="mail-problem"]').textContent).toBe('Der Mailserver hat Benutzer oder Passwort abgelehnt.')
  })

  it('speaks English and French', async () => {
    show('en')
    await wait()
    expect(label('mail-sender')).toBe('Sender')
    expect(find('[data-testid="mail-test"]').textContent).toBe('Send')
    act(() => root.unmount())
    root = createRoot(box)
    show('fr')
    await wait()
    expect(find('[data-testid="mail-save"]').textContent).toBe('Enregistrer')
  })
})
