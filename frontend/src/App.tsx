import { lazy, Suspense, useEffect, useRef, type ReactNode } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { inboxApi } from './api/client'
import { AppShell } from './components/AppShell'
import { usesDeadlines } from './lib/deadlines'
import { AboutPage } from './pages/AboutPage'
import { AccountPage } from './pages/AccountPage'
import { ForgotPage, InvitePage, LoginPage, MailConfirmPage, ResetPage, SenderConfirmPage, SetupPage } from './pages/AuthPages'
import { ArchivePage } from './pages/ArchivePage'
import { DeadlinesPage } from './pages/DeadlinesPage'
import { DocumentPage } from './pages/DocumentPage'
import { InboxPage } from './pages/InboxPage'
import { ExportLinkPage } from './pages/ExportLinkPage'
import { LinkPage } from './pages/LinkPage'
import { OAuthPage } from './pages/OAuthPage'
import { OrderPage } from './pages/OrderPage'
import { QuickPage } from './pages/QuickPage'
import { SettingsPage } from './pages/SettingsPage'
import { TrashPage } from './pages/TrashPage'
import { VaultsPage } from './pages/VaultsPage'
import { useAuth } from './state/auth'
import { UploadProvider } from './state/uploads'

/** The page "Fristen", for somebody who uses deadlines; whoever switched them off (My account, Reminders) lands in the
 * archive, also from an old link. */
function DeadlinesRoute() {
  const { me } = useAuth()
  return usesDeadlines(me) ? <DeadlinesPage /> : <Navigate to="/" replace />
}

/** The camera and its edge finder load only on its own page (a chunk of its own; OpenCV comes in its worker). */
const CameraPage = lazy(() => import('./pages/CameraPage'))

/** Everything behind the sign-in: without an account the page goes to the sign-in, and comes back after. An account
 * that still has to set up its second factor (the operator requires one) reaches its own account page only. */
function SignedIn({ children }: { children: ReactNode }) {
  const { status, me } = useAuth()
  const location = useLocation()
  if (status === 'loading') return null
  if (status === 'setup') return <Navigate to="/setup" replace />
  if (status === 'signedOut') return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />
  // Right after the password, the sign-in page sets the second factor up before anything else opens.
  if (me?.session_stage && me.session_stage !== 'full') return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />
  if (me?.second_factor_setup_required && location.pathname !== '/konto') return <Navigate to="/konto?tab=security" replace />
  return children
}

const QUICK_SHOWN = 'nexpaper.quickShown'
/** Narrower than this is a phone (the mock's `md`). */
const PHONE_WIDTH = 768

/** On the phone nexpaper opens on the quick upload, once per visit; "Alles" from there stays in the full app. The switch
 * is the person's (My account, Upload). */
function QuickStart() {
  const { me } = useAuth()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const wanted = me?.profile.quick_start !== false
  useEffect(() => {
    if (!me || pathname !== '/' || !wanted || window.innerWidth >= PHONE_WIDTH) return
    try {
      if (sessionStorage.getItem(QUICK_SHOWN)) return
      sessionStorage.setItem(QUICK_SHOWN, '1')
    } catch {
      // Private mode: then every time.
    }
    navigate('/schnell', { replace: true })
  }, [me, wanted, pathname, navigate])
  return null
}

const START_SHOWN = 'nexpaper.startShown'

/** The first page of a visit: when something waits in the inbox, that opens (the inbox is where work begins); else the
 * archive stays. Once per visit, so the menu's "Archiv" always opens the archive. A phone with the quick upload goes there
 * instead (`QuickStart`). */
function InboxStart() {
  const { me } = useAuth()
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const phone = me?.profile.quick_start !== false && window.innerWidth < PHONE_WIDTH
  const here = useRef(pathname)
  useEffect(() => {
    here.current = pathname
  })
  useEffect(() => {
    if (!me || pathname !== '/' || search || phone) return
    try {
      if (sessionStorage.getItem(START_SHOWN)) return
      sessionStorage.setItem(START_SHOWN, '1')
    } catch {
      // Private mode: no way to say "once", so never.
      return
    }
    // Not cancelled when the effect runs again (a strict-mode double run): the page is checked when the answer comes.
    void inboxApi.counts().then(
      (found) => here.current === '/' && (Number(found.inbox) || 0) + (Number(found.reading) || 0) > 0 && navigate('/eingang', { replace: true }),
      () => undefined,
    )
  }, [me, pathname, search, phone, navigate])
  return null
}

/** The signed-in part: one queue of uploads for the whole app, the phone's pages and the frame of the rest. */
function SignedInPart() {
  return (
    <SignedIn>
      <UploadProvider>
        <QuickStart />
        <InboxStart />
        <Outlet />
      </UploadProvider>
    </SignedIn>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="setup" element={<SetupPage />} />
      <Route path="login" element={<LoginPage />} />
      <Route path="invite/:token" element={<InvitePage />} />
      <Route path="forgot" element={<ForgotPage />} />
      <Route path="reset/:token" element={<ResetPage />} />
      <Route path="mail/:token" element={<MailConfirmPage />} />
      <Route path="absender/:token" element={<SenderConfirmPage />} />
      <Route path="l/:token" element={<LinkPage />} />
      <Route path="x/:token" element={<ExportLinkPage />} />
      <Route element={<SignedInPart />}>
        <Route path="schnell" element={<QuickPage />} />
        <Route path="teilen" element={<QuickPage shared />} />
        <Route
          path="kamera"
          element={
            <Suspense fallback={<div className="fixed inset-0 bg-[#0d0b09]" />}>
              <CameraPage />
            </Suspense>
          }
        />
        <Route path="oauth/authorize" element={<OAuthPage />} />
        <Route element={<AppShell />}>
          <Route index element={<ArchivePage />} />
          <Route path="eingang" element={<InboxPage />} />
          <Route path="eingang/:id" element={<InboxPage />} />
          <Route path="dokument/:id" element={<DocumentPage />} />
          <Route path="fristen" element={<DeadlinesRoute />} />
          <Route path="papierkorb" element={<TrashPage />} />
          <Route path="tresore" element={<VaultsPage />} />
          <Route path="ordnung" element={<OrderPage />} />
          <Route path="konto" element={<AccountPage />} />
          <Route path="einstellungen" element={<SettingsPage />} />
          <Route path="ueber" element={<AboutPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
