// Vorlage nexupdates 0.1.3
// @vitest-environment jsdom
/**
 * The card "Aktualisierungen" of the kit's about page with the module's state in the app: an operator sees the newer
 * version with its link, the current one, "not yet", "off", "no release yet" (U20), a failure, and switches and asks;
 * a member sees neither the card nor any state and the page asks only for its version (U15), nor does a page the server
 * answers with `hidden` (U21); no row "Projektseite"
 * while the app gives none (U18); the setup's box "Nach neuen Versionen sehen" is ticked by default (U1); the sentence
 * on what goes out names the address and the app's other calls. Copied once by bauplaene/updates/tools/sync.py to
 * `frontend/src/nexupdates.test.tsx`; then the app's file. Fill in the places marked APP.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AboutPage, NexuiLanguage } from './vendor/nexui'
import { UpdateSetupRow } from './vendor/nexupdates/UpdateSetupRow'
import { UPDATES_TEXTS, aboutUpdates, dailyHint, useUpdates, whatGoesOut, type Fetcher, type UpdatesAnswer } from './vendor/nexupdates/updates'

// APP: where the app mounts the routes, its name, its other calls by itself (the words its card names; none: []).
const BASE = '/api/v1/about'
const APP = 'nexpaper'
const OTHERS: string[] = ['den Mailserver, die KI und das Postfach, wenn ihr sie eingerichtet habt, die Push-Dienste der Browser, Paperless beim Import, wenn ihn jemand startet, und die Anmeldeanbieter, wenn sich jemand über sie anmeldet']

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let root: Root
let box: HTMLDivElement
let calls: { path: string; method: string; body: unknown }[]
let answer: UpdatesAnswer
let failing: boolean

const ABOUT = { version: '1.4.2', license: 'AGPL-3.0', repo_url: 'https://github.com/DerKezorm/nexapp', releases_url: 'https://github.com/DerKezorm/nexapp/releases', project_url: '' }

const fetcher: Fetcher = async (path, init) => {
  calls.push({ path, method: init.method ?? 'GET', body: init.body })
  if (failing && path !== BASE) return new Response('{}', { status: 500 })
  if (path === BASE) return new Response(JSON.stringify(ABOUT), { status: 200 })
  if (init.method === 'PUT') answer = { ...answer, update_check: JSON.parse(String(init.body)).update_check }
  if (init.method === 'POST') answer = { ...answer, checked: true, latest: 'v1.5.0', newer: true, checked_at: '2026-11-26T09:12:00Z', release_url: `${ABOUT.releases_url}/tag/v1.5.0` }
  return new Response(JSON.stringify(answer), { status: 200 })
}

function Page({ operator }: { operator: boolean }) {
  const state = useUpdates({ fetcher, base: BASE, operator, when: () => 'heute, 09:12' })
  if (!state.about) return null
  return (
    <AboutPage
      app={APP}
      logo="/logo.svg"
      tagline="tagline"
      version={state.about.version}
      licence={{ name: state.about.license, href: 'https://www.gnu.org/licenses/agpl-3.0.html' }}
      source={state.about.repo_url}
      releases={state.about.releases_url}
      project={state.about.project_url || null}
      updates={state.updates}
      showUpdates={state.showUpdates}
      operator={operator}
      onDaily={state.onDaily}
      onCheck={state.onCheck}
      checking={state.checking}
      problem={state.problem}
      builtWith={[]}
      texts={{ updatesWhatGoesOut: whatGoesOut(UPDATES_TEXTS.de, APP, undefined, OTHERS) }}
    />
  )
}

async function show(operator: boolean, language = 'de'): Promise<void> {
  await act(async () => root.render(<NexuiLanguage language={language}><Page operator={operator} /></NexuiLanguage>))
  await settle()
}

async function settle(): Promise<void> {
  await act(async () => await new Promise((resolve) => setTimeout(resolve, 0)))
}

const find = <T extends Element = HTMLElement>(selector: string) => box.querySelector<T>(selector)
const card = () => find('[data-card="about-updates"]')!
const stateText = () => find('[data-testid="about-update-state"]')!.textContent

beforeEach(() => {
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
  calls = []
  failing = false
  answer = { update_check: true, checked: true, latest: 'v1.5.0', newer: true, checked_at: '2026-11-26T09:12:00Z', release_url: `${ABOUT.releases_url}/tag/v1.5.0`, hidden: false }
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
})

describe('the card "Aktualisierungen" for the operator', () => {
  it('shows a newer version as a badge and links its release', async () => {
    await show(true)
    expect(find('[data-testid="about-facts"]')!.textContent).toContain('Version 1.5.0 ist erschienen')
    expect(stateText()).toContain('Version 1.5.0 ist erschienen')
    expect(card().querySelector('a')?.getAttribute('href')).toBe(`${ABOUT.releases_url}/tag/v1.5.0`)
    expect(card().textContent).toContain('heute, 09:12')
  })

  it('says when the running version is the newest, when it never checked, and when the daily check is off', async () => {
    answer = { ...answer, newer: false, latest: 'v1.4.2' }
    await show(true)
    expect(stateText()).toBe('Das ist die neueste Version.')
    act(() => root.unmount())
    root = createRoot(box)
    answer = { ...answer, checked: false, latest: null, checked_at: null, release_url: null }
    await show(true)
    expect(stateText()).toBe('Noch nicht nachgesehen.')
    act(() => root.unmount())
    root = createRoot(box)
    answer = { ...answer, update_check: false }
    await show(true)
    expect(stateText()).toBe('Das tägliche Nachsehen ist aus.')
  })

  it('never shows or links a tag of another form', async () => {
    answer = { ...answer, latest: 'v1.5.0"><script>', release_url: 'https://example.com/x' }
    await show(true)
    expect(card().textContent).not.toContain('script')
    expect(card().querySelector('a')).toBeNull()
  })

  it('switches the daily check and asks now, also when off', async () => {
    answer = { ...answer, update_check: false, checked: false, latest: null, newer: false, checked_at: null, release_url: null }
    await show(true)
    const daily = find<HTMLInputElement>('[data-testid="about-daily"]')!
    expect(daily.checked).toBe(false)
    await act(async () => find<HTMLButtonElement>('[data-testid="about-check"]')!.click())
    await settle()
    expect(calls.some((call) => call.method === 'POST' && call.path === `${BASE}/updates/check`)).toBe(true)
    expect(stateText()).toContain('Version 1.5.0 ist erschienen')
    await act(async () => daily.click())
    await settle()
    const put = calls.find((call) => call.method === 'PUT')!
    expect(JSON.parse(String(put.body))).toEqual({ update_check: true })
  })

  it('says so when asking fails, and keeps the page', async () => {
    await show(true)
    failing = true
    await act(async () => find<HTMLButtonElement>('[data-testid="about-check"]')!.click())
    await settle()
    expect(find('[role="alert"]')!.textContent).toBe(UPDATES_TEXTS.de.failed)
    expect(find('[data-testid="about-version"]')!.textContent).toBe('1.4.2')
  })
})

describe('the page for a member (U2, U15)', () => {
  it('shows the own version only: no card "Aktualisierungen", no news, and asks for nothing but the about facts', async () => {
    await show(false)
    expect(find('[data-testid="about-version"]')!.textContent).toBe('1.4.2')
    expect(find('[data-card="about-updates"]')).toBeNull()
    expect(box.textContent).not.toContain('1.5.0')
    expect(box.textContent).not.toContain('Aktualisierungen')
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual([`GET ${BASE}`])
  })

  it('gets no state from the helper either, whatever the server answered', () => {
    expect(aboutUpdates(answer, false, () => 'heute')).toBeNull()
    expect(aboutUpdates(answer, true, () => 'heute')?.latest).toBe('v1.5.0')
  })

  it('shows no card when the server says the state is hidden from this account (U21)', async () => {
    answer = { update_check: false, checked: false, latest: null, newer: false, checked_at: null, release_url: null, hidden: true }
    await show(true)
    expect(find('[data-testid="about-version"]')!.textContent).toBe('1.4.2')
    expect(find('[data-card="about-updates"]')).toBeNull()
    expect(box.textContent).not.toContain('Aktualisierungen')
    expect(aboutUpdates(answer, true, () => 'heute')).toBeNull()
  })
})

describe('the page without a project page and without a public repository (U18, U20)', () => {
  it('has no row "Projektseite" while the app gives none', async () => {
    await show(true)
    expect(find('[data-testid="about-facts"]')!.textContent).not.toContain('Projektseite')
  })

  it('says "Noch keine Veröffentlichung gefunden." where GitHub knows no release', async () => {
    answer = { ...answer, checked: true, latest: null, newer: false, release_url: null }
    await show(true)
    expect(stateText()).toBe('Noch keine Veröffentlichung gefunden.')
  })
})

describe('what goes out, and the setup (U1)', () => {
  it('names exactly the address and the app own other calls', () => {
    expect(whatGoesOut(UPDATES_TEXTS.de, APP)).toBe(
      `Hinaus geht nur eine Frage: eine Anfrage an api.github.com nach der neuesten Veröffentlichung von ${APP}, ohne Namen, Inhalte, Einstellungen oder die Version dieses Servers. Sonst ruft ${APP} von sich aus niemanden an.`,
    )
    expect(whatGoesOut(UPDATES_TEXTS.en, APP, 'https://updates.example.com/latest', ['the check of the internet connection'])).toBe(
      `Only one question goes out: a request to updates.example.com for the newest release of ${APP}, without names, contents, settings or the version of this server. By itself ${APP} also calls: the check of the internet connection.`,
    )
  })

  it('offers "Nach neuen Versionen sehen" ticked, in three languages', async () => {
    let on = true
    for (const [language, label] of [['de', 'Nach neuen Versionen sehen'], ['en', 'Look for new versions'], ['fr', 'Rechercher les nouvelles versions']] as const) {
      await act(async () =>
        root.render(
          <NexuiLanguage language={language}>
            <UpdateSetupRow app={APP} checked={on} onChange={(next) => (on = next)} />
          </NexuiLanguage>,
        ),
      )
      expect(box.textContent).toContain(label)
      expect(box.textContent).toContain('api.github.com')
      expect(find<HTMLInputElement>('[data-testid="setup-update-check"]')!.checked).toBe(true)
    }
    await act(async () => find<HTMLInputElement>('[data-testid="setup-update-check"]')!.click())
    expect(on).toBe(false)
  })

  it('without a bell the hint says where the answer stands instead (U19, since 0.1.2)', async () => {
    for (const language of ['de', 'en', 'fr'] as const) {
      await act(async () =>
        root.render(
          <NexuiLanguage language={language}>
            <UpdateSetupRow app={APP} checked onChange={() => undefined} bell={false} />
          </NexuiLanguage>,
        ),
      )
      const texts = UPDATES_TEXTS[language]
      expect(box.textContent).toContain(texts.setupHintNoBell.replace(/\{app\}/g, APP).replace('{host}', 'api.github.com'))
      expect(box.textContent).not.toContain(texts.setupHint.replace(/\{app\}/g, APP).replace('{host}', 'api.github.com'))
    }
  })

  it('without a bell but with paired devices the hint says so (U24, since 0.1.3)', async () => {
    for (const language of ['de', 'en', 'fr'] as const) {
      await act(async () =>
        root.render(
          <NexuiLanguage language={language}>
            <UpdateSetupRow app={APP} checked onChange={() => undefined} bell={false} devices />
          </NexuiLanguage>,
        ),
      )
      const texts = UPDATES_TEXTS[language]
      expect(box.textContent).toContain(texts.setupHintDevices.replace(/\{app\}/g, APP).replace('{host}', 'api.github.com'))
    }
    expect(UPDATES_TEXTS.de.setupHintDevices).toContain('solange ein Gerät eines Betreibers Hinweise auf neue Versionen bekommen will')
    expect(dailyHint(UPDATES_TEXTS.de, { bell: true, devices: true })).toBeUndefined()
    expect(dailyHint(UPDATES_TEXTS.de, { bell: false })).toBe('Fragt api.github.com, wenn ein Betreiber diese Seite öffnet, höchstens einmal am Tag. Aus: nur, wenn du den Knopf drückst.')
    expect(dailyHint(UPDATES_TEXTS.de, { bell: false, devices: true })).toContain('und einmal am Tag, solange ein Gerät eines Betreibers Hinweise auf neue Versionen bekommen will')
  })
})
