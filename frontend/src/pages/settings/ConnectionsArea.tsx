/**
 * My account › Connections (plan "Einstellungen", Verbindungen), in the plan's order and only what nexpaper has: 1
 * "Geräte" (the iPhone and iPad app; the card of the shared module geraete 0.1.0, its pairing window shows a QR code the
 * published app reads too, `api/devices.ts`), 2 "Auf diesem Gerät installieren", 3 the other nex apps
 * (verbinden 0.1.1, `VerbindenCards.tsx`), 4 nexpaper's own "Aus anderen Apps auf dem iPhone" (the shortcut and its upload key) and, for the
 * operator, "Kurzbefehl fürs iPhone" (the shared shortcut's link; both from the area "API" of before), 5 "API-Schlüssel"
 * (schluessel), 6 "KI-Werkzeuge (MCP)" (schluessel's card with the parts of the shared MCP module, mcp 1.1.0). The
 * notifications on the devices are under Notifications now.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { Me } from '../../api/client'
import { DEVICES_AT, SERVER_CONNECTIONS, deviceRequest } from '../../api/devices'
import { InstallCard } from '../../components/InstallCard'
import { KeysWait } from '../../components/KeysWait'
import { KEYS_CHANGED, ShortcutCard } from '../../components/PhoneCards'
import { ApiKeys } from './KeysCards'
import { AiTools } from './McpCards'
import { OtherApps } from './VerbindenCards'
import { ShortcutLinkCard } from './ShortcutLinkCard'
import { DevicesCard } from '../../vendor/nexgeraete'

export function ConnectionsArea({ me }: { me: Me }) {
  const { i18n } = useTranslation()
  // A key made by the shortcut's card shows in the list of keys at once.
  const [round, setRound] = useState(0)
  useEffect(() => {
    const again = () => setRound((count) => count + 1)
    window.addEventListener(KEYS_CHANGED, again)
    return () => window.removeEventListener(KEYS_CHANGED, again)
  }, [])
  return (
    <>
      <DevicesCard
        request={deviceRequest}
        base={DEVICES_AT}
        app="nexpaper"
        language={i18n.language}
        operator={me.role === 'operator'}
        serverHref={SERVER_CONNECTIONS}
      >
        {/* nexpaper's own: devices and keys wait for the account's own second factor where the operator asks one. */}
        <KeysWait />
      </DevicesCard>
      <InstallCard />
      <OtherApps operator={me.role === 'operator'} />
      <ShortcutCard />
      {me.role === 'operator' && <ShortcutLinkCard />}
      <ApiKeys key={round} />
      <AiTools />
    </>
  )
}
