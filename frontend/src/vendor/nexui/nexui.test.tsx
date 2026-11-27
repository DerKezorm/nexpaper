// @vitest-environment jsdom
/**
 * The kit's own test, run in every app's vitest (it comes with the kit, unchanged): the three kinds of buttons, each
 * with its symbol and the same size, and that every part is reachable as a reader and a test finds it (names, hints,
 * states, dialogs). Needs react-dom and @testing-library/dom, both in every app.
 */
import { fireEvent, getAllByRole, getByLabelText, getByRole, getByText, queryByRole } from '@testing-library/dom'
import { act, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  AboutPage,
  Avatar,
  Badge,
  Box,
  Button,
  ButtonGroup,
  Card,
  Checkbox,
  CheckboxRow,
  Chip,
  Collapsible,
  ConfirmDialog,
  Dialog,
  CopyRow,
  Facts,
  Field,
  IconButton,
  NEXUI_TEXTS,
  areaText,
  NexuiLanguage,
  NotifyWays,
  Row,
  Rows,
  Segment,
  SelectField,
  SettingsLayout,
  SettingsNav,
  SettingsPage,
  Table,
  ThemeSegment,
  ICONS,
  formatDay,
  formatMoment,
  inSentence,
  WhatsNewBanner,
  WhatsNewDialog,
} from './index'
import type { RowMarks } from './index'
import { BUTTON_KIND } from './styles'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let shown: { root: HTMLElement; unmount: () => void } | null = null

function show(element: ReactNode): HTMLElement {
  const root = document.createElement('div')
  document.body.append(root)
  const react = createRoot(root)
  act(() => react.render(element))
  shown = {
    root,
    unmount: () => {
      act(() => react.unmount())
      root.remove()
    },
  }
  return root
}

afterEach(() => {
  shown?.unmount()
  shown = null
})

describe('dates and moments (since 1.1.2, E65)', () => {
  const now = new Date(2027, 1, 24, 18, 30)
  const at = (day: number, hour: number, minute: number) => new Date(2027, 1, day, hour, minute)

  it('write a day with two digits in each language', () => {
    expect([formatDay(at(3, 9, 5), 'de'), formatDay(at(3, 9, 5), 'en'), formatDay(at(3, 9, 5), 'fr')]).toEqual(['03.02.2027', '03/02/2027', '03/02/2027'])
    expect(formatDay('no date', 'de')).toBe('no date')
  })

  it('say today and yesterday, else the day, with the time of 24 hours', () => {
    expect([formatMoment(at(24, 14, 5), 'de', now), formatMoment(at(23, 7, 3), 'de', now), formatMoment(at(22, 14, 5), 'de', now)]).toEqual([
      'heute, 14:05',
      'gestern, 07:03',
      '22.02.2027, 14:05',
    ])
    expect([formatMoment(at(24, 14, 5), 'en', now), formatMoment(at(23, 21, 0), 'en', now), formatMoment(at(22, 14, 5), 'en', now)]).toEqual([
      'today, 14:05',
      'yesterday, 21:00',
      '22/02/2027, 14:05',
    ])
    expect([formatMoment(at(24, 14, 5), 'fr', now), formatMoment(at(23, 21, 0), 'fr', now), formatMoment(at(22, 14, 5), 'fr', now)]).toEqual([
      'aujourd’hui, 14:05',
      'hier, 21:00',
      '22/02/2027, 14:05',
    ])
    expect(formatMoment(new Date(2027, 2, 1, 8, 0), 'de', new Date(2027, 2, 2, 0, 5))).toBe('gestern, 08:00')
  })

  it('put an area word into an English or French sentence in small letters (M-19)', () => {
    expect([inSentence('Address books', 'en'), inSentence('Carnets', 'fr'), inSentence('Adressbücher', 'de'), inSentence('IMAP folders', 'en')]).toEqual([
      'address books',
      'carnets',
      'Adressbücher',
      'IMAP folders',
    ])
  })
})

describe('Button', () => {
  it('comes in three kinds, each with its symbol in front, all the same size', () => {
    const root = show(
      <>
        <Button kind="primary" icon="Check">Save</Button>
        <Button kind="secondary" icon="KeyRound">Change password</Button>
        <Button kind="danger" icon="LogOut">Sign out everywhere else</Button>
      </>,
    )
    const buttons = Array.from(root.querySelectorAll('button'))
    expect(buttons.map((button) => button.dataset.kind)).toEqual(['primary', 'secondary', 'danger'])
    expect(buttons.map((button) => button.dataset.icon)).toEqual(['Check', 'KeyRound', 'LogOut'])
    for (const button of buttons) {
      expect(button.firstElementChild?.tagName.toLowerCase()).toBe('svg')
      expect(button.firstElementChild?.getAttribute('aria-hidden')).toBe('true')
      for (const size of ['h-10', 'rounded-[9px]', 'text-sm', 'font-semibold', 'px-4', 'border']) expect(button.className.split(' ')).toContain(size)
    }
    expect(buttons[0]?.className).toContain('bg-[var(--nexui-accent)]')
    expect(buttons[1]?.className).toContain('border-[var(--nexui-edge)]')
    expect(buttons[2]?.className).toContain('text-[var(--nexui-danger)]')
    // The name is the words alone; the symbol is hidden from readers.
    expect(getByRole(root, 'button', { name: 'Change password' })).toBe(buttons[1])
  })

  it('is a button that does not send a form unless told so, and locks while busy', () => {
    const clicked = vi.fn()
    const root = show(
      <Button kind="secondary" icon="RefreshCw" busy onClick={clicked}>
        New codes
      </Button>,
    )
    const button = getByRole(root, 'button', { name: 'New codes' }) as HTMLButtonElement
    expect(button.type).toBe('button')
    expect(button.disabled).toBe(true)
    expect(button.getAttribute('aria-busy')).toBe('true')
    fireEvent.click(button)
    expect(clicked).not.toHaveBeenCalled()
  })

  it('looks the same as a link and as a file picker', () => {
    const picked = vi.fn()
    const root = show(
      <>
        <Button kind="secondary" icon="KeyRound" href="/start">Sign in with Pocket ID</Button>
        <Button kind="secondary" icon="Upload" onFile={picked} accept="image/*" testId="picture">Upload picture</Button>
      </>,
    )
    const link = getByRole(root, 'link', { name: 'Sign in with Pocket ID' })
    expect(link.dataset.kind).toBe('secondary')
    expect(link.dataset.icon).toBe('KeyRound')
    const picker = getByLabelText(root, 'Upload picture') as HTMLInputElement
    expect(picker.type).toBe('file')
    expect(picker.accept).toBe('image/*')
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    fireEvent.change(picker, { target: { files: [file] } })
    expect(picked).toHaveBeenCalledWith(file)
    expect(root.querySelector('[data-testid="picture"]')?.getAttribute('data-kind')).toBe('secondary')
  })

  it('keeps its hidden helpers inside: a page with a fixed frame does not grow below the window (B7, 1.1.4)', () => {
    // `sr-only` is `position: absolute`; with no placed ancestor it hangs on the page, past every scrolling area.
    const root = show(
      <>
        <CopyRow label="Key" value="ntk_x" />
        <Button kind="secondary" icon="Upload" onFile={() => undefined}>Upload</Button>
      </>,
    )
    const hidden = [...root.querySelectorAll<HTMLElement>('.sr-only')]
    expect(hidden).toHaveLength(2)
    for (const element of hidden) expect(element.parentElement?.className.split(' ')).toContain('relative')
  })

  it('knows every symbol it is asked for by name', () => {
    for (const name of Object.keys(ICONS)) {
      const root = show(<Button kind="secondary" icon={name as keyof typeof ICONS}>{name}</Button>)
      expect(root.querySelector('button svg'), name).not.toBeNull()
      shown?.unmount()
      shown = null
    }
  })
})

describe('Card, Box, Row, Badge', () => {
  it('name their parts by their titles and describe a box by its line', () => {
    const root = show(
      <Card icon="ShieldCheck" title="Security" subtitle="How you sign in">
        <Box title="Second factor" badge={<Badge tone="off">Off</Badge>} hint="A code from an app" actions={<Button kind="primary" icon="ShieldCheck">Set up</Button>}>
          <Rows label="Devices">
            <Row icon="LogIn" name="Firefox" badge={<Badge tone="on">This browser</Badge>} detail="today" action={<Button kind="danger" icon="LogOut">Sign out</Button>} />
          </Rows>
        </Box>
      </Card>,
    )
    const card = getByRole(root, 'region', { name: 'Security' })
    expect(card.tagName.toLowerCase()).toBe('section')
    expect(getByRole(card, 'heading', { level: 2, name: 'Security' })).toBeTruthy()
    const box = getByRole(card, 'region', { name: 'Second factor' })
    expect(getByRole(box, 'heading', { level: 3, name: 'Second factor' })).toBeTruthy()
    const hint = document.getElementById(box.getAttribute('aria-describedby') ?? '')
    expect(hint?.textContent).toBe('A code from an app')
    expect(getByText(box, 'Off').dataset.tone).toBe('off')
    expect(getByText(box, 'This browser').dataset.tone).toBe('on')
    const list = getByRole(box, 'list', { name: 'Devices' })
    expect(getByRole(list, 'listitem').textContent).toContain('Firefox')
    expect(getByRole(box, 'button', { name: 'Sign out' }).dataset.kind).toBe('danger')
  })

  it('lets a long title of a box wrap instead of cutting it, the badge moves under it (since 1.0.0, 360 px)', () => {
    // nexmail at 360 px: "Wiederherstellungscodes" needs 172 px and had 162 next to its badge. jsdom draws nothing,
    // so the test holds the classes that make it right: the title never shrinks below its longest word, the row wraps.
    const root = show(
      <div style={{ width: '360px' }}>
        <Box title="Wiederherstellungscodes" badge={<Badge tone="warn">3 übrig</Badge>} hint="Für den Notfall" />
      </div>,
    )
    const heading = getByRole(root, 'heading', { level: 3, name: 'Wiederherstellungscodes' })
    const classes = heading.className.split(/\s+/)
    for (const cutting of ['truncate', 'min-w-0', 'whitespace-nowrap', 'overflow-hidden', 'text-ellipsis']) {
      expect(classes, cutting).not.toContain(cutting)
    }
    expect(classes).toContain('[overflow-wrap:break-word]')
    expect(heading.parentElement?.className.split(/\s+/)).toContain('flex-wrap')
    expect(heading.parentElement?.contains(getByText(root, '3 übrig'))).toBe(true)
    expect(heading.textContent).toBe('Wiederherstellungscodes')
  })
})

describe('fields', () => {
  it('are named by exactly their label and described by their hints and problem', () => {
    const root = show(
      <>
        <Field label="Username" hints={['You sign in with it.', '2 to 64 characters.']} value="kim" onChange={() => undefined} />
        <Field label="Email" error="That is no address." value="x" onChange={() => undefined} />
        <SelectField label="Language" options={[{ value: 'de', label: 'Deutsch' }]} value="de" onChange={() => undefined} />
      </>,
    )
    const username = getByLabelText(root, 'Username')
    const said = (field: HTMLElement) =>
      (field.getAttribute('aria-describedby') ?? '')
        .split(' ')
        .map((id) => document.getElementById(id)?.textContent)
        .join(' ')
    expect(said(username)).toBe('You sign in with it. 2 to 64 characters.')
    const email = getByLabelText(root, 'Email')
    expect(email.getAttribute('aria-invalid')).toBe('true')
    expect(said(email)).toBe('That is no address.')
    expect(getByRole(root, 'alert').textContent).toBe('That is no address.')
    expect(getByLabelText(root, 'Language').tagName.toLowerCase()).toBe('select')
  })

  it('tick boxes inline and as a framed row, the row described by its line', () => {
    const changed = vi.fn()
    const root = show(
      <>
        <Checkbox label="Stay signed in" checked onChange={changed} />
        <CheckboxRow label="Mail on a new sign-in" hint="When a new browser signs in" checked={false} onChange={changed} />
      </>,
    )
    const stay = getByLabelText(root, 'Stay signed in') as HTMLInputElement
    expect(stay.checked).toBe(true)
    const mail = getByRole(root, 'checkbox', { name: 'Mail on a new sign-in' })
    expect(document.getElementById(mail.getAttribute('aria-describedby') ?? '')?.textContent).toBe('When a new browser signs in')
    fireEvent.click(mail)
    expect(changed).toHaveBeenCalledWith(true)
  })
})

describe('ConfirmDialog', () => {
  it('is a dialog named by its title, cancels first and confirms with the given kind', () => {
    const confirmed = vi.fn()
    const cancelled = vi.fn()
    const root = show(
      <ConfirmDialog
        title="Remove passkey"
        text="Really?"
        confirm={{ label: 'Remove', kind: 'danger', icon: 'Trash2' }}
        cancel="Cancel"
        closeLabel="Close"
        onConfirm={confirmed}
        onCancel={cancelled}
      >
        <Field label="Password" type="password" value="secret" onChange={() => undefined} />
      </ConfirmDialog>,
    )
    const dialog = getByRole(document.body, 'dialog', { name: 'Remove passkey' })
    expect(root.contains(dialog)).toBe(true)
    expect(document.activeElement).toBe(getByLabelText(dialog, 'Password'))
    const buttons = Array.from(dialog.querySelectorAll<HTMLElement>('button[data-kind]'))
    expect(buttons.map((button) => [button.textContent, button.dataset.kind, button.dataset.icon])).toEqual([
      ['Cancel', 'secondary', 'X'],
      ['Remove', 'danger', 'Trash2'],
    ])
    fireEvent.click(getByRole(dialog, 'button', { name: 'Remove' }))
    expect(confirmed).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(cancelled).toHaveBeenCalledTimes(1)
    expect(queryByRole(dialog, 'button', { name: 'Close' })).not.toBeNull()
  })

  it.each([true, false])('with dismissable %s: Escape and a click beside it close only when dismissable (since E38)', (dismissable) => {
    const cancelled = vi.fn()
    show(
      <ConfirmDialog
        title="Restore"
        confirm={{ label: 'Restore', kind: 'primary', icon: 'RotateCcw' }}
        cancel="Cancel"
        closeLabel="Close"
        onConfirm={() => undefined}
        onCancel={cancelled}
        dismissable={dismissable}
      />,
    )
    const dialog = getByRole(document.body, 'dialog', { name: 'Restore' })
    fireEvent.keyDown(window, { key: 'Escape' })
    fireEvent.pointerDown(dialog.parentElement as HTMLElement)
    expect(cancelled).toHaveBeenCalledTimes(dismissable ? 2 : 0)
    // The buttons always end it: "Cancel" and the close button.
    fireEvent.click(getByRole(dialog, 'button', { name: 'Cancel' }))
    fireEvent.click(getByRole(dialog, 'button', { name: 'Close' }))
    expect(cancelled).toHaveBeenCalledTimes(dismissable ? 4 : 2)
  })

  it('Escape closes only the topmost of two stacked dialogs, a second Escape the one below (since E47)', () => {
    const closed: string[] = []
    function Stack() {
      const [lower, setLower] = useState(true)
      const [upper, setUpper] = useState(true)
      return (
        <>
          {lower && (
            <Dialog title="Lower" onClose={() => (closed.push('lower'), setLower(false))} closeLabel="Close">
              <p>below</p>
            </Dialog>
          )}
          {upper && (
            <Dialog title="Upper" onClose={() => (closed.push('upper'), setUpper(false))} closeLabel="Close">
              <p>on top</p>
            </Dialog>
          )}
        </>
      )
    }
    show(<Stack />)
    act(() => fireEvent.keyDown(window, { key: 'Escape' }))
    expect(closed).toEqual(['upper'])
    expect(queryByRole(document.body, 'dialog', { name: 'Lower' })).not.toBeNull()
    act(() => fireEvent.keyDown(window, { key: 'Escape' }))
    expect(closed).toEqual(['upper', 'lower'])
    expect(queryByRole(document.body, 'dialog')).toBeNull()
  })

  it('a topmost dialog that is not dismissable keeps Escape, the one below stays open', () => {
    const closed: string[] = []
    show(
      <>
        <Dialog title="Lower" onClose={() => closed.push('lower')} closeLabel="Close">
          <p>below</p>
        </Dialog>
        <Dialog title="Upper" onClose={() => closed.push('upper')} closeLabel="Close" dismissable={false}>
          <p>on top</p>
        </Dialog>
      </>,
    )
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(closed).toEqual([])
  })

  it('a Dialog that is not dismissable stays on Escape and a click beside it, its close button still closes', () => {
    const closed = vi.fn()
    show(
      <Dialog title="Pairing" onClose={closed} closeLabel="Close" dismissable={false}>
        <p>Scan the code</p>
      </Dialog>,
    )
    const dialog = getByRole(document.body, 'dialog', { name: 'Pairing' })
    fireEvent.keyDown(window, { key: 'Escape' })
    fireEvent.pointerDown(dialog.parentElement as HTMLElement)
    fireEvent.pointerDown(dialog)
    expect(closed).not.toHaveBeenCalled()
    fireEvent.click(getByRole(dialog, 'button', { name: 'Close' }))
    expect(closed).toHaveBeenCalledTimes(1)
  })
})

describe('Avatar, Row with a picture, Facts, ButtonGroup (since 0.1.1)', () => {
  it('shows the own picture, else the letter on its hue, round, 32 or 48 px, hidden from readers', () => {
    const root = show(
      <>
        <Avatar src="/a.webp" letter="K" hue={200} testId="picture" />
        <Avatar letter="M" hue={-20} size={48} testId="letter" />
      </>,
    )
    const picture = root.querySelector<HTMLElement>('[data-testid="picture"]')
    expect(picture?.tagName.toLowerCase()).toBe('img')
    expect(picture?.getAttribute('aria-hidden')).toBe('true')
    expect(picture?.className).toContain('rounded-full')
    expect(picture?.className).toContain('h-8')
    const letter = root.querySelector<HTMLElement>('[data-testid="letter"]')
    expect(letter?.textContent).toBe('M')
    expect(letter?.dataset.hue).toBe('340')
    expect(letter?.style.getPropertyValue('--nexui-avatar-hue')).toBe('340')
    expect(letter?.className).toContain('h-12')
    expect(letter?.className).toContain('var(--nexui-avatar-saturation)')
    expect(letter?.getAttribute('aria-hidden')).toBe('true')
    // A picture that does not load gives way to the letter.
    act(() => {
      picture?.dispatchEvent(new Event('error'))
    })
    expect(root.querySelector('[data-testid="picture"]')?.textContent).toBe('K')
  })

  it("paints the letter in the app's colour of the person where it has one (since 0.1.2)", () => {
    const root = show(
      <>
        <Avatar letter="K" hue={200} color="rgb(74, 100, 145)" testId="coloured" />
        <Avatar letter="M" hue={20} color="  " testId="plain" />
      </>,
    )
    const coloured = root.querySelector<HTMLElement>('[data-testid="coloured"]')
    expect(coloured?.style.backgroundColor).toBe('rgb(74, 100, 145)')
    expect(coloured?.dataset.color).toBe('rgb(74, 100, 145)')
    expect(coloured?.dataset.hue).toBe('200')
    const plain = root.querySelector<HTMLElement>('[data-testid="plain"]')
    expect(plain?.style.backgroundColor).toBe('')
    expect(plain?.dataset.color).toBeUndefined()
  })

  it('a row takes a picture in place of the symbol and a second line, an old row stays as it was', () => {
    const root = show(
      <Rows label="Accounts">
        <Row
          lead={<Avatar letter="K" hue={10} />}
          name="Kim"
          badge={
            <>
              <Badge tone="accent">Operator</Badge>
              <Badge tone="danger">Blocked</Badge>
            </>
          }
          sub="kim · kim@example.com"
          action={<Button kind="secondary" icon="UserCog">Manage</Button>}
        />
        <Row icon="KeyRound" name="Pocket ID" />
      </Rows>,
    )
    const [person, plain] = getAllByRole(root, 'listitem')
    expect(person?.querySelector('svg')?.closest('button')).not.toBeNull()
    expect(getByText(person as HTMLElement, 'kim · kim@example.com').className).toContain('text-xs')
    expect(getByText(person as HTMLElement, 'Operator').dataset.tone).toBe('accent')
    expect(getByText(person as HTMLElement, 'Blocked').dataset.tone).toBe('danger')
    expect(getByRole(person as HTMLElement, 'button', { name: 'Manage' }).dataset.icon).toBe('UserCog')
    expect(plain?.firstElementChild?.tagName.toLowerCase()).toBe('svg')
    expect(plain?.textContent).toBe('Pocket ID')
  })

  it('Facts pair every label with its value, ButtonGroup names its group by its heading', () => {
    const root = show(
      <>
        <Facts label="About Kim" items={[{ label: 'Username', value: 'kim' }, { label: 'Email', value: 'kim@example.com', note: 'confirmed' }]} />
        <ButtonGroup title="Access">
          <Button kind="secondary" icon="Link">Link for a new password</Button>
        </ButtonGroup>
        <ButtonGroup title="Rights" layout="list">
          <CheckboxRow label="AI allowed" checked onChange={() => undefined} />
        </ButtonGroup>
      </>,
    )
    const list = root.querySelector('dl')
    expect(list?.getAttribute('aria-label')).toBe('About Kim')
    expect(Array.from(list?.querySelectorAll('dt') ?? []).map((term) => term.textContent)).toEqual(['Username', 'Email'])
    const values = Array.from(list?.querySelectorAll('dd') ?? [])
    expect(values.map((value) => value.firstChild?.textContent)).toEqual(['kim', 'kim@example.com'])
    expect(values[1]?.querySelector('span')?.textContent).toBe('confirmed')
    const access = getByRole(root, 'region', { name: 'Access' })
    expect(getByRole(access, 'heading', { level: 3, name: 'Access' })).toBeTruthy()
    expect(getByRole(access, 'button', { name: 'Link for a new password' }).dataset.kind).toBe('secondary')
    const rights = getByRole(root, 'region', { name: 'Rights' })
    expect(rights.dataset.groupLayout).toBe('list')
    expect(getByRole(rights, 'checkbox', { name: 'AI allowed' })).toBeTruthy()
  })
})

describe('Button sizes, Field action, Segment (since 1.1.0)', () => {
  it('has two sizes, md by default as in 1.0.0 and sm for rows, both with symbol and words, in the three kinds only', () => {
    expect(Object.keys(BUTTON_KIND)).toEqual(['primary', 'secondary', 'danger'])
    const root = show(
      <>
        <Button kind="primary" icon="Check">Save</Button>
        <Button kind="primary" icon="Check" size="sm">Save row</Button>
        <Button kind="secondary" icon="Pencil" size="sm">Edit</Button>
        <Button kind="danger" icon="Trash2" size="sm">Remove</Button>
        <Button kind="secondary" icon="Download" size="sm" href="/file">Download</Button>
        <Button kind="secondary" icon="Upload" size="sm" onFile={() => undefined} testId="picker">Upload</Button>
      </>,
    )
    const all = Array.from(root.querySelectorAll<HTMLElement>('[data-kind]'))
    expect(all.map((element) => element.dataset.size)).toEqual(['md', 'sm', 'sm', 'sm', 'sm', 'sm'])
    for (const element of all) {
      // The symbol pledge holds for both sizes: a hidden symbol first, then words.
      expect(element.firstElementChild?.tagName.toLowerCase(), element.textContent ?? '').toBe('svg')
      expect(element.firstElementChild?.getAttribute('aria-hidden')).toBe('true')
      expect(element.dataset.icon).toBeTruthy()
      expect(element.textContent?.trim()).not.toBe('')
      expect(['primary', 'secondary', 'danger']).toContain(element.dataset.kind)
    }
    const [md, ...small] = all
    for (const size of ['h-10', 'px-4', 'text-sm']) expect(md?.className.split(' ')).toContain(size)
    expect(md?.firstElementChild?.getAttribute('class')).toContain('h-4')
    for (const element of small) {
      const classes = element.className.split(' ')
      for (const size of ['h-8', 'px-3', 'text-[13px]', 'rounded-[9px]', 'font-semibold']) expect(classes, size).toContain(size)
      expect(classes).not.toContain('h-10')
      expect(element.firstElementChild?.getAttribute('class')).toContain('h-3.5')
    }
  })

  it('puts the button of a field right of it, level with the field, and the hints under both over the whole width', () => {
    const root = show(
      <Field
        label="Public address"
        hints={['Links in mails start with it.']}
        value="https://notes.example.com"
        onChange={() => undefined}
        action={<Button kind="primary" icon="Check">Save</Button>}
      />,
    )
    const field = getByLabelText(root, 'Public address')
    const row = root.querySelector<HTMLElement>('[data-part="field-action"]')
    expect(row?.contains(field)).toBe(true)
    expect(row?.contains(getByRole(root, 'button', { name: 'Save' }))).toBe(true)
    expect(row?.className.split(' ')).toContain('items-start')
    expect(row?.contains(root.querySelector('label'))).toBe(false)
    const hint = document.getElementById(field.getAttribute('aria-describedby') ?? '')
    expect(hint?.textContent).toBe('Links in mails start with it.')
    expect(row?.contains(hint as Node)).toBe(false)
    expect(hint?.parentElement).toBe(row?.parentElement)
    // Without an action the field is laid out as in 1.0.0.
    shown?.unmount()
    shown = null
    const plain = show(<Field label="Name" value="" onChange={() => undefined} />)
    expect(plain.querySelector('[data-part="field-action"]')).toBeNull()
  })

  it('a segment is a radiogroup named by its label, the chosen one in the accent, the arrows move the choice', () => {
    const changed = vi.fn()
    const root = show(
      <Segment
        label="Light or dark"
        hints={['Applies on all your devices.']}
        value="system"
        onChange={changed}
        options={[
          { value: 'light', label: 'Light', icon: 'Sun' },
          { value: 'dark', label: 'Dark', icon: 'Moon', disabled: true },
          { value: 'system', label: 'As the system', icon: 'Monitor' },
        ]}
      />,
    )
    const group = getByRole(root, 'radiogroup', { name: 'Light or dark' })
    expect(document.getElementById(group.getAttribute('aria-describedby') ?? '')?.textContent).toBe('Applies on all your devices.')
    const radios = getAllByRole(group, 'radio')
    expect(radios.map((radio) => radio.getAttribute('aria-checked'))).toEqual(['false', 'false', 'true'])
    expect(radios.map((radio) => radio.tabIndex)).toEqual([-1, -1, 0])
    expect(radios.map((radio) => radio.dataset.icon)).toEqual(['Sun', 'Moon', 'Monitor'])
    expect(radios[2]?.className).toContain('color-mix(in_srgb,var(--nexui-accent)_14%,transparent)')
    expect(radios[2]?.className.split(' ')).toContain('h-8')
    fireEvent.click(radios[0] as HTMLElement)
    expect(changed).toHaveBeenLastCalledWith('light')
    // The arrows go round and skip the disabled one: from "As the system" both ways lead to "Light".
    changed.mockClear()
    fireEvent.keyDown(radios[2] as HTMLElement, { key: 'ArrowRight' })
    expect(changed).toHaveBeenLastCalledWith('light')
    changed.mockClear()
    fireEvent.keyDown(radios[2] as HTMLElement, { key: 'ArrowLeft' })
    expect(changed).toHaveBeenLastCalledWith('light')
    expect((radios[1] as HTMLButtonElement).disabled).toBe(true)
  })

  it('a segment with multiple is a group of boxes to tick, and keeps the last one when it must', () => {
    const changed = vi.fn()
    const root = show(
      <Segment
        multiple
        min={1}
        label="Languages"
        hideLabel
        value={['deu']}
        onChange={changed}
        options={[
          { value: 'deu', label: 'Deutsch' },
          { value: 'eng', label: 'English' },
        ]}
      />,
    )
    const group = getByRole(root, 'group', { name: 'Languages' })
    expect(root.textContent).not.toContain('Languages')
    const [german, english] = getAllByRole(group, 'checkbox') as HTMLButtonElement[]
    expect(german?.getAttribute('aria-checked')).toBe('true')
    expect(german?.disabled).toBe(true)
    fireEvent.click(english as HTMLElement)
    expect(changed).toHaveBeenLastCalledWith(['deu', 'eng'])
  })
})

describe('the parts of the settings (since 1.1.0)', () => {
  it('has its words in German, English and French, each with the same keys and none empty but a line', () => {
    const keys = (value: object, prefix = ''): string[] =>
      Object.entries(value).flatMap(([key, inner]) => (typeof inner === 'object' && inner ? keys(inner as object, `${prefix}${key}.`) : [`${prefix}${key}`]))
    const german = keys(NEXUI_TEXTS.de).sort()
    expect(keys(NEXUI_TEXTS.en).sort()).toEqual(german)
    expect(keys(NEXUI_TEXTS.fr).sort()).toEqual(german)
    for (const language of ['de', 'en', 'fr'] as const) {
      for (const [key, text] of Object.entries(NEXUI_TEXTS[language])) if (typeof text === 'string') expect(text, `${language}.${key}`).not.toBe('')
      expect(NEXUI_TEXTS[language].areas.profile.text).not.toBe('')
    }
    // The plan's words, word for word.
    expect(NEXUI_TEXTS.de.areas.connections.text).toBe('Geräte, andere Apps, API-Schlüssel und KI-Werkzeuge, die mit deinen {thingsDative} arbeiten.')
    expect(NEXUI_TEXTS.de.themeHint).toBe('Gilt auf allen deinen Geräten. „Wie das System“ folgt dem Gerät.')
  })

  it('a card carries its id as data-card; a button without words is only for moving and dragging, and named', () => {
    const root = show(
      <Card id="notify-ways" icon="Bell" title="Which way">
        <IconButton icon="ArrowUp" aria-label="Move Pocket ID up" />
        <IconButton icon="GripVertical" aria-label="Drag Pocket ID" />
      </Card>,
    )
    expect(root.querySelector('[data-card="notify-ways"]')?.tagName.toLowerCase()).toBe('section')
    const up = getByRole(root, 'button', { name: 'Move Pocket ID up' })
    expect(up.dataset.icon).toBe('ArrowUp')
    expect(up.textContent).toBe('')
    expect(up.getAttribute('title')).toBe('Move Pocket ID up')
    expect(getByRole(root, 'button', { name: 'Drag Pocket ID' }).className).toContain('cursor-grab')
  })

  it('a collapsible is closed until opened, its head a button that says how it stands, the status beside the title', () => {
    const root = show(
      <>
        <Collapsible title="Address with https" status={<Badge tone="on">ok</Badge>}>
          <p>Explained.</p>
        </Collapsible>
        <Collapsible variant="card" id="nextasks" icon="Plug" logo="/nextasks.svg" title="nextasks" subtitle="Tasks from notes" status="connected · tasks.example.com">
          <p>Address and key.</p>
        </Collapsible>
      </>,
    )
    const [box, card] = getAllByRole(root, 'button')
    expect(box?.getAttribute('aria-expanded')).toBe('false')
    expect(root.textContent).not.toContain('Explained.')
    expect(getByRole(root, 'heading', { level: 3, name: /Address with https/ }).contains(box as Node)).toBe(true)
    expect(box?.textContent).toContain('ok')
    act(() => {
      fireEvent.click(box as HTMLElement)
    })
    expect(box?.getAttribute('aria-expanded')).toBe('true')
    expect(document.getElementById(box?.getAttribute('aria-controls') ?? '')?.textContent).toBe('Explained.')
    const section = root.querySelector<HTMLElement>('[data-card="nextasks"]')
    expect(section?.dataset.collapsible).toBe('card')
    expect(section?.querySelector('img')?.getAttribute('src')).toBe('/nextasks.svg')
    expect(getByRole(root, 'heading', { level: 2, name: /nextasks/ }).contains(card as Node)).toBe(true)
    expect(card?.textContent).toContain('connected · tasks.example.com')
  })

  it('keeps a short title whole at 420 px: title and state wrap as a whole, the state goes under the title (V-15)', () => {
    const root = show(
      <div style={{ width: '420px' }}>
        <Collapsible variant="card" id="nextime" icon="Plug" title="nextime" subtitle="Termine und Aufgaben" status="Nicht erreichbar · time.example.com">
          <p>Inside.</p>
        </Collapsible>
      </div>,
    )
    const main = root.querySelector<HTMLElement>('[data-part="collapsible-main"]')!
    expect(main.className.split(' ')).toEqual(expect.arrayContaining(['flex', 'flex-wrap', 'min-w-0', 'flex-1']))
    const title = main.querySelector<HTMLElement>('[data-part="collapsible-title"]')!
    expect(title.className.split(' ')).toEqual(expect.arrayContaining(['min-w-[min(100%,10rem)]', 'basis-40', 'flex-1']))
    expect(title.textContent).toContain('nextime')
    const status = main.querySelector<HTMLElement>('[data-part="collapsible-status"]')!
    expect(status.className).not.toContain('shrink-0')
    expect(status.className.split(' ')).toEqual(expect.arrayContaining(['min-w-0', 'max-w-full']))
    expect(title.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('a collapsible held by the caller opens only when told', () => {
    const asked = vi.fn()
    const root = show(
      <Collapsible title="Proxy" open={false} onOpenChange={asked}>
        <p>Inside.</p>
      </Collapsible>,
    )
    fireEvent.click(getByRole(root, 'button', { name: /Proxy/ }))
    expect(asked).toHaveBeenCalledWith(true)
    expect(root.textContent).not.toContain('Inside.')
  })

  it('a table has a head row and the same rows as cards for a phone, both with their marks', () => {
    type Line = { id: number; level: string; message: string }
    const root = show(
      <Table<Line, 'level' | 'message'>
        label="Log"
        columns={[
          { key: 'level', label: 'Level', width: '5.5rem' },
          { key: 'message', label: 'Message' },
        ]}
        rows={[
          { id: 1, level: 'ERROR', message: 'It broke' },
          { id: 2, level: 'INFO', message: 'Started' },
        ]}
        rowKey={(line) => line.id}
        rowProps={(line) => ({ 'data-level': line.level })}
        cell={(line, key) => line[key]}
      />,
    )
    const table = getByRole(root, 'table', { name: 'Log' })
    expect(getAllByRole(table, 'columnheader').map((head) => head.textContent)).toEqual(['Level', 'Message'])
    expect(Array.from(table.querySelectorAll('tbody tr')).map((row) => row.getAttribute('data-level'))).toEqual(['ERROR', 'INFO'])
    expect(table.className).toContain('@min-[640px]:table')
    const cards = getByRole(root, 'list', { name: 'Log' })
    expect(cards.className).toContain('@min-[640px]:hidden')
    const items = getAllByRole(cards, 'listitem')
    expect(items.map((item) => item.getAttribute('data-level'))).toEqual(['ERROR', 'INFO'])
    expect(Array.from(items[0]?.querySelectorAll('dt') ?? []).map((term) => term.textContent)).toEqual(['Level', 'Message'])
    shown?.unmount()
    shown = null
    const none = show(<Table label="Log" columns={[{ key: 'a', label: 'A' }]} rows={[]} cell={() => null} empty="Nothing yet." />)
    expect(none.textContent).toBe('Nothing yet.')
  })

  it('a table row takes only data marks, never an id that would stand twice in the page (E56)', () => {
    const columns = [{ key: 'a', label: 'A' }]
    const marked = show(<Table label="Keys" columns={columns} rows={['x']} rowProps={() => ({ 'data-testid': 'key-row' })} cell={(row) => row} />)
    // Both forms carry the mark: a test takes the visible one.
    expect(marked.querySelectorAll('[data-testid="key-row"]')).toHaveLength(2)
    expect(marked.querySelectorAll('[id]')).toHaveLength(0)
    shown?.unmount()
    shown = null
    const withId: (row: string) => RowMarks = () => ({
      // @ts-expect-error an id is no data mark
      id: 'row-1',
    })
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    expect(() => show(<Table label="Keys" columns={columns} rows={['x']} rowProps={withId} cell={(row) => row} />)).toThrow(/not "id"/)
    quiet.mockRestore()
    shown = null
  })

  it('a copy row shows the value in fixed letters and copies it with a small button that says so', async () => {
    const written = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: written }, configurable: true })
    const root = show(
      <NexuiLanguage language="de-DE">
        <CopyRow label="Adresse" value="https://notes.example.com/caldav" />
      </NexuiLanguage>,
    )
    const field = getByLabelText(root, 'Adresse') as HTMLInputElement
    expect(field.readOnly).toBe(true)
    expect(field.className).toContain('font-mono')
    const button = getByRole(root, 'button', { name: 'Kopieren' })
    expect([button.dataset.size, button.dataset.kind, button.dataset.icon]).toEqual(['sm', 'secondary', 'Copy'])
    await act(async () => {
      fireEvent.click(button)
      await Promise.resolve()
    })
    expect(written).toHaveBeenCalledWith('https://notes.example.com/caldav')
    expect(getByRole(root, 'button', { name: 'Kopiert' }).dataset.icon).toBe('Check')
    expect(getByRole(root, 'status').textContent).toBe('Kopiert')
  })

  it('a chip shows a thing and, where it may go, a remove button named after it', () => {
    const removed = vi.fn()
    const root = show(
      <NexuiLanguage language="en">
        <Chip>Deutsch</Chip>
        <Chip name="Plattdeutsch" onRemove={removed}>
          Plattdeutsch (nds) · 412 texts
        </Chip>
      </NexuiLanguage>,
    )
    expect(getAllByRole(root, 'button')).toHaveLength(1)
    fireEvent.click(getByRole(root, 'button', { name: 'Remove Plattdeutsch' }))
    expect(removed).toHaveBeenCalledTimes(1)
  })

  it("the theme segment says light, dark, as the system in the kit's words", () => {
    const chosen = vi.fn()
    const root = show(
      <NexuiLanguage language="de">
        <ThemeSegment value="system" onChange={chosen} />
      </NexuiLanguage>,
    )
    const group = getByRole(root, 'radiogroup', { name: 'Hell oder dunkel' })
    expect(getAllByRole(group, 'radio').map((radio) => [radio.textContent, radio.dataset.icon, radio.getAttribute('aria-checked')])).toEqual([
      ['Hell', 'Sun', 'false'],
      ['Dunkel', 'Moon', 'false'],
      ['Wie das System', 'Monitor', 'true'],
    ])
    fireEvent.click(getByRole(group, 'radio', { name: 'Dunkel' }))
    expect(chosen).toHaveBeenCalledWith('dark')
  })

  it("the navigation puts my account first, the app's own group next, server last and about apart, marking where one is", () => {
    const root = show(
      <NexuiLanguage language="de">
        <SettingsLayout
          back="/settings"
          nav={
            <SettingsNav
              app="nexmail"
              things="Mails"
              current="rules"
              account={{ name: 'Kim', role: 'Betreiber' }}
              about={{ href: '/settings/about' }}
              groups={[
                { id: 'server', areas: [{ slug: 'general', icon: 'SlidersHorizontal', href: '/settings/general' }] },
                { id: 'account', areas: [{ slug: 'profile', icon: 'UserRound', href: '/settings/profile' }] },
                { id: 'mail', title: 'Mail', areas: [{ slug: 'rules', title: 'Regeln', icon: 'Mail', href: '/settings/rules' }] },
              ]}
            />
          }
        >
          <SettingsPage slug="connections" app="nexmail" things="Mails">
            <Card id="devices" icon="Smartphone" title="Geräte" />
          </SettingsPage>
        </SettingsLayout>
      </NexuiLanguage>,
    )
    const nav = getByRole(root, 'navigation', { name: 'Einstellungen' })
    expect(Array.from(nav.querySelectorAll('[data-group]')).map((group) => group.getAttribute('data-group'))).toEqual(['account', 'mail', 'server'])
    expect(getAllByRole(nav, 'link').map((link) => link.textContent)).toEqual(['Profil', 'Regeln', 'Allgemein', 'Über nexmail'])
    expect(getByRole(nav, 'link', { name: 'Regeln' }).getAttribute('aria-current')).toBe('page')
    // Every entry carries its whole name as title: a long one is cut off on screen (since E34).
    expect(getAllByRole(nav, 'link').map((link) => link.getAttribute('title'))).toEqual(['Profil', 'Regeln', 'Allgemein', 'Über nexmail'])
    expect(getByRole(nav, 'list', { name: 'Mein Konto' })).toBeTruthy()
    expect(getByRole(root, 'heading', { level: 1, name: 'Verbindungen' })).toBeTruthy()
    expect(root.textContent).toContain('Geräte, andere Apps, API-Schlüssel und KI-Werkzeuge, die mit deinen Mails arbeiten.')
    // Two forms since E34: the line of Connections takes the dative ("mit deinen Kalendern"), the plain form stands in.
    expect(areaText(NEXUI_TEXTS.de, 'connections', { app: 'nextime', things: 'Kalender', thingsDative: 'Kalendern' })?.text).toBe(
      'Geräte, andere Apps, API-Schlüssel und KI-Werkzeuge, die mit deinen Kalendern arbeiten.',
    )
    expect(areaText(NEXUI_TEXTS.de, 'connections', { app: 'nextime', things: 'Kalender' })?.text).toContain('mit deinen Kalender arbeiten')
    // U-3 (1.1.3): the line of Server › General names only the cards the app has.
    expect(areaText(NEXUI_TEXTS.de, 'general', { app: 'nexfolk', parts: ['interfaces', 'languages'] })?.text).toBe('Schnittstellen und eigene Sprachen.')
    expect(areaText(NEXUI_TEXTS.en, 'general', { app: 'nexfolk', parts: ['interfaces', 'nexApps', 'languages'] })?.text).toBe('Interfaces, other nex apps and added languages.')
    expect(areaText(NEXUI_TEXTS.fr, 'general', { app: 'nexfolk', parts: ['limits', 'languages'] })?.text).toBe('Limites et langues ajoutées.')
    expect(areaText(NEXUI_TEXTS.de, 'general', { app: 'nexnotes' })?.text).toBe('Grenzen, Funktionen für alle Konten und eigene Sprachen.')
    // E67 (1.2.1): Server › Verbindungen has its own slug beside My account › Verbindungen (`connections`), and the
    // line of General no longer names the interfaces in any language.
    expect(areaText(NEXUI_TEXTS.de, 'server-connections', { app: 'nexnotes' })).toEqual({
      title: 'Verbindungen',
      text: 'Wie sich andere nex-Apps, Programme und KI-Werkzeuge mit nexnotes verbinden.',
    })
    expect(areaText(NEXUI_TEXTS.en, 'server-connections', { app: 'nextime' })).toEqual({ title: 'Connections', text: 'How other nex apps, programs and AI tools connect with nextime.' })
    expect(areaText(NEXUI_TEXTS.fr, 'server-connections', { app: 'nexlore' })?.title).toBe('Connexions')
    for (const language of ['de', 'en', 'fr'] as const) {
      expect(NEXUI_TEXTS[language].areas.general.text).not.toMatch(/Schnittstellen|interfaces|nex/i)
      expect(NEXUI_TEXTS[language].areas['server-connections'].text).toContain('nex')
    }
    const page = show(
      <NexuiLanguage language="de">
        <SettingsPage slug="general" app="nexfolk" parts={['interfaces', 'nexApps', 'languages']} />
      </NexuiLanguage>,
    )
    expect(page.querySelector('[data-area="general"] p')?.textContent).toBe('Schnittstellen, andere nex-Apps und eigene Sprachen.')
    // A phone in an area: the list is hidden, the way back is there; on the list it is the other way round.
    const side = root.querySelector('[data-part="settings-side"]')
    expect(side?.className.split(' ')).toContain('hidden')
    expect(getByRole(root, 'link', { name: 'Einstellungen' }).getAttribute('href')).toBe('/settings')
    expect(root.querySelector('[data-part="settings-cards"] [data-card="devices"]')).not.toBeNull()
  })

  it('the about page shows version, what is new, licence, source, releases and the updates, the operator acts', () => {
    const checked = vi.fn()
    const daily = vi.fn()
    const root = show(
      <NexuiLanguage language="de">
        <AboutPage
          app="nexnotes"
          logo="/logo.svg"
          tagline="Schnelle Notizen, selbst gehostet."
          version="1.1.0"
          licence={{ name: 'AGPL-3.0', href: 'https://www.gnu.org/licenses/agpl-3.0.html' }}
          source="https://github.com/example/nexnotes"
          releases="https://github.com/example/nexnotes/releases"
          project="https://github.com/example/nexnotes"
          whatsNew={{ lead: 'Neu.', sections: [{ title: 'Einstellungen', where: 'Einstellungen', body: 'Aufgeräumt.' }], smallTitle: 'Kleines', small: ['Schneller'] }}
          updates={{ checkDaily: true, checked: true, latest: 'v1.2.0', newer: true, releaseUrl: 'https://github.com/example/nexnotes/releases/tag/v1.2.0' }}
          operator
          onDaily={daily}
          onCheck={checked}
          builtWith={[{ name: 'React', url: 'https://react.dev', licence: 'MIT' }]}
        />
      </NexuiLanguage>,
    )
    const head = root.querySelector<HTMLElement>('[data-card="about"]') as HTMLElement
    expect(head.querySelector('img')?.getAttribute('src')).toBe('/logo.svg')
    expect(getByRole(head, 'heading', { level: 2, name: 'nexnotes' })).toBeTruthy()
    expect(Array.from(head.querySelectorAll('dt')).map((term) => term.textContent)).toEqual([
      'Version',
      'Was ist neu',
      'Lizenz',
      'Quelltext',
      'Veröffentlichungen',
      'Einen Fehler gefunden?',
    ])
    expect(getByText(head, 'Version 1.2.0 ist erschienen').dataset.tone).toBe('accent')
    const news = getByRole(head, 'button', { name: 'Neu in nexnotes 1.1.0' })
    expect([news.dataset.size, news.dataset.kind]).toEqual(['sm', 'secondary'])
    act(() => {
      fireEvent.click(news)
    })
    const dialog = getByRole(document.body, 'dialog', { name: 'Neu in nexnotes 1.1.0' })
    expect(dialog.textContent).toContain('Aufgeräumt.')
    act(() => {
      fireEvent.click(getByRole(dialog, 'button', { name: 'Verstanden' }))
    })
    expect(queryByRole(document.body, 'dialog')).toBeNull()
    const updates = root.querySelector<HTMLElement>('[data-card="about-updates"]') as HTMLElement
    fireEvent.click(getByRole(updates, 'checkbox', { name: 'Einmal am Tag nachsehen' }))
    expect(daily).toHaveBeenCalledWith(false)
    fireEvent.click(getByRole(updates, 'button', { name: 'Jetzt nachsehen' }))
    expect(checked).toHaveBeenCalledTimes(1)
    expect(updates.textContent).toContain('api.github.com')
    expect(root.querySelector('[data-card="about-built-with"]')?.textContent).toContain('React(MIT)')
  })

  it('the about page leaves the card "Aktualisierungen" out for a member (since 1.1.1)', () => {
    const root = show(
      <NexuiLanguage language="de">
        <AboutPage
          app="nexnotes"
          logo="/logo.svg"
          tagline="Schnelle Notizen, selbst gehostet."
          version="1.1.0"
          licence={{ name: 'AGPL-3.0', href: 'https://www.gnu.org/licenses/agpl-3.0.html' }}
          source="https://github.com/example/nexnotes"
          updates={{ checkDaily: true, checked: true, latest: 'v1.2.0', newer: true }}
          showUpdates={false}
          builtWith={[{ name: 'React', url: 'https://react.dev', licence: 'MIT' }]}
        />
      </NexuiLanguage>,
    )
    expect(root.querySelector('[data-card="about-updates"]')).toBeNull()
    expect(root.textContent).not.toContain('1.2.0')
    expect(root.querySelector('[data-card="about"]')?.textContent).toContain('1.1.0')
    expect(root.querySelector('[data-card="about-built-with"]')).not.toBeNull()
  })

  it('the banner after an update says the version, shows the text and puts itself away (since 1.2.0)', () => {
    const showing = vi.fn()
    const away = vi.fn()
    const root = show(
      <NexuiLanguage language="de">
        <WhatsNewBanner app="nexlore" version="1.17.0" onShow={showing} onPutAway={away} />
      </NexuiLanguage>,
    )
    const banner = getByRole(root, 'status')
    expect(banner.dataset.testid).toBe('whats-new-banner')
    expect(banner.textContent).toContain('nexlore 1.17.0 ist da.')
    const open = getByRole(banner, 'button', { name: 'Was ist neu?' })
    expect([open.dataset.kind, open.dataset.size, open.dataset.icon]).toEqual(['primary', 'sm', 'Sparkles'])
    fireEvent.click(open)
    expect(showing).toHaveBeenCalledTimes(1)
    const put = getByRole(banner, 'button', { name: 'Ausblenden' })
    expect(put.getAttribute('title')).toBe('Ausblenden')
    fireEvent.click(put)
    expect(away).toHaveBeenCalledTimes(1)
  })

  it('the window shows several versions under their numbers, marks sections for operators and offers the earlier ones (since 1.2.0)', () => {
    const earlier = vi.fn()
    const closed = vi.fn()
    const entry = (title: string, operator = false) => ({ lead: `Lead ${title}`, sections: [{ title, where: 'Einstellungen', body: `Body ${title}`, operator }], smallTitle: '', small: [] })
    show(
      <NexuiLanguage language="de">
        <WhatsNewDialog
          app="nexlore"
          version="1.17.0"
          entries={[
            { version: '1.17.0', entry: entry('Neu') },
            { version: '1.16.0', entry: entry('Betrieb', true) },
          ]}
          onClose={closed}
          onEarlier={earlier}
        />
      </NexuiLanguage>,
    )
    const dialog = getByRole(document.body, 'dialog', { name: 'Neu in nexlore seit deinem letzten Besuch' })
    const parts = Array.from(dialog.querySelectorAll<HTMLElement>('section[data-version]'))
    expect(parts.map((part) => part.dataset.version)).toEqual(['1.17.0', '1.16.0'])
    expect(getByRole(parts[0] as HTMLElement, 'heading', { level: 3, name: 'Version 1.17.0' })).toBeTruthy()
    expect(parts[1]?.querySelector('[data-operator="true"]')?.textContent).toContain('Für Betreiber')
    expect(parts[0]?.querySelector('[data-operator]')).toBeNull()
    expect(dialog.textContent).not.toContain('Außerdem')
    const more = getByRole(dialog, 'button', { name: 'Frühere Versionen' })
    expect([more.dataset.kind, more.dataset.icon]).toEqual(['secondary', 'History'])
    fireEvent.click(more)
    expect(earlier).toHaveBeenCalledTimes(1)
    fireEvent.click(getByRole(dialog, 'button', { name: 'Verstanden' }))
    expect(closed).toHaveBeenCalledTimes(1)
  })

  it('the window of one version keeps its title; the history is titled as such (since 1.2.0)', () => {
    const entry = { lead: 'L', sections: [{ title: 'T', where: 'W', body: 'B' }], smallTitle: 'Außerdem', small: ['x'] }
    show(
      <NexuiLanguage language="en">
        <WhatsNewDialog app="nexlore" version="1.17.1" entries={[{ version: '1.17.0', entry }]} onClose={() => undefined} />
      </NexuiLanguage>,
    )
    expect(getByRole(document.body, 'dialog', { name: 'New in nexlore 1.17.0' }).textContent).toContain('Außerdem')
    expect(queryByRole(document.body, 'button', { name: 'Earlier versions' })).toBeNull()
    shown?.unmount()
    show(
      <NexuiLanguage language="en">
        <WhatsNewDialog app="nexlore" version="1.17.1" title="all" entries={[{ version: '1.17.0', entry }, { version: '1.16.0', entry }]} onClose={() => undefined} />
      </NexuiLanguage>,
    )
    expect(getByRole(document.body, 'dialog', { name: "What's new in nexlore" })).toBeTruthy()
  })

  it('the about page names the version of the text and opens the caller\'s window when given one (since 1.2.0)', () => {
    const opened = vi.fn()
    const root = show(
      <NexuiLanguage language="de">
        <AboutPage
          app="nexlore"
          logo="/logo.svg"
          tagline="Wissen."
          version="1.17.1"
          licence={{ name: 'AGPL-3.0', href: 'https://www.gnu.org/licenses/agpl-3.0.html' }}
          source="https://github.com/example/nexlore"
          whatsNewVersion="1.17.0"
          onWhatsNew={opened}
          showUpdates={false}
          builtWith={[]}
        />
      </NexuiLanguage>,
    )
    fireEvent.click(getByRole(root, 'button', { name: 'Neu in nexlore 1.17.0' }))
    expect(opened).toHaveBeenCalledTimes(1)
    expect(queryByRole(document.body, 'dialog')).toBeNull()
  })

  it("the ways of notifications show only the ways an app has, with the plan's buttons", () => {
    const removed = vi.fn()
    const root = show(
      <NexuiLanguage language="de">
        <NotifyWays
          mail={{ address: 'kim@example.com', confirmed: true, onChange: () => undefined }}
          browser={{ on: true, onTurnOn: () => undefined, onTurnOff: () => undefined, onProbe: () => undefined }}
          browsers={{ items: [{ id: 'a', name: 'Firefox unter Linux', current: true }], onRemove: removed }}
        />
      </NexuiLanguage>,
    )
    const card = root.querySelector<HTMLElement>('[data-card="notify-ways"]') as HTMLElement
    expect(getByRole(card, 'heading', { level: 2, name: 'Auf welchem Weg' })).toBeTruthy()
    expect(getAllByRole(card, 'heading', { level: 3 }).map((heading) => heading.textContent)).toEqual(['Mail', 'Dieser Browser', 'Browser mit Mitteilungen'])
    const said = (name: string) => {
      const button = getByRole(card, 'button', { name })
      return [button.dataset.kind, button.dataset.size, button.dataset.icon]
    }
    expect(said('Im Profil ändern')).toEqual(['secondary', 'sm', 'UserPen'])
    expect(said('Ausschalten')).toEqual(['danger', 'md', 'BellOff'])
    expect(said('Probemeldung schicken')).toEqual(['secondary', 'md', 'Send'])
    // The button says "Entfernen" and is named after its browser (since E33), so that a screen reader tells them apart.
    expect(said('Firefox unter Linux entfernen')).toEqual(['danger', 'sm', 'Trash2'])
    expect(getByRole(card, 'button', { name: 'Firefox unter Linux entfernen' }).textContent).toBe('Entfernen')
    fireEvent.click(getByRole(card, 'button', { name: 'Firefox unter Linux entfernen' }))
    expect(removed).toHaveBeenCalledWith('a')
    expect(queryByRole(card, 'heading', { name: 'iPhone und iPad' })).toBeNull()
  })

  it.each([
    ['de', 'Firefox unter Linux entfernen', 'Entfernen'],
    ['en', 'Remove Firefox unter Linux', 'Remove'],
    ['fr', 'Retirer Firefox unter Linux', 'Retirer'],
  ] as const)('names the button "Remove" of each browser after the browser (%s)', (language, name, words) => {
    const root = show(
      <NexuiLanguage language={language}>
        <NotifyWays browsers={{ items: [{ id: 'a', name: 'Firefox unter Linux' }, { id: 'b', name: 'Safari' }], onRemove: () => undefined }} />
      </NexuiLanguage>,
    )
    const button = getByRole(root, 'button', { name })
    expect([button.textContent, button.getAttribute('aria-label')]).toEqual([words, name])
    expect(getAllByRole(root, 'button').map((entry) => entry.getAttribute('aria-label'))).toHaveLength(2)
  })

  it('every button of the kit has a symbol and words, a size and one of the three kinds (the symbol-only ones excepted)', () => {
    const root = show(
      <NexuiLanguage language="en">
        <NotifyWays
          mail={{ address: 'kim@example.com', confirmed: false, onChange: () => undefined }}
          browser={{ on: false, onTurnOn: () => undefined, onTurnOff: () => undefined }}
          devices={{ onOpen: () => undefined }}
        />
        <CopyRow label="Key" value="ntk_x" />
      </NexuiLanguage>,
    )
    const buttons = Array.from(root.querySelectorAll<HTMLElement>('button, a[data-kind]'))
    expect(buttons.length).toBeGreaterThan(2)
    for (const button of buttons) {
      expect(['md', 'sm'], button.outerHTML).toContain(button.dataset.size)
      expect(['primary', 'secondary', 'danger']).toContain(button.dataset.kind)
      expect(button.firstElementChild?.tagName.toLowerCase()).toBe('svg')
      expect(button.textContent?.trim()).not.toBe('')
    }
  })
})
