// @vitest-environment jsdom
/**
 * Since 1.1.0: the module's cards in the app (``SignInPage.tsx``, ``AccountCards.tsx``): built from the ui kit, in the
 * order and with the words and buttons the plan "Einstellungen" names. Copied once by bauplaene/konten/tools/sync.py
 * to ``frontend/src/nexkonten.cards.test.tsx``; then the app's file. Fill in the places marked APP. Needs react-dom and
 * @testing-library/dom, both in every app. The words come from the module's files, filled the way i18next fills them.
 */
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NexuiLanguage } from './vendor/nexui'
import { AppearanceCard, SignOutCard, UnconfirmedEmailBox, WhatYouSeeCard } from './vendor/nexkonten/AccountCards'
import { SignInPage, type SignInView, type Translate } from './vendor/nexkonten/SignInPage'
import { kontenVariables, publicUrlPlaceholder, type Readiness } from './vendor/nexkonten/konten'
import german from './vendor/nexkonten/konten.de.json'
import english from './vendor/nexkonten/konten.en.json'

// APP: the app's name, as its container is called.
const APP = 'nexnotes'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/** The words of the module oidc the card "Sign-in" uses (the app loads them from its own copy of nexoidc). */
const OIDC: Record<string, string> = {
  'oidc.admin.signInTitle': 'Anmeldung',
  'oidc.admin.password': 'Anmeldung mit Passwort',
  'oidc.admin.passwordHint': 'Aus: Nur die Anbieter lassen herein.',
  'oidc.admin.address': 'Öffentliche Adresse',
  'oidc.admin.addressHint': 'Die Adresse, unter der man {{app}} erreicht.',
  'oidc.admin.addressChangeConfirm': 'authentik kennt noch {{address}}.',
  'oidc.admin.addressChangeHand_one': '{{count}} von Hand.',
  'oidc.admin.addressChangeHand_other': '{{count}} von Hand.',
}

function leaves(tree: Record<string, unknown>, prefix = ''): Record<string, string> {
  const found: Record<string, string> = {}
  for (const [name, value] of Object.entries(tree)) {
    const key = prefix ? `${prefix}.${name}` : name
    if (typeof value === 'string') found[key] = value
    else Object.assign(found, leaves(value as Record<string, unknown>, key))
  }
  return found
}

/** A ``t`` as i18next fills: plural by ``count``, ``{{name}}`` from the values and the module's default variables. */
function translator(words: Record<string, unknown>): Translate {
  const all = { ...leaves(words), ...OIDC }
  const defaults: Record<string, unknown> = { ...kontenVariables(APP) }
  return (key, values = {}) => {
    const filled = { ...defaults, ...values }
    const count = typeof filled.count === 'number' ? filled.count : null
    const text = (count !== null ? all[`${key}_${count === 1 ? 'one' : 'other'}`] : undefined) ?? all[key]
    if (text === undefined) throw new Error(`missing words: ${key}`)
    return text.replace(/\{\{(\w+)\}\}/g, (whole, name: string) => (name in filled ? String(filled[name]) : whole))
  }
}

const t = translator(german)

let root: Root
let box: HTMLDivElement

beforeEach(() => {
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
  document.body.innerHTML = ''
})

function show(node: ReactNode, language = 'de'): void {
  act(() => root.render(<NexuiLanguage language={language}>{node}</NexuiLanguage>))
}

async function click(element: Element | null | undefined): Promise<void> {
  if (!element) throw new Error('nothing to click')
  await act(async () => {
    ;(element as HTMLElement).click()
  })
}

function button(text: string): HTMLButtonElement {
  const found = [...document.querySelectorAll('button')].find((entry) => entry.textContent?.trim() === text)
  if (!found) throw new Error(`no button "${text}"`)
  return found
}

/** Every button with words says its kind, size and symbol, and there are only the three kinds. */
function checkButtons(): void {
  for (const entry of document.querySelectorAll('button[data-kind]')) {
    expect(['primary', 'secondary', 'danger']).toContain(entry.getAttribute('data-kind'))
    expect(['md', 'sm']).toContain(entry.getAttribute('data-size'))
    expect(entry.getAttribute('data-icon')).toBeTruthy()
  }
}

const VIEW: SignInView = {
  password_login: true,
  factor_required: false,
  passkeys_allowed: true,
  password_may_go_off: false,
  factor_may_go_on: false,
  second_factor_off: false,
}

const READY: Readiness = {
  state: 'bad',
  open: 2,
  points: [
    { key: 'address', state: 'ok', title: 'account.ready.address.title', text: 'account.ready.address.ok', values: { address: 'https://notes.example.com', app: APP } },
    { key: 'factorForAll', state: 'bad', title: 'account.ready.factorForAll.title', text: 'account.ready.factorForAll.bad', values: {} },
    { key: 'cookies', state: 'warn', title: 'account.ready.cookies.title', text: 'account.ready.cookies.warn', values: { app: APP } },
  ],
}

function page(change: Partial<Parameters<typeof SignInPage>[0]> = {}) {
  const props: Parameters<typeof SignInPage>[0] = {
    t,
    app: APP,
    view: VIEW,
    readiness: READY,
    publicUrl: '',
    operatorHasPassword: true,
    onChange: vi.fn(async () => undefined),
    onSaveAddress: vi.fn(async () => null),
    errorText: () => 'kaputt',
    providers: <section data-card="sign-in-providers">providers</section>,
    ...change,
  }
  show(<SignInPage {...props} />)
  return props
}

describe('Server › Sign-in (konten 1.1.0)', () => {
  it('stands in the order of the plan: ready, sign-in, then the providers', () => {
    page()
    expect([...document.querySelectorAll('[data-card]')].map((card) => card.getAttribute('data-card'))).toEqual([
      'sign-in-ready',
      'sign-in',
      'sign-in-providers',
    ])
    expect(document.querySelector('[data-testid="second-factor-off"]')).toBeNull()
    checkButtons()
  })

  it('shows the emergency hammer first, only while it is down', () => {
    page({ view: { ...VIEW, second_factor_off: true } })
    const notice = document.querySelector('[data-testid="second-factor-off"]')
    expect(notice?.textContent).toContain(t('account.secondFactorOff'))
    expect(notice?.compareDocumentPosition(document.querySelector('[data-card="sign-in-ready"]') as Node)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    )
  })

  it('colours the symbol by the worst point and keeps every point closed until opened', async () => {
    page()
    expect(document.querySelector('[data-ready]')?.getAttribute('data-ready')).toBe('bad')
    expect(document.querySelector('[data-testid="ready-summary"]')?.textContent).toBe('2 Punkte offen')
    const heads = [...document.querySelectorAll('[data-card="sign-in-ready"] button[aria-expanded]')]
    expect(heads).toHaveLength(3)
    expect(heads.every((head) => head.getAttribute('aria-expanded') === 'false')).toBe(true)
    expect(document.querySelector('[data-testid="ready-text-factorForAll"]')).toBeNull()
    await click(heads[1])
    expect(document.querySelector('[data-testid="ready-text-factorForAll"]')?.textContent).toBe(t('account.ready.factorForAll.bad'))
    expect(document.querySelector('[data-state="bad"]')?.getAttribute('aria-label')).toBe('offen')
  })

  it('has the parts of the card in their order, the placeholder of the app and the address saved beside its field', async () => {
    const props = page()
    const card = document.querySelector('[data-card="sign-in"]') as HTMLElement
    const labels = [...card.querySelectorAll('label')].map((label) => label.textContent?.trim())
    expect(labels).toEqual([t('oidc.admin.password'), t('oidc.admin.address'), t('account.factorRequiredSwitch'), t('account.passkeysAllowed')])
    const field = card.querySelector('input[type="url"]') as HTMLInputElement
    expect(field.placeholder).toBe(publicUrlPlaceholder(APP))
    expect(card.querySelector('[data-part="field-action"] button')?.textContent).toBe(t('account.save'))
    await click(card.querySelector('[data-part="field-action"] button'))
    expect(props.onSaveAddress).toHaveBeenCalledWith('', false)
  })

  it('keeps password sign-in on without a provider and the second factor off without an own one', () => {
    page()
    const boxes = [...document.querySelectorAll('[data-card="sign-in"] input[type="checkbox"]')] as HTMLInputElement[]
    expect(boxes.map((entry) => entry.disabled)).toEqual([true, true, false])
    expect(document.querySelector('[data-card="sign-in"]')?.textContent).toContain(t('account.ownSecondFactorFirst'))
  })

  it('asks for the password before the second factor goes off', async () => {
    const props = page({ view: { ...VIEW, factor_required: true, factor_may_go_on: true } })
    const factor = document.querySelectorAll('[data-card="sign-in"] input[type="checkbox"]')[1] as HTMLInputElement
    await click(factor)
    expect(props.onChange).not.toHaveBeenCalled()
    const dialog = document.querySelector('[data-testid="sign-in-factor-off"]') as HTMLElement
    expect(dialog.textContent).toContain(t('account.factorRequiredOffText'))
    const confirm = button(t('account.factorRequiredOff'))
    expect(confirm.getAttribute('data-kind')).toBe('danger')
    expect(confirm.disabled).toBe(true)
    const password = dialog.querySelector('input[type="password"]') as HTMLInputElement
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      setter?.call(password, 'geheim-geheim')
      password.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await click(button(t('account.factorRequiredOff')))
    expect(props.onChange).toHaveBeenCalledWith({ factor_required: false }, 'geheim-geheim')
  })
})

describe('the cards of the profile, appearance and accounts (konten 1.1.0)', () => {
  it('"Aussehen" is the theme of the account, "system" while it has none', async () => {
    const onChange = vi.fn()
    show(<AppearanceCard theme="" onChange={onChange} />)
    expect(document.querySelector('[data-card="appearance"] h2')?.textContent).toBe('Aussehen')
    const radios = [...document.querySelectorAll('[role="radio"]')]
    expect(radios.map((radio) => radio.getAttribute('aria-checked'))).toEqual(['false', 'false', 'true'])
    await click(radios[1])
    expect(onChange).toHaveBeenCalledWith('dark')
  })

  it('"Adresse noch nicht bestätigt" sends the link with a small button', async () => {
    const onSend = vi.fn(async () => undefined)
    show(<UnconfirmedEmailBox t={t} email="kim@example.com" onSend={onSend} errorText={() => ''} />)
    const send = button(t('account.emailProveSend'))
    expect([send.getAttribute('data-kind'), send.getAttribute('data-size'), send.getAttribute('data-icon')]).toEqual(['secondary', 'sm', 'Send'])
    await click(send)
    expect(onSend).toHaveBeenCalled()
    expect(document.querySelector('[role="status"]')?.textContent).toBe(t('account.emailProveSent', { email: 'kim@example.com' }))
  })

  it('"Abmelden" says the sentence of the module and asks first while changes wait', async () => {
    const onSignOut = vi.fn()
    show(<SignOutCard t={t} things="Notizen" pending={2} onSignOut={onSignOut} />)
    expect(document.querySelector('[data-card="sign-out"]')?.textContent).toContain('Beendet deine Sitzung in diesem Browser. Deine Notizen bleiben, wie sie sind.')
    await click(document.querySelector('[data-testid="sign-out"]'))
    expect(onSignOut).not.toHaveBeenCalled()
    await click(button(t('account.signOutAnyway')))
    expect(onSignOut).toHaveBeenCalled()
    checkButtons()
  })

  it('"Was du siehst" shows the sentence of the app', () => {
    show(<WhatYouSeeCard t={t} text="Als Betreiber siehst du Namen, aber nie Notizen." />)
    const card = document.querySelector('[data-card="accounts-what-you-see"]')
    expect(card?.querySelector('h2')?.textContent).toBe('Was du siehst')
    expect(card?.textContent).toContain('aber nie Notizen')
  })

  it('speaks English with the English words', () => {
    show(<SignOutCard t={translator(english)} things="notes" onSignOut={() => undefined} />, 'en')
    expect(document.querySelector('[data-card="sign-out"]')?.textContent).toContain('Your notes stay as they are.')
  })
})
