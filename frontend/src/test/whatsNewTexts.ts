/**
 * The texts of "Was ist neu" for the tests of the words: since the shared module wasneu they lie with the server
 * (`backend/app/whatsnew/<language>.json`), so the image carries them. Read at run time, not imported: the image builds
 * the interface from `frontend/` alone, where `tsc -b` would not find a file of the backend.
 */
export type WhatsNewTexts = Record<string, { lead: string; sections: { title: string; where: string; body: string }[]; smallTitle: string; small: string[] }>

export async function whatsNewTexts(language: 'de' | 'en' | 'fr'): Promise<WhatsNewTexts> {
  const fs = await import(/* @vite-ignore */ 'node:' + 'fs')
  const url = await import(/* @vite-ignore */ 'node:' + 'url')
  // A name in a variable: vite would take `new URL('<literal>', import.meta.url)` for an asset of the page.
  const target = '../../../backend/app/whatsnew/' + language + '.json'
  const file = url.fileURLToPath(new URL(target, import.meta.url))
  return JSON.parse(fs.readFileSync(file, 'utf-8')) as WhatsNewTexts
}
