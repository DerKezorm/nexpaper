/**
 * `/app-connect`: an iPhone, iPad or Mac app built on NexKonto opened nexpaper in the browser to connect (the shared
 * module geraete 0.1.0, G8). The person is signed in (the route is behind the sign-in, with the second factor or the
 * provider as always), sees who is signed in and which app asks, and connects; the browser goes back to the app with a
 * one-time code. The page is the module's (`AppConnectPage`), framed like nexpaper's other pages for an app.
 */
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { DEVICES_AT, deviceRequest } from '../api/devices'
import { LogoMark } from '../components/Logo'
import { useAuth } from '../state/auth'
import { AppConnectPage } from '../vendor/nexgeraete'

function framed(card: ReactNode): ReactNode {
  return (
    <div className="grid min-h-dvh place-items-center p-4">
      <div className="flex w-full max-w-md flex-col items-center gap-4">
        <LogoMark size={48} />
        {card}
      </div>
    </div>
  )
}

export function AppConnectRoute() {
  const { i18n } = useTranslation()
  const { me } = useAuth()
  return (
    <AppConnectPage
      request={deviceRequest}
      base={DEVICES_AT}
      app="nexpaper"
      scheme="nexpaper"
      account={me ? { name: me.display_name || me.name, login: me.name } : null}
      language={i18n.language}
      frame={framed}
    />
  )
}
