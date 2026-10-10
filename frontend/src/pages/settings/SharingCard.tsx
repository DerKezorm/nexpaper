/** Settings, Sharing: the operator's switch for links to the outside and the longest they may last. */
import { Link2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { sharingApi, type SharingOverview } from '../../api/client'
import { shortDate } from '../../lib/dates'
import { Card, Feedback, Select, SubHead, Toggle } from './ui'
import { useServerSettings } from './ServerCards'

const DAYS = ['7', '14', '30', '90'] as const

export function SharingCard() {
  const { t, i18n } = useTranslation()
  const server = useServerSettings()
  const [overview, setOverview] = useState<SharingOverview | null>(null)
  const settings = server.settings
  const allowed = settings?.links_allowed ?? false
  const longest = String(settings?.link_max_days ?? 30)
  useEffect(() => {
    sharingApi.overview().then(setOverview, () => undefined)
  }, [allowed, longest])
  return (
    <Card icon={Link2} title={t('sharingSettings.title')} text={t('sharingSettings.text')}>
      {settings && (
        <>
          <Toggle label={t('sharingSettings.allow')} hint={t('sharingSettings.allowHint')} checked={settings.links_allowed} onChange={(links_allowed) => void server.save({ links_allowed })} />
          {settings.links_allowed && (
            <div className="flex flex-wrap items-end gap-3">
              <Select
                className="w-40"
                label={t('sharingSettings.longest')}
                value={longest as (typeof DAYS)[number]}
                options={DAYS.map((d) => ({ value: d, label: t('sharingSettings.days', { count: Number(d) }) }))}
                onChange={(value) => void server.save({ link_max_days: Number(value) })}
              />
              <p className="max-w-md pb-2 text-xs text-muted">{t('sharingSettings.hint')}</p>
            </div>
          )}
        </>
      )}
      <SubHead title={t('sharingSettings.open')} />
      {overview && overview.open_links > 0 && overview.next_end ? (
        <p className="text-sm text-ink-2">
          {t('sharingSettings.overview', {
            links: t('sharingSettings.linkCount', { count: overview.open_links }),
            people: t('sharingSettings.personCount', { count: overview.people }),
            date: shortDate(overview.next_end, i18n.language),
          })}
        </p>
      ) : (
        <p className="text-sm text-ink-2">{t('sharingSettings.none')}</p>
      )}
      <Feedback problem={server.problem} values={server.values} />
    </Card>
  )
}
