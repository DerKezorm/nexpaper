/**
 * The small parts of the pages with documents: amounts as people type them, the span of time of the archive, the marks
 * of a search (ranges in UTF-16 units, never HTML), and the history in words for every action the server records.
 */
import type { TFunction } from 'i18next'
import { renderToStaticMarkup } from 'react-dom/server'

import type { DocumentEvent } from '../api/client'
import { Marked } from '../components/docs'
import i18n, { changeLanguage } from '../i18n'
import { filtersOf, spanDates } from './archive'
import { eventWhat, eventWho, standsAlone } from './events'
import { plain } from '../test/harness'
import { amountText, money, parseAmount } from './money'

beforeEach(async () => {
  await changeLanguage('de', false)
})

describe('amounts', () => {
  it('are taken with a comma or a point, thousands too', () => {
    expect(parseAmount('86,40')).toBe(8640)
    expect(parseAmount('86.40')).toBe(8640)
    expect(parseAmount('1.234,56')).toBe(123456)
    expect(parseAmount('1,234.56')).toBe(123456)
    expect(parseAmount('1.234')).toBe(123400)
    expect(parseAmount('12,5')).toBe(1250)
    expect(parseAmount('612')).toBe(61200)
    expect(parseAmount(' 224,91 € ')).toBe(22491)
    expect(parseAmount('-5,00')).toBe(-500)
    expect(parseAmount('')).toBeNull()
  })

  it('refuse what is no amount', () => {
    for (const wrong of ['abc', '1,2,3,4x', '12,3456', '1.2.3,45,6', ',', '9'.repeat(20)]) expect(parseAmount(wrong), wrong).toBe('invalid')
  })

  it('are shown in the way of the language', () => {
    expect(money(128417, 'de')).toBe('1.284,17 €')
    expect(money(8640, 'en')).toBe('€86.40')
    expect(money(null, 'de')).toBe('')
    expect(amountText(22491, 'de')).toBe('224,91')
    expect(amountText(22491, 'en')).toBe('224.91')
  })
})

describe('the span of time of the archive', () => {
  const now = new Date(2026, 9, 10)
  it('becomes dates for the server', () => {
    expect(spanDates('year', now)).toEqual({ date_from: '2026-01-01', date_to: '2026-12-31' })
    expect(spanDates('lastyear', now)).toEqual({ date_from: '2025-01-01', date_to: '2025-12-31' })
    expect(spanDates('12m', now)).toEqual({ date_from: '2025-10-10' })
    expect(spanDates('', now)).toEqual({})
  })

  it('and the chips become filters of what was filed', () => {
    expect(filtersOf({ vault: '7', kind: '3', sender: 'Stadtwerke', tag: 'strom', owner: '2', span: 'year' }, now)).toEqual({
      status: 'filed', vault_id: 7, kind_id: 3, sender: 'Stadtwerke', tag: 'strom', owner_id: 2, date_from: '2026-01-01', date_to: '2026-12-31',
    })
    expect(filtersOf({ vault: 'shared', kind: 'x', sender: '', tag: '', owner: '', span: '' }, now)).toEqual({ status: 'filed', via_share: true })
  })
})

describe('the marks of a search', () => {
  const html = (text: string, marks: [number, number][]) => renderToStaticMarkup(<Marked text={text} marks={marks} />)
  it('mark the ranges the server named, counted in UTF-16 units', () => {
    expect(html('Stadtwerke Lindenau', [[5, 10]])).toBe('<bdi>Stadt<mark>werke</mark> Lindenau</bdi>')
    // An emoji takes two units: the range after it still lands on the word.
    expect(html('🧾 Rechnung', [[3, 11]])).toBe('<bdi>🧾 <mark>Rechnung</mark></bdi>')
  })

  it('never let a text become markup, and cut ranges that overlap or run past the end', () => {
    expect(html('<b>x</b> Strom', [[9, 14]])).toBe('<bdi>&lt;b&gt;x&lt;/b&gt; <mark>Strom</mark></bdi>')
    expect(html('a <img src=x onerror=alert(1)>', [[2, 31]])).toBe('<bdi>a <mark>&lt;img src=x onerror=alert(1)&gt;</mark></bdi>')
    expect(html('abcdef', [[0, 3], [2, 5], [4, 99], [7, 2]])).toBe('<bdi><mark>abc</mark><mark>de</mark><mark>f</mark></bdi>')
  })
})

describe('the history in words', () => {
  const t = i18n.t.bind(i18n) as TFunction
  const context = {
    people: new Map([[3, { id: 3, name: 'lea', display_name: 'Lea' }]]),
    vaults: new Map([[9, 'Haushalt']]),
    sourceText: (source: string) => (source === 'mail' ? 'Aus dem Postfach' : 'Hochgeladen im Browser'),
  }
  const line = (action: string, detail: Record<string, unknown> | null = null, by = true, by_link = '') => {
    const event: DocumentEvent = { id: 1, at: '2026-10-01T08:00:00Z', action, by: by ? { id: 1, name: 'jule', display_name: 'Jule' } : null, by_link, detail }
    return plain(standsAlone(event) ? eventWhat(event, t, context) : `${eventWho(event, t)} ${eventWhat(event, t, context)}`)
  }

  it('say what the page tools did', () => {
    expect([
      line('pages_edited', { version: 2, from: 1, pages: 3 }),
      line('merged', { version: 3, from: [8, 9], pages: 5 }),
      line('merged_into', { into: 7 }),
      line('split', { into: [10, 11, 12], parts: 3, dropped: 2 }),
      line('split_kept', { version: 1 }),
      line('version_uploaded', { version: 4 }),
      line('version_added', { version: 4, pages: 2 }, false),
      line('version_failed', { version: 4, error: 'encrypted' }, false),
      line('version_restored', { version: 5, from: 1 }),
      line('version_discarded', { version: 4 }),
      line('created', { source: 'folder', split_from: 6 }),
      line('created', { source: 'paperless', from_archive: 'docx' }),
      line('created', { source: 'paperless', from_archive: 'other' }),
      line('created', { source: 'paperless', original_missing: true }),
    ]).toEqual([
      'Jule hat die Seiten bearbeitet (Fassung 2)',
      'Jule hat 2 Dokumente angefügt (Fassung 3)',
      'Jule hat es an ein anderes Dokument angefügt',
      'Jule hat es in 3 Dokumente aufgeteilt',
      'Jule hat es als ein Dokument behalten',
      'Jule hat Fassung 4 hochgeladen',
      'nexpaper hat Fassung 4 gelesen, sie ist jetzt die aktuelle',
      'nexpaper konnte Fassung 4 nicht lesen',
      'Jule hat Fassung 1 als Fassung 5 wiederhergestellt',
      'Jule hat Fassung 4 verworfen',
      'Jule hat es aus einem Stapel aufgeteilt',
      'Jule hat es angelegt: aus Paperless übernommen, als das PDF, das Paperless aus der Datei (.docx) gemacht hat. Diese Dateiart nimmt nexpaper selbst nicht an.',
      'Jule hat es angelegt: aus Paperless übernommen, als das PDF, das Paperless aus der Datei (andere Dateiart) gemacht hat. Diese Dateiart nimmt nexpaper selbst nicht an.',
      'Jule hat es angelegt: aus Paperless übernommen, die Originaldatei fehlte dort, übernommen ist die durchsuchbare Fassung',
    ])
  })

  it('say every action the server records, never its code', () => {
    const lines = [
      line('created', { source: 'mail' }),
      line('changed', { fields: ['title', 'amount'] }),
      line('changed', { fields: ['status'], status: 'filed' }),
      line('changed', { fields: ['status', 'sender'], status: 'inbox' }),
      line('changed', { fields: ['sender'], by: 'catalog' }),
      line('moved', { from: 9, to: 12 }),
      line('taken_over', { from: 2, to: 9, account: 'tom' }),
      line('shared', { to: 3, right: 'read' }),
      line('share_changed', { to: 3, right: 'edit' }),
      line('unshared', { to: 3 }),
      line('link_created', { days: 14 }),
      line('link_opened', null, false, 'Steuerbüro'),
      line('link_revoked'),
      line('link_revoked', { reason: 'account_deleted' }),
      line('link_copied', { link: 4 }),
      line('trashed'),
      line('restored'),
      line('note_added', { note: 1 }),
      line('note_changed', { note: 1 }),
      line('note_deleted', { note: 1 }),
      line('processed', { pages: 3, text_pages: 3, ocr_pages: 2 }, false),
      line('processed', { pages: 1, error: 'ocr_failed' }, false),
      line('process_failed', { error: 'encrypted' }, false),
      line('retried'),
      line('text_read', { text_pages: 1, ocr_pages: 0 }, false),
      line('pages_rotated'),
    ]
    expect(lines).toEqual([
      'Jule hat es angelegt: aus dem Postfach',
      'Jule hat den Titel und den Betrag geändert',
      'Jule hat es abgelegt',
      'Jule hat es in den Eingang zurückgelegt und den Absender geändert',
      'Jule hat den Absender in der Liste geändert, für alle Dokumente damit',
      'Jule hat es von Haushalt nach einem anderen Tresor verschoben',
      'Übernommen beim Löschen des Kontos tom',
      'Jule hat es mit Lea geteilt (Lesen)',
      'Jule hat das Recht von Lea auf Bearbeiten gesetzt',
      'Jule teilt es nicht mehr mit Lea',
      'Jule hat einen Link für 14 Tage angelegt',
      'Jemand über den Link für „Steuerbüro“ hat es geöffnet',
      'Jule hat einen Link zurückgezogen',
      'Ein Link endete, weil das Konto, das ihn angelegt hatte, gelöscht wurde',
      'Jule hat die Adresse eines Links kopiert',
      'Jule hat es in den Papierkorb gelegt',
      'Jule hat es aus dem Papierkorb zurückgeholt',
      'Jule hat eine Notiz geschrieben',
      'Jule hat eine Notiz geändert',
      'Jule hat eine Notiz gelöscht',
      'nexpaper hat es gelesen: 3 Seiten. Auf 2 Seiten wurde der Text erkannt.',
      'nexpaper hat es gelesen: eine Seite. Der Text ließ sich nicht erkennen.',
      'nexpaper konnte es nicht lesen: Das PDF ist mit einem Passwort geschützt',
      'Jule hat es noch einmal lesen lassen',
      'nexpaper hat den Text gelesen',
      'Jule hat etwas geändert',
    ])
  })
})
