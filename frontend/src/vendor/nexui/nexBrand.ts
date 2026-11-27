/**
 * Since 1.3.0 (B19): what `NexMark` needs besides drawing, in a file of its own (components and constants apart): the
 * colours of the mark "Kachelfamilie" (`nexapps/icons-vergleich/NEX-ZEICHEN.md`, "Farben"), the only colours the kit
 * writes out itself, and whether the page is light or dark.
 */
import { useSyncExternalStore } from 'react'

/** The two looks of the mark (NEX-ZEICHEN.md, "Farben"), without its indigo: the dot takes the app's accent. */
export const NEX_MARK_COLORS = {
  light: { tile: '#fff', border: '#475569', borderOpacity: 0.3, gradient: ['#94a3b8', '#475569', '#1e293b'] },
  dark: { tile: '#0f1218', border: '#94a3b8', borderOpacity: 0.45, gradient: ['#e2e8f0', '#94a3b8', '#64748b'] },
} as const

/** Lightness 0..1 of a colour as the browser gives a custom property back: hex of three or six digits, rgb or rgba, oklch. */
function lightnessOf(value: string): number | null {
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value)
  const rgb = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(value)
  const ok = /^ok(?:lch|lab)\(\s*([\d.]+)(%?)/i.exec(value)
  if (ok) return Number(ok[1]) / (ok[2] ? 100 : 1)
  let parts: number[] | null = null
  if (hex) {
    const digits = hex[1] ?? ''
    const full = digits.length === 3 ? [...digits].map((one) => one + one).join('') : digits
    parts = [0, 2, 4].map((at) => parseInt(full.slice(at, at + 2), 16))
  } else if (rgb) {
    parts = [rgb[1], rgb[2], rgb[3]].map((one) => Number(one))
  }
  if (!parts) return null
  const [red = 0, green = 0, blue = 0] = parts
  return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
}

/** Whether the page is dark: the kit's surface (`--nexui-surface`; apps mark their theme differently, `data-theme`
 * light or dark, a class, but every one sets the surface for both), else the system. */
export function pageIsDark(): boolean {
  if (typeof window === 'undefined' || typeof document === 'undefined') return false
  const value = getComputedStyle(document.documentElement).getPropertyValue('--nexui-surface').trim()
  const lightness = lightnessOf(value)
  if (lightness !== null) return lightness < 0.5
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function subscribeTheme(changed: () => void): () => void {
  if (typeof window === 'undefined' || typeof MutationObserver === 'undefined') return () => undefined
  const watcher = new MutationObserver(changed)
  watcher.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] })
  const system = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-color-scheme: dark)') : null
  system?.addEventListener?.('change', changed)
  return () => {
    watcher.disconnect()
    system?.removeEventListener?.('change', changed)
  }
}

/** The page's light or dark, kept up to date when the account or the system switches it. */
export function usePageDark(): boolean {
  return useSyncExternalStore(subscribeTheme, pageIsDark, () => false)
}
