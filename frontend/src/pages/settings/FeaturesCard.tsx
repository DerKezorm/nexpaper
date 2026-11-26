/**
 * Server › General: "Funktionen für alle Konten", as nexnotes' card of the same name: one switch per feature the
 * operator opens or closes for everybody. nexpaper's are links to the outside (with the longest they may last and how
 * many are open now) and upload requests (U1, off from the start, with how many take files now; never an address or a
 * name). The switch for API keys is under "Schnittstellen" now (schluessel 1.0.0).
 */
import { SlidersHorizontal } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { sharingApi, uploadRequestsApi, type RequestsOverview, type SharingOverview } from '../../api/client'
import { shortDate } from '../../lib/dates'
import { Card, CheckboxRow, Notice, SelectField } from '../../vendor/nexui'
import { Outcome } from './Outcome'
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
  const beneath = 'flex flex-col gap-2 border-0 border-l-2 border-solid border-[var(--nexui-line)] pl-4'
  return (
    <Card id="features" icon={SlidersHorizontal} title={t('server.features')} subtitle={t('server.featuresHint')}>
      <CheckboxRow label={t('sharingSettings.allow')} hint={t('sharingSettings.allowHint')} checked={linksOn} onChange={(links_allowed) => void server.save({ links_allowed })} />
      {linksOn && (
        <div className={beneath} data-testid="links-beneath">
          <div className="max-w-xs">
            <SelectField
              label={t('sharingSettings.longest')}
              hints={[t('sharingSettings.hint')]}
              value={longest}
              options={DAYS.map((d) => ({ value: d, label: t('sharingSettings.days', { count: Number(d) }) }))}
              onChange={(event) => void server.save({ link_max_days: Number(event.target.value) })}
            />
          </div>
          <p className="m-0 text-sm" data-testid="links-overview">
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
      <CheckboxRow
        label={t('uploadRequest.settings.allow')}
        hint={t('uploadRequest.settings.allowHint')}
        checked={requestsOn}
        onChange={(upload_requests_allowed) => void server.save({ upload_requests_allowed })}
      />
      {requestsOn && (
        <div className={beneath}>
          {!settings.public_url && <Notice tone="warn">{t('uploadRequest.settings.noAddress')}</Notice>}
          <p className="m-0 text-sm" data-testid="request-overview">
            {requests && requests.open_requests > 0
              ? t('uploadRequest.settings.overview', {
                  requests: t('uploadRequest.settings.requestCount', { count: requests.open_requests }),
                  people: t('sharingSettings.personCount', { count: requests.people }),
                })
              : t('uploadRequest.settings.none')}
          </p>
        </div>
      )}
      <Outcome problem={server.problem} values={server.values} />
    </Card>
  )
}
