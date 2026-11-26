/**
 * Other nex apps (the shared module verbinden 0.1.1): one card per partner of the catalog in My account › Connections
 * (place 3: nextime reads nexpaper's deadlines, nexmail adds documents, nexpaper uses tasks of nextasks), the operator's
 * card "Andere nex-Apps" (the switch and the addresses of the other apps) in Server › General, the consent page
 * `/connect/app` and the return `/connect/return`. Only the module's parts; nexpaper gives its word for its areas, the
 * vaults.
 */
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import { shortDate } from '../../lib/dates'
import { ConnectionsArea, ConnectionsOperatorCard, ConsentPage, ReturnPage, type PartnerView, type VerbindenRequest } from '../../vendor/nexverbinden'

const request: VerbindenRequest = (path, init = {}) => api(path, { method: init.method, body: init.body })

/** Partners of the catalog nexpaper has no use with yet (Bauplan V20: no card without an effect): nexpaper as a guest
 * of nextasks ("Aufgabe aus Dokument") is not built. */
// eslint-disable-next-line react-refresh/only-export-components
export const WITHOUT_USE = ['nextasks']

/** TODO verbinden 0.1.2: `ConnectionsArea` shows every partner of the catalog and takes no list of the app's; nexpaper
 * leaves the partners without a use out of the module's answer for the cards. */
const cardsRequest: VerbindenRequest = async <T,>(path: string, init: Parameters<VerbindenRequest>[1] = {}): Promise<T> => {
  const found = await request<T>(path, init)
  if (path.endsWith('/partners') && (init.method ?? 'GET') === 'GET' && Array.isArray(found)) {
    return (found as PartnerView[]).filter((view) => !WITHOUT_USE.includes(view.partner)) as T
  }
  return found
}

/** My account › Connections, place 3. */
export function OtherApps() {
  const { t, i18n } = useTranslation()
  return (
    <ConnectionsArea app="nexpaper" request={cardsRequest} areaWord={t('mcp.vaults')} language={i18n.language}
      when={(iso, language) => shortDate(iso, language)} />
  )
}

/** Server › General: "Andere nex-Apps". */
export function OtherAppsOperator() {
  const { i18n } = useTranslation()
  return <ConnectionsOperatorCard app="nexpaper" request={request} language={i18n.language} />
}

/** `/connect/app`: another nex app asks to connect with nexpaper. */
export function ConnectConsentPage() {
  const { t, i18n } = useTranslation()
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col justify-center px-4 py-10">
      <ConsentPage request={request} areaWord={t('mcp.vaults')} language={i18n.language} />
    </div>
  )
}

/** `/connect/return`: back from the other app, the connection is made. */
export function ConnectReturnPage() {
  const { i18n } = useTranslation()
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col justify-center px-4 py-10">
      <ReturnPage app="nexpaper" request={request} language={i18n.language} />
    </div>
  )
}
