// Vorlage nexoidc 1.2.0
// @vitest-environment jsdom
/**
 * Since 1.2.0: the cards "Sign-in providers" and "authentik in one step" (``SignInProviders.tsx``) in the app: built
 * from the ui kit, as nexnotes had them, with the buttons the plan "Einstellungen" names (the grip, small "Edit" and
 * "Remove", "Add provider"), the app's placeholders and no coupling. Copied once by bauplaene/oidc/tools/sync.py to
 * ``frontend/src/nexoidc.cards.test.tsx``; then the app's file. Fill in the places marked APP.
 */
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NexuiLanguage } from './vendor/nexui'
import { SignInProviders, type OidcAdminCalls, type OidcProviderRow, type Translate } from './vendor/nexoidc/SignInProviders'
import { AUTHENTIK_STEPS, issuerPlaceholder, oidcVariables } from './vendor/nexoidc/oidc'
import german from './vendor/nexoidc/oidc.de.json'

// APP: the app's name and where its API lives (nexpaper '/api/v1').
const APP = 'nexnotes'
const API = '/api'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

function leaves(tree: Record<string, unknown>, prefix = ''): Record<string, string> {
  const found: Record<string, string> = {}
  for (const [name, value] of Object.entries(tree)) {
    const key = prefix ? `${prefix}.${name}` : name
    if (typeof value === 'string') found[key] = value
    else Object.assign(found, leaves(value as Record<string, unknown>, key))
  }
  return found
}

const WORDS = leaves(german)
const t: Translate = (key, values = {}) => {
  const filled: Record<string, unknown> = { ...oidcVariables(APP), ...values }
  const count = typeof filled.count === 'number' ? filled.count : null
  const text = (count !== null ? WORDS[`${key}_${count === 1 ? 'one' : 'other'}`] : undefined) ?? WORDS[key]
  if (text === undefined) throw new Error(`missing words: ${key}`)
  return text.replace(/\{\{(\w+)\}\}/g, (whole, name: string) => (name in filled ? String(filled[name]) : whole))
}

function provider(id: number, label: string, change: Partial<OidcProviderRow> = {}): OidcProviderRow {
  return {
    id,
    slug: label.toLowerCase().replace(/\s+/g, '-'),
    label,
    issuer: `https://${label.toLowerCase().replace(/\s+/g, '')}.example.com/`,
    client_id: 'client',
    has_secret: true,
    scopes: 'openid profile email',
    enabled: true,
    auto_create: false,
    trusts_second_factor: true,
    managed: '',
    redirect_uri: `https://notes.example.com${API}/oidc/x/callback`,
    links: 0,
    editable: true,
    ...change,
  }
}

let root: Root
let box: HTMLDivElement
let listed: OidcProviderRow[]
let calls: OidcAdminCalls

beforeEach(() => {
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  listed = [provider(1, 'Pocket ID'), provider(2, 'authentik', { managed: 'authentik', enabled: false })]
  calls = {
    providers: vi.fn(async () => listed),
    add: vi.fn(async () => undefined),
    save: vi.fn(async () => undefined),
    remove: vi.fn(async () => undefined),
    impact: vi.fn(async () => ({ issuer_change: 0, count: 1, only: 0 })),
    order: vi.fn(async () => undefined),
    authentik: vi.fn(async () => ({ ok: true, steps: [{ key: 'reached', ok: true }] })),
    authentikAddress: vi.fn(async () => ({
      public_url: 'https://notes.example.com',
      seen: 'https://notes.example.com',
      forwarded_proto: '',
      forwarded_host: '',
      proxy_ignored: false,
      callback_path: `${API}/oidc/authentik/callback`,
      redirect_uri: '',
      registered_redirect_uri: '',
      stale: false,
    })),
    authentikSaveAddress: vi.fn(),
  }
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  document.body.innerHTML = ''
})

async function show(node: ReactNode): Promise<void> {
  await act(async () => root.render(<NexuiLanguage language="de">{node}</NexuiLanguage>))
}

async function cards(): Promise<void> {
  await show(<SignInProviders t={t} app={APP} apiPrefix={API} calls={calls} errorOf={() => null} publicUrl="https://notes.example.com" onAddress={() => undefined} />)
}

function buttons(text: string): HTMLButtonElement[] {
  return [...document.querySelectorAll('button')].filter((entry) => entry.textContent?.trim() === text)
}

describe('Sign-in providers and authentik (oidc 1.2.0)', () => {
  it('lists each provider with the grip, its badges and small buttons, and adds with a primary button', async () => {
    await cards()
    expect([...document.querySelectorAll('[data-card]')].map((card) => card.getAttribute('data-card'))).toEqual(['sign-in-providers', 'sign-in-authentik'])
    const rows = document.querySelectorAll('[data-testid="provider-list"] li')
    expect(rows).toHaveLength(2)
    const grip = rows[0]?.querySelector('button[data-icon="GripVertical"]')
    expect(grip?.getAttribute('aria-label')).toBe('Pocket ID verschieben: ziehen oder die Pfeiltasten')
    expect(rows[0]?.textContent).toContain('aktiv')
    expect(rows[1]?.textContent).toContain('aus')
    expect(rows[1]?.textContent).toContain('über authentik eingerichtet')
    for (const [text, kind, icon] of [
      ['Bearbeiten', 'secondary', 'Pencil'],
      ['Entfernen', 'danger', 'Trash2'],
    ] as const) {
      const found = buttons(text)
      expect(found).toHaveLength(2)
      for (const entry of found) expect([entry.dataset.kind, entry.dataset.size, entry.dataset.icon]).toEqual([kind, 'sm', icon])
    }
    const add = buttons('Anbieter hinzufügen')[0]
    expect([add?.dataset.kind, add?.dataset.size, add?.dataset.icon]).toEqual(['primary', 'md', 'Plus'])
  })

  it('moves a provider with the arrow keys on its grip', async () => {
    await cards()
    const grip = document.querySelector('[data-testid="provider-list"] li button[data-icon="GripVertical"]') as HTMLButtonElement
    await act(async () => {
      grip.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    })
    expect(calls.order).toHaveBeenCalledWith([2, 1])
  })

  it('a provider the app cannot change makes the list read only', async () => {
    listed = [provider(1, 'Pocket ID'), provider(2, 'Fremd', { editable: false })]
    await cards()
    expect(document.querySelector('button[data-icon="GripVertical"]')).toBeNull()
    expect(buttons('Anbieter hinzufügen')).toHaveLength(0)
    expect(buttons('Bearbeiten')).toHaveLength(1)
  })

  it('asks before removing, with the number of accounts', async () => {
    await cards()
    await act(async () => buttons('Entfernen')[0]?.click())
    expect(calls.impact).toHaveBeenCalledWith(1)
    expect(document.body.textContent).toContain('„Pocket ID“ entfernen? 1 Konto verliert die Verknüpfung')
    const confirm = buttons('Entfernen').find((entry) => entry.dataset.size === 'md')
    await act(async () => confirm?.click())
    expect(calls.remove).toHaveBeenCalledWith(1)
  })

  it('the form shows the placeholder of the app and the redirect under its prefix', async () => {
    await cards()
    await act(async () => buttons('Anbieter hinzufügen')[0]?.click())
    const dialog = document.querySelector('[data-testid="provider-dialog"]') as HTMLElement
    const issuer = [...dialog.querySelectorAll('input')].find((entry) => entry.placeholder.startsWith('https://auth.'))
    expect(issuer?.placeholder).toBe(issuerPlaceholder(APP))
    expect(dialog.textContent).toContain(t('oidc.admin.redirect'))
    expect([...dialog.querySelectorAll('input')].some((entry) => entry.value.endsWith(`${API}/oidc/…/callback`))).toBe(true)
    for (const entry of dialog.querySelectorAll('button[data-kind]')) expect(['primary', 'secondary', 'danger']).toContain(entry.getAttribute('data-kind'))
  })

  it('authentik: the button sets up, the blueprint is a link under the prefix, nothing of a coupling', async () => {
    await cards()
    expect(document.querySelector('[data-testid="authentik-blueprint"]')?.getAttribute('href')).toBe(`${API}/oidc/authentik/blueprint`)
    expect(document.body.textContent).not.toContain(t('oidc.authentik.why.coupled'))
    const run = document.querySelector('[data-testid="authentik-run"]') as HTMLButtonElement
    expect([run.dataset.kind, run.dataset.icon, run.disabled]).toEqual(['primary', 'Sparkles', true])
  })

  it('names Edit and Remove of each row "<action>: <provider>" (as before 1.2.0, since E37), the words unchanged', async () => {
    await cards()
    for (const [action, words] of [['oidc.admin.edit', 'Bearbeiten'], ['oidc.admin.remove', 'Entfernen']] as const) {
      const found = buttons(words)
      expect(found.map((entry) => entry.getAttribute('aria-label'))).toEqual([`${t(action)}: Pocket ID`, `${t(action)}: authentik`])
      expect(found[0]?.getAttribute('aria-label')).toBe(`${words}: Pocket ID`)
    }
  })

  // Since E33 (found in nextasks): the token goes after a run that worked all through, stays after a failure, and a
  // run that stops at another issuer only asks, without a line of steps behind the question.
  async function runAuthentik(): Promise<HTMLInputElement> {
    await cards()
    const url = document.querySelector('input[placeholder="https://auth.example.com"]') as HTMLInputElement
    const token = [...document.querySelectorAll<HTMLInputElement>('[data-card="sign-in-authentik"] input[type="password"]')].at(-1)
    if (!token) throw new Error('no token field')
    await act(async () => {
      for (const [field, value] of [[url, 'https://auth.example.com'], [token, 'the-token']] as const) {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(field, value)
        field.dispatchEvent(new Event('input', { bubbles: true }))
      }
    })
    await act(async () => (document.querySelector('[data-testid="authentik-run"]') as HTMLButtonElement).click())
    for (let i = 0; i < 6; i++) await act(async () => await Promise.resolve())
    return token
  }

  const rows = () => [...document.querySelectorAll('[data-testid="authentik-steps"] li')]

  it('authentik: after a run that worked all through the token goes, even when the answer names only the steps', async () => {
    for (const answer of [
      { ok: true, steps: AUTHENTIK_STEPS.map((key) => ({ key, ok: true })) },
      { steps: AUTHENTIK_STEPS.map((key) => ({ key, ok: true })) },
    ]) {
      calls.authentik = vi.fn(async () => answer as Awaited<ReturnType<OidcAdminCalls['authentik']>>)
      const token = await runAuthentik()
      expect(rows()).toHaveLength(AUTHENTIK_STEPS.length)
      expect(token.value).toBe('')
      act(() => root.unmount())
      root = createRoot(box)
    }
  })

  it('authentik: a step that failed keeps the token and says why', async () => {
    calls.authentik = vi.fn(async () => ({ ok: false, steps: [{ key: 'reached', ok: true }, { key: 'signingKey', ok: false, reason: 'token', status: 403 }] }))
    const token = await runAuthentik()
    expect(rows()).toHaveLength(2)
    expect(rows()[1]?.textContent).toContain(t('oidc.authentik.why.token', { status: 403 }))
    expect(token.value).toBe('the-token')
  })

  it('authentik: another issuer only asks, with no line of steps behind the question', async () => {
    calls.authentik = vi.fn(async () => ({ ok: false, count: 3, steps: [{ key: 'reached', ok: false, reason: 'issuer_change', status: 0 }] }))
    const token = await runAuthentik()
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain(t('oidc.admin.issuerChangeConfirm', { count: 3 }))
    expect(document.querySelector('[data-testid="authentik-steps"]')).toBeNull()
    expect(rows()).toEqual([])
    expect(token.value).toBe('the-token')
  })
})
