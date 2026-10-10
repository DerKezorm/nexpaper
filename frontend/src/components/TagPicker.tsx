/**
 * The field where a tag is added, the same on every page that has one (inbox, document, several at once in the inbox).
 * Typing shows the tags the vault already has that fit, in a list of our own in the flow of the page under the field,
 * with the typed part marked and the keyboard of the sender field (arrows, Enter, Escape). A tag that is new is made
 * only by its own entry at the end of the list ("neu anlegen"), and when something like it exists ("Strom" for
 * "Stromvertrag") the list says so first: "Meintest du Strom?". So two spellings of one thing do not grow side by side.
 */
import { useId, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { iso } from '../lib/say'
import { fold, similar, suggest } from '../lib/suggest'
import { Marked } from './docs'

type Props = {
  /** The tags of the vault the document is in (only those; never a name from another vault). */
  known: string[]
  /** The tags the document has already: not offered again. */
  taken: string[]
  /** A tag was settled: chosen from the list, or made new. With its name as it should be kept. */
  onAdd: (name: string) => void
  label: string
  placeholder?: string
  className?: string
  maxLength?: number
}

type Option = { key: string; name: string; kind: 'match' | 'similar' | 'create'; marks: [number, number][] }

export function TagPicker({ known, taken, onAdd, label, placeholder, className = 'h-7 w-24 rounded-full border border-dashed border-line bg-transparent px-2.5 text-xs outline-none focus:border-accent', maxLength = 40 }: Props) {
  const { t } = useTranslation()
  const id = useId()
  const [text, setText] = useState('')
  const [focused, setFocused] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [active, setActive] = useState(-1)

  const word = text.trim().replace(/^#/, '')
  const hadAlready = (name: string) => taken.some((had) => fold(had) === fold(name))
  const free = known.filter((name) => !hadAlready(name))
  const exact = known.find((name) => fold(name) === fold(word))
  const onTheDocument = word !== '' && hadAlready(word)

  const options: Option[] = []
  if (word !== '' && !onTheDocument) {
    const { shown } = suggest(free, word, 8)
    for (const hit of shown) options.push({ key: `m-${hit.name}`, name: hit.name, kind: 'match', marks: hit.marks })
    if (!exact) {
      // Look-alikes are named only while nothing in the list fits: a person choosing among fitting tags needs no question.
      for (const name of shown.length === 0 ? similar(free, word) : []) options.push({ key: `s-${name}`, name, kind: 'similar', marks: [] })
      options.push({ key: 'create', name: word, kind: 'create', marks: [] })
    }
  }
  const open = focused && !dismissed && options.length > 0
  const hasOthers = options.length > 1

  const settle = (name: string) => {
    setText('')
    setActive(-1)
    setDismissed(false)
    onAdd(name)
  }
  const take = (option: Option) => settle(option.name)

  const key = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (options.length === 0) return
      event.preventDefault()
      setDismissed(false)
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((at) => (at < 0 ? (step > 0 ? 0 : options.length - 1) : (at + step + options.length) % options.length))
    } else if (event.key === 'Enter') {
      // Never sends the form around the field by itself.
      event.preventDefault()
      if (word === '') return
      if (onTheDocument) {
        setText('')
        return
      }
      if (open && active >= 0 && options[active]) take(options[active])
      else if (exact) settle(exact)
      else if (options.length === 1) settle(word)
      else {
        // Something like it exists: the first Enter only shows which entry would make the new tag.
        setDismissed(false)
        setActive(options.length - 1)
      }
    } else if (event.key === 'Escape' && open) {
      event.preventDefault()
      event.stopPropagation()
      setDismissed(true)
      setActive(-1)
    }
  }

  // Drawn as the input and, after it, the list and the hints, each as a whole line of its own (`basis-full`) when the
  // parent wraps its children (chips and the field in a row): the field keeps its place, the list opens under the row.
  return (
    <>
      <input
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={open && active >= 0 ? `${id}-${active}` : undefined}
        autoComplete="off"
        value={text}
        maxLength={maxLength}
        aria-label={label}
        placeholder={placeholder}
        onFocus={() => {
          setFocused(true)
          setDismissed(false)
        }}
        onChange={(event) => {
          setText(event.target.value)
          setDismissed(false)
          setActive(-1)
        }}
        onBlur={() => {
          setFocused(false)
          setActive(-1)
          // Leaving the field settles what is clear: a tag the vault has, or a word that nothing is like. A word with
          // look-alikes stays in the field with the question, to be answered on purpose.
          if (word !== '' && !onTheDocument) {
            if (exact) settle(exact)
            else if (!hasOthers) settle(word)
          } else if (onTheDocument) setText('')
        }}
        onKeyDown={key}
        className={className}
      />
      {open && (
        <ul id={`${id}-list`} role="listbox" aria-label={label} className="soft-scroll mt-0.5 max-h-56 w-full basis-full overflow-auto rounded-xl border border-line bg-sheet py-1 text-left shadow-soft sm:max-w-sm">
          {options.map((option, index) => (
            <li
              key={option.key}
              id={`${id}-${index}`}
              role="option"
              aria-selected={index === active}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => take(option)}
              onMouseMove={() => setActive(index)}
              className={`cursor-pointer px-3 py-2 text-sm break-words ${index === active ? 'bg-accent-soft text-accent' : 'hover:bg-sheet-2'} ${option.kind === 'create' ? `font-semibold ${index > 0 ? 'border-t border-line' : ''}` : ''}`}
            >
              {option.kind === 'match' && <Marked text={option.name} marks={option.marks} />}
              {option.kind === 'similar' && t('docs.tagPicker.didYouMean', { name: iso(option.name) })}
              {option.kind === 'create' && t('docs.tagPicker.create', { name: iso(option.name) })}
            </li>
          ))}
        </ul>
      )}
      {onTheDocument && focused && <p className="basis-full text-xs text-muted">{t('docs.tagPicker.hasIt')}</p>}
      {!open && hasOthers && !focused && word !== '' && <p className="basis-full text-xs text-muted">{t('docs.tagPicker.waiting', { name: iso(word) })}</p>}
    </>
  )
}
