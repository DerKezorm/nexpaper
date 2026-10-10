/** The day of a moment in the person's time zone, and the time zone of the browser. */

import { browserTimeZone, dayOfMoment } from './dates'

describe('the day of a moment', () => {
  it('is the day in the time zone asked for, not the one the moment was written in', () => {
    const late = '2026-10-06T23:30:00Z'
    expect(dayOfMoment(late, 'de', 'Europe/Berlin')).toBe('7. Oktober')
    expect(dayOfMoment(late, 'de', 'America/New_York')).toBe('6. Oktober')
    expect(dayOfMoment(late, 'en', 'Europe/Berlin')).toBe('October 7')
  })

  it('falls back to the browser when the time zone is not one', () => {
    expect(dayOfMoment('2026-10-06T12:00:00Z', 'de', 'Not/AZone')).toBe('6. Oktober')
    expect(dayOfMoment('2026-10-06T12:00:00Z', 'de')).toBe('6. Oktober')
  })
})

describe('the time zone of the browser', () => {
  it('is a name or empty, never a throw', () => {
    expect(typeof browserTimeZone()).toBe('string')
  })
})
