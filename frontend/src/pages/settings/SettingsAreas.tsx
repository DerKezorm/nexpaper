/**
 * What each area of the settings shows: the cards of before (the tabs of "Mein Konto" and of the settings), sorted by
 * subject as in nexnotes. The cards stay in their files; an area only picks them.
 */
import { AboutArea } from './AboutArea'
import { AccountArea } from './AccountArea'
import { AiCard } from './AiCard'
import type { AreaSlug } from './areas'
import { FeaturesCard } from './FeaturesCard'
import { FilesCheckCard, useStorage } from './FilesCards'
import { ImportCard } from './ImportCard'
import { IntakeCards } from './IntakeCards'
import { OcrCard } from './OcrCard'
import { PushServerCard } from './PushCards'
import { ReadinessCard } from './ReadinessCards'
import { AccountsCard, AllApiKeysCard, BackupsCard, InterfaceCard, LanguagesCard, LogCard, MailCard, useServerSettings } from './ServerCards'
import { ShortcutLinkCard } from './ShortcutLinkCard'
import { SignInPart } from './SignInCards'
import { KindsCard, RulesCard } from './SortingCards'
import { DiskCard, LimitsCard } from './StorageCards'

export function AreaContent({ area }: { area: AreaSlug }) {
  switch (area) {
    case 'profile':
    case 'security':
    case 'appearance':
    case 'connections':
    case 'upload':
    case 'reminders':
    case 'ai':
      return <AccountArea part={area} />
    case 'about':
      return <AboutArea />
    default:
      return <ServerArea area={area} />
  }
}

/** The server's own settings, for the operator. */
function ServerArea({ area }: { area: Exclude<AreaSlug, 'profile' | 'security' | 'appearance' | 'connections' | 'upload' | 'reminders' | 'ai' | 'about'> }) {
  const server = useServerSettings()
  return (
    <div className="space-y-6" data-testid={`server-${area}`}>
      {area === 'general' && (
        <>
          <LimitsCard />
          <FeaturesCard />
          <PushServerCard />
          <LanguagesCard />
        </>
      )}
      {area === 'sign-in' && (
        <>
          {/* nexpaper's own look at the server (its points say "below"), then the cards of the shared module. */}
          <ReadinessCard />
          <SignInPart server={server} />
        </>
      )}
      {area === 'mail' && <MailCard server={server} />}
      {area === 'storage' && <StoragePart server={server} />}
      {area === 'ocr' && <OcrCard />}
      {area === 'filing' && (
        <>
          <KindsCard />
          <RulesCard server />
        </>
      )}
      {area === 'ai-setup' && <AiCard />}
      {area === 'inputs' && <IntakeCards />}
      {area === 'import' && <ImportCard />}
      {area === 'api' && (
        <>
          <InterfaceCard />
          <ShortcutLinkCard />
        </>
      )}
      {area === 'accounts' && (
        <>
          <AccountsCard />
          <AllApiKeysCard />
        </>
      )}
      {area === 'log' && <LogCard />}
    </div>
  )
}

/**
 * "Speicher und Sicherung": nexnotes' one card of storage and backups first, then nexpaper's own: how the files lie on
 * the disk, and the check of the files. One request of what lies where fills the head of the first and the last.
 */
export function StoragePart({ server }: { server: ReturnType<typeof useServerSettings> }) {
  const storage = useStorage()
  return (
    <>
      <BackupsCard server={server} space={storage.info} />
      <DiskCard />
      {storage.info && <FilesCheckCard info={storage.info} reload={storage.load} />}
    </>
  )
}
