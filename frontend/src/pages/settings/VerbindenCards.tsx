/**
 * Other nex apps (the shared module verbinden 0.1.1): one card per partner of the catalog in My account › Connections
 * (place 3: nextime reads nexpaper's deadlines, nexmail adds documents, nexpaper uses tasks of nextasks), the operator's
 * card "Andere nex-Apps" (the switch and the addresses of the other apps) in Server › General, the consent page
 * `/connect/app` and the return `/connect/return`. Only the module's parts; nexpaper gives its word for its areas, the
 * vaults, and whether the signed-in account is the operator (verbinden 0.1.8: only it sets a partner up and connects
 * a new one by hand). The two pages bring their own frame since 0.1.8 (`PAGE_FRAME`), nexpaper adds none.
 */
import { useTranslation } from 'react-i18next'

import { api } from '../../api/client'
import { ConnectionsArea, ConnectionsOperatorCard, ConsentPage, ReturnPage, type VerbindenRequest } from '../../vendor/nexverbinden'

const request: VerbindenRequest = (path, init = {}) => api(path, { method: init.method, body: init.body })

/** My account › Connections, place 3. */
export function OtherApps({ operator }: { operator: boolean }) {
  const { t, i18n } = useTranslation()
  return (
    <ConnectionsArea app="nexpaper" request={request} areaWord={t('mcp.vaults')} language={i18n.language} operator={operator} />
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
  return <ConsentPage request={request} areaWord={t('mcp.vaults')} language={i18n.language} />
}

/** `/connect/return`: back from the other app, the connection is made. */
export function ConnectReturnPage() {
  const { i18n } = useTranslation()
  return <ReturnPage app="nexpaper" request={request} language={i18n.language} />
}
