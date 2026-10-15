/** The calendar of the deadlines, worked out in the browser while a contract's terms are typed (the server does the same,
 * `services/deadlines.py`, `test_deadlines.py`). */
import { addDays, addMonths, daysBetween, lastToCancel, relative, whatOfKind } from './deadlines'
import { datesChanged } from './inbox'

describe('the last day to cancel', () => {
  it.each([
    ['2026-12-31', 3, 'months', '2026-09-30'],
    ['2027-05-31', 3, 'months', '2027-02-28'],
    ['2028-05-31', 3, 'months', '2028-02-29'],
    ['2026-06-30', 3, 'months', '2026-03-31'],
    ['2026-03-15', 1, 'months', '2026-02-15'],
    ['2026-01-15', 2, 'months', '2025-11-15'],
    ['2026-11-15', 4, 'weeks', '2026-10-18'],
    ['2026-01-05', 1, 'weeks', '2025-12-29'],
  ] as const)('of a contract until %s with %i %s notice is %s', (end, n, unit, last) => {
    expect(lastToCancel(end, { n, unit })).toBe(last)
  })

  it('keeps the last day of a month when it moves ahead', () => {
    expect(addMonths('2026-02-28', 1)).toBe('2026-03-31')
    expect(addMonths('2026-01-30', 1)).toBe('2026-02-28')
    expect(addMonths('2027-12-31', 12)).toBe('2028-12-31')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
  })
})

describe('how far away a day is', () => {
  it('counts days and says them as the mock does', () => {
    expect(daysBetween('2026-10-08', '2026-10-05')).toBe(-3)
    expect(relative(0)).toEqual({ key: 'today', count: 0 })
    expect(relative(1)).toEqual({ key: 'tomorrow', count: 1 })
    expect(relative(-1)).toEqual({ key: 'sinceYesterday', count: 1 })
    expect(relative(-3)).toEqual({ key: 'since', count: 3 })
    expect(relative(23)).toEqual({ key: 'inDays', count: 23 })
    expect(relative(45)).toEqual({ key: 'inDays', count: 45 })
    expect(relative(60)).toEqual({ key: 'inMonths', count: 2 })
    expect(relative(84)).toEqual({ key: 'inMonths', count: 3 })
  })

  it('names what a done date was: paid, cancelled, done', () => {
    expect(['due', 'contract_end', 'warranty_end'].map(whatOfKind)).toEqual(['pay', 'cancel', 'warranty'])
  })
})

describe('what a page sends of the terms', () => {
  const contract = { kind: 'contract_end' as const, date: '2026-10-07', notice: { n: 3, unit: 'months' as const }, renew_months: 12 }

  it('sends only what changed, so a page that is behind never sends back the old end', () => {
    expect(datesChanged([contract], [{ ...contract, notice: { n: 6, unit: 'weeks' } }])).toEqual({ set_dates: [{ kind: 'contract_end', notice: { n: 6, unit: 'weeks' } }] })
    expect(datesChanged([contract], [{ ...contract, renew_months: null }])).toEqual({ set_dates: [{ kind: 'contract_end', renew_months: null }] })
    expect(datesChanged([contract], [{ ...contract, date: '2027-01-31' }])).toEqual({ set_dates: [{ kind: 'contract_end', date: '2027-01-31' }] })
  })

  it('sends a new term whole, a removed one by its kind, and nothing when nothing changed', () => {
    const due = { kind: 'due' as const, date: '2026-10-20' }
    expect(datesChanged([contract], [contract, due])).toEqual({ set_dates: [due] })
    expect(datesChanged([contract, due], [due])).toEqual({ remove_dates: ['contract_end'] })
    expect(datesChanged([contract, due], [contract, due])).toEqual({})
  })

  it('says whether a keeping time was set by hand, with or without a new day', () => {
    const worked = { kind: 'keep_until' as const, date: '2036-12-31', manual: false }
    // Another day is by hand; the same day taken over by hand sends only the mark; the kind's own day sends nothing.
    expect(datesChanged([worked], [{ kind: 'keep_until', date: '2040-06-30', manual: true }])).toEqual({ set_dates: [{ kind: 'keep_until', date: '2040-06-30', manual: true }] })
    expect(datesChanged([worked], [{ ...worked, manual: true }])).toEqual({ set_dates: [{ kind: 'keep_until', manual: true }] })
    expect(datesChanged([worked], [worked])).toEqual({})
    // Given back to the kind: the term leaves the list, and the kind works it out again.
    expect(datesChanged([{ ...worked, manual: true }], [])).toEqual({ remove_dates: ['keep_until'] })
  })
})
