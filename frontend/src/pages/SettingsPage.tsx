/**
 * Settings (plan "Einstellungen") in the frame of the ui kit: `SettingsLayout` with `SettingsNav` (the account at the
 * top, "Mein Konto", "Server" for the operator, "Über nexpaper" set apart at the end) and one `SettingsPage` per area:
 * its title, one line, then only cards. Each area has its own address (`/settings/<slug>`, `settings/areas.ts`).
 * `/settings` alone is the list on a phone and the profile beside the navigation on a wider page. An area someone may
 * not open, a slug of before or a page of before (`/konto`, `/einstellungen`, `/ueber`, each with its `?tab=`) leads on
 * with the address replaced, so the navigation always marks where one is.
 */
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation, useParams } from 'react-router-dom'

import { Avatar } from '../components/Avatar'
import { APP_NAME } from '../i18n'
import { useAuth } from '../state/auth'
import { areaText, languageOf, NEXUI_TEXTS, NexuiLanguage, SettingsLayout, SettingsNav, SettingsPage as Area, type SettingsGroup } from '../vendor/nexui'
import { ABOUT_AREA, areaPath, areasFor, findArea, formerAddress, GENERAL_PARTS, GROUPS, resolveArea, type Area as AreaInfo } from './settings/areas'
import { AreaContent } from './settings/SettingsAreas'

export function SettingsPage() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const { tab: asked } = useParams()
  const { search, hash } = useLocation()
  if (!me) return null
  const where = resolveArea(asked, me.role, search, hash)
  if ('redirect' in where) return <Navigate to={where.redirect} replace />
  const area = findArea(where.area)
  if (!area) return null
  const things = t('settings.things')
  const thingsDative = t('settings.thingsDative')
  const shared = (info: AreaInfo) => areaText(NEXUI_TEXTS[languageOf(i18n.language)], info.slug, { app: APP_NAME, things, thingsDative, parts: GENERAL_PARTS })
  const words = (info: AreaInfo) => {
    if (info.own) return { title: t(`settings.areas.${info.key}.title`), text: t(`settings.areas.${info.key}.text`) }
    const kit = shared(info) ?? { title: info.slug, text: '' }
    return info.line ? { title: kit.title, text: t(`settings.areas.${info.key}.text`) } : kit
  }
  const groups: SettingsGroup[] = GROUPS.map((group) => ({
    id: group,
    areas: areasFor(me.role)
      .filter((entry) => entry.group === group)
      .map((entry) => ({ slug: entry.slug, icon: entry.icon, href: areaPath(entry.slug), title: entry.own ? words(entry).title : undefined })),
  }))
  const shown = me.display_name || me.name
  const own = area.own || area.line ? words(area) : null
  return (
    <NexuiLanguage language={i18n.language}>
      {/* Room below for the phone's bar of the app. */}
      <div className="pb-20 lg:pb-4">
        <SettingsLayout
          list={asked === undefined}
          back="/settings"
          link={Link}
          nav={
            <SettingsNav
              app={APP_NAME}
              things={things}
              thingsDative={thingsDative}
              groups={groups}
              about={{ href: areaPath(ABOUT_AREA.slug), slug: ABOUT_AREA.slug }}
              current={area.slug}
              account={{ name: shown, role: t(`me.role.${me.role}`), picture: <Avatar person={me} size={40} /> }}
              link={Link}
            />
          }
        >
          <Area slug={area.slug} app={APP_NAME} things={things} thingsDative={thingsDative} parts={GENERAL_PARTS} title={own?.title} subtitle={own?.text}>
            <AreaContent key={area.slug} area={area.slug} />
          </Area>
        </SettingsLayout>
      </div>
    </NexuiLanguage>
  )
}

/** An address of before (`/konto?tab=…`, `/einstellungen?tab=…`, `/ueber`): on to the area it meant. */
export function FormerAddress({ page }: { page: 'konto' | 'einstellungen' | 'ueber' }) {
  const { search } = useLocation()
  return <Navigate to={formerAddress(page, search)} replace />
}
