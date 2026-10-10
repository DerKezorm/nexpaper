/**
 * Settings, for the operator only: the server in one row of tabs (accounts, sign-in, mail, AI, storage, sharing, Web Push,
 * backups, languages, log, API). Everything personal is under "My account". The part is in the address (`?tab=signin`), so a
 * link can point at one. A member has no use for this page and is sent to their account. Filing, inputs, sharing and
 * import join the row with the blocks that make them.
 */
import { BellRing, FolderInput, FolderTree, HardDrive, Inbox, KeyRound, Languages, Link2, Mail, Plug, ScrollText, Sparkles, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Navigate, useSearchParams } from 'react-router-dom'

import { useAuth } from '../state/auth'
import { AiCard } from './settings/AiCard'
import { ImportCard } from './settings/ImportCard'
import { IntakeCards } from './settings/IntakeCards'
import { PushServerCard } from './settings/PushCards'
import { ReadinessCard } from './settings/ReadinessCards'
import { SharingCard } from './settings/SharingCard'
import { KindsCard, RulesCard } from './settings/SortingCards'
import { ShortcutLinkCard } from './settings/ShortcutLinkCard'
import { FilesCards } from './settings/FilesCards'
import { DiskCard, LimitsCard } from './settings/StorageCards'
import { OcrCard } from './settings/OcrCard'
import { AccountsCard, ApiKeysCard, BackupsCard, InterfaceCard, LanguagesCard, LogCard, MailCard, SignInCard, useServerSettings } from './settings/ServerCards'
import { TabRow, type Tab } from './settings/ui'

type Part = 'accounts' | 'signin' | 'mail' | 'ai' | 'storage' | 'inputs' | 'sharing' | 'push' | 'backups' | 'languages' | 'import' | 'log' | 'api'
const PARTS: Part[] = ['accounts', 'signin', 'mail', 'ai', 'storage', 'inputs', 'sharing', 'push', 'backups', 'languages', 'import', 'log', 'api']
const PART_ICON = { accounts: Users, signin: KeyRound, mail: Mail, ai: Sparkles, storage: FolderTree, inputs: FolderInput, sharing: Link2, push: BellRing, backups: HardDrive, languages: Languages, import: Inbox, log: ScrollText, api: Plug }

export function SettingsPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [params, setParams] = useSearchParams()
  if (!me) return null
  if (me.role !== 'operator') return <Navigate to="/konto" replace />
  const asked = params.get('tab') as Part | null
  const part: Part = asked && PARTS.includes(asked) ? asked : 'accounts'
  const tabs: Tab<Part>[] = PARTS.map((value) => ({ value, label: value === 'inputs' ? t('intake.tab') : value === 'import' ? t('paperless.tab') : t(`settings.parts.${value}`), icon: PART_ICON[value] }))
  return (
    <div className="page space-y-5 pt-8 pb-28 lg:pb-12">
      <h1 className="font-display text-3xl font-semibold tracking-tight">{t('settings.title')}</h1>
      <TabRow tabs={tabs} active={part} onChange={(value) => setParams(value === 'accounts' ? {} : { tab: value }, { replace: true })} label={t('settings.title')} />
      <div className="space-y-6 pt-1">
        <ServerPart part={part} />
      </div>
    </div>
  )
}

/** One part of the server, for the operator. */
function ServerPart({ part }: { part: Part }) {
  const server = useServerSettings()
  switch (part) {
    case 'accounts':
      return <AccountsCard />
    case 'signin':
      return (
        <div className="space-y-6">
          <ReadinessCard />
          <SignInCard server={server} />
        </div>
      )
    case 'mail':
      return <MailCard server={server} />
    case 'ai':
      return <AiCard />
    case 'storage':
      return (
        <div className="space-y-6">
          <KindsCard />
          <RulesCard server />
          <LimitsCard />
          <OcrCard />
          <DiskCard />
        </div>
      )
    case 'inputs':
      return <IntakeCards />
    case 'sharing':
      return <SharingCard />
    case 'push':
      return <PushServerCard />
    case 'backups':
      return (
        <div className="space-y-6">
          <BackupsCard server={server} />
          <FilesCards />
        </div>
      )
    case 'languages':
      return <LanguagesCard />
    case 'import':
      return <ImportCard />
    case 'log':
      return <LogCard />
    case 'api':
      return (
        <div className="space-y-6">
          <InterfaceCard />
          <ApiKeysCard server={server} />
          <ShortcutLinkCard />
        </div>
      )
  }
}
