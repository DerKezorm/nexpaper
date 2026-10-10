/**
 * The tag field: typing shows the tags the vault has that fit (whole, the typed part marked, the keyboard of the sender
 * field), look-alikes are named before a new tag is made ("Meintest du Strom?"), and a new tag is made only by its own
 * entry (or by leaving the field when nothing is like it).
 */
import { act, useState } from 'react'

import { changeLanguage } from '../i18n'
import { Page, plain } from '../test/harness'
import { TagPicker } from './TagPicker'

const page = new Page()
const KNOWN = ['Strom', 'Steuer-2025', 'Zahnarzt', 'Ärztliche Post', 'Versicherung']

let added: string[] = []

function Field({ known = KNOWN, start = [] as string[] }: { known?: string[]; start?: string[] }) {
  const [tags, setTags] = useState(start)
  return (
    <div>
      <div className="flex flex-wrap">
        <TagPicker
          known={known}
          taken={tags}
          label="Tag hinzufügen"
          onAdd={(name) => {
            added.push(name)
            setTags((had) => [...had, name])
          }}
        />
      </div>
      <p data-testid="tags">{tags.join('|')}</p>
      <input aria-label="Danach" />
    </div>
  )
}

const field = () => page.box.querySelector<HTMLInputElement>('input[aria-label="Tag hinzufügen"]')!
const options = () => [...page.box.querySelectorAll('[role="option"]')].map((o) => plain(o.textContent))
const tags = () => page.box.querySelector('[data-testid="tags"]')!.textContent
const leave = () => act(async () => void field().dispatchEvent(new FocusEvent('focusout', { bubbles: true })))

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
  added = []
})
afterEach(() => page.close())

describe('typing a tag', () => {
  it('shows the tags that fit, whole, with the typed part marked, in the flow of the page', async () => {
    await page.show(<Field />)
    await focus()
    expect(options()).toEqual([])
    await page.type(field(), 'ste')
    expect(options()).toEqual(['Steuer-2025', '„ste“ neu anlegen'])
    expect([...page.box.querySelectorAll('[role="option"] mark')].map((m) => m.textContent)).toEqual(['Ste'])
    const list = page.box.querySelector('[role="listbox"]')!
    expect(list.className).not.toMatch(/\babsolute\b|\bfixed\b/)
  })

  it('does not care for case or accents, and finds parts of words', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'arztl')
    expect(options()[0]).toBe('Ärztliche Post')
    await page.type(field(), 'ZAHN')
    expect(options()[0]).toBe('Zahnarzt')
    await page.type(field(), 'cherung')
    expect(options()[0]).toBe('Versicherung')
  })

  it('does not offer a tag the document has already, and says so', async () => {
    await page.show(<Field start={['Strom']} />)
    await focus()
    await page.type(field(), 'strom')
    expect(options()).toEqual([])
    expect(page.text).toContain('Dieses Tag hat das Dokument schon.')
    await press('Enter')
    expect(added).toEqual([])
  })
})

describe('a tag the document has already, typed in part', () => {
  it('is not offered again, and not named as a look-alike either', async () => {
    await page.show(<Field start={['Strom']} />)
    await focus()
    await page.type(field(), 'str')
    expect(options()).toEqual(['„str“ neu anlegen'])
    await page.type(field(), 'Stromvertrag')
    expect(options()).toEqual(['„Stromvertrag“ neu anlegen'])
  })
})

describe('a tag that is something like one the vault has', () => {
  it('asks "Meintest du Strom?" before the entry that makes the new tag', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'Stromvertrag')
    expect(options()).toEqual(['Meintest du Strom?', '„Stromvertrag“ neu anlegen'])
  })

  it('names a slip of the finger too', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'Versicherrung')
    expect(options()).toEqual(['Meintest du Versicherung?', '„Versicherrung“ neu anlegen'])
  })

  it('does not ask while tags that fit are in the list', async () => {
    await page.show(<Field known={[...KNOWN, 'Stromzähler']} />)
    await focus()
    await page.type(field(), 'Stromz')
    expect(options()).toEqual(['Stromzähler', '„Stromz“ neu anlegen'])
  })

  it('takes the one that was meant, with a click', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'Stromvertrag')
    await page.click(page.box.querySelectorAll<HTMLElement>('[role="option"]')[0])
    expect(added).toEqual(['Strom'])
    expect(field().value).toBe('')
  })

  it('makes the new tag only by its own entry', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'Stromvertrag')
    await page.click(page.box.querySelectorAll<HTMLElement>('[role="option"]')[1])
    expect(added).toEqual(['Stromvertrag'])
    expect(tags()).toBe('Stromvertrag')
  })

  it('does not make it by a first Enter: that shows the entry, the second makes it', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'Stromvertrag')
    await press('Enter')
    expect(added).toEqual([])
    expect(page.box.querySelectorAll('[role="option"]')[1].getAttribute('aria-selected')).toBe('true')
    await press('Enter')
    expect(added).toEqual(['Stromvertrag'])
  })

  it('does not make it by leaving the field either: the word stays, with a hint', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'Stromvertrag')
    await leave()
    expect(added).toEqual([])
    expect(field().value).toBe('Stromvertrag')
    expect(page.text).toContain('„Stromvertrag“ ist noch kein Tag.')
  })
})

describe('the keyboard', () => {
  it('moves with the arrows round the list and takes the one it stands on with Enter', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'ste')
    await press('ArrowDown')
    expect(page.box.querySelectorAll('[role="option"]')[0].getAttribute('aria-selected')).toBe('true')
    await press('ArrowDown')
    expect(page.box.querySelectorAll('[role="option"]')[1].getAttribute('aria-selected')).toBe('true')
    await press('ArrowDown')
    expect(page.box.querySelectorAll('[role="option"]')[0].getAttribute('aria-selected')).toBe('true')
    await press('Enter')
    expect(added).toEqual(['Steuer-2025'])
    expect(field().value).toBe('')
  })

  it('takes a tag the vault has by Enter when it is typed whole, whatever the case', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'zahnarzt')
    await press('Enter')
    expect(added).toEqual(['Zahnarzt'])
  })

  it('makes a word nothing is like by Enter, and closes the list with Escape', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'qwx')
    expect(options()).toEqual(['„qwx“ neu anlegen'])
    await press('Escape')
    expect(options()).toEqual([])
    await press('Enter')
    expect(added).toEqual(['qwx'])
  })
})

describe('leaving the field', () => {
  it('takes a tag of the vault as the vault has it', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'STROM')
    await leave()
    expect(added).toEqual(['Strom'])
  })

  it('makes a word that nothing is like', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'Garantie')
    await leave()
    expect(added).toEqual(['Garantie'])
  })

  it('leaves a part of a word alone', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), 'Zahn')
    await leave()
    expect(added).toEqual([])
    expect(field().value).toBe('Zahn')
  })

  it('takes a word with a hash sign without it', async () => {
    await page.show(<Field />)
    await focus()
    await page.type(field(), '#Garantie')
    await press('Enter')
    expect(added).toEqual(['Garantie'])
  })
})

describe('a vault with no tags yet', () => {
  it('offers only to make the first one', async () => {
    await page.show(<Field known={[]} />)
    await focus()
    await page.type(field(), 'Strom')
    expect(options()).toEqual(['„Strom“ neu anlegen'])
  })
})
