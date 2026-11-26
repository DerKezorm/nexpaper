/**
 * Plan "Einstellungen" E28: "Auf diesem Gerät installieren" stands in Connections always. With the
 * browser's own question the button "Installieren"; without it the way of this browser (Safari on iPhone and iPad:
 * Share › Add to Home Screen; Safari on the Mac: File › Add to Dock; Firefox: it cannot; any other: its menu); in the
 * installed app it says so.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import i18n from '../i18n'
import { InstallCard, installWay } from './InstallCard'
import { setPwaState } from '../lib/install'

const FIREFOX = 'Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0'
const SAFARI_MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 15_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15'
const CHROME_MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 15_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36'

let root: Root
let box: HTMLDivElement

beforeEach(async () => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  await i18n.changeLanguage('de')
  box = document.createElement('div')
  document.body.append(box)
  root = createRoot(box)
})

afterEach(async () => {
  act(() => root.unmount())
  box.remove()
  setPwaState({ installable: false, ios: false, standalone: false })
  vi.unstubAllGlobals()
  await i18n.changeLanguage('en')
})

async function show(): Promise<void> {
  await act(async () => root.render(<InstallCard />))
}

const card = () => box.querySelector<HTMLElement>('[data-card="install"]')
const $ = (testId: string) => box.querySelector<HTMLElement>(`[data-testid="${testId}"]`)

describe('E28 the card "Auf diesem Gerät installieren"', () => {
  it('offers the button "Installieren" while the browser offers its question', async () => {
    setPwaState({ installable: true, ios: false, standalone: false })
    await show()
    expect(card()!.querySelector('h2')!.textContent).toBe('Auf diesem Gerät installieren')
    const button = $('install')!
    expect(button.textContent).toBe('Installieren')
    expect([button.dataset.kind, button.dataset.icon]).toEqual(['primary', 'Download'])
  })

  it('stands there without the question too, with the way of this browser', async () => {
    for (const [ios, agent, way, words] of [
      [true, 'iPhone', 'ios', 'Teilen › Zum Home-Bildschirm'],
      [false, SAFARI_MAC, 'safari', 'Ablage › Zum Dock hinzufügen'],
      [false, FIREFOX, 'firefox', 'Firefox kann Web-Apps nicht installieren'],
      [false, CHROME_MAC, 'other', 'in seinem Menü'],
    ] as const) {
      expect(installWay(ios, agent), agent).toBe(way)
      vi.stubGlobal('navigator', { ...navigator, userAgent: agent })
      setPwaState({ installable: false, ios, standalone: false })
      await show()
      expect(card(), agent).not.toBeNull()
      expect($('install'), agent).toBeNull()
      expect($(`install-${way}`)!.textContent, agent).toContain(words)
    }
  })

  it('in the installed app says that it runs installed', async () => {
    setPwaState({ installable: false, ios: true, standalone: true })
    await show()
    expect(card()).not.toBeNull()
    expect($('install-done')!.textContent).toContain('schon als installierte App')
    expect($('install-ios')).toBeNull()
  })
})
