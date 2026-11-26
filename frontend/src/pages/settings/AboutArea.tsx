/**
 * About nexpaper, the ui kit's `AboutPage` (plan "Einstellungen", "Über"): the logo as a picture, version, "Was ist
 * neu" from nexpaper's own file, licence, where it comes from, whether a newer one is out, and what it is built with.
 * The last area of the settings, `/settings/about`; the old address `/ueber` leads there.
 *
 * The switch for the daily check stands here, where its answer shows, and the page says what goes out. Every account
 * sees the answer; switching and asking now belong to the operator, because the question goes out for the whole
 * installation.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ApiError } from '../../api/client'
import { APP_NAME } from '../../i18n'
import { errorText } from '../../lib/errors'
import { useWhatsNew } from '../../lib/whatsNew'
import { useAuth } from '../../state/auth'
import { AboutPage, Notice, type BuiltWith } from '../../vendor/nexui'

type About = { version: string; license: string; repo_url: string; releases_url: string; project_url: string }
type Updates = { update_check: boolean; checked: boolean; latest: string | null; newer: boolean; checked_at: string | null; release_url: string | null }

const PARTS: BuiltWith[] = [
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
const FONTS = ['Inter']

function code(error: unknown): string {
  return error instanceof ApiError ? error.code : 'internal_error'
}

export function AboutArea() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [about, setAbout] = useState<About | null>(null)
  const [updates, setUpdates] = useState<Updates | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // The written text of the running version, to read again at any time.
  const { entry } = useWhatsNew(me?.version, i18n.language)

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

  if (!about) return problem ? <Notice tone="danger">{errorText(problem)}</Notice> : null
  return (
    <AboutPage
      app={APP_NAME}
      logo="/logo.svg"
      tagline={t('about.subtitle')}
      version={about.version}
      licence={{ name: about.license, href: 'https://www.gnu.org/licenses/agpl-3.0.html' }}
      source={about.repo_url}
      releases={about.releases_url}
      project={about.project_url || null}
      whatsNew={entry}
      updates={
        updates
          ? {
              checkDaily: updates.update_check,
              checked: updates.checked,
              latest: updates.latest,
              newer: updates.newer,
              checkedAt: updates.checked_at ? new Date(updates.checked_at).toLocaleString(i18n.language) : null,
              releaseUrl: updates.release_url,
            }
          : null
      }
      operator={me?.role === 'operator'}
      onDaily={(on) => void switchCheck(on)}
      onCheck={() => void checkNow()}
      checking={busy}
      builtWith={PARTS}
      builtWithMore={
        <div className="flex flex-col gap-1" data-testid="about-fonts">
          <h3 className="m-0 text-xs font-semibold text-[var(--nexui-text-muted)]">{t('about.fonts')}</h3>
          <p className="m-0 text-xs leading-relaxed text-[var(--nexui-text-muted)]">{t('about.fontsText')}</p>
          <ul className="m-0 flex list-none flex-wrap gap-x-3 gap-y-1 p-0 text-sm">
            {FONTS.map((font) => (
              <li key={font}>
                {font}
                <span className="ml-1 text-xs text-[var(--nexui-text-muted)]">(OFL-1.1)</span>
              </li>
            ))}
          </ul>
        </div>
      }
      problem={problem ? errorText(problem) : null}
      texts={{ updatesWhatGoesOut: t('about.updates.whatGoesOut') }}
    />
  )
}
