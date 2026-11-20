/**
 * "Regeln erneut anwenden" against a stand-in of the server (issue #11): the look goes on in steps until the server says
 * all were looked at, changes nothing, shows each field before and after with where the new value comes from and the
 * moves first; only the ticked documents are sorted again, in calls of at most a hundred.
 */
import { act } from 'react'

import { changeLanguage } from '../i18n'
import { Page, Server, plain } from '../test/harness'
import { idle, until } from '../test/wait'
import { SortAgainDialog } from './SortAgain'

const say = vi.fn()
vi.mock('../lib/say', async (original) => ({ ...(await original<typeof import('../lib/say')>()), useSay: () => say }))

const server = new Server()
const page = new Page()
const onClose = vi.fn()
const LOOK = '/api/v1/inbox/sort-again/preview'
const APPLY = '/api/v1/inbox/sort-again'

const vaults = [
  { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 1, size: 1, members: [] },
  { id: 9, name: 'Chrysler 300', icon: 'car', personal_of: null, my_right: 'edit', documents: 1, size: 1, members: [] },
]
function doc(id: number, title: string, extra: Record<string, unknown> = {}) {
  return {
    id, vault_id: 7, owner: null, title, sender: { id: 5, name: 'Autohaus Brandt' }, kind: null, date: '2026-10-06', amount: null, currency: 'EUR',
    tags: [], dates: [], pages: 1, source: 'upload', status: 'inbox', added_at: '2026-10-08T07:42:00Z', trashed_at: null, trash_ends_at: null,
    change_seq: id, current_version: 1, my_right: 'manage', via_share: false, can_share: true, notes: 0, process_error: '', duplicate: null, ...extra,
  }
}
const tagged = (id: number, title: string) => ({ fields: ['tags'], origins: { tags: 'rule' }, before: doc(id, title), after: doc(id, title, { tags: ['auto'] }) })
const moved = (id: number, title: string) => ({ fields: ['tags', 'vault'], origins: { tags: 'rule', vault: 'rule' }, before: doc(id, title), after: doc(id, title, { vault_id: 9, tags: ['auto'] }) })

const respond = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })

/** Answers of the look by where they go on (`after`); every call is noted like the stand-in's own. */
function steps(answers: Record<number, unknown>) {
  const own = globalThis.fetch
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    if (url !== LOOK) return own(url, init)
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    server.calls.push({ method: init?.method ?? 'GET', url, body })
    return respond(answers[body.after ?? 0])
  })
}
const open = (ids?: number[]) => page.show(<SortAgainDialog ids={ids} vaults={vaults as never} mineId={1} onClose={onClose} />)
const looks = () => server.calls.filter((c) => c.url === LOOK)
const dialogText = () => plain(page.dialog!.textContent)
const box = (title: string) => page.dialog!.querySelector<HTMLInputElement>(`input[aria-label="„${title}“ übernehmen"]`)

beforeEach(async () => {
  await changeLanguage('de', false)
  say.mockClear()
  onClose.mockClear()
  server.answers = { [`POST ${APPLY}`]: { changed: [2], moved: 1, unchanged: 0, skipped: 0, failed: 0 } }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('sorting the inbox again', () => {
  it('looks in steps until all were looked at, and changes nothing while it looks', async () => {
    steps({
      0: { items: [tagged(1, 'Inspektion')], looked_at: 100, total: 230, next: 120 },
      120: { items: [moved(2, 'Reifenwechsel')], looked_at: 100, total: 230, next: 260 },
      260: { items: [], looked_at: 30, total: 230, next: null },
    })
    await open()
    await until(() => page.dialog?.querySelector('[data-testid="sort-again-summary"]'))
    expect(looks().map((c) => c.body)).toEqual([{}, { after: 120 }, { after: 260 }])
    expect(server.changes()).toEqual([`POST ${LOOK}`, `POST ${LOOK}`, `POST ${LOOK}`])
    const text = dialogText()
    expect(text).toContain('2 Dokumente ändern sich.')
    expect(text).toContain('1 davon kommt in einen anderen Tresor.')
    expect(text).toContain('Was du selbst eingetragen hast, bleibt. Noch ändert sich nichts.')
  })

  it('shows how far it got while it looks, and offers nothing to take over before the end', async () => {
    let release: (value: unknown) => void = () => undefined
    const held = new Promise((resolve) => (release = resolve))
    steps({ 0: { items: [moved(2, 'Reifenwechsel')], looked_at: 100, total: 230, next: 120 } })
    const counted = globalThis.fetch
    // The second step is held back, and not counted as open: the page is looked at while it waits.
    globalThis.fetch = (async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : {}
      if (url !== LOOK || body.after !== 120) return counted(url, init)
      server.calls.push({ method: 'POST', url, body })
      return held.then(respond)
    }) as typeof fetch
    try {
      await open()
      expect(looks()).toHaveLength(2)
      expect(dialogText()).toContain('Geprüft: 100 von 230')
      expect(page.dialog!.querySelector('[data-testid="sort-again-summary"]')).toBeNull()
      expect(page.button('1 Dokument übernehmen', page.dialog!)).toBeUndefined()
      expect(page.button('Abbrechen', page.dialog!)).toBeTruthy()
      await act(async () => {
        release({ items: [], looked_at: 130, total: 230, next: null })
        await held
      })
      await idle()
      expect(page.dialog!.querySelector('[data-testid="sort-again-summary"]')).toBeTruthy()
      expect(page.button('1 Dokument übernehmen', page.dialog!)).toBeTruthy()
    } finally {
      globalThis.fetch = counted
    }
  })

  it('shows each field before and after with where it comes from, the moves first, all ticked', async () => {
    steps({ 0: { items: [tagged(1, 'Inspektion'), moved(2, 'Reifenwechsel')], looked_at: 2, total: 2, next: null } })
    await open()
    await until(() => page.dialog?.querySelector('[data-testid="sort-again-summary"]'))
    const rows = [...page.dialog!.querySelectorAll('li')]
    expect(rows.map((li) => plain(li.querySelector('.font-semibold')!.textContent))).toEqual(['Reifenwechsel', 'Inspektion'])
    const vault = plain(rows[0].querySelector('[data-field="vault"]')!.textContent)
    expect(vault).toBe('Tresor:Mein TresorChrysler 300Regel')
    expect(plain(rows[1].querySelector('[data-field="tags"]')!.textContent)).toBe('Tags:leerautoRegel')
    expect(box('Inspektion')!.checked && box('Reifenwechsel')!.checked).toBe(true)
    expect(page.button('2 Dokumente übernehmen', page.dialog!)).toBeTruthy()
  })

  it('sorts again only the ticked ones and says what became of them', async () => {
    steps({ 0: { items: [tagged(1, 'Inspektion'), moved(2, 'Reifenwechsel')], looked_at: 2, total: 2, next: null } })
    await open()
    await until(() => page.dialog?.querySelector('[data-testid="sort-again-summary"]'))
    await page.click(box('Inspektion'))
    await page.inDialog('1 Dokument übernehmen')
    expect(server.called('POST', APPLY)!.body).toEqual({ ids: [2] })
    expect(say).toHaveBeenCalledWith('1 Dokument neu einsortiert. 1 davon liegt jetzt in einem anderen Tresor.')
    expect(onClose).toHaveBeenCalled()
  })

  it('sends a hundred at a time', async () => {
    const many = Array.from({ length: 150 }, (_, n) => tagged(n + 1, `Brief ${String(n + 1).padStart(3, '0')}`))
    steps({ 0: { items: many, looked_at: 150, total: 150, next: null } })
    server.answers[`POST ${APPLY}`] = { changed: [], moved: 0, unchanged: 0, skipped: 0, failed: 0 }
    await open()
    await until(() => page.dialog?.querySelector('[data-testid="sort-again-summary"]'))
    await page.inDialog('150 Dokumente übernehmen')
    const sent = server.calls.filter((c) => c.url === APPLY).map((c) => (c.body as { ids: number[] }).ids.length)
    expect(sent).toEqual([100, 50])
    expect(say).toHaveBeenCalledWith('Nichts geändert. Die Dokumente waren schon so einsortiert.')
  })

  it('names the documents selected, and says when nothing would change', async () => {
    steps({ 0: { items: [], looked_at: 2, total: 2, next: null } })
    await open([4, 5])
    await until(() => page.dialog?.querySelector('[data-testid="sort-again-nothing"]'))
    expect(looks()[0].body).toEqual({ ids: [4, 5] })
    expect(dialogText()).toContain('die 2 ausgewählten Dokumente')
    expect(dialogText()).toContain('Keine Änderungen.')
    expect(page.dialog!.querySelectorAll('input[type="checkbox"]')).toHaveLength(0)
    await page.inDialog('Abbrechen')
    expect(server.calls.some((c) => c.url === APPLY)).toBe(false)
    expect(onClose).toHaveBeenCalled()
  })

  it('says a move to a vault the person does not see, without the document afterwards', async () => {
    steps({ 0: { items: [{ fields: ['vault'], origins: { vault: 'rule' }, before: doc(3, 'Lieferschein'), after: null }], looked_at: 1, total: 1, next: null } })
    await open()
    await until(() => page.dialog?.querySelector('[data-testid="sort-again-summary"]'))
    expect(dialogText()).toMatch(/Tresor: Mein Tresor\s+kommt in einen Tresor, den du nicht siehst/)
  })

  it('says what the server refused and changes nothing', async () => {
    server.fails[`POST ${LOOK}`] = { status: 429, code: 'too_fast' }
    await open()
    await until(() => page.dialog?.querySelector('[role="alert"]'))
    expect(server.calls.some((c) => c.url === APPLY)).toBe(false)
  })
})
