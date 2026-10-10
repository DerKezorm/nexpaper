import workerSource from 'pdfjs-dist/build/pdf.worker.min.mjs?raw'

import { classicWorker, openable, plainName } from './pdfFrame'

describe('what the frame may ask for', () => {
  it('is a plain file name, never a path', () => {
    expect(plainName('78-EUC-H.bcmap')).toBe(true)
    expect(plainName('FoxitSans.pfb')).toBe(true)
    expect(plainName('openjpeg.wasm')).toBe(true)
    for (const bad of ['../secret', 'a/b', '..bcmap', '', '.hidden', 'x'.repeat(200), 'a b']) expect(plainName(bad)).toBe(false)
  })

  it('opens only the web and mail from a PDF', () => {
    expect(openable('https://example.com/a')).toBe(true)
    expect(openable('mailto:a@example.com')).toBe(true)
    for (const bad of ['javascript:alert(1)', 'file:///etc/passwd', '/api/file?path=x', 'data:text/html,x', ' https://x']) expect(openable(bad)).toBe(false)
  })
})

describe("pdf.js's worker", () => {
  it('runs as a classic script once the module parts are gone', () => {
    const classic = classicWorker(workerSource)
    expect(classic).not.toMatch(/import\.meta/)
    expect(classic).not.toMatch(/export\s*\{/)
    // Parsed, not run, as plain script code: a module's syntax (import, export) would throw here.
    expect(() => new Function(classic)).not.toThrow()
    expect(classic).toContain('WorkerMessageHandler')
  })

  it('refuses a worker that is still a module', () => {
    expect(() => classicWorker('import x from "y"\nexport { WorkerMessageHandler }')).toThrow()
    expect(() => classicWorker('const a = import.meta.url; export{Other};')).toThrow()
  })
})
