/**
 * Settings in areas, as in nexnotes: "My account" for every account, "Server" for the operator, "About nexpaper" for
 * everyone at the end. Each area has its own address (`/settings/<slug>`, `settings/areas.ts`), `/settings` is the
 * profile. An area someone may not open leads on to the profile, so the navigation always marks where one is. The
 * pages of before (`/konto`, `/einstellungen`, `/ueber`, each with its `?tab=`) lead to their area (`FormerAddress`).
 */
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation, useParams } from 'react-router-dom'

import { useAuth } from '../state/auth'
import { findArea, formerAddress, resolveArea } from './settings/areas'
import { AreaContent } from './settings/SettingsAreas'
import { SettingsJump, SettingsNav } from './settings/SettingsNav'

export function SettingsPage() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const { tab: asked } = useParams()
  const { search } = useLocation()
  if (!me) return null
  const where = resolveArea(asked, me.role, search)
  if ('redirect' in where) return <Navigate to={where.redirect} replace />
  const area = findArea(where.area)
  if (!area) return null
  return (
    <div className="@container mx-auto w-full max-w-6xl px-4 pt-6 pb-28 sm:px-6 sm:pt-8 lg:pb-12">
      <div className="flex flex-col gap-5 @min-[700px]:flex-row @min-[700px]:items-start @min-[700px]:gap-8">
        <SettingsNav me={me} current={area.slug} />
        <SettingsJump me={me} current={area.slug} />
        <div className="min-w-0 flex-1 space-y-5" data-testid={`settings-area-${area.slug}`}>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{t(`settings.areas.${area.key}.title`)}</h1>
            <p className="mt-1 text-sm text-muted">{t(`settings.areas.${area.key}.text`)}</p>
          </div>
          <AreaContent key={area.slug} area={area.slug} />
        </div>
      </div>
    </div>
  )
}

/** An address of before (`/konto?tab=…`, `/einstellungen?tab=…`, `/ueber`): on to the area it meant. */
export function FormerAddress({ page }: { page: 'konto' | 'einstellungen' | 'ueber' }) {
  const { search } = useLocation()
  return <Navigate to={formerAddress(page, search)} replace />
}
