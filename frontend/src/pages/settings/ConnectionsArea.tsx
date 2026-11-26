/**
 * My account › Connections (plan "Einstellungen", Verbindungen), in the plan's order and only what nexpaper has: 1
 * "Geräte" (the iPhone and iPad app, connected by a QR code), 2 "Auf diesem Gerät installieren", 3 no other nex app
 * connects here, 4 nexpaper's own "Aus anderen Apps auf dem iPhone" (the shortcut and its upload key) and, for the
 * operator, "Kurzbefehl fürs iPhone" (the shared shortcut's link; both from the area "API" of before), 5 "API-Schlüssel"
 * (schluessel). nexpaper has no MCP access (E27), so no "KI-Werkzeuge (MCP)". The notifications on the devices are
 * under Notifications now.
 */
import { useEffect, useState } from 'react'

import type { Me } from '../../api/client'
import { InstallCard } from '../../components/InstallCard'
import { PairedDevices } from '../../components/PairedDevices'
import { KEYS_CHANGED, ShortcutCard } from '../../components/PhoneCards'
import { ApiKeys } from './KeysCards'
import { ShortcutLinkCard } from './ShortcutLinkCard'

export function ConnectionsArea({ me }: { me: Me }) {
  // A key made by the shortcut's card shows in the list of keys at once.
  const [round, setRound] = useState(0)
  useEffect(() => {
    const again = () => setRound((count) => count + 1)
    window.addEventListener(KEYS_CHANGED, again)
    return () => window.removeEventListener(KEYS_CHANGED, again)
  }, [])
  return (
    <>
      <PairedDevices />
      <InstallCard />
      <ShortcutCard />
      {me.role === 'operator' && <ShortcutLinkCard />}
      <ApiKeys key={round} />
    </>
  )
}
