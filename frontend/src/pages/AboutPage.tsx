/**
 * About nexpaper, as the mock (and nexlore): version, licence, where it comes from, whether a newer one is out, and
 * what it is built with. Reached from the account menu.
 *
 * The switch for the daily check stands here, where its answer shows, and the page says what goes out. Every account
 * sees the answer; switching and asking now belong to the operator, because the question goes out for the whole
 * installation.
 */
import { BookOpen, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ApiError } from '../api/client'
import { LogoMark } from '../components/Logo'
import { WhatsNewWindow } from '../components/WhatsNew'
import { useWhatsNew } from '../lib/whatsNew'
import { useAuth } from '../state/auth'
import { Button, Card, Feedback, Toggle } from './settings/ui'

type About = { version: string; license: string; repo_url: string; releases_url: string; project_url: string }
type Updates = { update_check: boolean; checked: boolean; latest: string | null; newer: boolean; checked_at: string | null; release_url: string | null }

const PARTS = [
  { name: 'FastAPI', url: 'https://fastapi.tiangolo.com', licence: 'MIT' },
  { name: 'SQLAlchemy', url: 'https://www.sqlalchemy.org', licence: 'MIT' },
  { name: 'SQLite', url: 'https://sqlite.org', licence: 'Public Domain' },
  { name: 'OCRmyPDF', url: 'https://ocrmypdf.readthedocs.io', licence: 'MPL-2.0' },
  { name: 'Tesseract', url: 'https://tesseract-ocr.github.io', licence: 'Apache-2.0' },
  { name: 'pikepdf', url: 'https://pikepdf.readthedocs.io', licence: 'MPL-2.0' },
  { name: 'img2pdf', url: 'https://gitlab.mister-muffin.de/josch/img2pdf', licence: 'LGPL-3.0' },
  { name: 'pypdfium2', url: 'https://github.com/pypdfium2-team/pypdfium2', licence: 'Apache-2.0' },
  { name: 'Pillow', url: 'https://python-pillow.org', licence: 'MIT-CMU' },
  { name: 'React', url: 'https://react.dev', licence: 'MIT' },
  { name: 'Vite', url: 'https://vite.dev', licence: 'MIT' },
  { name: 'Tailwind CSS', url: 'https://tailwindcss.com', licence: 'MIT' },
  { name: 'PDF.js', url: 'https://mozilla.github.io/pdf.js', licence: 'Apache-2.0' },
  { name: 'OpenCV.js', url: 'https://opencv.org', licence: 'Apache-2.0' },
  { name: 'jscanify', url: 'https://github.com/ColonelParrot/jscanify', licence: 'MIT' },
  { name: 'Lucide', url: 'https://lucide.dev', licence: 'ISC' },
  { name: 'i18next', url: 'https://www.i18next.com', licence: 'MIT' },
]
const FONTS = ['Fraunces', 'Figtree']

function Out({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="text-accent underline decoration-accent/40 underline-offset-4 hover:decoration-accent">
      {children}
    </a>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line py-3 last:border-b-0">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="text-sm font-semibold">{children}</dd>
    </div>
  )
}

function code(error: unknown): string {
  return error instanceof ApiError ? error.code : 'internal_error'
}

export function AboutPage() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const operator = me?.role === 'operator'
  const [about, setAbout] = useState<About | null>(null)
  const [updates, setUpdates] = useState<Updates | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // The written text of the running version, to read again at any time.
  const { entry } = useWhatsNew(me?.version, i18n.language)
  const [reading, setReading] = useState(false)

  const load = useCallback(() => {
    api<About>('/api/v1/about').then(setAbout, (error: unknown) => setProblem(code(error)))
    // The answer is a side matter: when it does not come, the page simply shows none.
    api<Updates>('/api/v1/about/updates').then(setUpdates, () => setUpdates(null))
  }, [])
  useEffect(load, [load])

  async function checkNow() {
    setBusy(true)
    try {
      setUpdates(await api<Updates>('/api/v1/about/updates/check', { method: 'POST' }))
      setProblem(null)
    } catch (error) {
      setProblem(code(error))
    } finally {
      setBusy(false)
    }
  }

  async function switchCheck(on: boolean) {
    if (updates) setUpdates({ ...updates, update_check: on })
    try {
      setUpdates(await api<Updates>('/api/v1/about/updates', { method: 'PUT', body: { update_check: on } }))
    } catch (error) {
      setProblem(code(error))
      load()
    }
  }

  const latest = updates?.latest?.replace(/^v/, '')
  return (
    <div className="page space-y-6 pt-8 pb-28 lg:pb-12">
      <div className="flex items-center gap-4">
        <LogoMark size={52} />
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">nexpaper</h1>
          <p className="text-sm text-ink-2">{t('about.subtitle')}</p>
        </div>
      </div>
      <Feedback problem={problem} />
      {about && (
        <dl className="card px-6 py-2" data-testid="about-facts">
          <Row label={t('about.version')}>
            <span className="flex flex-wrap items-center gap-2">
              <span data-testid="about-version">{about.version}</span>
              {updates?.newer && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs font-bold text-accent">{t('about.newer', { version: latest })}</span>}
            </span>
          </Row>
          {entry && me && (
            <Row label={t('about.whatsNew')}>
              <button type="button" onClick={() => setReading(true)} className="text-accent underline decoration-accent/40 underline-offset-4">
                {t('whatsNew.title', { version: me.version })}
              </button>
            </Row>
          )}
          <Row label={t('about.licence')}>
            <Out href="https://www.gnu.org/licenses/agpl-3.0.html">{about.license}</Out>
          </Row>
          <Row label={t('about.source')}>
            <Out href={about.repo_url}>{about.repo_url.replace(/^https:\/\//, '')}</Out>
          </Row>
          <Row label={t('about.releases')}>
            <Out href={about.releases_url}>{t('about.releasesLink')}</Out>
          </Row>
          {about.project_url && (
            <Row label={t('about.project')}>
              <Out href={about.project_url}>{about.project_url.replace(/^https:\/\//, '')}</Out>
            </Row>
          )}
          <Row label={t('about.report')}>
            <Out href={`${about.repo_url}/issues/new`}>{t('about.reportLink')}</Out>
          </Row>
        </dl>
      )}

      <Card icon={RefreshCw} title={t('about.updates.title')} text={t('about.updates.text')} id="about-updates">
        {operator && updates && <Toggle label={t('about.updates.daily')} hint={t('about.updates.dailyHint')} checked={updates.update_check} onChange={(on) => void switchCheck(on)} />}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm" aria-live="polite">
          {operator && (
            <Button onClick={() => void checkNow()} busy={busy}>
              {t('about.updates.now')}
            </Button>
          )}
          <span data-testid="about-update-state" className="text-ink-2">
            {!updates || !updates.checked ? (
              updates && !updates.update_check ? t('about.updates.off') : t('about.updates.notYet')
            ) : updates.newer ? (
              <>
                {t('about.newer', { version: latest })}
                {updates.release_url && (
                  <>
                    {' · '}
                    <Out href={updates.release_url}>{t('about.updates.toRelease')}</Out>
                  </>
                )}
              </>
            ) : updates.latest ? (
              t('about.updates.current')
            ) : (
              t('about.updates.none')
            )}
          </span>
          {updates?.checked_at && <span className="text-xs text-muted">{t('about.updates.checkedAt', { when: new Date(updates.checked_at).toLocaleString(i18n.language) })}</span>}
        </div>
        <p className="text-xs leading-relaxed text-muted">{t('about.updates.whatGoesOut')}</p>
      </Card>

      <Card icon={BookOpen} title={t('about.builtWith')}>
        <ul className="flex flex-wrap gap-x-3 gap-y-1.5 text-sm">
          {PARTS.map((part) => (
            <li key={part.name}>
              <Out href={part.url}>{part.name}</Out>
              <span className="ml-1 text-xs text-muted">({part.licence})</span>
            </li>
          ))}
        </ul>
        <h3 className="pt-1 text-xs font-bold tracking-wide text-muted uppercase">{t('about.fonts')}</h3>
        <p className="text-xs leading-relaxed text-muted">{t('about.fontsText')}</p>
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
          {FONTS.map((font) => (
            <li key={font}>
              {font}
              <span className="ml-1 text-xs text-muted">(OFL-1.1)</span>
            </li>
          ))}
        </ul>
      </Card>
      {reading && entry && me && <WhatsNewWindow version={me.version} entry={entry} onClose={() => setReading(false)} />}
    </div>
  )
}
