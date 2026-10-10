/**
 * The dialog that asks "really?" before everything that deletes or locks out: the focus starts on "Abbrechen", Escape and
 * "Abbrechen" send nothing, the red button sends the request once (a second click while it is on its way does nothing), a
 * refusal of the server is told inside the dialog, and over another dialog Escape closes only the one on top.
 */
import { act } from 'react'

import { ApiError } from '../api/client'
import { changeLanguage } from '../i18n'
import { Page } from '../test/harness'
import { idle } from '../test/wait'
import { Dialog } from './Dialog'
import { useConfirm, type ConfirmOptions } from './useConfirm'

const page = new Page()

function Asker({ options, outer = false }: { options: ConfirmOptions; outer?: boolean }) {
  const { ask, dialog } = useConfirm()
  const body = (
    <>
      <button type="button" onClick={() => ask(options)}>
        Löschen
      </button>
      {dialog}
    </>
  )
  return outer ? <Dialog title="Außen" onClose={() => document.body.setAttribute('data-outer-closed', 'yes')}>{body}</Dialog> : body
}

beforeEach(async () => {
  await changeLanguage('de', false)
  document.body.removeAttribute('data-outer-closed')
})
afterEach(() => page.close())

const options = (run: ConfirmOptions['run'], extra: Partial<ConfirmOptions> = {}): ConfirmOptions => ({ title: 'Wirklich?', text: 'Das lässt sich nicht zurückholen.', confirm: 'Endgültig löschen', run, ...extra })

async function escape() {
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  await idle()
}

describe('the dialog that asks first', () => {
  it('sends nothing before the red button, starts on Abbrechen and says what happens', async () => {
    const run = vi.fn(async () => undefined)
    await page.show(<Asker options={options(run)} />)
    await page.click(page.button('Löschen'))
    expect(run).not.toHaveBeenCalled()
    expect(page.dialog).toBeTruthy()
    expect(page.dialog!.textContent).toContain('Das lässt sich nicht zurückholen.')
    expect(document.activeElement).toBe(page.button('Abbrechen', page.dialog!))
    // Red where it cannot be taken back.
    expect(page.button('Endgültig löschen', page.dialog!)!.className).toContain('bg-bad')
    await page.inDialog('Endgültig löschen')
    expect(run).toHaveBeenCalledTimes(1)
    expect(page.dialog).toBeNull()
  })

  it('is not red where it can be taken back', async () => {
    await page.show(<Asker options={options(async () => undefined, { danger: false })} />)
    await page.click(page.button('Löschen'))
    expect(page.button('Endgültig löschen', page.dialog!)!.className).not.toContain('bg-bad')
  })

  it('sends nothing on Abbrechen, on Escape or on the close button', async () => {
    const run = vi.fn(async () => undefined)
    await page.show(<Asker options={options(run)} />)
    await page.click(page.button('Löschen'))
    await page.inDialog('Abbrechen')
    expect(page.dialog).toBeNull()
    await page.click(page.button('Löschen'))
    await escape()
    expect(page.dialog).toBeNull()
    await page.click(page.button('Löschen'))
    await page.inDialog('Schließen')
    expect(page.dialog).toBeNull()
    expect(run).not.toHaveBeenCalled()
  })

  it('sends the request once, however often the button is pressed while it is on its way', async () => {
    let finish: () => void = () => undefined
    const run = vi.fn(() => new Promise<void>((resolve) => (finish = resolve)))
    await page.show(<Asker options={options(run)} />)
    await page.click(page.button('Löschen'))
    const red = page.button('Endgültig löschen', page.dialog!)!
    await act(async () => {
      red.click()
      red.click()
      red.click()
    })
    await page.click(page.button('…', page.dialog!))
    expect(run).toHaveBeenCalledTimes(1)
    await act(async () => finish())
    await idle()
    expect(page.dialog).toBeNull()
  })

  it('tells a refusal inside the dialog, which stays open, and asks again once the person presses it anew', async () => {
    const run = vi.fn()
    run.mockRejectedValueOnce(new ApiError(409, 'not_in_trash')).mockResolvedValueOnce(undefined)
    await page.show(<Asker options={options(run)} />)
    await page.click(page.button('Löschen'))
    await page.inDialog('Endgültig löschen')
    expect(page.dialog!.textContent).toContain('Das Dokument liegt nicht mehr im Papierkorb.')
    expect(run).toHaveBeenCalledTimes(1)
    await page.inDialog('Endgültig löschen')
    expect(run).toHaveBeenCalledTimes(2)
    expect(page.dialog).toBeNull()
  })

  it('asks for the password again where the server wants it, and hands it on', async () => {
    const run = vi.fn(async (_password: string) => undefined)
    await page.show(<Asker options={options(run, { password: true })} />)
    await page.click(page.button('Löschen'))
    await page.type(page.dialog!.querySelector<HTMLInputElement>('input[type="password"]'), 'geheimwort')
    await page.inDialog('Endgültig löschen')
    expect(run).toHaveBeenCalledWith('geheimwort')
  })

  it('lets a request ask the next question itself and keeps the dialog for it', async () => {
    const second = vi.fn(async () => undefined)
    function Twice() {
      const { ask, dialog } = useConfirm()
      const again = () => ask(options(second, { title: 'Noch einmal?', confirm: 'Trotzdem löschen' }))
      return (
        <>
          <button type="button" onClick={() => ask(options(async () => again()))}>
            Löschen
          </button>
          {dialog}
        </>
      )
    }
    await page.show(<Twice />)
    await page.click(page.button('Löschen'))
    await page.inDialog('Endgültig löschen')
    expect(page.dialog!.textContent).toContain('Noch einmal?')
    expect(second).not.toHaveBeenCalled()
    await page.inDialog('Trotzdem löschen')
    expect(second).toHaveBeenCalledTimes(1)
    expect(page.dialog).toBeNull()
  })

  it('answers to Escape on top only, not in the dialog below', async () => {
    await page.show(<Asker options={options(async () => undefined)} outer />)
    await page.click(page.button('Löschen'))
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(2)
    await escape()
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1)
    expect(document.body.getAttribute('data-outer-closed')).toBeNull()
    await escape()
    expect(document.body.getAttribute('data-outer-closed')).toBe('yes')
  })
})
