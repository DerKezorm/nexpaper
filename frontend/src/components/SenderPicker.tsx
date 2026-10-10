/**
 * The field where a sender is chosen or typed, the same on every page that has one (inbox, document, rules, the
 * archive's filter). Typing shows the senders that fit in a list of our own, in the flow of the page under the field (so
 * it never covers the fields below), with the typed part marked, the whole names, and the keyboard (arrows, Enter,
 * Escape). Beside the field a button "Suchen" opens all senders of the vaults in a window with a search field of its own.
 *
 * Two kinds: a field that takes any name (a new name makes a new sender, `known` off), and a field that only chooses
 * among the names there are (the filter of the archive, `known` on, with a way back to "all").
 */
import { Search, X } from 'lucide-react'
import { useId, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { filterNames, suggest } from '../lib/suggest'
import { Dialog } from './Dialog'
import { Marked } from './docs'

type Props = {
  value: string
  onChange: (value: string) => void
  /** The name is settled (left the field, Enter, or chosen from a list); with the name as it stands. */
  onCommit?: (value: string) => void
  names: string[]
  label: string
  className?: string
  /** Only a name from the list counts (a filter). */
  known?: boolean
  /** What the field says while it is empty. */
  placeholder?: string
  /** The search button as a magnifying glass alone (with its name for screen readers and a hint on hover), where the
   * line is short; else it carries the word "Suchen". */
  iconOnly?: boolean
}

export function SenderPicker({ value, onChange, onCommit, names, label, className = 'input', known = false, placeholder, iconOnly = false }: Props) {
  const { t } = useTranslation()
  const id = useId()
  const [focused, setFocused] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [active, setActive] = useState(-1)
  const [typed, setTyped] = useState<string | null>(null)
  const [all, setAll] = useState(false)

  const shownText = known ? (typed ?? value) : value
  const { shown, more } = suggest(names, shownText)
  const justThat = shown.length === 1 && shown[0].name === shownText.trim()
  const open = focused && !dismissed && shown.length > 0 && !justThat
  const isNew = !known && focused && !dismissed && shownText.trim() !== '' && shown.length === 0

  const settle = (name: string) => {
    setTyped(null)
    setActive(-1)
    setDismissed(true)
    onChange(name)
    onCommit?.(name)
  }
  const key = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (shown.length === 0) return
      event.preventDefault()
      setDismissed(false)
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((at) => (at < 0 ? (step > 0 ? 0 : shown.length - 1) : (at + step + shown.length) % shown.length))
    } else if (event.key === 'Enter') {
      if (open && active >= 0 && shown[active]) {
        event.preventDefault()
        settle(shown[active].name)
      } else if (!known) onCommit?.(value)
    } else if (event.key === 'Escape' && open) {
      event.preventDefault()
      event.stopPropagation()
      setDismissed(true)
      setActive(-1)
    }
  }

  return (
    <div>
      <div className="flex items-stretch gap-2">
        <div className="relative min-w-0 flex-1">
          <input
            role="combobox"
            aria-expanded={open}
            aria-controls={`${id}-list`}
            aria-autocomplete="list"
            aria-activedescendant={open && active >= 0 ? `${id}-${active}` : undefined}
            autoComplete="off"
            value={shownText}
            maxLength={160}
            aria-label={label}
            placeholder={placeholder}
            onFocus={(event) => {
              setFocused(true)
              setDismissed(false)
              if (known) event.currentTarget.select()
            }}
            onChange={(event) => {
              setDismissed(false)
              setActive(-1)
              if (known) {
                setTyped(event.target.value)
                if (event.target.value === '') onChange('')
              } else onChange(event.target.value)
            }}
            onBlur={() => {
              setFocused(false)
              setActive(-1)
              setTyped(null)
              if (!known) onCommit?.(value)
            }}
            onKeyDown={key}
            className={`${className} ${known && value ? 'pr-9' : ''}`}
          />
          {known && value && (
            <button
              type="button"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => settle('')}
              aria-label={t('docs.senderPicker.clear')}
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded-full p-1 text-muted hover:bg-sheet-2 hover:text-ink"
            >
              <X size={14} aria-hidden />
            </button>
          )}
        </div>
        <button
          type="button"
          // Pressing it must not take the focus from the field first: that would settle a half-typed name.
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => setAll(true)}
          aria-label={t('docs.senderPicker.searchAria')}
          title={iconOnly ? t('docs.senderPicker.searchAria') : undefined}
          className={`inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl border border-line bg-sheet text-sm font-semibold text-ink-2 transition hover:bg-sheet-2 hover:text-ink ${iconOnly ? 'w-9 px-0' : 'px-3'}`}
        >
          <Search size={15} aria-hidden />
          {!iconOnly && <span>{t('docs.senderPicker.search')}</span>}
        </button>
      </div>

      {open && (
        <ul id={`${id}-list`} role="listbox" aria-label={label} className="soft-scroll mt-1.5 max-h-56 overflow-auto rounded-xl border border-line bg-sheet py-1 shadow-soft">
          {shown.map((hit, index) => (
            <li
              key={hit.name}
              id={`${id}-${index}`}
              role="option"
              aria-selected={index === active}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => settle(hit.name)}
              onMouseMove={() => setActive(index)}
              className={`cursor-pointer px-3 py-2 text-sm break-words ${index === active ? 'bg-accent-soft text-accent' : 'hover:bg-sheet-2'}`}
            >
              <Marked text={hit.name} marks={hit.marks} />
            </li>
          ))}
          {more > 0 && <li className="px-3 py-1.5 text-xs text-muted">{t('docs.senderPicker.more', { count: more })}</li>}
        </ul>
      )}
      {isNew && <p className="mt-1.5 text-xs text-muted">{t('docs.senderPicker.isNew')}</p>}

      {all && (
        <AllSenders
          names={names}
          label={label}
          chosen={value}
          onClose={() => setAll(false)}
          onPick={(name) => {
            setAll(false)
            settle(name)
          }}
        />
      )}
    </div>
  )
}

/** Every sender of the vaults in one window, with a search field and a list to choose from. */
function AllSenders({ names, label, chosen, onClose, onPick }: { names: string[]; label: string; chosen: string; onClose: () => void; onPick: (name: string) => void }) {
  const { t, i18n } = useTranslation()
  const [query, setQuery] = useState('')
  const hits = filterNames(names, query)
  return (
    <Dialog title={t('docs.senderPicker.title', { field: label })} onClose={onClose}>
      <input
        data-autofocus
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t('docs.senderPicker.filterPlaceholder')}
        aria-label={t('docs.senderPicker.filter')}
        autoComplete="off"
        maxLength={160}
        className="input"
      />
      <p className="mt-2 text-xs text-muted">{t('docs.senderPicker.count', { shown: hits.length.toLocaleString(i18n.language), total: names.length.toLocaleString(i18n.language) })}</p>
      {hits.length > 0 ? (
        <ul className="soft-scroll mt-2 max-h-[50dvh] overflow-auto rounded-xl border border-line">
          {hits.map((hit) => (
            <li key={hit.name} className="border-b border-line last:border-b-0">
              <button
                type="button"
                onClick={() => onPick(hit.name)}
                aria-current={hit.name === chosen}
                className={`block w-full px-3 py-2.5 text-left text-sm break-words hover:bg-sheet-2 ${hit.name === chosen ? 'bg-accent-soft font-semibold text-accent' : ''}`}
              >
                <Marked text={hit.name} marks={hit.marks} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-muted">{names.length === 0 ? t('docs.senderPicker.none') : t('docs.senderPicker.nothing')}</p>
      )}
    </Dialog>
  )
}
