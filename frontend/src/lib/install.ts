/**
 * nexpaper as an installed app (plan "Einstellungen" E6, E28): whether it runs installed (`display-mode: standalone`),
 * and the browser's offer to install it (`beforeinstallprompt`, Chrome, Edge, Android), kept from the start of the page
 * for the card "Auf diesem Gerät installieren" (My account › Connections). iPhone and iPad have no such offer: there it is
 * Share › Add to Home Screen. As nexnotes' `pwa/worker.ts`.
 */
import { useSyncExternalStore } from 'react'

import { installed, onIphone } from './push'

type State = {
  /** Runs as the installed app. */
  standalone: boolean
  /** The browser offers to install the app (Chrome, Edge, Android). */
  installable: boolean
  /** iPhone or iPad (Share › Add to Home Screen). */
  ios: boolean
}

type InstallOffer = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }> }

let state: State = { standalone: false, installable: false, ios: false }
let offer: InstallOffer | null = null
const listeners = new Set<() => void>()

function set(next: Partial<State>): void {
  state = { ...state, ...next }
  for (const listener of listeners) listener()
}

/** The browser's offer to install, kept from the start of the page (it comes once, early). */
export function listenForInstall(): void {
  if (typeof window === 'undefined') return
  set({ standalone: installed(), ios: onIphone() })
  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault()
    offer = event as InstallOffer
    set({ installable: true })
  })
  window.addEventListener('appinstalled', () => {
    offer = null
    set({ installable: false, standalone: installed() })
  })
}

/** The browser's own question to install; true when it was accepted. */
export async function install(): Promise<boolean> {
  if (!offer) return false
  const asked = offer
  offer = null
  set({ installable: false })
  await asked.prompt()
  const { outcome } = await asked.userChoice
  return outcome === 'accepted'
}

export function usePwa(): State {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => state,
    () => state,
  )
}

/** For the tests. */
export function setPwaState(next: Partial<State>): void {
  set(next)
}
