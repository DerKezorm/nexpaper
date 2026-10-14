/**
 * "Darf weg": the documents whose keeping time is over, picked and put in the trash only after the question. Nothing
 * goes by itself, and nothing is sent before "In den Papierkorb" in the dialog.
 */
import type { DocumentInfo, Vault } from '../api/client'
import { changeLanguage } from '../i18n'
import { useMayGo } from '../lib/mayGo'
import { Page, Server, plain } from '../test/harness'
import { until } from '../test/wait'
import { MayGo, MayGoChip } from './MayGo'

const server = new Server()
const page = new Page()

const vaults = [
  { id: 7, name: 'Jule', icon: 'user', personal_of: 1, my_right: 'manage', documents: 3, size: 1, members: [] },
  { id: 9, name: 'Haushalt', icon: 'home', personal_of: null, my_right: 'edit', documents: 9, size: 1, members: [] },
] as Vault[]

const doc = (id: number, title: string, vault_id: number, keep: { date: string; manual: boolean }, date: string | null, kind: string | null = null) =>
  ({
    id, vault_id, title, date, added_at: '2026-10-02T10:00:00Z', status: 'filed', sender: { id: id + 100, name: `Absender ${id}` },
    kind: kind ? { id: id + 200, key: '', name: kind, hue: 30, position: 0 } : null, dates: [{ kind: 'keep_until', ...keep }],
  }) as unknown as DocumentInfo

const ITEMS = [
  doc(1, 'Gehaltsabrechnungen 2013', 7, { date: '2023-12-31', manual: true }, '2013-12-31'),
  doc(2, 'Rechnung Dachrinne', 9, { date: '2024-12-31', manual: false }, '2022-05-10', 'Rechnung'),
  ...Array.from({ length: 8 }, (_, i) => doc(10 + i, `Kontoauszug ${i + 1}`, 9, { date: '2025-12-31', manual: true }, null)),
]

function Section({ onChanged = () => undefined }: { onChanged?: () => void }) {
  const found = useMayGo()
  return (
    <>
      <MayGoChip count={found.total} active={false} onClick={() => undefined} />
      <MayGo items={found.items} total={found.total} vaults={vaults} mineId={1} onChanged={() => { onChanged(); found.reload() }} />
    </>
  )
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = {
    'GET /api/v1/keeping?limit=500': { items: ITEMS, total: ITEMS.length },
    'POST /api/v1/documents/trash': { trashed: [1, 2], failed: [] },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

const rows = () => [...page.box.querySelectorAll('section ul > li')].map((li) => plain(li.textContent))

describe('may go', () => {
  it('lists what may go with until when and why, the first eight and then all', async () => {
    await page.show(<Section />)
    await until(() => rows().length > 0)
    expect(page.button('Darf weg 10')).toBeTruthy()
    expect(plain(page.box.querySelector('section h2')!.textContent)).toBe('Darf weg 10')
    expect(rows()).toHaveLength(9)
    expect(rows()[0]).toContain('Gehaltsabrechnungen 2013')
    expect(rows()[0]).toContain('Mein Tresor')
    expect(rows()[0]).toContain('bis 31.12.2023von Hand gesetzt')
    expect(rows()[1]).toContain('Haushalt')
    expect(rows()[1]).toContain('bis 31.12.2024aus der Art, 2 Jahre')
    expect(rows()[8]).toBe('Alle 10 zeigen')
    await page.click(page.button('Alle 10 zeigen'))
    expect(rows()).toHaveLength(10)
  })

  it('puts the picked ones in the trash only after the question', async () => {
    const changed = vi.fn()
    await page.show(<Section onChanged={changed} />)
    await until(() => rows().length > 0)
    expect(page.button('In den Papierkorb')!.disabled).toBe(true)
    await page.check(page.box.querySelector<HTMLInputElement>('input[aria-label="Gehaltsabrechnungen 2013 auswählen"]'))
    await page.check(page.box.querySelector<HTMLInputElement>('input[aria-label="Rechnung Dachrinne auswählen"]'))
    await page.click(page.button('In den Papierkorb (2)'))
    expect(plain(page.dialog!.textContent)).toContain('2 Dokumente in den Papierkorb?')
    expect(plain(page.dialog!.textContent)).toContain('Sie liegen dann 30 Tage im Papierkorb und lassen sich bis dahin zurückholen.')
    await page.inDialog('Abbrechen')
    expect(server.changes()).toEqual([])
    await page.click(page.button('In den Papierkorb (2)'))
    await page.inDialog('In den Papierkorb')
    expect(server.changes()).toEqual(['POST /api/v1/documents/trash'])
    expect(server.called('POST', '/api/v1/documents/trash')!.body).toEqual({ ids: [1, 2] })
    expect(changed).toHaveBeenCalledTimes(1)
  })

  it('picks all at once', async () => {
    await page.show(<Section />)
    await until(() => rows().length > 0)
    const all = [...page.box.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')][0]
    await page.check(all)
    expect(page.button('In den Papierkorb (10)')).toBeTruthy()
    await page.check(all)
    expect(page.button('In den Papierkorb')).toBeTruthy()
  })

  it('says so when nothing may go, and has no chip then', async () => {
    server.answers['GET /api/v1/keeping?limit=500'] = { items: [], total: 0 }
    await page.show(<Section />)
    await until(() => page.text.includes('Nichts, dessen Aufbewahrungszeit um ist.'))
    expect(page.button('Darf weg 0')).toBeUndefined()
  })
})
