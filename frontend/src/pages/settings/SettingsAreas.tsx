/**
 * What each area of the settings shows, in the order of the plan "Einstellungen": only cards. The cards stay in their
 * files; an area only picks them.
 */
import { AboutArea } from './AboutArea'
import { AccountArea } from './AccountArea'
import { AccountsTab } from './AccountsTab'
import { AiCard } from './AiCard'
import type { AreaSlug } from './areas'
import { FeaturesCard } from './FeaturesCard'
import { ImportCard } from './ImportCard'
import { IntakeCards } from './IntakeCards'
import { AllKeys, Interfaces } from './KeysCards'
import { OcrCard } from './OcrCard'
import { PushServerCard } from './PushCards'
import { LanguagesCard, LogArea, MailArea } from './ServerCards'
import { SignInArea } from './SignInArea'
import { KindsCard, RulesCard } from './SortingCards'
import { StorageArea } from './StorageArea'
import { LimitsCard } from './StorageCards'

export function AreaContent({ area }: { area: AreaSlug }) {
  switch (area) {
    case 'profile':
    case 'security':
    case 'appearance':
    case 'upload':
    case 'ai':
    case 'notifications':
    case 'connections':
      return <AccountArea part={area} />
    case 'about':
      return <AboutArea />
    case 'general':
      return (
        <>
          <LimitsCard />
          <FeaturesCard />
          <Interfaces />
          <PushServerCard />
          <LanguagesCard />
        </>
      )
    case 'sign-in':
      return <SignInArea />
    case 'mail':
      return <MailArea />
    case 'storage':
      return <StorageArea />
    case 'ocr':
      return <OcrCard />
    case 'ai-provider':
      return <AiCard />
    case 'filing':
      return (
        <>
          <KindsCard />
          <RulesCard server />
        </>
      )
    case 'inputs':
      return <IntakeCards />
    case 'import':
      return <ImportCard />
    case 'accounts':
      return (
        <>
          <AccountsTab />
          <AllKeys />
        </>
      )
    case 'log':
      return <LogArea />
  }
}
