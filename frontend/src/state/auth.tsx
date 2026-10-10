/**
 * Who is signed in. `loading` until the server answered, `setup` while nexpaper has no account yet, `signedOut`,
 * or `signedIn` with the account. A request that finds the session gone sends `SIGNED_OUT_EVENT`.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { ApiError, authApi, SIGNED_OUT_EVENT, type Me } from '../api/client'
import i18n, { changeLanguage } from '../i18n'
import { browserTimeZone } from '../lib/dates'
import { forgetPictures } from '../lib/pictures'
import { applyMode, isMode, storedMode } from '../lib/theme'

type Status = 'loading' | 'setup' | 'signedOut' | 'signedIn'

const REPORTED_ZONE = 'nexpaper.reportedZone'

function reportedZone(): string | null {
  try {
    return localStorage.getItem(REPORTED_ZONE)
  } catch {
    return null
  }
}

function rememberReportedZone(zone: string): void {
  try {
    localStorage.setItem(REPORTED_ZONE, zone)
  } catch {
    // Then this browser reports again next time; no harm.
  }
}

/**
 * Whether this browser tells the server its time zone: never over a zone the person chose; always while the server
 * knows none; else only when this browser's zone changed since it last reported (a journey), not on every page load.
 * Two devices in two zones therefore do not switch the account back and forth: the last one that changed wins.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function shouldReportZone(zone: string, serverZone: string, source: string, reported: string | null): boolean {
  if (!zone || source === 'manual' || zone === serverZone) return false
  return !serverZone || zone !== reported
}

type Auth = {
  status: Status
  me: Me | null
  refresh: () => Promise<void>
  setMe: (me: Me) => void
  signOut: () => Promise<void>
}

const Context = createContext<Auth | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [me, setMeState] = useState<Me | null>(null)

  const setMe = useCallback((next: Me) => {
    setMeState(next)
    setStatus('signedIn')
    // The account's language and light or dark win over what this browser remembered.
    if (next.language && next.language !== i18n.language) void changeLanguage(next.language)
    const mode = next.profile?.mode
    if (isMode(mode) && mode !== storedMode()) applyMode(mode)
    // "Today" is the date in the person's own time zone; the server learns it from the browser in use.
    const zone = browserTimeZone()
    if (next.profile && !next.second_factor_setup_required && shouldReportZone(zone, next.profile.timezone, next.profile.timezone_source, reportedZone())) {
      void authApi.preferences({ timezone: zone, timezone_source: 'browser' }).then(
        (profile) => {
          rememberReportedZone(zone)
          setMeState((current) => (current && current.id === next.id ? { ...current, profile } : current))
        },
        () => undefined,
      )
    }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const state = await authApi.setupState()
      if (state.needs_setup) {
        setStatus('setup')
        return
      }
      if (!state.signed_in) {
        setStatus('signedOut')
        setMeState(null)
        return
      }
      setMe(await authApi.me())
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setStatus('signedOut')
        setMeState(null)
      } else {
        // The server is not reachable: keep trying, the page shows the sign-in meanwhile.
        setStatus('signedOut')
      }
    }
  }, [setMe])

  useEffect(() => {
    void refresh()
    const gone = () => {
      forgetPictures()
      setStatus('signedOut')
      setMeState(null)
    }
    window.addEventListener(SIGNED_OUT_EVENT, gone)
    return () => window.removeEventListener(SIGNED_OUT_EVENT, gone)
  }, [refresh])

  const signOut = useCallback(async () => {
    await authApi.logout().catch(() => undefined)
    // The pictures of pages fetched for this person stay in the tab no longer.
    forgetPictures()
    setMeState(null)
    setStatus('signedOut')
  }, [])

  const value = useMemo(() => ({ status, me, refresh, setMe, signOut }), [status, me, refresh, setMe, signOut])
  return <Context.Provider value={value}>{children}</Context.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): Auth {
  const value = useContext(Context)
  if (!value) throw new Error('useAuth outside AuthProvider')
  return value
}

/** Only addresses inside nexpaper, so a link cannot send someone elsewhere after signing in. */
// eslint-disable-next-line react-refresh/only-export-components
export function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\') ? next : '/'
}
