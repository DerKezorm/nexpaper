/**
 * Settings, Backups: the card "Check files" (the state of the last check, a check on a click, the progress of one that
 * runs), the card "Storage" (sizes, the warning for a database on a network share) and the trial run before a restore,
 * against a stand-in of the server. Also the warning signs on a document.
 */
import { act } from 'react'

import type { Me } from '../../api/client'
import { FileNotice, FileSign } from '../../components/docs'
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { FilesCards, type StorageInfo } from './FilesCards'
import { BackupsCard, type ServerSettings } from './ServerCards'

const me = { id: 1, name: 'jule', role: 'operator', sign_in: 'password' } as unknown as { role: string } & Me
vi.mock('../../state/auth', () => ({ useAuth: () => ({ me }) }))

const server = new Server()
const page = new Page()

const settings = { backup_schedule: 'daily', backup_keep: 7 } as unknown as ServerSettings
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

describe('the card "Speicher"', () => {
  it('shows what lies where, and the free room', async () => {
    await page.show(<FilesCards />)
    const text = page.text
    expect(text).toContain('Speicher')
    expect(text).toContain('8,8 GB')
    expect(text).toContain('davon Originale 2,1 GB')
    expect(text).toContain('142 MB')
    expect(text).toContain('davon Suchindex 90 MB')
    expect(text).toContain('31 GB')
    expect(text).toContain('von 500 GB')
    expect(text).toContain('Exporte')
    expect(text).toContain('Sicherungen')
  })

  it('is calm about a database on a local drive', async () => {
    await page.show(<FilesCards />)
    const box = document.querySelector('[data-testid="database-local"]')
    expect(box?.textContent).toContain('Die Datenbank liegt auf einem lokalen Laufwerk.')
    expect(box?.getAttribute('role')).toBeNull()
  })

  it('warns about a database on a network share, as an alert, with the kind of share', async () => {
    server.answers['GET /api/v1/storage'] = info({ database: { ...info().database, where: share }, data: { where: share } })
    await page.show(<FilesCards />)
    const box = document.querySelector('[data-testid="database-network"]')
    expect(box?.getAttribute('role')).toBe('alert')
    expect(box?.textContent).toContain('Die Datenbank liegt auf einer Netzwerkfreigabe (nfs4).')
    expect(box?.textContent).toContain('SQLite kann dort Daten verlieren')
    expect(document.querySelector('[data-testid="database-local"]')).toBeNull()
  })

  it('does not claim to know where the database lies when the server could not tell', async () => {
    server.answers['GET /api/v1/storage'] = info({ database: { ...info().database, where: { kind: 'unknown', fstype: '', network: false } } })
    await page.show(<FilesCards />)
    expect(document.querySelector('[data-testid="database-unknown"]')?.textContent).toContain('Nicht festzustellen')
    expect(page.text).not.toContain('Die Datenbank liegt auf einem lokalen Laufwerk')
  })

  it('says documents on a share are fine, and when a count was cut off', async () => {
    server.answers['GET /api/v1/storage'] = info({ documents: { ...info().documents, where: share, complete: false } })
    await page.show(<FilesCards />)
    expect(page.text).toContain('Die Dokumente liegen auf einer Netzwerkfreigabe. Das ist in Ordnung.')
    expect(page.text).toContain('Die Zahlen sind mindestens so groß.')
  })

  it('has no German left in the English page', async () => {
    await changeLanguage('en', false)
    server.answers['GET /api/v1/storage'] = info({ database: { ...info().database, where: share } })
    await page.show(<FilesCards />)
    expect(page.text).toContain('The database lies on a network share (nfs4).')
    expect(page.text).toContain('Storage')
    expect(page.text).not.toMatch(/Datenbank|Netzwerkfreigabe|Speicher/)
  })
})

describe('the trial run before a restore', () => {
  const entry = { name: 'nexpaper-2026-10-08-030000.zip', size: 148_000_000, created: '2026-10-08T03:00:00+00:00', kind: 'scheduled', note: '', accounts: 3, version: '0.1.0', documents: 1657 }
  const brief = {
    name: entry.name, usable: true, too_new: false, accounts: 3, documents: 1657, missing_documents: 2, changed_documents: 1, not_compared: 0,
    newer_documents: 8, rebuilds_index: true, created: entry.created,
  }

  beforeEach(() => {
    server.answers['GET /api/v1/backups'] = [entry]
    server.answers[`POST /api/v1/backups/${entry.name}/check`] = brief
    server.answers[`POST /api/v1/backups/${entry.name}/restore`] = { ...brief, restarting: true }
  })

  it('lists the documents in the line of a backup', async () => {
    await page.show(<BackupsCard server={{ settings, busy: false } as never} />)
    expect(page.text).toContain('3 Konten, 1657 Dokumente')
  })

  it('shows the trial run in words: missing and changed files, what would go, the new search', async () => {
    await page.show(<BackupsCard server={{ settings, busy: false } as never} />)
    await page.click(page.button('Prüfen'))
    const lines = document.querySelector('[data-testid="trial-run"] [data-testid="restore-preview"]')?.textContent ?? ''
    expect(lines).toContain('Die Sicherung kennt 1657 Dokumente.')
    expect(lines).toContain('Zu 2 Dokumenten fehlt eine Datei auf der Platte.')
    expect(lines).toContain('1 Dokument hat eine Datei mit anderer Prüfsumme.')
    expect(lines).toContain('Zurückspielen entfernt 8 Dokumente, die seitdem dazukamen. Ihre Dateien bleiben im Ordner liegen.')
    expect(lines).toContain('Die Suche wird danach neu aufgebaut.')
    expect(lines).not.toContain('Alle ihre Dateien liegen auf der Platte.')
  })

  it('says what a restore brings back to life: devices, keys and links ended since the backup', async () => {
    server.answers[`POST /api/v1/backups/${entry.name}/check`] = { ...brief, revived_devices: 2, revived_keys: 1, revived_links: 3 }
    await page.show(<BackupsCard server={{ settings, busy: false } as never} />)
    await page.click(page.button('Prüfen'))
    const lines = document.querySelector('[data-testid="restore-preview"]')?.textContent ?? ''
    expect(lines).toContain('Zurückspielen macht 2 Geräte wieder gültig, die seit der Sicherung gesperrt oder entfernt wurden.')
    expect(lines).toContain('Zurückspielen macht 1 Schlüssel wieder gültig, der seit der Sicherung gesperrt wurde.')
    expect(lines).toContain('Zurückspielen macht 3 Links wieder gültig, die seit der Sicherung zurückgezogen wurden.')
  })

  it('says nothing of the kind when nothing was ended since the backup', async () => {
    server.answers[`POST /api/v1/backups/${entry.name}/check`] = { ...brief, revived_devices: 0, revived_keys: 0, revived_links: 0 }
    await page.show(<BackupsCard server={{ settings, busy: false } as never} />)
    await page.click(page.button('Prüfen'))
    expect(document.querySelector('[data-testid="restore-preview"]')?.textContent).not.toContain('wieder gültig')
  })

  it('says all files are there when none is missing or changed', async () => {
    server.answers[`POST /api/v1/backups/${entry.name}/check`] = { ...brief, missing_documents: 0, changed_documents: 0, newer_documents: 0 }
    await page.show(<BackupsCard server={{ settings, busy: false } as never} />)
    await page.click(page.button('Prüfen'))
    expect(document.querySelector('[data-testid="restore-preview"]')?.textContent).toContain('Alle ihre Dateien liegen auf der Platte.')
  })

  it('asks for the trial run first, shows it in the dialog, and restores only after the password and the one click', async () => {
    await page.show(<BackupsCard server={{ settings, busy: false } as never} />)
    await page.click(page.button('Wiederherstellen'))
    expect(server.changes()).toEqual([`POST /api/v1/backups/${entry.name}/check`])
    const dialog = page.dialog!
    expect(dialog.textContent).toContain('Der jetzige Stand wird vorher gesichert.')
    expect(dialog.textContent).toContain('Zu 2 Dokumenten fehlt eine Datei auf der Platte.')
    // Cancel: nothing was sent but the trial.
    await page.click(page.button('Abbrechen', dialog))
    expect(server.changes()).toEqual([`POST /api/v1/backups/${entry.name}/check`])
    await page.click(page.button('Wiederherstellen'))
    const again = page.dialog!
    await page.type(again.querySelector<HTMLInputElement>('input[type="password"]'), 'a made-up password')
    await page.click(page.button('Wiederherstellen', again))
    expect(server.called('POST', `/api/v1/backups/${entry.name}/restore`)?.body).toEqual({ password: 'a made-up password' })
  })

  it('opens no dialog for a backup that cannot be used', async () => {
    server.answers[`POST /api/v1/backups/${entry.name}/check`] = { ...brief, usable: false, too_new: true }
    await page.show(<BackupsCard server={{ settings, busy: false } as never} />)
    await page.click(page.button('Wiederherstellen'))
    expect(page.dialog).toBeNull()
    expect(page.text).toContain('neueren Version von nexpaper')
    expect(server.changes()).toEqual([`POST /api/v1/backups/${entry.name}/check`])
  })

  it('says the search index is not in the backup', async () => {
    await page.show(<BackupsCard server={{ settings, busy: false } as never} />)
    expect(page.text).toContain('Der Suchindex ist nicht dabei')
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
    expect(document.querySelector('[data-testid="file-notice"] a')?.getAttribute('href')).toBe('/einstellungen?tab=backups')
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
