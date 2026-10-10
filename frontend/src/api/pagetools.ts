/**
 * The page tools of the server (`/api/v1/documents/...`): turning, deleting and ordering pages, joining, splitting, the blank
 * separator pages of a batch scan, the versions of a document. Every change names the version it was made for; when the
 * document moved on in the meantime the server answers `version_changed`.
 */
import { api, type DocumentInfo } from './client'

/** Degrees clockwise. */
export type Turn = 0 | 90 | 180 | 270
export type PageSpec = { page: number; turn: Turn }

export type VersionInfo = {
  n: number
  current: boolean
  pages: number
  size: number
  sha256: string
  created_at: string
  created_by: { id: number; name: string; display_name: string } | null
  note: string
  kind: string
  has_archive: boolean
  has_pages: boolean
  /** `pages`, `merged`, `split`, `restored`, `uploaded`, or empty for the file the document came with. */
  origin: string
  from_n: number | null
  state: 'ready' | 'processing' | 'failed'
  error: string
}

export type Separators = {
  version: number
  checked: boolean
  blank_pages: number[]
  parts: number[][]
  duplex: boolean
  dismissed: boolean
  suggested: boolean
}

/** A turn as the server takes it, whatever was added up in the editor. */
export function turnOf(degrees: number): Turn {
  return ((((Math.round(degrees / 90) * 90) % 360) + 360) % 360) as Turn
}

/** The address of a page picture (`small` for strips, `large` for reading); each version has its own. */
export function pagePicture(document: number, version: number, page: number, size: 'small' | 'large' = 'small'): string {
  return `/api/v1/documents/${document}/versions/${version}/pages/${page}?size=${size}`
}

export const pageToolsApi = {
  editPages: (document: number, baseVersion: number, pages: PageSpec[]) =>
    api<DocumentInfo>(`/api/v1/documents/${document}/pages`, { method: 'POST', body: { base_version: baseVersion, pages } }),
  merge: (document: number, baseVersion: number, others: { id: number; base_version: number }[]) =>
    api<DocumentInfo>(`/api/v1/documents/${document}/merge`, { method: 'POST', body: { base_version: baseVersion, others } }),
  split: (document: number, baseVersion: number, parts: { pages: PageSpec[]; title?: string }[]) =>
    api<{ items: DocumentInfo[] }>(`/api/v1/documents/${document}/split`, { method: 'POST', body: { base_version: baseVersion, parts } }),
  separators: (document: number) => api<Separators>(`/api/v1/documents/${document}/separators`),
  keepAsOne: (document: number) => api<void>(`/api/v1/documents/${document}/separators`, { method: 'DELETE' }),
  versions: (document: number) => api<VersionInfo[]>(`/api/v1/documents/${document}/versions`),
  /** An uploaded version that could not be read goes again. */
  discard: (document: number, version: number) => api<void>(`/api/v1/documents/${document}/versions/${version}`, { method: 'DELETE' }),
  restore: (document: number, version: number, baseVersion: number) =>
    api<DocumentInfo>(`/api/v1/documents/${document}/versions/${version}/restore`, { method: 'POST', body: { base_version: baseVersion } }),
  uploadVersion: (document: number, file: File, note = '', signal?: AbortSignal) => {
    const form = new FormData()
    form.append('file', file, file.name)
    if (note) form.append('note', note)
    return api<VersionInfo>(`/api/v1/documents/${document}/versions`, { method: 'POST', form, signal })
  },
}
