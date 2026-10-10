/**
 * Settings, Import against a stand-in of the server: the words of the mock, "connect and look" (it saves, then looks),
 * the owners with their proposed people and a changed choice, where it goes, the start with what was chosen, the run
 * with its progress, the skipped ones with their reasons, stopping and going on, the token never shown, and the
 * server's refusals in the words of the card.
 */
import type { PaperlessCheck, PaperlessRun, PaperlessSettings, PaperlessSkipped } from '../../api/client'
import { changeLanguage } from '../../i18n'
import { Page, Server } from '../../test/harness'
import { ImportCard } from './ImportCard'

const server = new Server()
const page = new Page()

function run(change: Partial<PaperlessRun> = {}): PaperlessRun {
  return { state: 'idle', total: 0, done: 0, taken: 0, skipped: 0, reasons: {}, error: '', stop: false, started_at: null, finished_at: null, ...change }
}

function skipped(numbers: number[], reason: string, more = 0): PaperlessSkipped {
  return { items: numbers.map((id) => ({ paperless_id: id, reason })), total: numbers.length + more, more }
}

function settings(change: Partial<PaperlessSettings> = {}): PaperlessSettings {
  return { url: '', token_set: false, private: false, where: 'owner', vault_id: null, run: run(), ...change }
}

const looked: PaperlessCheck = {
  version: '2.14.7', api_version: 7, documents: 1432, tags: 38, correspondents: 112, document_types: 14, custom_fields: 2,
  new_kinds: ['Nebenkostenabrechnung'],
  owners: [
    { paperless_id: 1, name: 'admin', documents: 1200, user_id: 1, matched: false },
    { paperless_id: 2, name: 'tom', documents: 200, user_id: 2, matched: true },
    { paperless_id: 3, name: 'scanner', documents: 32, user_id: 1, matched: false },
  ],
  users_hidden: false, already: 0, inbox_documents: 37,
  people: [{ id: 1, name: 'jule', display_name: 'Jule' }, { id: 2, name: 'tom', display_name: 'Tom' }, { id: 3, name: 'lea', display_name: 'Lea' }],
  vaults: [{ id: 7, name: 'Haushalt', own: false }, { id: 1, name: 'jule', own: true }],
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = {
    'GET /api/v1/settings/paperless': settings(),
    'PUT /api/v1/settings/paperless': settings({ url: 'http://paperless.example.com:8000/', token_set: true, private: true }),
    'POST /api/v1/settings/paperless/check': looked,
    'POST /api/v1/settings/paperless/start': settings({ token_set: true, run: run({ state: 'queued', total: 0 }) }),
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

function field(label: string): HTMLInputElement {
  const input = [...document.querySelectorAll<HTMLLabelElement>('label')].find((l) => l.textContent?.startsWith(label))?.querySelector('input')
  expect(input, label).toBeTruthy()
  return input!
}

async function connect() {
  await page.show(<ImportCard />)
  await page.type(field('Adresse von Paperless'), 'http://paperless.example.com:8000')
  await page.type(field('API-Token'), 'made-up-token')
  await page.click(document.querySelector<HTMLButtonElement>('button[role="switch"][aria-label="Paperless läuft im eigenen Netz"]'))
  await page.click(page.button('Verbinden und nachsehen'))
}

describe('Settings, Import', () => {
  it('starts with the words of the mock', async () => {
    await page.show(<ImportCard />)
    for (const words of [
      'Aus Paperless übernehmen',
      'Holt alles über die Schnittstelle von Paperless-ngx. Der erkannte Text kommt mit, es wird nichts neu gelesen. Paperless selbst bleibt unberührt.',
      'Adresse von Paperless', 'API-Token', 'In Paperless unter Profil, „API-Auth-Token“. Ein Token der Betreiberin sieht alles.',
      'Verbinden und nachsehen',
    ]) {
      expect(page.text, words).toContain(words)
    }
    expect(field('Adresse von Paperless').placeholder).toBe('http://paperless:8000')
    expect(page.button('Verbinden und nachsehen')!.disabled).toBe(true)
  })

  it('saves address, token and switch, then looks, and shows what Paperless holds', async () => {
    await connect()
    expect(server.called('PUT', '/api/v1/settings/paperless')!.body).toEqual({ url: 'http://paperless.example.com:8000', token: 'made-up-token', private: true })
    expect(server.called('POST', '/api/v1/settings/paperless/check')).toBeTruthy()
    for (const words of [
      '1.432', 'Dokumente', '38', 'Tags', '112', 'Korrespondenten', '14', 'Dokumenttypen', 'So wird übersetzt',
      'Korrespondent → Absender, Dokumenttyp → Art (unbekannte werden neue Arten), Tags → Tags',
      'Notizen → Notizen, eigene Felder → eine Notiz mit allen Werten',
      'Speicherpfade und Arbeitsabläufe → gibt es hier nicht, werden übersprungen', 'Neue Arten: Nebenkostenabrechnung',
      'Besitzer in Paperless → Person hier', 'admin', 'scanner', 'Wohin', 'Je Besitzer in dessen Tresor', 'Alles nach Haushalt',
      'Danach lässt sich alles verschieben. Was in Paperless mit anderen geteilt war, wird hier mit denselben Personen geteilt.',
      '1.432 Dokumente übernehmen', 'Zurück',
    ]) {
      expect(page.text, words).toContain(words)
    }
    expect(page.select('Person für admin')!.value).toBe('1')
    expect(page.select('Person für tom')!.value).toBe('2')
    // The token is gone from the page once it was sent.
    expect(document.body.innerHTML).not.toContain('made-up-token')
  })

  it('starts with the people and the place chosen', async () => {
    await connect()
    await page.choose(page.select('Person für scanner'), '3')
    await page.click([...document.querySelectorAll<HTMLButtonElement>('button[role="radio"]')].find((b) => b.textContent === 'Alles nach Haushalt'))
    await page.click(page.button('1.432 Dokumente übernehmen'))
    expect(server.called('POST', '/api/v1/settings/paperless/start')!.body).toEqual({
      where: 'vault', vault_id: 7, sort: 'paperless',
      people: [{ paperless_id: 1, user_id: 1 }, { paperless_id: 2, user_id: 2 }, { paperless_id: 3, user_id: 3 }],
    })
    expect(page.text).toContain('Startet gleich.')
    expect(page.text).toContain('Anhalten')
  })

  it('asks how to sort, with how many Paperless has in its inbox, and starts with the answer', async () => {
    await connect()
    expect(page.text).toContain('Einsortieren')
    expect(page.text).toContain('37 von 1.432 Dokumenten liegen in Paperless im Posteingang und warten hier im Eingang. Die anderen 1.395 werden gleich abgelegt.')
    await page.click([...document.querySelectorAll<HTMLButtonElement>('button[role="radio"]')].find((b) => b.textContent === 'Alles in den Eingang'))
    expect(page.text).toContain('Alle 1.432 Dokumente warten im Eingang, und du legst sie selbst ab.')
    await page.click(page.button('1.432 Dokumente übernehmen'))
    expect(server.called('POST', '/api/v1/settings/paperless/start')!.body).toMatchObject({ where: 'owner', sort: 'inbox' })
  })

  it('shows the run and what was skipped with its reason', async () => {
    server.answers['GET /api/v1/settings/paperless'] = settings({ token_set: true, run: run({ state: 'running', total: 1432, done: 400 }) })
    await page.show(<ImportCard />)
    expect(page.text).toContain('Läuft. 400 von 1.432 übernommen. Du kannst die Seite schließen; es läuft im Hintergrund weiter und lässt sich jederzeit fortsetzen.')
    expect(document.querySelector('[role="progressbar"]')!.getAttribute('aria-valuenow')).toBe('28')
    page.close()
    server.answers['GET /api/v1/settings/paperless'] = settings({ token_set: true, run: run({ state: 'done', total: 1432, done: 1429, taken: 1429, skipped: 3, reasons: { file_missing: 3 } }) })
    server.answers['GET /api/v1/settings/paperless/skipped'] = skipped([67, 70, 71], 'file_missing')
    await page.show(<ImportCard />)
    expect(page.text).toContain('Fertig. 1.429 übernommen, 3 übersprungen.')
    expect(page.text).toContain('Nochmal laufen lassen holt nur, was seitdem in Paperless dazugekommen ist.')
    await page.click(page.button('Nochmal laufen lassen'))
    expect(page.text).toContain('Verbinden und nachsehen')
  })

  it('fills the bar when it is done and sets the skipped part apart', async () => {
    server.answers['GET /api/v1/settings/paperless'] = settings({ token_set: true, run: run({ state: 'done', total: 92, done: 86, taken: 86, skipped: 6, reasons: { file_missing: 6 } }) })
    server.answers['GET /api/v1/settings/paperless/skipped'] = skipped([67, 70, 71, 72, 73, 76], 'file_missing')
    await page.show(<ImportCard />)
    expect(page.text).toContain('Fertig. 86 übernommen, 6 übersprungen.')
    const bar = document.querySelector('[role="progressbar"]')!
    expect(bar.getAttribute('aria-valuenow')).toBe('100')
    const [taken, apart] = [...bar.children] as HTMLElement[]
    expect(Number.parseFloat(taken.style.width) + Number.parseFloat(apart.style.width)).toBeCloseTo(100, 5)
    expect(Number.parseFloat(apart.style.width)).toBeCloseTo((6 / 92) * 100, 5)
    expect(apart.className).not.toBe(taken.className)
    // Without a skipped one the whole bar is the taken part.
    page.close()
    server.answers['GET /api/v1/settings/paperless'] = settings({ token_set: true, run: run({ state: 'done', total: 92, done: 92, taken: 92 }) })
    await page.show(<ImportCard />)
    expect(document.querySelectorAll('[role="progressbar"] > div')).toHaveLength(1)
    expect((document.querySelector('[role="progressbar"] > div') as HTMLElement).style.width).toBe('100%')
  })

  it('lists the skipped ones with their number and the reason in plain words, and what is more', async () => {
    server.answers['GET /api/v1/settings/paperless'] = settings({ token_set: true, run: run({ state: 'done', total: 120, done: 60, taken: 60, skipped: 60 }) })
    server.answers['GET /api/v1/settings/paperless/skipped'] = { ...skipped([67, 70], 'file_missing', 58), items: [{ paperless_id: 67, reason: 'file_missing' }, { paperless_id: 70, reason: 'too_large' }, { paperless_id: 71, reason: 'something_new' }] }
    await page.show(<ImportCard />)
    expect(page.text).toContain('Übersprungene Dokumente')
    expect(page.text).toContain('Paperless-Nummer 67: Die Datei fehlt in Paperless, und eine ganze durchsuchbare Fassung gibt es dort auch nicht.')
    expect(page.text).toContain('Paperless-Nummer 70: Die Datei ist größer, als nexpaper annimmt.')
    // A reason the card does not know is not shown as a code.
    expect(page.text).toContain('Paperless-Nummer 71: Aus einem Grund, der im Log steht.')
    expect(page.text).not.toContain('something_new')
    expect(page.text).toContain('und 58 weitere')
    expect(server.called('GET', '/api/v1/settings/paperless/skipped')).toBeTruthy()
  })

  it('asks for no list while the run goes on or when nothing was skipped', async () => {
    server.answers['GET /api/v1/settings/paperless'] = settings({ token_set: true, run: run({ state: 'running', total: 92, done: 40, skipped: 2 }) })
    await page.show(<ImportCard />)
    expect(server.called('GET', '/api/v1/settings/paperless/skipped')).toBeUndefined()
    page.close()
    server.answers['GET /api/v1/settings/paperless'] = settings({ token_set: true, run: run({ state: 'done', total: 92, done: 92, taken: 92 }) })
    await page.show(<ImportCard />)
    expect(server.called('GET', '/api/v1/settings/paperless/skipped')).toBeUndefined()
    expect(page.text).not.toContain('Übersprungene Dokumente')
  })

  it('stops, and goes on with what was chosen', async () => {
    server.answers['GET /api/v1/settings/paperless'] = settings({ token_set: true, run: run({ state: 'running', total: 10, done: 2 }) })
    server.answers['POST /api/v1/settings/paperless/stop'] = settings({ token_set: true, run: run({ state: 'paused', total: 10, done: 3 }) })
    await page.show(<ImportCard />)
    await page.click(page.button('Anhalten'))
    expect(page.text).toContain('Angehalten. 3 von 10 übernommen. Fortsetzen holt den Rest.')
    await page.click(page.button('Fortsetzen'))
    expect(server.called('POST', '/api/v1/settings/paperless/start')!.body).toEqual({ resume: true })
  })

  it('says why a run broke off', async () => {
    server.answers['GET /api/v1/settings/paperless'] = settings({ token_set: true, run: run({ state: 'failed', total: 10, done: 4, error: 'paperless_unreachable' }) })
    await page.show(<ImportCard />)
    expect(page.text).toContain('Abgebrochen: nexpaper erreicht Paperless nicht. 4 von 10 übernommen. Fortsetzen macht dort weiter.')
  })

  it('says the refusals in its own words', async () => {
    server.fails['POST /api/v1/settings/paperless/check'] = { status: 422, code: 'paperless_address_private' }
    await connect()
    expect(page.text).toContain('Diese Adresse liegt im eigenen Netz. Setze dafür den Haken „Paperless läuft im eigenen Netz“.')
    expect(page.text).toContain('Verbinden und nachsehen')
  })

  it('keeps a stored token without showing it, and removes the connection', async () => {
    server.answers['GET /api/v1/settings/paperless'] = settings({ url: 'http://paperless.example.com:8000/', token_set: true })
    server.answers['DELETE /api/v1/settings/paperless'] = settings()
    await page.show(<ImportCard />)
    expect(page.text).toContain('Ein Token ist gespeichert. Leer lassen, um es zu behalten.')
    expect(field('API-Token').value).toBe('')
    expect(page.button('Verbinden und nachsehen')!.disabled).toBe(false)
    await page.click(page.button('Verbindung entfernen'))
    expect(server.called('DELETE', '/api/v1/settings/paperless')).toBeUndefined()
    await page.inDialog('Abbrechen')
    expect(server.called('DELETE', '/api/v1/settings/paperless')).toBeUndefined()
    await page.click(page.button('Verbindung entfernen'))
    await page.inDialog('Verbindung vergessen')
    expect(server.called('DELETE', '/api/v1/settings/paperless')).toBeTruthy()
    expect(field('Adresse von Paperless').value).toBe('')
  })

  it('names owners it cannot name', async () => {
    server.answers['POST /api/v1/settings/paperless/check'] = { ...looked, users_hidden: true, already: 400, owners: [{ paperless_id: null, name: '', documents: 3, user_id: 1, matched: false }, { paperless_id: 9, name: '', documents: 5, user_id: 1, matched: false }] }
    await connect()
    expect(page.text).toContain('ohne Besitzer')
    expect(page.text).toContain('Konto 9')
    expect(page.text).toContain('Das Token darf die Konten von Paperless nicht auflisten.')
    expect(page.text).toContain('400 davon sind schon hier und werden nicht noch einmal geholt.')
    expect(page.text).toContain('1.032 Dokumente übernehmen')
  })

  it('marks owners without a person of their name, and says where the documents go', async () => {
    await connect()
    expect(page.text).toContain('kein Konto gleichen Namens, geht an Jule')
    expect(page.text.match(/kein Konto gleichen Namens/g)).toHaveLength(2)
    expect(page.text).toContain('Die Dokumente kommen in die persönlichen Tresore der zugeordneten Personen; jede sieht sie dort.')
    await page.choose(page.select('Person für scanner'), '3')
    expect(page.text).toContain('kein Konto gleichen Namens, geht an Lea')
    await page.click([...document.querySelectorAll<HTMLButtonElement>('button[role="radio"]')].find((b) => b.textContent === 'Alles nach Haushalt'))
    expect(page.text).toContain('Wer nicht Mitglied dieses Tresors ist, wird nicht Besitzer')
  })

  it('offers nothing to take over when everything is here already', async () => {
    server.answers['POST /api/v1/settings/paperless/check'] = { ...looked, already: 1432 }
    await connect()
    expect(page.button('0 Dokumente übernehmen')!.disabled).toBe(true)
  })

  it('keeps a stored token when the field stays empty, and asks for it again for a new address', async () => {
    server.answers['GET /api/v1/settings/paperless'] = settings({ url: 'http://paperless.example.com:8000/', token_set: true })
    await page.show(<ImportCard />)
    await page.click(page.button('Verbinden und nachsehen'))
    expect(server.called('PUT', '/api/v1/settings/paperless')!.body).toEqual({ url: 'http://paperless.example.com:8000/', private: false })
    page.close()
    await page.show(<ImportCard />)
    await page.type(field('Adresse von Paperless'), 'http://paperless.example.com:8010/')
    expect(page.text).not.toContain('Ein Token ist gespeichert.')
    expect(page.text).toContain('In Paperless unter Profil')
    expect(page.button('Verbinden und nachsehen')!.disabled).toBe(true)
  })

  it('says a redirect, a certificate and a changed address in plain words', async () => {
    for (const [code, words] of [
      ['paperless_redirected', 'Paperless leitet auf eine andere Adresse um, etwa von http auf https.'],
      ['paperless_tls_failed', 'Das Zertifikat von Paperless wird nicht anerkannt'],
    ]) {
      server.fails['POST /api/v1/settings/paperless/check'] = { status: 502, code }
      await connect()
      expect(page.text).toContain(words)
      page.close()
    }
    server.fails = {}
    server.answers['GET /api/v1/settings/paperless'] = settings({ token_set: true, run: run({ state: 'paused', total: 10, done: 3 }) })
    server.fails['POST /api/v1/settings/paperless/start'] = { status: 409, code: 'paperless_address_changed' }
    await page.show(<ImportCard />)
    await page.click(page.button('Fortsetzen'))
    expect(page.text).toContain('Die Adresse von Paperless hat sich seit dem letzten Start geändert.')
  })

  it('speaks English', async () => {
    await changeLanguage('en', false)
    await page.show(<ImportCard />)
    expect(page.text).toContain('Take over from Paperless')
    expect(page.text).toContain('Connect and look')
  })
})
