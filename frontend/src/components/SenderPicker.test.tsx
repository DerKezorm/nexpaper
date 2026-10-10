/**
 * The sender field: typing shows the senders that fit in a list of its own (whole names, the typed part marked, the
 * keyboard), a button opens all of them in a window, a field that only chooses (the filter) never takes a made-up name.
 */
import { act, useState } from 'react'

import { changeLanguage } from '../i18n'
import { Page, plain } from '../test/harness'
import { SenderPicker } from './SenderPicker'

const page = new Page()
const NAMES = ['Glanzwerk Reinigungsservice und Gebäudepflege Lindenau', 'Stadtwerke Lindenau', 'Zahnarztpraxis Dr. Sommer', 'Bäckerei Müller']

let committed: string[] = []
let changed: string[] = []

function Free({ known = false, start = '', iconOnly = false }: { known?: boolean; start?: string; iconOnly?: boolean }) {
  const [value, setValue] = useState(start)
  return (
    <div>
      <SenderPicker
        known={known}
        value={value}
        onChange={(v) => {
          changed.push(v)
          setValue(v)
        }}
        onCommit={(v) => committed.push(v)}
        names={NAMES}
        label="Absender"
        iconOnly={iconOnly}
      />
      <p data-testid="now">{value}</p>
      <input aria-label="Art" />
    </div>
  )
}

const field = () => page.box.querySelector<HTMLInputElement>('input[aria-label="Absender"]')!
const options = () => [...page.box.querySelectorAll('[role="option"]')].map((o) => plain(o.textContent))
const now = () => page.box.querySelector('[data-testid="now"]')!.textContent

async function focus(): Promise<void> {
  await act(async () => field().focus())
}
async function press(key: string): Promise<void> {
  await act(async () => {
    field().dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
  })
}

beforeEach(async () => {
  await changeLanguage('de', false)
  committed = []
  changed = []
})
afterEach(() => page.close())

describe('typing in the sender field', () => {
  it('shows the fitting senders, whole, with the typed part marked, in the flow of the page', async () => {
    await page.show(<Free />)
    await focus()
    await page.type(field(), 'linden')
    expect(options()).toEqual(['Glanzwerk Reinigungsservice und Gebäudepflege Lindenau', 'Stadtwerke Lindenau'])
    expect([...page.box.querySelectorAll('[role="option"] mark')].map((m) => m.textContent)).toEqual(['Linden', 'Linden'])
    // Not drawn over the next field: the list is a sibling in the normal flow, nothing is positioned absolutely.
    const list = page.box.querySelector('[role="listbox"]')!
    expect(list.className).not.toMatch(/\babsolute\b|\bfixed\b/)
    expect(list.className).toContain('max-h-56')
  })

  it('shows nothing before anything is typed, and says a new name will be made', async () => {
    await page.show(<Free />)
    await focus()
    expect(options()).toEqual([])
    await page.type(field(), 'Neuer Laden')
    expect(options()).toEqual([])
    expect(page.text).toContain('Kein Absender dieses Namens. Er wird neu angelegt.')
  })

  it('chooses with the arrows and Enter, and Escape closes the list', async () => {
    await page.show(<Free />)
    await focus()
    await page.type(field(), 'a')
    await press('Escape')
    expect(options()).toEqual([])
    await press('ArrowDown')
    expect(options().length).toBeGreaterThan(1)
    await press('ArrowDown')
    await press('ArrowDown')
    const chosen = plain(page.box.querySelector('[role="option"][aria-selected="true"]')!.textContent)
    await press('Enter')
    expect(now()).toBe(chosen)
    expect(committed).toEqual([chosen])
    expect(options()).toEqual([])
  })

  it('chooses by clicking a suggestion without settling the half-typed name first', async () => {
    await page.show(<Free />)
    await focus()
    await page.type(field(), 'zahn')
    const option = page.box.querySelector<HTMLElement>('[role="option"]')!
    // The press itself is kept from taking the focus away (otherwise "zahn" would be settled as a new sender).
    const press = new MouseEvent('mousedown', { bubbles: true, cancelable: true })
    option.dispatchEvent(press)
    expect(press.defaultPrevented).toBe(true)
    await page.click(option)
    expect(now()).toBe('Zahnarztpraxis Dr. Sommer')
    expect(committed).toEqual(['Zahnarztpraxis Dr. Sommer'])
  })

  it('settles what was typed when the field is left', async () => {
    await page.show(<Free />)
    await focus()
    await page.type(field(), 'Eigener Name')
    await act(async () => field().blur())
    expect(committed).toEqual(['Eigener Name'])
  })
})

describe('the button "Suchen"', () => {
  it('opens all senders in a window with a search field, and takes the one chosen', async () => {
    await page.show(<Free />)
    await page.click(page.button('Absender suchen'))
    const dialog = page.dialog!
    expect(dialog).toBeTruthy()
    expect([...dialog.querySelectorAll('li button')].map((b) => plain(b.textContent))).toEqual([
      'Bäckerei Müller',
      'Glanzwerk Reinigungsservice und Gebäudepflege Lindenau',
      'Stadtwerke Lindenau',
      'Zahnarztpraxis Dr. Sommer',
    ])
    expect(dialog.textContent).toContain('4 von 4')
    await page.type(dialog.querySelector('input'), 'stadt')
    expect(dialog.textContent).toContain('1 von 4')
    await page.click(dialog.querySelector<HTMLElement>('li button'))
    expect(page.dialog).toBeNull()
    expect(now()).toBe('Stadtwerke Lindenau')
    expect(committed).toEqual(['Stadtwerke Lindenau'])
  })

  it('says so when no sender matches or there are none', async () => {
    await page.show(<Free />)
    await page.click(page.button('Absender suchen'))
    await page.type(page.dialog!.querySelector('input'), 'xyz')
    expect(page.dialog!.textContent).toContain('Kein Absender passt.')
  })
})

describe('the look of the search button', () => {
  it('carries the word "Suchen" beside the magnifying glass', async () => {
    await page.show(<Free />)
    const button = page.button('Absender suchen')!
    expect(plain(button.textContent)).toBe('Suchen')
    expect(button.hasAttribute('title')).toBe(false)
  })

  it('is a magnifying glass alone where asked, still named for screen readers and with a hint on hover', async () => {
    await page.show(<Free iconOnly />)
    const button = page.button('Absender suchen')!
    expect(plain(button.textContent)).toBe('')
    expect(button.getAttribute('aria-label')).toBe('Absender suchen')
    expect(button.getAttribute('title')).toBe('Absender suchen')
    expect(button.querySelector('svg')).not.toBeNull()
    await page.click(button)
    expect(page.dialog).not.toBeNull()
  })
})

describe('a field that only chooses (the filter)', () => {
  it('takes no made-up name: leaving it restores the choice, clearing it says "all"', async () => {
    await page.show(<Free known start="Stadtwerke Lindenau" />)
    expect(field().value).toBe('Stadtwerke Lindenau')
    await focus()
    await page.type(field(), 'Unbekannt')
    expect(changed).toEqual([])
    await act(async () => field().blur())
    expect(field().value).toBe('Stadtwerke Lindenau')
    await page.click(page.button('Auswahl aufheben'))
    expect(now()).toBe('')
  })

  it('chooses from the list', async () => {
    await page.show(<Free known />)
    await focus()
    await page.type(field(), 'bäck')
    await page.click(page.box.querySelector<HTMLElement>('[role="option"]'))
    expect(now()).toBe('Bäckerei Müller')
  })
})
