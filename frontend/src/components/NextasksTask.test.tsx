/**
 * "Aufgabe in nextasks" on a document's page (Bauplan V19, a draft): the button stands only while the connection with
 * nextasks holds; the window chooses the list used last first, makes the task with one request, says when the
 * document had one already, and names a refusal in words.
 */
import { changeLanguage } from '../i18n'
import { Page, Server } from '../test/harness'
import { NextasksTaskButton } from './NextasksTask'

const server = new Server()
const page = new Page()

const LISTS = {
  lists: [
    { id: 'list-home', name: 'Haushalt', space_name: 'Zuhause' },
    { id: 'list-garden', name: 'Garten', space_name: 'Zuhause' },
  ],
  last_list_id: 'list-garden',
}

beforeEach(async () => {
  await changeLanguage('de', false)
  server.answers = {
    'GET /api/v1/nextasks': { usable: true },
    'GET /api/v1/nextasks/lists': LISTS,
    'POST /api/v1/documents/7/nextasks': { task_id: 'task-1', title: 'Stromrechnung', link: 'https://tasks.example.com/task/1', created: true },
  }
  server.fails = {}
  server.install()
})
afterEach(() => {
  page.close()
  vi.unstubAllGlobals()
})

describe('a task in nextasks', () => {
  it('has no button while no connection holds', async () => {
    server.answers['GET /api/v1/nextasks'] = { usable: false }
    await page.show(<NextasksTaskButton documentId={7} />)
    expect(page.button('Aufgabe in nextasks')).toBeUndefined()
  })

  it('has no button when the server cannot say', async () => {
    server.fails['GET /api/v1/nextasks'] = { status: 403, code: 'browser_only' }
    await page.show(<NextasksTaskButton documentId={7} />)
    expect(page.button('Aufgabe in nextasks')).toBeUndefined()
  })

  it('makes the task in the list used last, with one request', async () => {
    await page.show(<NextasksTaskButton documentId={7} />)
    await page.click(page.button('Aufgabe in nextasks'))
    const select = page.select('Liste in nextasks')
    expect(select?.value).toBe('list-garden')
    expect(page.text).toContain('Zuhause · Haushalt')
    await page.inDialog('Aufgabe anlegen')
    expect(server.changes()).toEqual(['POST /api/v1/documents/7/nextasks'])
    expect(server.called('POST', '/api/v1/documents/7/nextasks')?.body).toEqual({ list_id: 'list-garden' })
    expect(page.text).toContain('Die Aufgabe steht jetzt in nextasks.')
    expect(page.dialog?.querySelector('a')?.getAttribute('href')).toBe('https://tasks.example.com/task/1')
  })

  it('says when the document has its task already', async () => {
    server.answers['POST /api/v1/documents/7/nextasks'] = { task_id: 'task-1', title: 'Stromrechnung', link: null, created: false }
    await page.show(<NextasksTaskButton documentId={7} />)
    await page.click(page.button('Aufgabe in nextasks'))
    await page.choose(page.select('Liste in nextasks'), 'list-home')
    await page.inDialog('Aufgabe anlegen')
    expect(server.called('POST', '/api/v1/documents/7/nextasks')?.body).toEqual({ list_id: 'list-home' })
    expect(page.text).toContain('Für dieses Dokument gibt es in nextasks schon eine Aufgabe.')
    expect(page.dialog?.querySelector('a')).toBeNull()
  })

  it('names nextasks away in words and keeps the window', async () => {
    server.fails['POST /api/v1/documents/7/nextasks'] = { status: 502, code: 'nextasks_unreachable' }
    await page.show(<NextasksTaskButton documentId={7} />)
    await page.click(page.button('Aufgabe in nextasks'))
    await page.inDialog('Aufgabe anlegen')
    expect(page.text).toContain('nextasks ist gerade nicht erreichbar.')
    expect(page.button('Aufgabe anlegen', page.dialog!)).toBeTruthy()
  })

  it('names a connection that no longer holds when the lists are asked for', async () => {
    server.fails['GET /api/v1/nextasks/lists'] = { status: 409, code: 'nextasks_disconnected' }
    await page.show(<NextasksTaskButton documentId={7} />)
    await page.click(page.button('Aufgabe in nextasks'))
    expect(page.text).toContain('Die Verbindung mit nextasks trägt nicht mehr.')
    expect(page.button('Aufgabe anlegen', page.dialog!)).toBeUndefined()
  })
})
