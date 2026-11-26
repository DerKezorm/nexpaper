/**
 * Settings › Connections: "Auf diesem Gerät installieren" (plan "Einstellungen", Verbindungen 2, E6, E28), as nexnotes'.
 * The card always stands there: the button "Installieren" while the browser offers its own question, otherwise a short
 * way for this browser (Safari on iPhone and iPad: Share › Add to Home Screen; Safari on the Mac: File › Add to Dock;
 * Firefox says it cannot install web apps; any other: its menu), and in the installed app that it runs installed already.
 */
import { Info, Share } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { install, usePwa } from '../lib/install'
import { Button, Buttons, Card } from '../vendor/nexui'

/** The way to install for a browser without its own question (`ios` from the page's state). */
export type InstallWay = 'ios' | 'safari' | 'firefox' | 'other'

// eslint-disable-next-line react-refresh/only-export-components
export function installWay(ios: boolean, agent = typeof navigator === 'undefined' ? '' : navigator.userAgent): InstallWay {
  if (ios) return 'ios'
  if (/Firefox\//.test(agent)) return 'firefox'
  if (/Macintosh/.test(agent) && /Safari\//.test(agent) && !/Chrome|Chromium|CriOS|Edg|OPR|Firefox/.test(agent)) return 'safari'
  return 'other'
}

function Way({ testId, share, children }: { testId: string; share?: boolean; children: string }) {
  const Icon = share ? Share : Info
  return (
    <p className="m-0 flex items-start gap-2 text-sm text-[var(--nexui-text)]" data-testid={testId}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-[var(--nexui-accent-text)]" aria-hidden /> {children}
    </p>
  )
}

export function InstallCard() {
  const { t } = useTranslation()
  const { installable, ios, standalone } = usePwa()
  const [asked, setAsked] = useState(false)
  const way = installWay(ios)
  return (
    <Card id="install" icon="Download" title={t('install.title')} subtitle={t('install.text')}>
      {standalone && <Way testId="install-done">{t('install.installed')}</Way>}
      {!standalone && installable && (
        <Buttons>
          <Button
            kind="primary"
            icon="Download"
            onClick={() => {
              setAsked(true)
              void install()
            }}
            testId="install"
          >
            {t('install.button')}
          </Button>
        </Buttons>
      )}
      {!standalone && !installable && asked && <Way testId="install-asked">{t('install.asked')}</Way>}
      {!standalone && !installable && !asked && (
        <Way testId={`install-${way}`} share={way === 'ios'}>
          {t(`install.${way}`)}
        </Way>
      )}
    </Card>
  )
}
