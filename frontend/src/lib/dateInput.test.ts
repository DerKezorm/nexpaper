import { ApiError } from '../api/client'
import { expandYear, problemOf, refusedOf, refusedValue, shownAtField, yearOf } from './dateInput'

describe('a year under 100 is read as 20xx', () => {
  it.each([
    ['0027-02-28', '2027-02-28'],
    ['27-02-28', '2027-02-28'],
    ['0000-01-05', '2000-01-05'],
    ['0099-12-31', '2099-12-31'],
    ['0100-01-01', '0100-01-01'],
    ['1999-05-05', '1999-05-05'],
    ['2026-10-06', '2026-10-06'],
    ['', ''],
    ['not a day', 'not a day'],
  ])('%s becomes %s', (typed, read) => expect(expandYear(typed)).toBe(read))

  it('names the year as it was typed', () => {
    expect(yearOf('0027-02-28')).toEqual({ text: '0027', number: 27 })
    expect(yearOf('27-02-28')).toEqual({ text: '0027', number: 27 })
    expect(yearOf('')).toBeNull()
  })
})

describe('a refused date', () => {
  const sent = { date: '0027-02-28', dates: [{ date: '2026-10-20' }, { date: '0027-03-01' }] }
  it('keeps the field and the value that was sent', () => {
    const date = problemOf(new ApiError(422, 'invalid_date', { field: 'date' }), sent)
    expect(date).toEqual({ code: 'invalid_date', values: { field: 'date', value: '0027-02-28' } })
    const term = problemOf(new ApiError(422, 'invalid_date', { field: 'dates[1]' }), sent)
    expect(refusedOf(term)).toEqual({ field: 'dates[1]', value: '0027-03-01' })
    expect(refusedValue(term, 'dates[1]')).toBe('0027-03-01')
    expect(refusedValue(term, 'dates[0]')).toBeUndefined()
    expect(refusedValue(term, 'date')).toBeUndefined()
    expect(shownAtField(term)).toBe(true)
  })

  it('is shown below, as before, when no field is named or other things went wrong', () => {
    const plain = problemOf(new ApiError(422, 'invalid_date'), sent)
    expect(shownAtField(plain)).toBe(false)
    expect(shownAtField(problemOf(new ApiError(409, 'in_trash'), sent))).toBe(false)
    expect(problemOf(new Error('x'))).toEqual({ code: 'internal_error', values: {} })
    expect(refusedOf(null)).toBeNull()
  })
})
