/**
 * Since 1.1.0: choice buttons as one group, 32 px high, the chosen one in the accent at 14 %, each with a symbol where it
 * helps. One of several (`radiogroup`, the arrow keys move the choice, as in nexnotes' theme switcher): light, dark or as
 * the system, the levels of the log, a rhythm. With `multiple` several at once (a `group` of `checkbox`es): the
 * languages of the text recognition; `min` keeps the last ones from being unticked.
 *
 * The group's name is `label`, written above it like the label of a field (or only for readers with `hideLabel`, as in
 * the bar above the log); `hints` stand under it, each its own line, joined by `aria-describedby`.
 */
import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'

import { iconOf, type IconLike } from './icons'
import { HINT, LABEL, SEGMENT_ITEM, SEGMENT_STATE } from './styles'
import { useNexuiTexts } from './texts'

export type SegmentOption<T extends string> = {
  value: T
  label: string
  icon?: IconLike
  disabled?: boolean
  testId?: string
}

type SegmentBase<T extends string> = {
  /** The name of the group ("Hell oder dunkel"). */
  label: string
  /** Only for readers (the bar above the log). */
  hideLabel?: boolean
  hints?: readonly ReactNode[]
  options: readonly SegmentOption<T>[]
  disabled?: boolean
  testId?: string
}

export type SegmentProps<T extends string> =
  | (SegmentBase<T> & { multiple?: false; value: T; onChange: (value: T) => void })
  | (SegmentBase<T> & {
      multiple: true
      value: readonly T[]
      onChange: (value: T[]) => void
      /** How many must stay chosen (the last language of the text recognition cannot be unticked). */
      min?: number
    })

export function Segment<T extends string>(props: SegmentProps<T>) {
  const { label, hideLabel = false, hints = [], options, disabled = false, testId } = props
  const own = useId()
  const items = useRef<(HTMLButtonElement | null)[]>([])
  const labelId = `${own}-label`
  const hintIds = hints.map((_, index) => `${own}-hint-${index}`)
  const chosen = (value: T) => (props.multiple ? props.value.includes(value) : props.value === value)
  const usable = options.map((option) => !disabled && !option.disabled)

  function pick(value: T) {
    if (props.multiple) {
      const on = props.value.includes(value)
      if (on && props.value.length <= (props.min ?? 0)) return
      props.onChange(on ? props.value.filter((item) => item !== value) : [...props.value, value])
    } else if (props.value !== value) {
      props.onChange(value)
    }
  }

  /** One of several: the arrow keys go to the next usable choice and choose it, as radio buttons do. */
  function key(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (props.multiple) return
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    event.preventDefault()
    for (let turn = 1; turn <= options.length; turn += 1) {
      const next = (index + step * turn + options.length * turn) % options.length
      const target = options[next]
      if (target && usable[next]) {
        items.current[next]?.focus()
        pick(target.value)
        return
      }
    }
  }

  const current = props.multiple ? -1 : options.findIndex((option) => option.value === props.value)
  return (
    <div className="flex min-w-0 flex-col gap-1">
      {!hideLabel && (
        <span id={labelId} className={LABEL}>
          {label}
        </span>
      )}
      <div
        role={props.multiple ? 'group' : 'radiogroup'}
        aria-labelledby={hideLabel ? undefined : labelId}
        aria-label={hideLabel ? label : undefined}
        aria-describedby={hintIds.length ? hintIds.join(' ') : undefined}
        aria-disabled={disabled || undefined}
        className="flex min-w-0 flex-wrap items-center gap-1.5"
        data-segment={props.multiple ? 'multiple' : 'single'}
        data-testid={testId}
      >
        {options.map((option, index) => {
          const on = chosen(option.value)
          const last = props.multiple && on && props.value.length <= (props.min ?? 0)
          const Icon = option.icon ? iconOf(option.icon).Icon : null
          // One of several: only the chosen one (or the first usable) is reached by Tab, the arrows do the rest.
          const reach = props.multiple || index === current || (current < 0 && index === usable.indexOf(true))
          return (
            <button
              key={option.value}
              ref={(element) => {
                items.current[index] = element
              }}
              type="button"
              role={props.multiple ? 'checkbox' : 'radio'}
              aria-checked={on}
              disabled={!usable[index] || last}
              tabIndex={reach ? 0 : -1}
              onClick={() => pick(option.value)}
              onKeyDown={(event) => key(event, index)}
              className={`${SEGMENT_ITEM} ${on ? SEGMENT_STATE.chosen : SEGMENT_STATE.open}`}
              data-value={option.value}
              data-icon={option.icon ? iconOf(option.icon).name : undefined}
              data-testid={option.testId}
            >
              {Icon && <Icon aria-hidden className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />}
              <span className="min-w-0">{option.label}</span>
            </button>
          )
        })}
      </div>
      {hints.map((hint, index) => (
        <span key={index} id={hintIds[index]} className={HINT}>
          {hint}
        </span>
      ))}
    </div>
  )
}

/** The account's choice of light or dark (konten's profile field `theme`): "As the system" follows each device. */
export type ThemeChoice = 'light' | 'dark' | 'system'

/**
 * Since 1.1.0: the segment "Light or dark" of the card "Look" under Appearance, with its three choices (Sun, Moon,
 * Monitor) and its hint, in the kit's words. What is chosen and where it is kept is the caller's.
 */
export function ThemeSegment({ value, onChange, disabled, testId }: { value: ThemeChoice; onChange: (value: ThemeChoice) => void; disabled?: boolean; testId?: string }) {
  const texts = useNexuiTexts()
  return (
    <Segment<ThemeChoice>
      label={texts.themeLabel}
      hints={[texts.themeHint]}
      value={value}
      onChange={onChange}
      disabled={disabled}
      testId={testId}
      options={[
        { value: 'light', label: texts.themeLight, icon: 'Sun', testId: 'theme-light' },
        { value: 'dark', label: texts.themeDark, icon: 'Moon', testId: 'theme-dark' },
        { value: 'system', label: texts.themeSystem, icon: 'Monitor', testId: 'theme-system' },
      ]}
    />
  )
}
