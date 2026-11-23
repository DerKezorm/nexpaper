/**
 * The way through the settings, as in nexnotes. Where the page is wide enough (700 px of its own), a navigation on the
 * left: the account at the top, then the groups "My account" and, for the operator, "Server", and "About nexpaper" at
 * the end. Narrower, a choice above the content that goes to the area chosen. The page's own width counts, not the
 * window's: beside the app's sidebar a laptop is narrow too.
 */
import { Info } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import type { Me } from '../../api/client'
import { Avatar } from '../../components/Avatar'
import { ABOUT_AREA, areaPath, areasFor, GROUPS, type AreaSlug } from './areas'

const ENTRY = 'flex items-center gap-2.5 rounded-[9px] px-2.5 py-2 text-sm transition-colors '
const QUIET_ENTRY = 'text-ink-2 hover:bg-sheet-2 hover:text-ink'

export function SettingsNav({ me, current }: { me: Me; current: AreaSlug }) {
  const { t } = useTranslation()
  const areas = areasFor(me.role)
  const groups = GROUPS.filter((group) => areas.some((area) => area.group === group))
  const shown = me.display_name || me.name
  return (
    <nav aria-label={t('settings.title')} className="hidden w-56 shrink-0 @min-[700px]:sticky @min-[700px]:top-6 @min-[700px]:block" data-testid="settings-nav">
      <div className="mb-4 flex items-center gap-3 px-2.5">
        <Avatar person={me} size={40} />
        <div className="min-w-0">
          <p className="truncate font-semibold" title={shown}>
            {shown}
          </p>
          <p className="text-xs text-muted">{t(`me.role.${me.role}`)}</p>
        </div>
      </div>
      {groups.map((group) => (
        <div key={group} className="mb-4">
          <p id={`settings-group-${group}`} className="px-2.5 pb-1.5 text-[11px] font-semibold tracking-wider text-muted uppercase">
            {t(`settings.groups.${group}`)}
          </p>
          <ul aria-labelledby={`settings-group-${group}`} className="space-y-0.5">
            {areas
              .filter((area) => area.group === group)
              .map(({ slug, key, icon: Icon }) => {
                const here = slug === current
                return (
                  <li key={slug}>
                    <Link to={areaPath(slug)} aria-current={here ? 'page' : undefined} className={ENTRY + (here ? 'chosen font-medium' : QUIET_ENTRY)} data-testid={`settings-nav-${slug}`}>
                      <Icon className="h-4 w-4 shrink-0" strokeWidth={1.8} aria-hidden />
                      <span className="min-w-0 truncate">{t(`settings.areas.${key}.title`)}</span>
                    </Link>
                  </li>
                )
              })}
          </ul>
        </div>
      ))}
      <div className="border-t border-line pt-2">
        <Link
          to={areaPath(ABOUT_AREA.slug)}
          aria-current={current === ABOUT_AREA.slug ? 'page' : undefined}
          className={ENTRY + (current === ABOUT_AREA.slug ? 'chosen font-medium' : QUIET_ENTRY)}
          data-testid="settings-nav-about"
        >
          <Info className="h-4 w-4 shrink-0" strokeWidth={1.8} aria-hidden />
          <span className="min-w-0 truncate">{t(`settings.areas.${ABOUT_AREA.key}.title`)}</span>
        </Link>
      </div>
    </nav>
  )
}

/** The narrow page: one choice with the groups, and "About nexpaper" beside it. */
export function SettingsJump({ me, current }: { me: Me; current: AreaSlug }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const areas = areasFor(me.role)
  const groups = GROUPS.filter((group) => areas.some((area) => area.group === group))
  return (
    <div className="flex items-center gap-2 @min-[700px]:hidden" data-testid="settings-jump-row">
      <label className="min-w-0 flex-1">
        <span className="sr-only">{t('settings.jump')}</span>
        <select className="input" value={current} onChange={(event) => navigate(areaPath(event.target.value as AreaSlug))} data-testid="settings-jump">
          {groups.map((group) => (
            <optgroup key={group} label={t(`settings.groups.${group}`)}>
              {areas
                .filter((area) => area.group === group)
                .map(({ slug, key }) => (
                  <option key={slug} value={slug}>
                    {t(`settings.areas.${key}.title`)}
                  </option>
                ))}
            </optgroup>
          ))}
          <option value={ABOUT_AREA.slug}>{t(`settings.areas.${ABOUT_AREA.key}.title`)}</option>
        </select>
      </label>
      <Link
        to={areaPath(ABOUT_AREA.slug)}
        aria-current={current === ABOUT_AREA.slug ? 'page' : undefined}
        className="btn btn-ghost shrink-0"
        aria-label={t(`settings.areas.${ABOUT_AREA.key}.title`)}
        title={t(`settings.areas.${ABOUT_AREA.key}.title`)}
      >
        <Info className="h-4 w-4" aria-hidden />
      </Link>
    </div>
  )
}
