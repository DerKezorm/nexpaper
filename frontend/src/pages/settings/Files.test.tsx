/**
 * Server › Storage and backups: nexpaper's card "Dateien prüfen" (the state of the last check, a check on a click, the
 * progress of one that runs), nexpaper's part of the module's cards "Speicher" and "Sicherung" (sicherung 1.0.1, under
 * `/api/v1/server/storage`: its words for its parts, what a backup holds, the counts of an entry, the trial run before a
 * restore in nexpaper's words), against a stand-in of the server. Also the warning signs on a document.
 */
import { act } from 'react'

import type { Me } from '../../api/client'
import { FileNotice, FileSign } from '../../components/docs'
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { FilesCards, type StorageInfo } from './FilesCards'
import { StorageArea } from './StorageArea'

const me = { id: 1, name: 'jule', role: 'operator', sign_in: 'password', profile: { timezone: 'Europe/Berlin' } } as unknown as { role: string } & Me
vi.mock('../../state/auth', () => ({ useAuth: () => ({ me }) }))

const server = new Server()
const page = new Page()

const local = { kind: 'local', fstype: 'ext4', network: false } as const
const share = { kind: 'network', fstype: 'nfs4', network: true } as const

function info(change: Partial<StorageInfo> = {}): StorageInfo {
  return {
    database: { bytes: 142_000_000, index_bytes: 90_000_000, where: local },
    documents: { bytes: 8_800_000_000, files: 5112, complete: true, originals_bytes: 2_100_000_000, where: local },
    cache: { bytes: 300_000_000, files: 400, complete: true },
    exports: { bytes: 0, files: 0, complete: true },
    backups: { bytes: 296_000_000, files: 2, complete: true },
    free_bytes: 31_000_000_000,
    total_bytes: 500_000_000_000,
    data: { where: local },
    files: {
      running: false, documents_total: 0, documents_done: 0, last_finished_at: '2026-10-10T03:12:00Z', last_files: 5112, last_documents: 1657,
      last_problems: 0, last_skipped: 0, flagged_documents: 0, every_days: 7,
    },
    ...change,
  }
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = { 'GET /api/v1/storage': info(), 'GET /api/v1/backups': [] }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('the card "Dateien prüfen"', () => {
  it('says all files are in order, with their number, and when it looked', async () => {
    await page.show(<FilesCards />)
    expect(page.text).toContain('Dateien prüfen')
    expect(document.querySelector('[data-testid="check-fine"]')?.textContent).toContain('5.112 Dateien, alle in Ordnung')
    expect(page.text).toContain('zuletzt')
    expect(page.text).toContain('Warnzeichen')
  })

  it('says how many documents have a problem instead', async () => {
    server.answers['GET /api/v1/storage'] = info({ files: { ...info().files, flagged_documents: 3, last_problems: 3 } })
    await page.show(<FilesCards />)
    expect(document.querySelector('[data-testid="check-problems"]')?.textContent).toContain('3 Dokumente mit Auffälligkeiten')
    expect(document.querySelector('[data-testid="check-fine"]')).toBeNull()
  })

  it('says it has not looked yet', async () => {
    server.answers['GET /api/v1/storage'] = info({ files: { ...info().files, last_finished_at: null, last_files: 0 } })
    await page.show(<FilesCards />)
    expect(page.text).toContain('Noch nicht geprüft.')
  })

  it('starts a check with one click and not before', async () => {
    server.answers['POST /api/v1/storage/files/check'] = { ...info().files, running: true, started: true }
    await page.show(<FilesCards />)
    expect(server.changes()).toEqual([])
    await page.click(page.button('Jetzt prüfen'))
    expect(server.changes()).toEqual(['POST /api/v1/storage/files/check'])
    expect(page.text).toContain('Die Prüfung läuft im Hintergrund.')
  })

  it('shows the progress of a check that runs, asks again, and cannot be started twice', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    server.answers['GET /api/v1/storage'] = info({ files: { ...info().files, running: true, documents_total: 1657, documents_done: 400 } })
    await page.show(<FilesCards />)
    expect(document.querySelector('[data-testid="check-running"]')?.textContent).toBe('Prüfung läuft: 400 von 1.657 Dokumenten')
    expect(page.button('Jetzt prüfen')?.disabled).toBe(true)
    server.answers['GET /api/v1/storage'] = info({ files: { ...info().files, running: true, documents_total: 1657, documents_done: 900 } })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500)
    })
    expect(document.querySelector('[data-testid="check-running"]')?.textContent).toContain('900 von 1.657')
    server.answers['GET /api/v1/storage'] = info()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500)
    })
    expect(document.querySelector('[data-testid="check-running"]')).toBeNull()
    expect(page.button('Jetzt prüfen')?.disabled).toBe(false)
  })

  it('says in English what it says in German', async () => {
    await changeLanguage('en', false)
    await page.show(<FilesCards />)
    expect(document.querySelector('[data-testid="check-fine"]')?.textContent).toContain('5,112 files, all in order')
    expect(page.text).toContain('Check files')
  })
})

/** What the module's card "Speicher" gets from nexpaper's server (`GET /api/v1/server/storage`, sicherung 1.0.1). */
function overview(change: Record<string, unknown> = {}) {
  return {
    app: 'nexpaper',
    used: 9_538_000_000,
    parts: [
      { key: 'documents', bytes: 8_800_000_000, within: '', complete: true },
      { key: 'originals', bytes: 2_100_000_000, within: 'documents', complete: true },
      { key: 'database', bytes: 142_000_000, within: '', complete: true },
      { key: 'index', bytes: 90_000_000, within: 'database', complete: true },
      { key: 'pages', bytes: 300_000_000, within: '', complete: true },
      { key: 'exports', bytes: 0, within: '', complete: true },
      { key: 'backups', bytes: 296_000_000, within: '', complete: true },
    ],
    complete: true,
    total: 500_000_000_000,
    disk_used: 469_000_000_000,
    free: 31_000_000_000,
    nearly_full: false,
    where: { data: { kind: 'local', fstype: 'ext4' }, database: { kind: 'local', fstype: 'ext4' }, documents: { kind: 'local', fstype: 'ext4' } },
    network: [],
    ...change,
  }
}

/** What the module's card "Sicherung" gets (`GET /api/v1/server/storage/backups`). */
function backups(entries: unknown[] = []) {
  return {
    schedule: { every: 'daily', time: '03:00', keep: 7 }, zone: 'Europe/Berlin', last: null, count: entries.length, kept: 7, failure: null, running: false,
    restore_failure: null, restored: null, restore: 'restart', download_password: false, backups: entries,
  }
}

const AT = '/api/v1/server/storage'

describe('Speicher und Sicherung: nexpaper\'s part of the module\'s cards', () => {
  beforeEach(() => {
    server.answers[`GET ${AT}`] = overview()
    server.answers[`GET ${AT}/backups`] = backups()
  })

  it('shows what lies where in nexpaper\'s words, and the free room', async () => {
    await page.show(<StorageArea />)
    const card = document.querySelector('[data-card="storage"]')!
    expect(card.querySelector('h2')!.textContent).toBe('Speicher')
    // What nexpaper takes, in one sum; its parts in one line, with nexpaper's own (originals, page pictures).
    expect(document.querySelector('[data-testid="storage-used"]')!.textContent).toBe('8,9 GB')
    expect(page.text).toContain('nexpaper belegt')
    expect(document.querySelector('[data-testid="storage-parts"]')!.textContent).toBe(
      'Dokumente 8,2 GB · Datenbank 135 MB · Seitenbilder (Zwischenspeicher) 286 MB · Exporte 0 B · Sicherungen 282 MB (davon Originale 2,0 GB, davon Suchindex 85,8 MB)',
    )
    expect(document.querySelector('[data-testid="storage-free"]')!.textContent).toBe('28,9 GB frei von 466 GB')
    // Everything from the module's route; the old card's route only for the check of the files.
    expect(server.calls.filter((call) => call.url === AT)).toHaveLength(1)
  })

  it('is calm about a database on a local drive', async () => {
    await page.show(<StorageArea />)
    expect(document.querySelector('[data-testid="storage-network"]')).toBeNull()
    expect(document.querySelector('[data-testid="storage-network-places"]')).toBeNull()
  })

  it('warns about a data folder on a network share, with nexpaper\'s word for what it keeps', async () => {
    server.answers[`GET ${AT}`] = overview({ network: ['data', 'database'] })
    await page.show(<StorageArea />)
    expect(document.querySelector('[data-testid="storage-network"]')!.textContent).toContain('Das kann Dokumente beschädigen.')
    expect(document.querySelector('[data-testid="storage-network-places"]')!.textContent).toContain('Datenbank')
  })

  it('names documents on a share, and says when a count was cut off', async () => {
    server.answers[`GET ${AT}`] = overview({ network: ['documents'], complete: false })
    await page.show(<StorageArea />)
    expect(document.querySelector('[data-testid="storage-network"]')).toBeNull()
    expect(document.querySelector('[data-testid="storage-network-places"]')!.textContent).toContain('Dokumente')
    expect(page.text).toContain('Noch nicht alles gezählt')
  })

  // Where the database lies stays nexpaper's own word, in the card "So liegen die Dateien auf der Platte" (the module's
  // card only names a place on a share): calm on a local drive, an alert with the kind of share, honest when unknown.
  it('is calm about a database on a local drive, in the card of the disk', async () => {
    await page.show(<StorageArea />)
    const box = document.querySelector('[data-card="disk"] [data-testid="database-local"]')
    expect(box?.textContent).toContain('Die Datenbank liegt auf einem lokalen Laufwerk.')
    expect(box?.querySelector('[role="alert"]')).toBeNull()
  })

  it('warns about a database on a network share, as an alert, with the kind of share', async () => {
    server.answers['GET /api/v1/storage'] = info({ database: { ...info().database, where: share }, data: { where: share } })
    await page.show(<StorageArea />)
    const box = document.querySelector('[data-card="disk"] [data-testid="database-network"]')!
    expect(box.querySelector('[role="alert"]')).toBeTruthy()
    expect(box.textContent).toContain('Die Datenbank liegt auf einer Netzwerkfreigabe (nfs4).')
    expect(box.textContent).toContain('SQLite kann dort Daten verlieren')
    expect(document.querySelector('[data-testid="database-local"]')).toBeNull()
  })

  it('does not claim to know where the database lies when the server could not tell', async () => {
    server.answers['GET /api/v1/storage'] = info({ database: { ...info().database, where: { kind: 'unknown', fstype: '', network: false } } })
    await page.show(<StorageArea />)
    expect(document.querySelector('[data-testid="database-unknown"]')?.textContent).toContain('Nicht festzustellen')
    expect(page.text).not.toContain('Die Datenbank liegt auf einem lokalen Laufwerk')
  })

  it('says documents on a share are fine', async () => {
    server.answers['GET /api/v1/storage'] = info({ documents: { ...info().documents, where: share } })
    await page.show(<StorageArea />)
    expect(document.querySelector('[data-card="disk"]')!.textContent).toContain('Die Dokumente liegen auf einer Netzwerkfreigabe. Das ist in Ordnung.')
  })

  it('stands before the disk card and the check of the files, in the plan\'s order', async () => {
    server.answers[`GET ${AT}/backups`] = backups()
    await page.show(<StorageArea />)
    const order = ['storage', 'backups', 'disk', 'files-check'].map((id) => document.querySelector(`[data-card="${id}"]`))
    expect(order.every(Boolean)).toBe(true)
    for (let index = 1; index < order.length; index += 1) expect(order[index - 1]!.compareDocumentPosition(order[index]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(server.calls.filter((call) => call.url === '/api/v1/storage')).toHaveLength(1)
  })

  it('has no German left in the English page', async () => {
    await changeLanguage('en', false)
    server.answers[`GET ${AT}`] = overview({ network: ['data'] })
    await page.show(<StorageArea />)
    expect(page.text).toContain('Page pictures (cache)')
    expect(page.text).toContain('originals')
    expect(page.text).toContain('Storage')
    expect(page.text).not.toMatch(/Datenbank|Netzwerkfreigabe|Speicher|Dokumente|Seitenbilder/)
  })
})

describe('the trial run before a restore', () => {
  const entry = {
    name: 'nexpaper-2026-10-08-030000.zip', size: 148_000_000, created: '2026-10-08T03:00:00+00:00', kind: 'scheduled', note: '', version: '0.1.0', uploaded: false,
    locked: false, readable: true, facts: { accounts: 3, documents: 1657 },
  }
  const details = { schema: 20, documents: 1657, missing_documents: 2, changed_documents: 1, not_compared: 0, newer_documents: 8, rebuilds_index: true }
  const brief = (more: Record<string, unknown> = {}, change: Record<string, unknown> = {}) => ({
    name: entry.name, created: entry.created, kind: 'scheduled', note: '', version: '0.1.0', uploaded: false, database_ok: true, files_ok: true, damaged: [],
    too_new: false, blocked: '', blocked_text: '', usable: true, facts: entry.facts, details: { ...details, ...more }, ...change,
  })

  beforeEach(() => {
    server.answers[`GET ${AT}`] = overview()
    server.answers[`GET ${AT}/backups`] = backups([entry])
    server.answers[`POST ${AT}/backups/${entry.name}/check`] = brief()
    server.answers[`POST ${AT}/backups/${entry.name}/restore`] = { ...brief(), result: {}, restarting: true }
  })

  const check = async () => page.click(page.button('Prüfen', document.querySelector<HTMLElement>('[data-testid="backup-list"]')!))
  const preview = () => document.querySelector('[data-testid="backup-brief"] [data-testid="restore-preview"]')?.textContent ?? ''

  it('lists the accounts and documents in the line of a backup', async () => {
    await page.show(<StorageArea />)
    expect(document.querySelector(`[data-testid="backup-${entry.name}"]`)!.textContent).toContain('3 Konten, 1657 Dokumente')
  })

  it('shows the trial run in words: missing and changed files, what would go, the new search', async () => {
    await page.show(<StorageArea />)
    await check()
    expect(server.called('POST', `${AT}/backups/${entry.name}/check`)).toBeTruthy()
    const lines = preview()
    expect(lines).toContain('Die Sicherung kennt 1657 Dokumente.')
    expect(lines).toContain('Zu 2 Dokumenten fehlt eine Datei auf der Platte.')
    expect(lines).toContain('1 Dokument hat eine Datei mit anderer Prüfsumme.')
    expect(lines).toContain('Zurückspielen entfernt 8 Dokumente, die seitdem dazukamen. Ihre Dateien bleiben im Ordner liegen.')
    expect(lines).toContain('Die Suche wird danach neu aufgebaut.')
    expect(lines).not.toContain('Alle ihre Dateien liegen auf der Platte.')
  })

  it('says what a restore brings back to life: devices, keys and links ended since the backup', async () => {
    server.answers[`POST ${AT}/backups/${entry.name}/check`] = brief({ revived_devices: 2, revived_keys: 1, revived_links: 3 })
    await page.show(<StorageArea />)
    await check()
    const lines = preview()
    expect(lines).toContain('Zurückspielen macht 2 Geräte wieder gültig, die seit der Sicherung gesperrt oder entfernt wurden.')
    expect(lines).toContain('Zurückspielen macht 1 API-Schlüssel wieder gültig, der seit der Sicherung gesperrt wurde.')
    expect(lines).toContain('Zurückspielen macht 3 Links wieder gültig, die seit der Sicherung zurückgezogen wurden.')
  })

  it('says how many further documents a restore shows through a link again (N2)', async () => {
    server.answers[`POST ${AT}/backups/${entry.name}/check`] = brief({ revived_links: 1, revived_link_documents: 2 })
    await page.show(<StorageArea />)
    await check()
    expect(preview()).toContain('Zurückspielen zeigt 2 Dokumente wieder über einen Link, die seit der Sicherung herausgenommen wurden oder deren Link zurückgezogen wurde.')
  })

  it('says how many kept PDF passwords a restore brings back, without a name (P1)', async () => {
    server.answers[`POST ${AT}/backups/${entry.name}/check`] = brief({ revived_pdf_passwords: 2 })
    await page.show(<StorageArea />)
    await check()
    expect(preview()).toContain('Zurückspielen bringt 2 gemerkte PDF-Passwörter zurück, die seit der Sicherung gelöscht wurden.')
  })

  it('says all three together: further documents of links, kept PDF passwords and upload requests (N2, P1, U1)', async () => {
    server.answers[`POST ${AT}/backups/${entry.name}/check`] = brief({ revived_link_documents: 2, revived_pdf_passwords: 1, revived_upload_requests: 3 })
    await page.show(<StorageArea />)
    await check()
    const lines = [...document.querySelectorAll('[data-testid="restore-preview"] li')].map((li) => li.textContent)
    expect(lines).toContain('Zurückspielen zeigt 2 Dokumente wieder über einen Link, die seit der Sicherung herausgenommen wurden oder deren Link zurückgezogen wurde.')
    expect(lines).toContain('Zurückspielen bringt 1 gemerktes PDF-Passwort zurück, das seit der Sicherung gelöscht wurde.')
    expect(lines).toContain('Zurückspielen öffnet 3 Upload-Bitten wieder, die seit der Sicherung zurückgezogen oder beendet wurden.')
  })

  it('says nothing of the kind when nothing was ended since the backup', async () => {
    server.answers[`POST ${AT}/backups/${entry.name}/check`] = brief({ revived_devices: 0, revived_keys: 0, revived_links: 0 })
    await page.show(<StorageArea />)
    await check()
    expect(preview()).not.toContain('wieder gültig')
  })

  it('says all files are there when none is missing or changed', async () => {
    server.answers[`POST ${AT}/backups/${entry.name}/check`] = brief({ missing_documents: 0, changed_documents: 0, newer_documents: 0 })
    await page.show(<StorageArea />)
    await check()
    expect(preview()).toContain('Alle ihre Dateien liegen auf der Platte.')
  })

  it('asks for the trial run first, shows it in the dialog, and restores only after the password and the one click', async () => {
    await page.show(<StorageArea />)
    await page.click(page.button('Wiederherstellen', document.querySelector<HTMLElement>('[data-testid="backup-list"]')!))
    expect(server.changes()).toEqual([`POST ${AT}/backups/${entry.name}/check`])
    const dialog = page.dialog!
    expect(dialog.textContent).toContain('Erst wird der jetzige Stand gesichert')
    expect(dialog.textContent).toContain('Zu 2 Dokumenten fehlt eine Datei auf der Platte.')
    // Cancel: nothing was sent but the trial.
    await page.click(page.button('Abbrechen', dialog))
    expect(server.changes()).toEqual([`POST ${AT}/backups/${entry.name}/check`])
    await page.click(page.button('Wiederherstellen', document.querySelector<HTMLElement>('[data-testid="backup-list"]')!))
    const again = page.dialog!
    expect(page.button('Wiederherstellen', again)!.disabled).toBe(true)
    await page.type(again.querySelector<HTMLInputElement>('input[type="password"]'), 'a made-up password')
    await page.click(page.button('Wiederherstellen', again))
    expect(server.called('POST', `${AT}/backups/${entry.name}/restore`)?.body).toEqual({ password: 'a made-up password' })
  })

  it('opens no dialog for a backup that cannot be used', async () => {
    server.answers[`POST ${AT}/backups/${entry.name}/check`] = brief({}, { usable: false, too_new: true, version: '9.0.0' })
    await page.show(<StorageArea />)
    await page.click(page.button('Wiederherstellen', document.querySelector<HTMLElement>('[data-testid="backup-list"]')!))
    expect(page.dialog).toBeNull()
    expect(page.text).toContain('Diese Sicherung stammt aus nexpaper 9.0.0, neuer als diese.')
    expect(server.changes()).toEqual([`POST ${AT}/backups/${entry.name}/check`])
  })

  it('says what a backup holds: the database and the key, not the documents, and not the search index', async () => {
    await page.show(<StorageArea />)
    const subtitle = document.querySelector('[data-card="backups"] h2 + p')!.textContent ?? ''
    expect(subtitle).toContain('nicht die Dokumente selbst')
    expect(subtitle).toContain('Den Suchindex baut nexpaper nach dem Wiederherstellen neu.')
  })
})

describe('the warning sign of a document', () => {
  it('shows nothing for a document in order', async () => {
    await page.show(
      <>
        <FileSign state="" />
        <FileSign />
        <FileNotice state="" />
      </>,
    )
    expect(document.querySelector('[data-testid="file-sign"]')).toBeNull()
    expect(document.querySelector('[data-testid="file-notice"]')).toBeNull()
  })

  it('tells the operator the way out and everybody else whom to ask', async () => {
    await page.show(<FileNotice state="missing" />)
    const operatorText = document.querySelector('[data-testid="file-notice"]')?.textContent ?? ''
    expect(operatorText).toContain('aus der Sicherung deines Servers zurück')
    expect(operatorText).toContain('Zu „Dateien prüfen“')
    expect(document.querySelector('[data-testid="file-notice"] a')?.getAttribute('href')).toBe('/settings/storage')
    expect(operatorText).not.toContain('Sag dem Betreiber')
    page.close()
    me.role = 'member'
    try {
      for (const state of ['missing', 'changed']) {
        await page.show(<FileNotice state={state} />)
        const text = document.querySelector('[data-testid="file-notice"]')?.textContent ?? ''
        expect(text).toContain('Sag dem Betreiber deines Servers Bescheid.')
        expect(text).not.toContain('Zu „Dateien prüfen“')
        expect(document.querySelector('[data-testid="file-notice"] a')).toBeNull()
        page.close()
      }
    } finally {
      me.role = 'operator'
    }
  })

  it('lets the operator look at the one document again, and reloads when the server answered', async () => {
    server.answers['POST /api/v1/storage/files/documents/7/check'] = { files_state: '' }
    const checked = vi.fn()
    await page.show(<FileNotice state="missing" documentId={7} onChecked={checked} />)
    await page.click(page.button('Dieses Dokument jetzt neu prüfen'))
    expect(server.changes()).toEqual(['POST /api/v1/storage/files/documents/7/check'])
    expect(checked).toHaveBeenCalledTimes(1)
  })

  it('shows no button for the one document to a member, and none when the notice does not know the document', async () => {
    await page.show(<FileNotice state="missing" />)
    expect(page.text).not.toContain('jetzt neu prüfen')
    page.close()
    me.role = 'member'
    try {
      await page.show(<FileNotice state="missing" documentId={7} />)
      expect(page.text).not.toContain('jetzt neu prüfen')
    } finally {
      me.role = 'operator'
    }
  })

  it('names a missing and a changed file, with the way out', async () => {
    await page.show(
      <>
        <FileSign state="missing" />
        <FileNotice state="changed" />
      </>,
    )
    expect(document.querySelector('[data-testid="file-sign"]')?.getAttribute('aria-label')).toBe('Datei fehlt')
    const notice = document.querySelector('[data-testid="file-notice"]')
    expect(notice?.getAttribute('role')).toBe('alert')
    expect(notice?.textContent).toContain('nicht mehr dieselbe')
    expect(notice?.textContent).toContain('aus der Sicherung deines Servers zurück')
  })
})
