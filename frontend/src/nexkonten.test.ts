// Vorlage nexkonten 1.1.0
/**
 * Every text of the konten module is in the app, in German and English, through the app's own i18n, and the screens
 * show the module's fields in the module's order. Copied once by the module's `tools/sync.py` to
 * `frontend/src/nexkonten.test.ts`; then the app's file. Fill in the places marked APP.
 *
 * The module's own tests check the wording files word for word against the blueprint; this test checks that the
 * app really loads them (merged into its resources, `{{app}}`, `{{setupTokenEnv}}` and `{{minimum}}` filled in
 * through kontenVariables) and that nothing in the app overrides them. Since 0.3.7 it shows the app's screens
 * (APP_RENDER) and checks that every field is found by exactly its label and that the profile saves with one button;
 * this needs `@testing-library/dom` among the app's devDependencies and vitest's `environment: 'jsdom'`. Since 1.0.0
 * all helpers stand in one section before the first block: a block taken over later needs only that section.
 *
 * nexpaper shows its screens with a stand-in of the signed-in state (`state/auth`) and of the server (a stubbed
 * `fetch` answering by `METHOD /path`), the page at its address.
 */
import { fireEvent, getAllByRole, getByLabelText, queryByRole } from '@testing-library/dom'
import { act, createElement, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { AccountRow, Me } from './api/client'
import { ForgotPage, InvitePage, LoginPage, ResetPage, SetupPage } from './pages/AuthPages'
import { AccountArea } from './pages/settings/AccountArea'
import { AccountsTab } from './pages/settings/AccountsTab'
import { APP_CAPS as SHOWN_CAPS, appOwnActions } from './pages/settings/accountList'
import { idle } from './test/wait'
import {
  ACCOUNT_NAMESPACE,
  accountActions,
  BUTTONS,
  FIELDS,
  kontenVariables,
  MANAGE_DIALOG,
  MANAGE_GROUPS,
  NOT_ON_SELF,
  PAGES,
  pageOrder,
  passwordChanged,
  SCREENS,
  screenFields,
  suggestUsername,
} from './vendor/nexkonten/konten'
import type { AccountCaps, AccountField, ListedAccount, OwnAction } from './vendor/nexkonten/konten'
import de from './vendor/nexkonten/konten.de.json'
import en from './vendor/nexkonten/konten.en.json'
// APP: the app's i18n instance after its set-up (with the module's files merged into the resources and
// interpolation.defaultVariables: kontenVariables(APP_NAME)).
import i18n from './i18n'

// APP: the app's name as its container is called.
const APP_NAME = 'nexpaper'
// APP: the fields each screen of the app shows, top to bottom, by the module's field names (screenFields).
const APP_SCREENS: Partial<Record<keyof typeof SCREENS, readonly string[]>> = {
  setup: SCREENS.setup,
  invite: SCREENS.invite,
  login: SCREENS.login,
  forgot: SCREENS.forgot,
  reset: SCREENS.reset,
  profile: SCREENS.profile,
}

// APP (since 0.3.6): the parts of the app's pages "Profile" and "Security", top to bottom, by the module's part names
// (PAGES), then the app's own parts, which always come after the module's. nexpaper's own: signing out (profile); the
// sign-in providers (security).
const APP_PAGES: Record<keyof typeof PAGES, readonly string[]> = {
  profile: pageOrder('profile', ['signOut']),
  security: pageOrder('security', ['providers']),
}

/** A screen of the app shown in the document: the element that holds it, and how to take it away again. */
type Shown = { root: HTMLElement; unmount: () => void }

const ME: Me = {
  id: 1, name: 'robin', display_name: 'Robin', role: 'operator', sign_in: 'password', email: 'robin@example.com',
  email_confirmed: true, email_counts: true, email_pending: '', language: 'de', oidc_linked: false, two_factor: false,
  totp: false, passkeys: 0, two_factor_recovery_left: 0, avatar: null, version: '1.13.0', whats_new_seen: '1.13.0',
  has_password: true, mail: true, mail_links: true, session_stage: 'full', passkeys_allowed: true,
  profile: { mode: 'light', quick_start: true, view: 'list', default_vault: null, timezone: 'Europe/Berlin', timezone_source: 'browser', ai: true, notify_login: true, deadlines: true },
}
const ROWS: AccountRow[] = [
  { ...ME, locked: false, blocked: false, blocked_at: null, has_password: true, email_duplicate: false, self: true, documents: 3, created_at: '2026-11-01T08:00:00Z', last_seen_at: '2026-11-25T08:00:00Z', ai_allowed: true },
  { ...ME, id: 2, name: 'kim', display_name: 'Kim', role: 'member', email: 'kim@example.com', locked: false, blocked: false, blocked_at: null, has_password: true, email_duplicate: false, self: false, documents: 12, created_at: '2026-11-02T08:00:00Z', last_seen_at: null, ai_allowed: true, totp: true },
]

const auth = { status: 'signedOut' as string, me: null as Me | null, setMe: vi.fn(), refresh: vi.fn(async () => undefined), signOut: vi.fn(async () => undefined) }
vi.mock('./state/auth', () => ({ useAuth: () => auth, safeNext: (next: string | null) => next ?? '/' }))

const TOKEN = 'abcdefghijklmnopqrstuvwxyz'
/** What the stand-in server answers, by `METHOD /path` (lists empty where a page asks for one). */
const ANSWERS: Record<string, unknown> = {
  'GET /api/v1/setup': { needs_setup: true, code_required: true, signed_in: false, version: '1.13.0', min_password: 12, factor_required: false },
  'GET /api/v1/auth/methods': { password: true, providers: [], passkeys: false, forgot: true, session_days: 30 },
  [`GET /api/v1/invite/${TOKEN}`]: { min_password: 12, signed_in_as: null, display_name: '', name: '', email: '' },
  [`GET /api/v1/reset/${TOKEN}`]: { name: 'kim', display_name: 'Kim', min_password: 12 },
  'GET /api/v1/accounts': ROWS,
  'GET /api/v1/invites': [],
  'GET /api/v1/oidc/admin/links': [],
  'GET /api/v1/oidc/me': [],
  'GET /api/v1/auth/passkeys': [],
  'GET /api/v1/auth/sessions': [],
  'GET /api/v1/locales': [],
}

/** Shows a page at an address with the stand-in server, waits until it has loaded, and gives its element. */
async function show(element: ReactNode, at: string, path = '*', status = 'signedOut'): Promise<Shown> {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  auth.status = status
  auth.me = status === 'signedIn' ? ME : null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const found = ANSWERS[`${init?.method ?? 'GET'} ${String(url).split('?')[0]}`]
      return new Response(JSON.stringify(found ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }),
  )
  const host = document.createElement('div')
  document.body.append(host)
  const react = createRoot(host)
  await act(async () =>
    react.render(createElement(MemoryRouter, { initialEntries: [at] }, createElement(Routes, null, createElement(Route, { path, element })))),
  )
  await idle()
  await idle()
  return {
    root: host,
    unmount: () => {
      act(() => react.unmount())
      host.remove()
      vi.unstubAllGlobals()
    },
  }
}

// APP (since 0.3.7): for every screen of APP_SCREENS, show it in the document as the app does (its own components,
// the server answered by the app's test helpers, e.g. a stubbed fetch), wait until it has loaded, and give its root.
// `profile` is the page "Profile" of an account with a password. In German: the tests below switch to 'de' first.
const APP_RENDER: Partial<Record<keyof typeof SCREENS, () => Promise<Shown>>> = {
  setup: () => show(createElement(SetupPage), '/setup', '*', 'setup'),
  invite: () => show(createElement(InvitePage), `/invite/${TOKEN}`, '/invite/:token'),
  login: () => show(createElement(LoginPage), '/login'),
  forgot: () => show(createElement(ForgotPage), '/forgot'),
  reset: () => show(createElement(ResetPage), `/reset/${TOKEN}`, '/reset/:token'),
  profile: () => show(createElement(AccountArea, { part: 'profile' }), '/settings/profile', '*', 'signedIn'),
}

// APP (since 0.3.8): the page "Security" of an account with a password, shown as the app does, like APP_RENDER.
const APP_PAGE_RENDER: { security?: () => Promise<Shown> } = {
  security: () => show(createElement(AccountArea, { part: 'security' }), '/settings/security', '*', 'signedIn'),
}

// APP (since 0.3.8): the text keys of the buttons the app words itself, by their role in BUTTONS (e.g. signIn: the key
// of "Sign in").
const APP_BUTTON_WORDS: Partial<Record<keyof typeof BUTTONS, string>> = {
  signOut: 'me.signOut.button',
  signIn: 'auth.login.submit',
  setupSubmit: 'auth.setup.submit',
  inviteSubmit: 'auth.invite.submit',
  resetSubmit: 'auth.reset.submit',
}

// APP (since 0.3.9): what the app's server can do for the operator in the account list (AccountCaps: rename, roles,
// emailRemove, resetLink, factorReset, signOut, unlink, blocking, remove, restore) and the app's own buttons and boxes
// in the dialog "Manage" (OwnAction).
const APP_CAPS: AccountCaps = SHOWN_CAPS
const APP_OWN: readonly OwnAction[] = appOwnActions({ ai_allowed: true })

// APP (since 0.3.9): the operator's account list, shown as the app does, like APP_RENDER: signed in as the operator,
// with the own account first and another one last (a provider "Pocket ID" linked where the app has providers).
const APP_ACCOUNTS_RENDER: { list?: () => Promise<Shown> } = {
  list: () => show(createElement(AccountsTab), '/settings/accounts', '*', 'signedIn'),
}

// --- Helpers (since 1.0.0 all here, before the first block) ---------------------------------------------------------
// Every block below uses only what stands above it: the APP_ places, the imports and these helpers. An app that takes
// over a block of a newer version later copies this whole section with it (and the imports the block names), never a
// part of another block (nexmail missed `said`, which stood in the block of 0.3.8 until 0.3.10).

type Tree = { [key: string]: string | Tree }

function leaves(tree: Tree, prefix = ''): [string, string][] {
  return Object.entries(tree).flatMap(([name, value]) => {
    const key = prefix ? `${prefix}.${name}` : name
    return typeof value === 'string' ? [[key, value] as [string, string]] : leaves(value, key)
  })
}

// Every value a text of the module asks for (since 0.3.10 also name, day and providers, the words of 0.3.9).
const values = { username: 'kim', email: 'kim@example.com', provider: 'Pocket ID', name: 'Kim', day: '25.11.2026', providers: 'Pocket ID, Entra', address: 'https://paper.example.com', used: '1 GB', limit: '5 GB', things: 'Dokumente', thingsDative: 'Dokumenten', variable: 'NEXPAPER_TRUSTED_PROXIES', networks: '0.0.0.0/0', proxy: '172.18.0.2', proxies: '172.18.0.0/16', trusts: 'Der Anbieter prüft den zweiten Faktor selbst' }
const fill: Record<string, string | number> = { ...kontenVariables(APP_NAME), ...values }
/** Plural keys (``days_one``, ``recoveryLeft_other``) are asked by their base with a count that picks them. */
const PLURAL = /_(one|other)$/
const COUNTS: Record<string, number> = { one: 1, other: 5 }

/** The texts of the elements ``aria-describedby`` names, one after the other. */
function description(field: HTMLElement): string {
  const ids = (field.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean)
  return ids.map((id) => field.ownerDocument.getElementById(id)?.textContent ?? '').join(' ')
}

/** The field of a screen, found by exactly its label (getByLabelText fails on none and on more than one). */
function labelled(root: HTMLElement, field: AccountField): HTMLElement {
  return getByLabelText(root, i18n.t(FIELDS[field].label))
}

async function shown(screen: keyof typeof SCREENS): Promise<Shown> {
  await i18n.changeLanguage('de')
  const render = APP_RENDER[screen]
  if (!render) throw new Error(`APP_RENDER.${screen} is missing`)
  return render()
}

/** What a button says: its text without the symbol (an `svg` has no text). */
function said(element: Element): string {
  return (element.textContent ?? '').replace(/\s+/g, ' ').trim()
}

/** Every account the tests ask accountActions about: the operator's own, another with everything, blocked, deleted. */
function sample(change: Partial<ListedAccount> = {}): ListedAccount {
  return {
    id: 2,
    username: 'kim',
    displayName: 'Kim',
    email: 'kim@example.com',
    emailConfirmed: true,
    operator: false,
    self: false,
    hasPassword: true,
    authenticator: true,
    passkeys: 1,
    providers: [{ id: 7, label: 'Pocket ID' }],
    blocked: false,
    lastSeenAt: null,
    ...change,
  }
}

/** The words of every button of BUTTONS as the app says them (the provider named 'Pocket ID'), the app's own too. */
function buttonWords(): Map<string, keyof typeof BUTTONS> {
  const words = new Map<string, keyof typeof BUTTONS>()
  for (const name of Object.keys(BUTTONS) as (keyof typeof BUTTONS)[]) {
    const own = APP_BUTTON_WORDS[name]
    const text = name.includes('.') ? i18n.t(name, { name: 'Pocket ID', provider: 'Pocket ID' }) : own && i18n.t(own)
    if (text && !words.has(text)) words.set(text, name)
  }
  for (const entry of APP_OWN) {
    if (entry.group !== 'rights' && !words.has(i18n.t(entry.label))) words.set(i18n.t(entry.label), entry.button)
  }
  return words
}

/** Checks kind and symbol of every button in an element whose words are a button of BUTTONS; gives how many. */
function checkButtons(root: HTMLElement, where: string): number {
  const words = buttonWords()
  let found = 0
  for (const element of Array.from(root.querySelectorAll<HTMLElement>('button, [role="button"], [data-kind]'))) {
    const name = words.get(said(element))
    if (!name) continue
    found += 1
    expect(element.getAttribute('data-kind'), `${where}: ${said(element)}`).toBe(BUTTONS[name].kind)
    expect(element.getAttribute('data-icon'), `${where}: ${said(element)}`).toBe(BUTTONS[name].icon)
  }
  return found
}

describe('the konten texts', () => {
  for (const [language, tree] of [['de', de], ['en', en]] as const) {
    it(`are all in the app in ${language}, word for word`, async () => {
      await i18n.changeLanguage(language)
      for (const [key, text] of leaves(tree as Tree)) {
        const plural = PLURAL.exec(key)
        const count = plural ? COUNTS[plural[1] ?? 'other'] : undefined
        const given: Record<string, string | number> = count === undefined ? { ...fill } : { ...fill, count }
        const expected = text.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(given[name] ?? ''))
        const asked = plural ? key.replace(PLURAL, '') : key
        expect(i18n.t(asked, count === undefined ? values : { ...values, count }), key).toBe(expected)
      }
    })

    it(`keep the namespace account to the module in ${language}, no text of the app's own there (since 0.3.10)`, () => {
      const module = new Set(leaves(tree as Tree).map(([key]) => key))
      const data = (i18n.getDataByLanguage(language) ?? {}) as Record<string, Tree>
      for (const [namespace, resources] of Object.entries(data)) {
        const own = namespace === ACCOUNT_NAMESPACE ? resources : resources[ACCOUNT_NAMESPACE]
        if (own === undefined || typeof own === 'string') continue
        const extra = leaves(own, ACCOUNT_NAMESPACE).map(([key]) => key).filter((key) => !module.has(key))
        expect(extra, `${namespace}: the app's own keys under ${ACCOUNT_NAMESPACE}`).toEqual([])
      }
    })
  }
})

describe('the konten screens', () => {
  it('show the fields of the module in its order', () => {
    for (const [screen, fields] of Object.entries(APP_SCREENS)) {
      expect(fields, screen).toEqual(screenFields(screen as keyof typeof SCREENS).map((entry) => entry.field))
    }
  })

  it('suggest the username the server would', () => {
    expect(suggestUsername('Max Müller')).toBe('max-mueller')
  })
})

describe('the konten pages (since 0.3.6)', () => {
  it("show the module's parts first, in its order, and the app's own after them", () => {
    for (const page of Object.keys(PAGES) as (keyof typeof PAGES)[]) {
      const module = pageOrder(page)
      const shown = APP_PAGES[page]
      expect(shown.slice(0, module.length), page).toEqual(module)
      for (const own of shown.slice(module.length)) expect(module, `${page}: ${own}`).not.toContain(own)
    }
  })

  it("title every part with the module's texts", async () => {
    await i18n.changeLanguage('de')
    expect(i18n.t('account.sessions')).toBe('Angemeldete Geräte')
    expect(i18n.t('account.signOutEverywhere')).toBe('Überall sonst abmelden')
    expect(i18n.t('account.stateOff')).toBe('Aus')
    expect(i18n.t('account.pictureUpload')).toBe('Profilbild hochladen')
    for (const page of Object.values(PAGES)) {
      for (const part of page.parts) {
        const rules = 'rules' in part ? [part.rules] : []
        for (const key of [part.title, ...part.buttons, ...rules]) expect(i18n.exists(key), key).toBe(true)
      }
    }
    expect(i18n.t(PAGES.profile.saveButton)).toBe('Speichern')
  })
})

describe('the konten fields (since 0.3.7)', () => {
  for (const screen of Object.keys(APP_SCREENS) as (keyof typeof SCREENS)[]) {
    it(`${screen}: every field is found by exactly its label, its hints by aria-describedby`, async () => {
      const { root, unmount } = await shown(screen)
      try {
        for (const spec of screenFields(screen)) {
          const label = i18n.t(spec.label)
          const field = getByLabelText(root, label)
          const own = field.getAttribute('aria-label')
          expect(own === null || own === label, `${screen}.${spec.field}: aria-label`).toBe(true)
          const said = description(field)
          for (const hint of spec.hints) expect(said, `${screen}.${spec.field}: ${hint}`).toContain(i18n.t(hint))
        }
      } finally {
        unmount()
      }
    })
  }
})

describe('the profile saves with one button (since 0.3.7)', () => {
  it('has exactly one "Save" for display name, username and email', async () => {
    const { root, unmount } = await shown('profile')
    try {
      const fields = PAGES.profile.saveFields.map((field) => labelled(root, field))
      // The card: the closest element holding all three fields.
      let card: HTMLElement = fields[0] ?? root
      while (!fields.every((field) => card.contains(field)) && card.parentElement) card = card.parentElement
      expect(getAllByRole(card, 'button', { name: i18n.t(PAGES.profile.saveButton) })).toHaveLength(1)
    } finally {
      unmount()
    }
  })

  it('saves nothing when a field is changed and left', async () => {
    const { root, unmount } = await shown('profile')
    const sent = vi.spyOn(globalThis, 'fetch')
    try {
      for (const field of PAGES.profile.saveFields) {
        const input = labelled(root, field)
        fireEvent.focus(input)
        fireEvent.change(input, { target: { value: field === 'email' ? 'neu@example.com' : 'neu' } })
        fireEvent.focusOut(input)
        fireEvent.blur(input)
      }
      await new Promise((done) => setTimeout(done, 50))
      const writes = sent.mock.calls.filter(([input, init]) => {
        const method = init?.method ?? (input instanceof Request ? input.method : 'GET')
        return method.toUpperCase() !== 'GET'
      })
      expect(writes).toEqual([])
    } finally {
      sent.mockRestore()
      unmount()
    }
  })
})

describe('every button of the account pages has its kind and symbol (since 0.3.8)', () => {
  const screens: [string, (() => Promise<Shown>) | undefined][] = [
    ...(Object.keys(APP_SCREENS) as (keyof typeof SCREENS)[]).map((screen) => [screen, APP_RENDER[screen]] as [string, (() => Promise<Shown>) | undefined]),
    ['security', APP_PAGE_RENDER.security],
  ]
  for (const [screen, render] of screens) {
    it(`${screen}: kind and symbol as BUTTONS says, no button without them`, async () => {
      if (!render) throw new Error(`no render for ${screen}`)
      await i18n.changeLanguage('de')
      const { root, unmount } = await render()
      try {
        const words = new Map<string, keyof typeof BUTTONS>()
        for (const name of Object.keys(BUTTONS) as (keyof typeof BUTTONS)[]) {
          const own = APP_BUTTON_WORDS[name]
          const text = name.includes('.') ? i18n.t(name, { name: 'Pocket ID', provider: 'Pocket ID' }) : own && i18n.t(own)
          if (text && !words.has(text)) words.set(text, name)
        }
        let found = 0
        for (const element of Array.from(root.querySelectorAll<HTMLElement>('button, [role="button"], [data-kind]'))) {
          const name = words.get(said(element))
          if (!name) continue
          found += 1
          const spec = BUTTONS[name]
          expect(element.getAttribute('data-kind'), `${screen}: ${said(element)}`).toBe(spec.kind)
          expect(element.getAttribute('data-icon'), `${screen}: ${said(element)}`).toBe(spec.icon)
        }
        expect(found, `${screen}: no button of BUTTONS found`).toBeGreaterThan(0)
      } finally {
        unmount()
      }
    })
  }
})

describe('the box Password says when it was changed last (since 0.3.10)', () => {
  it('shows "Last changed on …" or that it is not known, on the page "Security"', async () => {
    const render = APP_PAGE_RENDER.security
    if (!render) throw new Error('APP_PAGE_RENDER.security is missing')
    await i18n.changeLanguage('de')
    const { root, unmount } = await render()
    try {
      const text = (root.textContent ?? '').replace(/\s+/g, ' ')
      const known = i18n.t(passwordChanged('x').text, { day: '' }).trim()
      const unknown = i18n.t(passwordChanged(null).text)
      expect(text.includes(known) || text.includes(unknown), `"${known}" or "${unknown}"`).toBe(true)
    } finally {
      unmount()
    }
  })
})

describe('the account list and its dialog "Manage" (since 0.3.9)', () => {
  it('never offers on the own account what belongs in the profile', () => {
    for (const row of [sample({ self: true, operator: true }), sample({ self: true, operator: true, blocked: true })]) {
      const names = accountActions(row, APP_CAPS, APP_OWN).map((action) => action.name.split(':')[0])
      for (const forbidden of NOT_ON_SELF) expect(names, forbidden).not.toContain(forbidden)
      for (const entry of APP_OWN) if (entry.notSelf) expect(names, entry.name).not.toContain(entry.name)
    }
  })

  it("takes every button of the dialog, the app's own too, with its kind and symbol from BUTTONS", () => {
    const rows = [sample(), sample({ blocked: true, operator: true }), sample({ deletedAt: '2026-11-25T10:00:00Z', purgeAt: '2026-12-25T10:00:00Z' })]
    for (const row of rows) {
      for (const action of accountActions(row, APP_CAPS, APP_OWN)) {
        if (action.type !== 'button') continue
        expect(action.button in BUTTONS, action.name).toBe(true)
        expect([action.kind, action.icon], action.name).toEqual([BUTTONS[action.button].kind, BUTTONS[action.button].icon])
      }
    }
  })

  it('shows one row per account with "Manage", and the dialog with its groups in order, every button as BUTTONS says', async () => {
    const render = APP_ACCOUNTS_RENDER.list
    if (!render) throw new Error('APP_ACCOUNTS_RENDER.list is missing')
    await i18n.changeLanguage('de')
    const { root, unmount } = await render()
    try {
      expect(checkButtons(root, 'list'), 'list: no button of BUTTONS found').toBeGreaterThan(0)
      const manage = Array.from(root.querySelectorAll<HTMLElement>('button')).filter((button) => said(button) === i18n.t('account.manage'))
      expect(manage.length, 'one "Verwalten" per account').toBeGreaterThan(1)
      fireEvent.click(manage[manage.length - 1] as HTMLElement)
      await new Promise((done) => setTimeout(done, 50))
      const title = i18n.t('account.manageTitle', { name: '' }).trim()
      const dialog = getAllByRole(document.body, 'dialog').find((element) => (element.textContent ?? '').includes(title))
      if (!dialog) throw new Error('the dialog "Manage" did not open')
      expect(checkButtons(dialog, 'manage'), 'manage: no button of BUTTONS found').toBeGreaterThan(0)
      const titles = MANAGE_GROUPS.map((group) => i18n.t(MANAGE_DIALOG.groups[group].title))
      const shown = Array.from(dialog.querySelectorAll('h3'))
        .map((heading) => heading.textContent ?? '')
        .filter((text) => titles.includes(text))
      expect(shown.length, 'the dialog shows its groups').toBeGreaterThan(0)
      expect(shown, 'groups in their order').toEqual(titles.filter((text) => shown.includes(text)))
      expect(queryByRole(dialog, 'menu'), 'no menu in the dialog').toBeNull()
    } finally {
      unmount()
    }
  })
})
