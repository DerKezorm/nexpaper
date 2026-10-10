/**
 * The place of a file on the disk, as a person reads it. The server names the folders of a document without a date, a
 * sender or a kind with fixed English words (`undated`, `no sender`, `Document`), because the disk does not change its
 * language with the person looking at it. In the page those words are said in the person's language; the real path
 * stays available (the title of the line), and a word that stands anywhere else than a placeholder does is left alone.
 */
import type { TFunction } from 'i18next'

/** The words the server writes for what a document does not have (`services/storage.py`). */
const NO_DATE = 'undated'
const NO_SENDER = 'no sender'

export function readablePath(path: string, t: TFunction): string {
  const parts = path.split('/')
  const last = parts.length - 1
  return parts
    .map((part, index) => {
      // Folders: vault / year / sender / file.
      if (index === 1 && part === NO_DATE) return t('docs.document.pathNoDate')
      if (index === 2 && index < last && part === NO_SENDER) return t('docs.document.pathNoSender')
      if (index === last && last >= 3) {
        const match = /^(\d{4}-\d{2}-\d{2}|undated) Document((?: \([^)]*\))*\.[^./]*)?$/.exec(part)
        if (match) {
          const day = match[1] === NO_DATE ? t('docs.document.pathNoDate') : match[1]
          return `${day} ${t('docs.document.pathNoKind')}${match[2] ?? ''}`
        }
      }
      return part
    })
    .join('/')
}
