// @vitest-environment jsdom
/**
 * The kit's own test, run in every app's vitest (it comes with the kit, unchanged): the three kinds of buttons, each
 * with its symbol and the same size, and that every part is reachable as a reader and a test finds it (names, hints,
 * states, dialogs). Needs react-dom and @testing-library/dom, both in every app.
 */
import { fireEvent, getAllByRole, getByLabelText, getByRole, getByText, queryByRole } from '@testing-library/dom'
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { Avatar, Badge, Box, Button, ButtonGroup, Card, Checkbox, CheckboxRow, ConfirmDialog, Facts, Field, Row, Rows, SelectField, ICONS } from './index'

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
