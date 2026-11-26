// @vitest-environment jsdom
/**
 * The page's own test, run in every app's vitest (it comes with the module, unchanged): the cards "Speicher" and
 * "Sicherung" as the plan draws them (data-card, Segment, Field with its button, `sm` buttons with symbols in every row,
 * Löschen danger, the result of a check as a box), the password asked before download, restore, delete and upload, the
 * trial run before a restore, a locked archive asked for its own password, and the calls to the module's routes.
 * Needs react-dom and @testing-library/dom, both in every app.
 */
import { fireEvent, getByLabelText, getByRole, getByText, queryByRole, waitFor } from '@testing-library/dom'
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { NexuiLanguage } from '../nexui'
import { SICHERUNG_TEXTS, StorageArea, blockedWords, makeSicherungApi, passwordHeader, shares, bytes, type Backups, type Brief, type Entry, type Overview, type SicherungApi } from './index'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let shown: { root: HTMLElement; unmount: () => void } | null = null

async function show(element: ReactNode, language = 'de'): Promise<HTMLElement> {
  const root = document.createElement('div')
  document.body.append(root)
  const react = createRoot(root)
  await act(async () => react.render(<NexuiLanguage language={language}>{element}</NexuiLanguage>))
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

const OVERVIEW: Overview = {
  app: 'nexnotes',
  used: 3 * 1024 * 1024,
  parts: [
    { key: 'database', bytes: 1024 * 1024, within: '', complete: true },
    { key: 'attachments', bytes: 2 * 1024 * 1024, within: '', complete: true },
  ],
  complete: true,
  total: 100 * 1024 ** 3,
  disk_used: 95 * 1024 ** 3,
  free: 5 * 1024 ** 3,
  nearly_full: true,
  where: { data: { kind: 'network', fstype: 'nfs4' } },
  network: ['data'],
}

function entry(name: string, more: Partial<Entry> = {}): Entry {
  return { name, size: 2048, created: '2026-11-25T03:00:00+00:00', kind: 'scheduled', note: '', version: '1.4.0', uploaded: false, locked: false, readable: true, facts: { notes: 12, files: 3 }, ...more }
}

const BACKUPS: Backups = {
  schedule: { every: 'daily', time: '03:00', keep: 7 },
  zone: 'Europe/Berlin',
  last: { created: '2026-11-25T03:00:00+00:00', size: 2048, kind: 'scheduled' },
  count: 2,
  kept: 1,
  failure: null,
  running: false,
  restore_failure: null,
  restored: null,
  restore: 'restart',
  download_password: false,
  backups: [entry('nexnotes-2026-11-25-030000.zip'), entry('nexnotes-2026-11-24-120000-upload.zip', { uploaded: true, locked: true, kind: 'manual' })],
}

function brief(usable = true): Brief {
  return { name: 'nexnotes-2026-11-25-030000.zip', created: '2026-11-25T03:00:00+00:00', kind: 'scheduled', note: '', version: '1.4.0', uploaded: false, database_ok: usable, files_ok: true, damaged: usable ? [] : ['database'], too_new: false, blocked: '', blocked_text: '', usable, facts: {}, details: { would_add: 1, would_change: 0, would_remove: 2 } }
}

function fakeApi(): SicherungApi & { calls: string[] } {
  const calls: string[] = []
  const note = (call: string) => calls.push(call)
  return {
    calls,
    overview: vi.fn(async () => OVERVIEW),
    backups: vi.fn(async () => BACKUPS),
    saveSchedule: vi.fn(async (schedule) => (note(`schedule ${schedule.every} ${schedule.time} ${schedule.keep}`), schedule)),
    make: vi.fn(async (text) => (note(`make ${text ?? '-'}`), { name: 'x' })),
    upload: vi.fn(async (_file, password) => (note(`upload ${password}`), { name: 'y' })),
    check: vi.fn(async (name, archivePassword) => (note(`check ${name} ${archivePassword ?? '-'}`), brief())),
    download: vi.fn(async (name, password, archivePassword) => (note(`download ${name} ${password} ${archivePassword ?? '-'}`), new Blob(['zip']))),
    restore: vi.fn(async (name, password, archivePassword) => (note(`restore ${name} ${password} ${archivePassword ?? '-'}`), { ...brief(), result: {}, restarting: true })),
    remove: vi.fn(async (name, password) => void note(`remove ${name} ${password}`)),
    dismissFailed: vi.fn(async () => void note('dismiss')),
  }
}

async function area(api: SicherungApi, password = true, language = 'de'): Promise<HTMLElement> {
  const root = await show(
    <StorageArea
      app="nexnotes"
      things="Notizen"
      holds="Eine Sicherung enthält alle Notizen."
      api={api}
      password={password}
      language={language === 'fr' ? 'fr' : 'de'}
      facts={(item) => `${String(item.facts.notes)} Notizen`}
      details={(found) => <p data-testid="details">{String(found.details.would_remove)} fallen weg</p>}
      onRestarting={() => undefined}
    >
      <section data-card="app-own">eigene Karte</section>
    </StorageArea>,
    language,
  )
  await waitFor(() => expect(root.querySelector('[data-testid="backup-list"]')).not.toBeNull())
  return root
}

describe('the area "Speicher und Sicherung"', () => {
  it('shows the cards in their order, the app\'s own after them', async () => {
    const root = await area(fakeApi())
    const cards = Array.from(root.querySelectorAll('[data-card]')).map((card) => card.getAttribute('data-card'))
    expect(cards).toEqual(['storage', 'backups', 'app-own'])
    expect(getByRole(root, 'heading', { name: 'Speicher' })).not.toBeNull()
    expect(getByRole(root, 'heading', { name: 'Sicherung' })).not.toBeNull()
    expect(getByText(root, 'Eine Sicherung enthält alle Notizen.')).not.toBeNull()
  })

  it('names what the app takes, the free space and a network share', async () => {
    const root = await area(fakeApi())
    expect(getByText(root, 'nexnotes belegt')).not.toBeNull()
    expect(root.querySelector('[data-testid="storage-parts"]')?.textContent).toBe('Datenbank 1,0 MB · Anhänge 2,0 MB')
    expect(root.querySelector('[data-testid="storage-free"]')?.textContent).toBe('5,0 GB frei von 100 GB')
    expect(root.querySelector('[data-testid="storage-network"]')?.textContent).toContain('Das kann Notizen beschädigen')
    expect(root.querySelector('[data-nearly-full]')).not.toBeNull()
  })

  it('chooses the schedule in a segment and saves time and number with the field\'s own button', async () => {
    const api = fakeApi()
    const root = await area(api)
    const group = getByRole(root, 'radiogroup', { name: 'Automatisch' })
    const choices = Array.from(group.querySelectorAll('[role="radio"]')).map((item) => item.textContent)
    expect(choices).toEqual(['Aus', 'Jede Nacht', 'Jede Woche', 'Jeden Monat'])
    await act(async () => fireEvent.click(getByRole(group, 'radio', { name: 'Jede Woche' })))
    expect(api.calls).toContain('schedule weekly 03:00 7')
    await act(async () => fireEvent.click(getByRole(group, 'radio', { name: 'Jeden Monat' })))
    expect(api.calls).toContain('schedule monthly 03:00 7')
    const keep = getByLabelText(root, 'Behalten (Stück)') as HTMLInputElement
    const row = keep.closest('[data-part="field-action"]') as HTMLElement
    const save = getByRole(row, 'button', { name: 'Speichern' })
    expect(save.dataset.icon).toBe('Check')
    fireEvent.change(getByLabelText(root, 'Uhrzeit'), { target: { value: '04:30' } })
    fireEvent.change(keep, { target: { value: '3' } })
    await act(async () => fireEvent.click(save))
    expect(api.calls).toContain('schedule daily 04:30 3')
  })

  it('has "Jetzt sichern" primary and "Sicherung hochladen" secondary, and small buttons with symbols in every row', async () => {
    const api = fakeApi()
    const root = await area(api)
    const now = root.querySelector('[data-testid="backup-now"]') as HTMLElement
    expect([now.dataset.kind, now.dataset.icon, now.dataset.size]).toEqual(['primary', 'Archive', 'md'])
    const upload = root.querySelector('[data-testid="backup-upload"]') as HTMLElement
    expect([upload.dataset.kind, upload.dataset.icon]).toEqual(['secondary', 'Upload'])
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    const buttons = Array.from(row.querySelectorAll('button'))
    expect(buttons.map((button) => [button.textContent, button.dataset.icon, button.dataset.kind, button.dataset.size])).toEqual([
      ['Prüfen', 'ShieldCheck', 'secondary', 'sm'],
      ['Herunterladen', 'Download', 'secondary', 'sm'],
      ['Wiederherstellen', 'RotateCcw', 'secondary', 'sm'],
      ['Löschen', 'Trash2', 'danger', 'sm'],
    ])
    expect(row.textContent).toContain('12 Notizen')
    await act(async () => fireEvent.click(now))
    await act(async () => fireEvent.click(getByRole(getByRole(document.body, 'dialog', { name: 'Jetzt sichern' }), 'button', { name: 'Sichern' })))
    expect(api.calls).toContain('make ')
  })

  it('writes every time of the card through the app\'s when (since E34), and as before without it', async () => {
    const api = fakeApi()
    api.backups = vi.fn(async () => ({
      ...BACKUPS,
      failure: { at: '2026-11-25T04:00:00+00:00', reason: 'disk_full' },
      restore_failure: { at: '2026-11-25T05:00:00+00:00', name: 'nexnotes-2026-11-24-120000-upload.zip' },
    }))
    const asked: string[] = []
    const root = await show(
      <StorageArea app="nexnotes" things="Notizen" holds="h" api={api} password language="de"
        when={(iso, language) => (asked.push(`${iso} ${language}`), `heute 3:00 AM <${iso.slice(11, 16)}>`)} />,
    )
    await waitFor(() => expect(root.querySelector('[data-testid="backup-list"]')).not.toBeNull())
    expect(root.querySelector('[data-testid="backup-last"]')?.textContent).toContain('heute 3:00 AM <03:00>')
    expect(root.querySelector('[data-testid="backup-failure"]')?.textContent).toContain('heute 3:00 AM <04:00>')
    expect(root.querySelector('[data-testid="restore-failure"]')?.textContent).toContain('heute 3:00 AM <05:00>')
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-24-120000-upload.zip"]') as HTMLElement
    expect(row.textContent).toContain('heute 3:00 AM <03:00>')
    const first = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(first, 'button', { name: /^Prüfen/ })))
    expect(root.querySelector('[data-testid="backup-brief"]')?.textContent).toContain('heute 3:00 AM <03:00>')
    expect(asked.every((call) => call.endsWith(' de'))).toBe(true)
    // No time of the card in the browser's own way.
    const plain = new Date('2026-11-25T03:00:00+00:00').toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' })
    expect(root.textContent).not.toContain(plain)
    shown?.unmount()
    const before = await area(fakeApi())
    expect(before.querySelector('[data-testid="backup-last"]')?.textContent).toContain(plain)
  })

  it("says an app's own blocking reason in the app's words and the page's language (since E37), as before without", async () => {
    const api = fakeApi()
    const blocked = { ...brief(), blocked: 'backup_other_master_key', blocked_text: 'This backup comes from another server.' }
    api.check = vi.fn(async () => blocked)
    api.restore = vi.fn(async () => Promise.reject({ code: 'backup_other_master_key' }))
    const words = { backup_other_master_key: { de: 'Diese Sicherung stammt von einem anderen Server.', en: 'From another server.' } }
    const root = await show(
      <StorageArea app="nexdiary" things="Einträge" holds="h" api={api} password language="de" blockedText={words} />,
    )
    await waitFor(() => expect(root.querySelector('[data-testid="backup-list"]')).not.toBeNull())
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(row, 'button', { name: /^Prüfen/ })))
    const box = root.querySelector('[data-testid="backup-brief"]') as HTMLElement
    expect(box.textContent).toContain('Diese Sicherung stammt von einem anderen Server.')
    expect(box.textContent).not.toContain('This backup comes from another server.')
    shown?.unmount()
    // Without the app's words: the server's sentence, as before.
    const plain = await show(<StorageArea app="nexdiary" things="Einträge" holds="h" api={api} password language="de" />)
    await waitFor(() => expect(plain.querySelector('[data-testid="backup-list"]')).not.toBeNull())
    const again = plain.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(again, 'button', { name: /^Prüfen/ })))
    expect(plain.querySelector('[data-testid="backup-brief"]')?.textContent).toContain('This backup comes from another server.')
  })

  it('takes English for a language the app has no words in, and leaves other codes to the module', () => {
    const words = { backup_other_master_key: { en: 'From another server.' } }
    expect(blockedWords(words, 'backup_other_master_key', 'fr')).toBe('From another server.')
    expect(blockedWords(words, 'backup_damaged', 'de')).toBeNull()
    expect(blockedWords(undefined, 'backup_other_master_key', 'de')).toBeNull()
  })

  it("asks the app's own questions when restoring and sends the answers (since E38)", async () => {
    const api = fakeApi()
    const answered: unknown[] = []
    api.restore = vi.fn(async (_name, _password, _archivePassword, options) => (answered.push(options), { ...brief(), result: {}, restarting: false }))
    const root = await show(
      <StorageArea app="nexmail" things="Mails" holds="h" api={api} password language="de"
        restoreOptions={[
          { key: 'address', label: 'Öffentliche Adresse aus der Sicherung übernehmen', hint: 'Sonst bleibt die jetzige.' },
          { key: 'mode', label: 'Postfächer', choices: [{ value: 'keep', label: 'Behalten' }, { value: 'replace', label: 'Ersetzen' }] },
        ]} />,
    )
    await waitFor(() => expect(root.querySelector('[data-testid="backup-list"]')).not.toBeNull())
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(row, 'button', { name: /^Wiederherstellen/ })))
    const dialog = await waitFor(() => root.ownerDocument.querySelector('[data-testid="backup-confirm-restore"]') as HTMLElement)
    expect(dialog.textContent).toContain('Sonst bleibt die jetzige.')
    await act(async () => fireEvent.click(getByLabelText(dialog, 'Öffentliche Adresse aus der Sicherung übernehmen')))
    await act(async () => fireEvent.change(getByLabelText(dialog, 'Postfächer'), { target: { value: 'replace' } }))
    await act(async () => fireEvent.change(getByLabelText(dialog, 'Dein Passwort'), { target: { value: 'secret' } }))
    await act(async () => fireEvent.click(getByRole(dialog, 'button', { name: /^Wiederherstellen/ })))
    await waitFor(() => expect(answered).toEqual([{ address: true, mode: 'replace' }]))
  })

  it('sends no answers without questions, as before', async () => {
    const api = fakeApi()
    const restored: unknown[][] = []
    api.restore = vi.fn(async (...given: unknown[]) => (restored.push(given), { ...brief(), result: {}, restarting: false }))
    const root = await area(api)
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(row, 'button', { name: /^Wiederherstellen/ })))
    const dialog = await waitFor(() => root.ownerDocument.querySelector('[data-testid="backup-confirm-restore"]') as HTMLElement)
    await act(async () => fireEvent.change(getByLabelText(dialog, 'Dein Passwort'), { target: { value: 'secret' } }))
    await act(async () => fireEvent.click(getByRole(dialog, 'button', { name: /^Wiederherstellen/ })))
    await waitFor(() => expect(restored).toHaveLength(1))
    expect(restored[0]).toHaveLength(3)
  })

  it('shows the result of a check as a box', async () => {
    const root = await area(fakeApi())
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(row, 'button', { name: /^Prüfen/ })))
    const box = root.querySelector('[data-testid="backup-brief"]') as HTMLElement
    expect(box.textContent).toContain('Die Sicherung ist vollständig und lesbar.')
    expect(box.querySelector('[data-tone="on"]')?.textContent).toBe('Vollständig')
    expect(box.querySelector('[data-testid="details"]')?.textContent).toBe('2 fallen weg')
  })

  it('checks before a restore, then asks for the password', async () => {
    const api = fakeApi()
    const root = await area(api)
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(row, 'button', { name: /^Wiederherstellen/ })))
    expect(api.calls[0]).toBe('check nexnotes-2026-11-25-030000.zip -')
    const dialog = getByRole(document.body, 'dialog', { name: 'Diese Sicherung wiederherstellen?' })
    const confirm = getByRole(dialog, 'button', { name: 'Wiederherstellen' }) as HTMLButtonElement
    expect(confirm.dataset.kind).toBe('danger')
    expect(confirm.disabled).toBe(true)
    fireEvent.change(getByLabelText(dialog, 'Dein Passwort'), { target: { value: 'geheim' } })
    await act(async () => fireEvent.click(confirm))
    expect(api.calls).toContain('restore nexnotes-2026-11-25-030000.zip geheim -')
    expect(root.querySelector('[data-testid="backup-restarting"]')?.textContent).toContain('nexnotes startet mit der Sicherung neu')
  })

  it('never asks to restore a damaged backup, and says why', async () => {
    const api = fakeApi()
    api.check = vi.fn(async () => brief(false))
    const root = await area(api)
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(row, 'button', { name: /^Wiederherstellen/ })))
    expect(queryByRole(document.body, 'dialog')).toBeNull()
    const box = root.querySelector('[data-testid="backup-brief"]') as HTMLElement
    expect(box.textContent).toContain('Beschädigt: Diese Sicherung lässt sich nicht wiederherstellen.')
    expect(box.querySelector('[data-tone="danger"]')?.textContent).toBe('Beschädigt')
    expect(api.restore).not.toHaveBeenCalled()
  })

  it('asks a locked backup for its own password', async () => {
    const api = fakeApi()
    const root = await area(api)
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-24-120000-upload.zip"]') as HTMLElement
    expect(row.textContent).toContain('verschlüsselt')
    await act(async () => fireEvent.click(getByRole(row, 'button', { name: /^Prüfen/ })))
    const dialog = getByRole(document.body, 'dialog')
    fireEvent.change(getByLabelText(dialog, 'Passwort der Sicherung'), { target: { value: 'sesam' } })
    await act(async () => fireEvent.click(getByRole(dialog, 'button', { name: 'Prüfen' })))
    expect(api.calls).toContain('check nexnotes-2026-11-24-120000-upload.zip sesam')
  })

  it('deletes and downloads only with the password; without one when the operator has none', async () => {
    const api = fakeApi()
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const root = await area(api, false)
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(row, 'button', { name: /^Löschen/ })))
    const dialog = getByRole(document.body, 'dialog', { name: 'Diese Sicherung löschen?' })
    expect(queryByRole(dialog, 'textbox')).toBeNull()
    await act(async () => fireEvent.click(getByRole(dialog, 'button', { name: 'Löschen' })))
    expect(api.calls).toContain('remove nexnotes-2026-11-25-030000.zip ')
  })
})

describe('an app that encrypts its downloads (nexmail)', () => {
  it('asks for the file\'s password twice, at least 8 characters, and sends it', async () => {
    const api = fakeApi()
    api.backups = vi.fn(async () => ({ ...BACKUPS, download_password: true }))
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const root = await area(api)
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(row, 'button', { name: /^Herunterladen/ })))
    const dialog = getByRole(document.body, 'dialog', { name: 'Diese Sicherung herunterladen?' })
    const confirm = getByRole(dialog, 'button', { name: 'Herunterladen' }) as HTMLButtonElement
    fireEvent.change(getByLabelText(dialog, 'Dein Passwort'), { target: { value: 'geheim' } })
    fireEvent.change(getByLabelText(dialog, 'Passwort für die Datei'), { target: { value: 'kurz' } })
    fireEvent.change(getByLabelText(dialog, 'Passwort wiederholen'), { target: { value: 'kurz' } })
    expect(confirm.disabled).toBe(true)
    fireEvent.change(getByLabelText(dialog, 'Passwort für die Datei'), { target: { value: 'lang genug' } })
    fireEvent.change(getByLabelText(dialog, 'Passwort wiederholen'), { target: { value: 'lang genau' } })
    expect(confirm.disabled).toBe(true)
    expect(getByText(dialog, 'Die beiden Passwörter sind verschieden.')).not.toBeNull()
    fireEvent.change(getByLabelText(dialog, 'Passwort wiederholen'), { target: { value: 'lang genug' } })
    expect(confirm.disabled).toBe(false)
    await act(async () => fireEvent.click(confirm))
    expect(api.calls).toContain('download nexnotes-2026-11-25-030000.zip geheim lang genug')
  })

  it('downloads without a password of its own in every other app', async () => {
    const api = fakeApi()
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const root = await area(api)
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    await act(async () => fireEvent.click(getByRole(row, 'button', { name: /^Herunterladen/ })))
    const dialog = getByRole(document.body, 'dialog')
    expect(queryByRole(dialog, 'textbox', { name: 'Passwort für die Datei' })).toBeNull()
    expect(dialog.querySelectorAll('input[type="password"]').length).toBe(1)
    fireEvent.change(getByLabelText(dialog, 'Dein Passwort'), { target: { value: 'geheim' } })
    await act(async () => fireEvent.click(getByRole(dialog, 'button', { name: 'Herunterladen' })))
    expect(api.calls).toContain('download nexnotes-2026-11-25-030000.zip geheim -')
  })
})

describe('the words', () => {
  it('come in French too', async () => {
    const root = await area(fakeApi(), true, 'fr')
    expect(getByRole(root, 'heading', { name: 'Stockage' })).not.toBeNull()
    const group = getByRole(root, 'radiogroup', { name: 'Automatiquement' })
    expect(Array.from(group.querySelectorAll('[role="radio"]')).map((item) => item.textContent)).toEqual(['Désactivée', 'Chaque nuit', 'Chaque semaine', 'Chaque mois'])
    expect(getByRole(root, 'button', { name: 'Sauvegarder maintenant' })).not.toBeNull()
  })

  it('have the same keys in every language', () => {
    const keys = (tree: unknown, prefix = ''): string[] =>
      typeof tree === 'object' && tree !== null ? Object.entries(tree).flatMap(([key, value]) => keys(value, `${prefix}${key}.`)) : [prefix]
    expect(keys(SICHERUNG_TEXTS.en).sort()).toEqual(keys(SICHERUNG_TEXTS.de).sort())
    expect(keys(SICHERUNG_TEXTS.fr).sort()).toEqual(keys(SICHERUNG_TEXTS.de).sort())
  })
})

describe('the calls', () => {
  it('go to the module\'s routes with the password where it belongs', async () => {
    const seen: [string, RequestInit][] = []
    const fetcher = vi.fn(async (path: string, init: RequestInit) => {
      seen.push([path, init])
      return new Response(JSON.stringify({ name: 'n' }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    const api = makeSicherungApi(fetcher, '/api/v1/server/storage')
    await api.make('hand')
    await api.upload(new Blob(['zip']), 'Grüße')
    await api.restore('a b.zip', 'pw')
    expect(seen.map(([path, init]) => `${init.method} ${path}`)).toEqual([
      'POST /api/v1/server/storage/backups',
      'POST /api/v1/server/storage/backups/upload',
      'POST /api/v1/server/storage/backups/a%20b.zip/restore',
    ])
    expect((seen[1]?.[1].headers as Record<string, string>)['X-Backup-Password']).toBe(passwordHeader('Grüße'))
    expect(JSON.parse(String(seen[2]?.[1].body))).toEqual({ password: 'pw' })
  })

  it('turn a refusal into its code', async () => {
    const api = makeSicherungApi(async () => new Response(JSON.stringify({ detail: { code: 'backup_running', message: 'busy' } }), { status: 409 }))
    await expect(api.make()).rejects.toMatchObject({ code: 'backup_running', status: 409 })
  })

  it('reckon bars and sizes', () => {
    expect(shares({ used: 10, disk_used: 50, total: 100 })).toEqual({ own: 10, other: 40 })
    expect(shares({ used: 1, disk_used: 1, total: 0 })).toEqual({ own: 0, other: 0 })
    expect(bytes(1536, 'de')).toBe('1,5 KB')
    expect(bytes(1536, 'en')).toBe('1.5 KB')
    expect(bytes(1536, 'fr')).toBe('1,5 KB')
    expect(passwordHeader('Grüße')).toBe('R3LDvMOfZQ==')
  })
})

describe('a time inside a sentence (E62)', () => {
  /** The three forms an app's `when` gives: today, yesterday, a date; each must read right in every sentence. */
  const FORMS: Record<'de' | 'en' | 'fr', string[]> = {
    de: ['heute, 17:15', 'gestern, 17:15', '26.11.2026, 17:15'],
    en: ['today, 5:15 PM', 'yesterday, 5:15 PM', 'Nov 26, 2026, 5:15 PM'],
    fr: ['aujourd’hui, 17:15', 'hier, 17:15', '26 nov. 2026, 17:15'],
  }
  /** What each language says around the time, written out here, not read from the module's words. */
  const SAID = {
    de: {
      row: (action: string, at: string) => `${action}: Sicherung (${at})`,
      actions: ['Prüfen', 'Herunterladen', 'Wiederherstellen', 'Löschen'],
      brief: (at: string) => `Prüfung der Sicherung (${at})`,
      failed: (at: string) => `Die Sicherung ist gescheitert (${at}):`,
      restoreFailed: (at: string) => `Das Wiederherstellen ist gescheitert (${at}).`,
    },
    en: {
      row: (action: string, at: string) => `${action}: backup (${at})`,
      actions: ['Check', 'Download', 'Restore', 'Delete'],
      brief: (at: string) => `Check of the backup (${at})`,
      failed: (at: string) => `The backup failed (${at}):`,
      restoreFailed: (at: string) => `Restoring failed (${at}).`,
    },
    fr: {
      row: (action: string, at: string) => `${action} : sauvegarde (${at})`,
      actions: ['Vérifier', 'Télécharger', 'Restaurer', 'Supprimer'],
      brief: (at: string) => `Vérification de la sauvegarde (${at})`,
      failed: (at: string) => `La sauvegarde a échoué (${at}) :`,
      restoreFailed: (at: string) => `La restauration a échoué (${at}).`,
    },
  }

  it('never puts a word before the time that fits only one of its forms', () => {
    // "vom heute", "on today", "du aujourd’hui": a preposition before {when} is right for one form and wrong for another.
    const before = /(?<!\p{L})(?:am|an|um|vom|von|im|seit|on|of|at|from|since|du|le|de|depuis|à)\s*\{when\}/giu
    for (const language of ['de', 'en', 'fr'] as const) {
      const found = JSON.stringify(SICHERUNG_TEXTS[language]).match(before)
      expect(found, language).toBeNull()
    }
  })

  for (const language of ['de', 'en', 'fr'] as const) {
    for (const at of FORMS[language]) {
      it(`reads right in ${language} with "${at}": the row's buttons, the check, both failures`, async () => {
        const said = SAID[language]
        const api = fakeApi()
        api.backups = vi.fn(async () => ({
          ...BACKUPS,
          backups: [entry('nexnotes-2026-11-25-030000.zip')],
          failure: { at: '2026-11-25T04:00:00+00:00', reason: 'disk_full' },
          restore_failure: { at: '2026-11-25T05:00:00+00:00', name: 'nexnotes-2026-11-25-030000.zip' },
        }))
        const root = await show(<StorageArea app="nexnotes" things="Notizen" holds="h" api={api} password language={language} when={() => at} />, language)
        await waitFor(() => expect(root.querySelector('[data-testid="backup-list"]')).not.toBeNull())
        const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
        const names = Array.from(row.querySelectorAll('button')).map((button) => button.getAttribute('aria-label'))
        expect(names).toEqual(said.actions.map((action) => said.row(action, at)))
        expect(root.querySelector('[data-testid="backup-failure"]')?.textContent).toContain(said.failed(at))
        expect(root.querySelector('[data-testid="restore-failure"]')?.textContent).toContain(said.restoreFailed(at))
        await act(async () => fireEvent.click(getByRole(row, 'button', { name: said.row(said.actions[0]!, at) })))
        expect(root.querySelector('[data-testid="backup-brief"]')?.textContent).toContain(said.brief(at))
      })
    }
  }
})

describe('"Jetzt sichern" asks for a note (E63)', () => {
  const dialogOf = () => getByRole(document.body, 'dialog', { name: 'Jetzt sichern' })

  it('opens a small window with the optional field "Notiz" (at most 200), Abbrechen and Sichern, and no password', async () => {
    const api = fakeApi()
    const root = await area(api)
    await act(async () => fireEvent.click(root.querySelector('[data-testid="backup-now"]') as HTMLElement))
    expect(api.calls).toEqual([])
    const dialog = dialogOf()
    const field = getByLabelText(dialog, 'Notiz') as HTMLInputElement
    expect([field.maxLength, field.value, field.type]).toEqual([200, '', 'text'])
    expect(dialog.textContent).toContain('Freiwillig, höchstens 200 Zeichen.')
    expect(dialog.querySelector('input[type="password"]')).toBeNull()
    const make = getByRole(dialog, 'button', { name: 'Sichern' }) as HTMLButtonElement
    expect([make.dataset.kind, make.dataset.icon, make.disabled]).toEqual(['primary', 'Archive', false])
    await act(async () => fireEvent.click(getByRole(dialog, 'button', { name: 'Abbrechen' })))
    expect(queryByRole(document.body, 'dialog')).toBeNull()
    expect(api.calls).toEqual([])
  })

  it('sends the note without the blanks around it, none for blanks alone, then says so and loads the list again', async () => {
    const api = fakeApi()
    const root = await area(api)
    const loads = (api.backups as ReturnType<typeof vi.fn>).mock.calls.length
    await act(async () => fireEvent.click(root.querySelector('[data-testid="backup-now"]') as HTMLElement))
    fireEvent.change(getByLabelText(dialogOf(), 'Notiz'), { target: { value: '  vor dem Umzug  ' } })
    await act(async () => fireEvent.click(getByRole(dialogOf(), 'button', { name: 'Sichern' })))
    expect(api.calls).toEqual(['make vor dem Umzug'])
    expect(queryByRole(document.body, 'dialog')).toBeNull()
    expect(root.textContent).toContain('Sicherung erstellt.')
    expect((api.backups as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(loads)
    await act(async () => fireEvent.click(root.querySelector('[data-testid="backup-now"]') as HTMLElement))
    expect((getByLabelText(dialogOf(), 'Notiz') as HTMLInputElement).value).toBe('')
    fireEvent.change(getByLabelText(dialogOf(), 'Notiz'), { target: { value: '   ' } })
    await act(async () => fireEvent.click(getByRole(dialogOf(), 'button', { name: 'Sichern' })))
    expect(api.calls).toEqual(['make vor dem Umzug', 'make '])
  })

  it('keeps the window with the reason when the server refuses, and the list shows each note', async () => {
    const api = fakeApi()
    api.make = vi.fn(async () => {
      throw Object.assign(new Error('busy'), { code: 'backup_running', status: 409 })
    })
    api.backups = vi.fn(async () => ({ ...BACKUPS, backups: [entry('nexnotes-2026-11-25-030000.zip', { kind: 'manual', note: 'vor dem Umzug' })] }))
    const root = await area(api)
    const row = root.querySelector('[data-testid="backup-nexnotes-2026-11-25-030000.zip"]') as HTMLElement
    expect(row.textContent).toContain('vor dem Umzug')
    await act(async () => fireEvent.click(root.querySelector('[data-testid="backup-now"]') as HTMLElement))
    await act(async () => fireEvent.click(getByRole(dialogOf(), 'button', { name: 'Sichern' })))
    expect(dialogOf().textContent).toContain(SICHERUNG_TEXTS.de.error.backup_running)
  })

  for (const [language, title, label, button, cancel] of [
    ['en', 'Back up now', 'Note', 'Back up', 'Cancel'],
    ['fr', 'Sauvegarder maintenant', 'Note', 'Sauvegarder', 'Annuler'],
  ] as const) {
    it(`speaks ${language}`, async () => {
      const api = fakeApi()
      const root = await show(<StorageArea app="nexnotes" things="notes" holds="h" api={api} password language={language} />, language)
      await waitFor(() => expect(root.querySelector('[data-testid="backup-now"]')).not.toBeNull())
      await act(async () => fireEvent.click(root.querySelector('[data-testid="backup-now"]') as HTMLElement))
      const dialog = getByRole(document.body, 'dialog', { name: title })
      expect((getByLabelText(dialog, label) as HTMLInputElement).maxLength).toBe(200)
      getByRole(dialog, 'button', { name: cancel })
      await act(async () => fireEvent.click(getByRole(dialog, 'button', { name: button })))
      expect(api.calls).toEqual(['make '])
    })
  }
})
