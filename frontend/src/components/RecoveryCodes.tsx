/** The recovery codes, shown once: a grid, to copy or to keep as a file. */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { copyText } from '../lib/copy'
import { saveAsFile } from '../pages/settings/actions'
import { AccountButton } from './AccountButton'

export function RecoveryCodes({ codes }: { codes: string[] }) {
  return (
    <ol data-testid="recovery-codes" className="m-0 grid list-none grid-cols-2 gap-2 rounded-[9px] bg-[var(--nexui-field)] px-4 py-3 font-mono text-sm sm:grid-cols-4">
      {codes.map((code) => (
        <li key={code}>{code}</li>
      ))}
    </ol>
  )
}

/** "Kopieren" and "Als Datei speichern", the account module's buttons next to each other. */
export function KeepCodes({ codes, account }: { codes: string[]; account: string; className?: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  const text = codes.join('\n')
  return (
    <>
      <AccountButton name="copy" size="md" onClick={() => void copyText(text).then(setCopied)}>
        {copied ? t('common.copied') : t('common.copy')}
      </AccountButton>
      <AccountButton name="download" onClick={() => saveAsFile(`nexpaper-recovery-codes-${account}.txt`, new Blob([text + '\n'], { type: 'text/plain' }))}>
        {t('twofactor.codesDownload')}
      </AccountButton>
    </>
  )
}
