/**
 * A page the browser translated keeps working: something appearing before a text or a text going away no longer
 * throws, and an untouched page still puts everything where React wants it.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import { bearTranslatedPages } from './translatedPage'

/** Does what Chrome's translator does: every text node is replaced by <font><font>…</font></font>. */
function translateLikeChrome(root: Node): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const texts: Text[] = []
  while (walker.nextNode()) texts.push(walker.currentNode as Text)
  for (const text of texts) {
    const outer = document.createElement('font')
    const inner = document.createElement('font')
    inner.textContent = text.data
    outer.appendChild(inner)
    text.replaceWith(outer)
  }
}

function Line({ busy, note }: { busy: boolean; note: boolean }) {
  return (
    <p data-line>
      {busy && <b>busy</b>}
      Saved
      {note && ' just now'}
    </p>
  )
}

let root: Root
let box: HTMLDivElement

function draw(busy: boolean, note: boolean): void {
  act(() => root.render(<Line busy={busy} note={note} />))
}

const line = () => box.querySelector('[data-line]')!

beforeAll(() => {
  bearTranslatedPages()
})

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  box = document.createElement('div')
  document.body.appendChild(box)
  root = createRoot(box)
})

afterEach(() => {
  act(() => root.unmount())
  box.remove()
})

test('a translated page keeps working when something appears before a text', () => {
  draw(false, false)
  translateLikeChrome(line())
  draw(true, false)
  // Where the text belonged nobody knows any more; the new part stands at the end instead of not at all.
  expect(line().querySelector('b')).not.toBeNull()
})

test('something meant to go before a wrapped node goes before its wrapper', () => {
  const host = document.createElement('p')
  const text = document.createTextNode('Saved')
  host.append(document.createTextNode('a'), text)
  const wrapper = document.createElement('font')
  host.replaceChild(wrapper, text)
  wrapper.appendChild(text)

  host.insertBefore(document.createElement('b'), text)

  expect([...host.childNodes].map((node) => node.nodeName)).toEqual(['#text', 'B', 'FONT'])
})

test('a translated page keeps working when a text goes away', () => {
  draw(false, true)
  translateLikeChrome(line())
  draw(false, false)
  expect(line().isConnected).toBe(true)
})

test('an untouched page still puts things where React wants them', () => {
  draw(false, false)
  draw(true, true)
  expect(line().textContent).toBe('busySaved just now')
  draw(false, false)
  expect(line().textContent).toBe('Saved')
})
