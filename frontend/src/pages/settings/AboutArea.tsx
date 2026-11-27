/**
 * About nexpaper, the ui kit's `AboutPage` (plan "Einstellungen", "Über"): the logo as a picture, version, "Was ist
 * neu" from the shared module wasneu (the newest text and the earlier versions; reading here puts nothing away), licence, where it comes from, whether a newer one is out, and what it is built with.
 * The last area of the settings, `/settings/about`; the old address `/ueber` leads there.
 *
 * The card "Aktualisierungen" comes from the shared module `nexupdates` (updates 0.1.3): only an operator sees it,
 * switches the daily question and asks now (U2, U15), because the question goes out for the whole installation; a
 * member's page shows the own version and asks for nothing else. The sentence on what goes out names the address and
 * nexpaper's other calls by itself (U11). nexpaper has no bell: the hint under the switch says the background looks
 * once a day only while a device of an operator wants to hear of new versions (U24, `dailyHint`).
 */
import { useTranslation } from 'react-i18next'

import { tabFetch } from '../../api/client'
import { APP_NAME } from '../../i18n'
import { useAuth } from '../../state/auth'
import { AboutPage, Notice, formatMoment, type BuiltWith } from '../../vendor/nexui'
import { dailyHint, useUpdates, useUpdatesTexts, whatGoesOut } from '../../vendor/nexupdates/updates'
import { useAboutWhatsNew } from '../../vendor/nexwasneu/useWhatsNew'

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

/** A moment as all nex apps write it (E65, ui `formatMoment`): "heute, 09:12", else "26.11.2026, 09:12". */
function when(language: string): (iso: string) => string {
  return (iso) => formatMoment(iso, language)
}

export function AboutArea() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const operator = me?.role === 'operator'
  // The written text of the running version and the earlier ones, to read again at any time.
  const news = useAboutWhatsNew({ app: APP_NAME, logo: '/logo.svg', fetcher: tabFetch, base: '/api/v1/whats-new', language: i18n.language })
  const texts = useUpdatesTexts(i18n.language)
  const { about, updates, showUpdates, onDaily, onCheck, checking, problem } = useUpdates({
    fetcher: tabFetch,
    base: '/api/v1/about',
    operator,
    when: when(i18n.language),
    language: i18n.language,
  })

  if (!about) return problem ? <Notice tone="danger">{problem}</Notice> : null
  return (
    <>
      <AboutPage
        app={APP_NAME}
        logo="/logo.svg"
        tagline={t('about.subtitle')}
        version={about.version}
        licence={{ name: about.license, href: 'https://www.gnu.org/licenses/agpl-3.0.html' }}
        source={about.repo_url}
        releases={about.releases_url}
        project={about.project_url || null}
        {...news.about}
        updates={updates}
        showUpdates={showUpdates}
        operator={operator}
        onDaily={onDaily}
        onCheck={onCheck}
        checking={checking}
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
        problem={problem}
        texts={{
          updatesWhatGoesOut: whatGoesOut(texts, APP_NAME, undefined, [t('about.updates.otherCalls')]),
          updatesDailyHint: dailyHint(texts, { bell: false, devices: true }),
        }}
      />
      {news.window}
    </>
  )
}
