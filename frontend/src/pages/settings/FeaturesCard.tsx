/**
 * Settings, General: "Funktionen für alle Konten", as nexnotes' card of the same name: one switch per feature the
 * operator opens or closes for everybody. nexpaper's are links to the outside (with the longest they may last and how
 * many are open now), upload requests (U1, off from the start, with how many take files now; never an address or a
 * name) and API keys.
 */
import { SlidersHorizontal } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { sharingApi, uploadRequestsApi, type RequestsOverview, type SharingOverview } from '../../api/client'
import { shortDate } from '../../lib/dates'
import { Card, Feedback, Select, Toggle } from './ui'
import { useServerSettings } from './ServerCards'

const DAYS = ['7', '14', '30', '90'] as const

export function FeaturesCard() {
  const { t, i18n } = useTranslation()
  const server = useServerSettings()
  const [overview, setOverview] = useState<SharingOverview | null>(null)
  const [requests, setRequests] = useState<RequestsOverview | null>(null)
  const settings = server.settings
  const linksOn = settings?.links_allowed ?? false
  const longest = String(settings?.link_max_days ?? 30)
  const requestsOn = settings?.upload_requests_allowed ?? false
  useEffect(() => {
    sharingApi.overview().then(setOverview, () => undefined)
  }, [linksOn, longest])
  useEffect(() => {
    uploadRequestsApi.overview().then(setRequests, () => undefined)
  }, [requestsOn])
  if (!settings) return null
  // What belongs to a switch stands under it, a little in, while the switch is on.
  const beneath = 'space-y-2 border-l-2 border-line pl-4'
  return (
    <Card id="features" icon={SlidersHorizontal} title={t('server.features')}>
      <Toggle label={t('sharingSettings.allow')} hint={t('sharingSettings.allowHint')} checked={linksOn} onChange={(links_allowed) => void server.save({ links_allowed })} />
      {linksOn && (
        <div className={beneath} data-testid="links-beneath">
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
          <p className="text-sm text-ink-2" data-testid="links-overview">
            {overview && overview.open_links > 0 && overview.next_end ? (
              <>
                <span className="font-semibold">{t('sharingSettings.open')}: </span>
                {t('sharingSettings.overview', {
                  links: t('sharingSettings.linkCount', { count: overview.open_links }),
                  people: t('sharingSettings.personCount', { count: overview.people }),
                  date: shortDate(overview.next_end, i18n.language),
                })}
              </>
            ) : (
              t('sharingSettings.none')
            )}
          </p>
        </div>
      )}
      <Toggle
        label={t('uploadRequest.settings.allow')}
        hint={t('uploadRequest.settings.allowHint')}
        checked={requestsOn}
        onChange={(upload_requests_allowed) => void server.save({ upload_requests_allowed })}
      />
      {requestsOn && (
        <div className={beneath}>
          {!settings.public_url && <p className="text-sm text-warn">{t('uploadRequest.settings.noAddress')}</p>}
          <p className="text-sm text-ink-2" data-testid="request-overview">
            {requests && requests.open_requests > 0
              ? t('uploadRequest.settings.overview', {
                  requests: t('uploadRequest.settings.requestCount', { count: requests.open_requests }),
                  people: t('sharingSettings.personCount', { count: requests.people }),
                })
              : t('uploadRequest.settings.none')}
          </p>
        </div>
      )}
      <Toggle label={t('server.apiKeys.allow')} hint={t('server.apiKeys.allowHint')} checked={settings.api_keys_allowed} onChange={(api_keys_allowed) => void server.save({ api_keys_allowed })} />
      <Feedback problem={server.problem} values={server.values} />
    </Card>
  )
}
