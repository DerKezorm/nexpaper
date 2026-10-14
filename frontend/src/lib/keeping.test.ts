/** The sum of a keeping time, as the server does it (`services/keeping.py`), and where a stored one came from. */
import { baseYear, keepUntil, keptOf } from './keeping'

describe('keeping', () => {
  it('counts from the end of the year of the date, else of the day it came in', () => {
    expect(keepUntil(baseYear('2026-03-14', '2026-10-01T10:00:00Z'), 10)).toBe('2036-12-31')
    expect(keepUntil(baseYear(null, '2025-07-01T10:00:00Z'), 6)).toBe('2031-12-31')
    expect(keepUntil(2026, 1)).toBe('2027-12-31')
  })

  it('reads where a stored date came from', () => {
    const doc = (manual?: boolean) => ({ date: '2026-03-14', added_at: '2026-10-01T10:00:00Z', dates: [{ kind: 'keep_until', date: '2036-12-31', ...(manual === undefined ? {} : { manual }) }] })
    expect(keptOf(doc(false))).toEqual({ date: '2036-12-31', from: 'kind', years: 10 })
    expect(keptOf(doc(true))).toEqual({ date: '2036-12-31', from: 'hand' })
    expect(keptOf(doc())).toEqual({ date: '2036-12-31', from: 'hand' })
    expect(keptOf({ date: null, added_at: '2026-10-01T10:00:00Z', dates: [] })).toBeNull()
  })
})
