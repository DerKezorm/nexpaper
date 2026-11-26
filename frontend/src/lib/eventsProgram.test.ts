/**
 * MCP decision 15: a change made by an AI program names the person and the key ("Anna (MCP · Laptop)"); a change by
 * hand names the person alone.
 */
import i18n from '../i18n'
import type { DocumentEvent } from '../api/client'
import { changeLanguage } from '../i18n'
import { eventWho } from './events'

const plain = (text: string) => text.split(String.fromCharCode(0x2068)).join('').split(String.fromCharCode(0x2069)).join('')
const event = (mcp: string): DocumentEvent => ({
  id: 1, at: '2026-11-26T09:00:00Z', action: 'changed', by: { id: 2, name: 'anna', display_name: 'Anna' } as DocumentEvent['by'],
  by_link: '', detail: { fields: ['title'] }, mcp,
})

it('names the program beside the person, and the person alone for a change by hand', async () => {
  await changeLanguage('de', false)
  expect(plain(eventWho(event('Laptop'), i18n.t))).toBe('Anna (MCP · Laptop)')
  expect(plain(eventWho(event(''), i18n.t))).toBe('Anna')
})
