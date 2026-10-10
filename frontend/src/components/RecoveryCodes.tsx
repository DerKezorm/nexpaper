/** The recovery codes, shown once: the grid of the mock, to copy or to keep as a file. */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { copyText } from '../lib/copy'
import { saveAsFile } from '../pages/settings/ui'

export function RecoveryCodes({ codes }: { codes: string[] }) {
  return (
    <ol data-testid="recovery-codes" className="grid grid-cols-2 gap-2 rounded-xl bg-sheet-2 p-4 font-mono text-sm sm:grid-cols-4">
      {codes.map((code) => (
        <li key={code}>{code}</li>
      ))}
    </ol>
  )
}

/** "Kopieren" and "Als Datei speichern", as round buttons next to each other. */
export function KeepCodes({ codes, account, className = '' }: { codes: string[]; account: string; className?: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const text = codes.join('\n')
  const look = 'h-10 flex-1 rounded-full border border-line text-sm font-semibold hover:bg-sheet-2'
  return (
    <div className={'flex gap-2 ' + className}>
      <button type="button" className={look} onClick={() => void copyText(text).then(setCopied)}>
        {copied ? t('common.copied') : t('common.copy')}
      </button>
      <button type="button" className={look} onClick={() => saveAsFile(`nexpaper-recovery-codes-${account}.txt`, new Blob([text + '\n'], { type: 'text/plain' }))}>
        {t('twofactor.codesDownload')}
      </button>
    </div>
  )
}
