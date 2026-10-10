/**
 * What the page and the PDF frame say to each other. The frame (`/pdfview.html`, `src/pdfview/main.ts`) has no
 * origin of its own and no network at all: the page fetches the PDF and the few files pdf.js asks for, and hands them
 * over. A PDF is code from someone else (fonts, forms, images in odd formats); whatever goes wrong in pdf.js stays in
 * a frame that reaches neither the session nor the documents.
 */
export type Colours = { ground: string; panel: string; text: string; muted: string; accent: string; line: string }

export type FrameTexts = { pages: string; contents: string; noContents: string; password: string; broken: string; page: string }

export type ToFrame =
  | { type: 'open'; data: ArrayBuffer; page: number; colours: Colours; texts: FrameTexts; sidebar: boolean; compact: boolean }
  | { type: 'go'; page: number }
  | { type: 'zoom'; to: 'in' | 'out' | 'width' }
  | { type: 'find'; query: string; previous: boolean; again: boolean }
  | { type: 'sidebar'; show: boolean }
  | { type: 'colours'; colours: Colours }
  | { type: 'data'; id: number; bytes: ArrayBuffer | null }

export type FromFrame =
  | { type: 'ready' }
  | { type: 'loaded'; pages: number }
  | { type: 'page'; page: number }
  | { type: 'scale'; percent: number }
  | { type: 'found'; current: number; total: number }
  | { type: 'link'; href: string }
  /** A click on a page that is no link and selects no text: the page may open the document large. */
  | { type: 'click' }
  | { type: 'data'; id: number; kind: DataKind; name: string }
  | { type: 'failed'; reason: 'password' | 'broken' }
  /** Ctrl+F inside the frame: the page opens its find bar (the browser's own would search the frame only). */
  | { type: 'findKey' }

/** The kinds of file pdf.js may ask for, and the folder they lie in under `/pdfjs/`. */
export type DataKind = 'cMapUrl' | 'standardFontDataUrl' | 'wasmUrl'
export const DATA_FOLDERS: Record<DataKind, string> = { cMapUrl: 'cmaps', standardFontDataUrl: 'standard_fonts', wasmUrl: 'wasm' }

/** A file name pdf.js may ask for: no path, nothing but letters, digits, dots, dashes and underscores. */
export function plainName(name: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$/.test(name) && !name.includes('..')
}

/** A message the frame listens to: only from the page that holds it (the frame's parent), never from another window
 * (a link the PDF opened, another frame), whatever it says. */
export function fromParent(event: Pick<MessageEvent, 'source'>, parent: Window | null): boolean {
  return parent !== null && event.source === parent
}

/** Only what the web is: an address a click in a PDF may open, in a tab of its own. */
export function openable(href: string): boolean {
  return /^(https?:\/\/|mailto:)/i.test(href)
}

/**
 * pdf.js's worker as a classic script. It comes inside this script, not from an address: a frame without an origin
 * may start no worker of the server, and Chrome starts no module worker in it at all (measured: a classic one from a
 * blob answers, a module one fails). pdf.js ships the worker as a module; its only module parts are the export at the
 * end and `import.meta.url` in two image decoders, both replaced here. Anything else of a module stops right here.
 */
export function classicWorker(source: string): string {
  const classic = source
    .replace(/export\s*\{\s*WorkerMessageHandler\s*\};?\s*(\/\/# sourceMappingURL=\S*)?\s*$/, '')
    .replaceAll('import.meta.url', 'self.location.href')
  if (/(^|[;}\s])export\s*\{|import\.meta|^\s*import\s/m.test(classic)) throw new Error('pdf.js worker is no longer a plain script')
  return classic
}
