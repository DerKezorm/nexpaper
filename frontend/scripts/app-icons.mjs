/* The icons for the home screen, rendered once from the light version of the mark.
 *
 * Same shape as components/Logo.tsx and public/logo.svg; the source of every version is nexapps/icons-vergleich/neu.py.
 * Rendered with Playwright, which the end-to-end tests bring anyway:  node scripts/app-icons.mjs
 *
 * The maskable icon is cropped by Android, so the mark sits smaller on a full white square. The Apple touch icon is
 * full bleed: iOS rounds it itself. The badge is one colour: Android tints everything that is not transparent.
 */
import { chromium } from '@playwright/test'

const VERLAUF = `<defs><linearGradient id="g" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
  <stop offset="0" stop-color="#d9a86c"/><stop offset=".5" stop-color="#9a6a3a"/><stop offset="1" stop-color="#5e3d1d"/>
</linearGradient></defs>`
const ZEICHEN = `<rect x="16.5" y="12" width="29" height="24" rx="2.5" fill="#fff" stroke="url(#g)" stroke-width="3" stroke-opacity=".6" transform="rotate(-7 31 24)"/>
  <rect x="19" y="16" width="26" height="22" rx="2.5" fill="#fff" stroke="#c0661c" stroke-width="3.4"/>
  <path d="M23.5 22.5h17M23.5 28h11" stroke="#c0661c" stroke-width="2.8" stroke-linecap="round"/>
  <path d="M10 35h11.5l3 5.5h15l3-5.5H54v11a4 4 0 0 1-4 4H14a4 4 0 0 1-4-4Z" fill="#fff" stroke="url(#g)" stroke-width="4.2" stroke-linejoin="round"/>`

const kachel = (s) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${s}" height="${s}">${VERLAUF}
  <rect x="2" y="2" width="60" height="60" rx="16" fill="#fff"/>
  <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="15.3" fill="none" stroke="#9a6a3a" stroke-opacity=".35" stroke-width="1.5"/>
  ${ZEICHEN}</svg>`
const voll = (s, m) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${s}" height="${s}">${VERLAUF}
  <rect width="64" height="64" fill="#fff"/>
  <g transform="translate(32 32) scale(${m}) translate(-32 -31)">${ZEICHEN}</g></svg>`
const randlos = (s) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="2 2 60 60" width="${s}" height="${s}">${VERLAUF}
  <rect x="2" y="2" width="60" height="60" fill="#fff"/>${ZEICHEN}</svg>`
const abzeichen = (s) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${s}" height="${s}">
  <rect x="19" y="14" width="26" height="22" rx="2.5" fill="none" stroke="#fff" stroke-width="4.5"/>
  <path d="M8 35h13l3 5.5h16l3-5.5h13v12a4 4 0 0 1-4 4H12a4 4 0 0 1-4-4Z" fill="#fff"/></svg>`

const BILDER = [
  ['public/icon-192.png', kachel(192), 192],
  ['public/icon-512.png', kachel(512), 512],
  ['public/icon-maskable-512.png', voll(512, 0.8), 512],
  ['public/apple-touch-icon.png', randlos(180), 180],
  ['public/badge-96.png', abzeichen(96), 96],
]

const browser = await chromium.launch()
for (const [pfad, svg, groesse] of BILDER) {
  const seite = await browser.newPage({ viewport: { width: groesse, height: groesse } })
  await seite.setContent(`<body style="margin:0;background:transparent">${svg}</body>`)
  await seite.locator('svg').screenshot({ path: pfad, omitBackground: true })
  await seite.close()
  console.log('written:', pfad)
}
await browser.close()
