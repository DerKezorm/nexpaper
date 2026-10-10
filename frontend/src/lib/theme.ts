/**
 * Light or dark, or as the system is set. It belongs to the account (`profile.mode`, kept on the server); this browser
 * keeps a copy so that `public/theme.js` can paint the right one before the page has asked the server. It is only a
 * preview: whatever the account says wins once it is known. The colours behind it live solely in index.css; this only
 * holds which mode is active. There is one accent, kraft paper, in a light and a dark form.
 */

export type Theme = 'dark' | 'light'
export type Mode = Theme | 'system'
const KEY = 'nexpaper.theme'
const PAPER: Record<Theme, string> = { light: '#f7f3ec', dark: '#171310' }

function systemTheme(): Theme {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function isMode(value: unknown): value is Mode {
  return value === 'system' || value === 'light' || value === 'dark'
}

/** The mode chosen in this browser; nothing chosen yet means the system's. */
export function storedMode(): Mode {
  try {
    const stored = localStorage.getItem(KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'system'
  } catch {
    return 'system'
  }
}

/** The mode as it shows now: the system's when that was chosen. */
export function storedTheme(): Theme {
  const mode = storedMode()
  return mode === 'system' ? systemTheme() : mode
}

function paint(theme: Theme): void {
  const root = document.documentElement
  if (theme === 'dark') root.setAttribute('data-theme', 'dark')
  else root.removeAttribute('data-theme')
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', PAPER[theme])
}

export function applyMode(mode: Mode): void {
  paint(mode === 'system' ? systemTheme() : mode)
  try {
    localStorage.setItem(KEY, mode)
  } catch {
    // Then the choice only holds until the next reload.
  }
}

/** While the mode is the system's, the page changes along when the system does. Once, at the start. */
export function followSystem(): void {
  try {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (storedMode() === 'system') paint(systemTheme())
    })
  } catch {
    // An old browser: the mode stays as it was at the start.
  }
}
