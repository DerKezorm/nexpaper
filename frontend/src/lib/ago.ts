/**
 * "gerade eben", "vor 2 Stunden", "gestern", "vor 5 Tagen": how long ago a moment was, in the language of the page.
 * `now` comes in from outside so that a test sets the clock.
 */

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

export function ago(moment: string, language: string, justNow: string, now: number = Date.now()): string {
  const passed = now - new Date(moment).getTime()
  if (!Number.isFinite(passed) || passed < MINUTE) return justNow
  const say = new Intl.RelativeTimeFormat(language, { numeric: 'auto' })
  if (passed < HOUR) return say.format(-Math.floor(passed / MINUTE), 'minute')
  if (passed < DAY) return say.format(-Math.floor(passed / HOUR), 'hour')
  return say.format(-Math.floor(passed / DAY), 'day')
}

/** "heute", "gestern", "vor 3 Tagen": the day of a moment, counted in whole days. */
export function daysAgo(moment: string, language: string, now: number = Date.now()): string {
  const start = (time: number) => {
    const day = new Date(time)
    return new Date(day.getFullYear(), day.getMonth(), day.getDate()).getTime()
  }
  const days = Math.round((start(now) - start(new Date(moment).getTime())) / DAY)
  return new Intl.RelativeTimeFormat(language, { numeric: 'auto' }).format(-Math.max(0, days), 'day')
}
