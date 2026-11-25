/**
 * Since 1.1.0: the area "About <app>", as nexnotes' (`AboutArea.tsx`), the same in every app. Three cards:
 *
 * 1. The head (`id="about"`): the app's logo as a picture (never a hand-written word mark), its name and its sentence;
 *    under it the facts: Version (with the badge "Version x is out"), "What's new" (a `sm` button that opens the text
 *    of the running version), Licence, Source code, Releases, Project page (only where it differs from the source),
 *    "Found a problem?".
 * 2. "Updates" (`id="about-updates"`, RefreshCw): "Check once a day" (the operator's), "Check now" (secondary, the
 *    operator's), the state, and what goes out.
 * 3. "Built with" (`id="about-built-with"`): the parts with their licences; `builtWithMore` below them (the fonts).
 *
 * The page only shows: what the server says and what happens on a click are the caller's (`updates`, `onDaily`,
 * `onCheck`). `WhatsNewDialog` is the window of "What's new" (the shape nexpaper, nexlore and nexdiary keep in
 * `i18n/whatsnew/<language>.json`), for the banner after an update too.
 */
import { useState, type ReactNode } from 'react'

import { Button } from './Button'
import { Badge, Card } from './Card'
import { Dialog } from './Dialog'
import { Facts, type Fact } from './Facts'
import { CheckboxRow } from './Field'
import { HINT, MUTED, PLAIN } from './styles'
import { fill, useNexuiTexts, type NexuiTexts } from './texts'

export type BuiltWith = { name: string; url: string; licence: string }

export type WhatsNewLink = { label: string; href: string }
export type WhatsNewSection = { title: string; where: string; body: string; link?: WhatsNewLink }
export type WhatsNewEntry = { lead: string; sections: readonly WhatsNewSection[]; smallTitle: string; small: readonly string[] }

/** What the server knows about newer versions (nexnotes' `/api/about/updates`). */
export type AboutUpdates = {
  /** Whether the server checks once a day by itself. */
  checkDaily: boolean
  /** Whether it has checked at all. */
  checked: boolean
  /** The newest release found ("v1.2.0" or "1.2.0"). */
  latest: string | null
  newer: boolean
  /** When it last checked, already in the reader's words ("today, 09:12"). */
  checkedAt?: string | null
  releaseUrl?: string | null
}

const LINK = 'text-[var(--nexui-accent-text)] underline decoration-[color-mix(in_srgb,var(--nexui-accent-text)_40%,transparent)] underline-offset-4 hover:decoration-[var(--nexui-accent-text)]'

function Out({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className={LINK}>
      {children}
    </a>
  )
}

const bare = (url: string) => url.replace(/^https?:\/\//, '').replace(/\/$/, '')

export function AboutPage({
  app,
  logo,
  tagline,
  version,
  licence,
  source,
  releases,
  project,
  report,
  whatsNew,
  updates,
  operator = false,
  onDaily,
  onCheck,
  checking = false,
  builtWith,
  builtWithMore,
  problem,
  texts: own,
  children,
}: {
  app: string
  /** The address of the app's logo. */
  logo: string
  /** The app's sentence under its name. */
  tagline: ReactNode
  version: string
  licence: { name: string; href: string }
  /** The source code (the repository). */
  source: string
  releases?: string
  /** The project page, only where it is not the repository. */
  project?: string | null
  /** Where to report a problem (default: new issue at the source). */
  report?: string
  /** The text of the running version; without, no row "What's new". */
  whatsNew?: WhatsNewEntry | null
  updates?: AboutUpdates | null
  /** Only the operator switches the daily check and checks now. */
  operator?: boolean
  onDaily?: (on: boolean) => void
  onCheck?: () => void
  checking?: boolean
  builtWith: readonly BuiltWith[]
  builtWithMore?: ReactNode
  /** What went wrong (loading, checking), above the cards. */
  problem?: ReactNode
  /** The app's own words for some of the kit's (`updatesWhatGoesOut` names what the app never sends). */
  texts?: Partial<NexuiTexts>
  /** More cards after these (rarely; the plan puts nothing else here). */
  children?: ReactNode
}) {
  const texts = { ...useNexuiTexts(), ...own }
  const [reading, setReading] = useState(false)
  const latest = updates?.latest?.replace(/^v/, '') ?? ''
  const newer = updates?.newer ? fill(texts.aboutNewer, { version: latest }) : null
  const facts: Fact[] = [
    {
      label: texts.aboutVersion,
      value: (
        <span className="inline-flex flex-wrap items-center justify-end gap-2">
          <span data-testid="about-version">{version}</span>
          {newer && <Badge tone="accent">{newer}</Badge>}
        </span>
      ),
    },
  ]
  if (whatsNew) {
    facts.push({
      label: texts.aboutWhatsNew,
      value: (
        <Button kind="secondary" size="sm" icon="Sparkles" onClick={() => setReading(true)} testId="about-whats-new">
          {fill(texts.aboutWhatsNewButton, { app, version })}
        </Button>
      ),
    })
  }
  facts.push(
    { label: texts.aboutLicence, value: <Out href={licence.href}>{licence.name}</Out> },
    { label: texts.aboutSource, value: <Out href={source}>{bare(source)}</Out> },
  )
  if (releases) facts.push({ label: texts.aboutReleases, value: <Out href={releases}>{texts.aboutReleasesLink}</Out> })
  if (project && bare(project) !== bare(source)) facts.push({ label: texts.aboutProject, value: <Out href={project}>{bare(project)}</Out> })
  facts.push({ label: texts.aboutReport, value: <Out href={report ?? `${source.replace(/\/$/, '')}/issues/new`}>{texts.aboutReportLink}</Out> })

  const state = !updates || !updates.checked ? (updates && !updates.checkDaily ? texts.updatesOff : texts.updatesNotYet) : null
  return (
    <div className="flex min-w-0 flex-col gap-6" data-testid="about-area">
      {problem && (
        <p role="alert" className={`${PLAIN} text-sm leading-5 text-[var(--nexui-danger)]`}>
          {problem}
        </p>
      )}
      <Card id="about" icon="Info" logo={logo} title={app} subtitle={tagline}>
        <Facts items={facts} label={fill(texts.aboutApp, { app })} testId="about-facts" />
      </Card>

      <Card id="about-updates" icon="RefreshCw" title={texts.updatesTitle} subtitle={fill(texts.updatesText, { app })}>
        {operator && updates && onDaily && <CheckboxRow label={texts.updatesDaily} hint={texts.updatesDailyHint} checked={updates.checkDaily} onChange={onDaily} testId="about-daily" />}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm leading-5" aria-live="polite">
          {operator && onCheck && (
            <Button kind="secondary" icon="RefreshCw" busy={checking} onClick={onCheck} testId="about-check">
              {texts.updatesNow}
            </Button>
          )}
          <span data-testid="about-update-state" className={MUTED}>
            {state ??
              (updates?.newer ? (
                <>
                  {newer}
                  {updates.releaseUrl && (
                    <>
                      {' · '}
                      <Out href={updates.releaseUrl}>{texts.updatesToRelease}</Out>
                    </>
                  )}
                </>
              ) : updates?.latest ? (
                texts.updatesCurrent
              ) : (
                texts.updatesNone
              ))}
          </span>
          {updates?.checkedAt && <span className={`${PLAIN} text-xs leading-4 ${MUTED}`}>{fill(texts.updatesCheckedAt, { when: updates.checkedAt })}</span>}
        </div>
        <p className={HINT}>{fill(texts.updatesWhatGoesOut, { app })}</p>
      </Card>

      <Card id="about-built-with" icon="BookOpen" title={texts.builtWith}>
        <ul className="m-0 flex list-none flex-wrap gap-x-3 gap-y-1.5 p-0 text-sm leading-5" data-testid="about-built-with">
          {builtWith.map((part) => (
            <li key={part.name}>
              <Out href={part.url}>{part.name}</Out>
              <span className={`ml-1 text-xs leading-4 ${MUTED}`}>({part.licence})</span>
            </li>
          ))}
        </ul>
        {builtWithMore}
      </Card>
      {children}
      {reading && whatsNew && <WhatsNewDialog app={app} version={version} entry={whatsNew} onClose={() => setReading(false)} logo={logo} />}
    </div>
  )
}

/** The text of one version: its lead, each part with where to find it, the small things at the end. */
export function WhatsNewDialog({ app, version, entry, logo, onClose }: { app: string; version: string; entry: WhatsNewEntry; logo?: string; onClose: () => void }) {
  const texts = useNexuiTexts()
  return (
    <Dialog title={fill(texts.aboutWhatsNewButton, { app, version })} onClose={onClose} closeLabel={texts.close} testId="whats-new-window">
      <div className="flex flex-col gap-4 text-sm leading-5 tracking-normal">
        <div className="flex items-start gap-3">
          {logo && <img src={logo} alt="" className="h-9 w-9 shrink-0 rounded-[12px]" />}
          <p className={`${PLAIN} text-[var(--nexui-text)]`}>{entry.lead}</p>
        </div>
        <ul className="m-0 flex list-none flex-col gap-4 p-0">
          {entry.sections.map((part) => (
            <li key={part.title}>
              <h3 className={`${PLAIN} text-sm leading-5 font-semibold text-[var(--nexui-text)]`}>{part.title}</h3>
              <p className={`${PLAIN} ${MUTED}`}>{part.body}</p>
              {part.link && part.link.href.startsWith('https://') && (
                <a href={part.link.href} target="_blank" rel="noopener noreferrer" className={`mt-1 inline-block text-sm font-semibold ${LINK}`}>
                  {part.link.label}
                </a>
              )}
              <p className={`${HINT} mt-1`}>
                <span className="font-semibold">{texts.whatsNewWhere}</span> {part.where}
              </p>
            </li>
          ))}
        </ul>
        {entry.small.length > 0 && (
          <section>
            <h3 className={`${PLAIN} text-xs leading-4 font-semibold tracking-wide uppercase ${MUTED}`}>{entry.smallTitle}</h3>
            <ul className={`mt-1.5 list-disc pl-5 ${MUTED}`}>
              {entry.small.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>
        )}
        <div className="flex justify-end">
          <Button kind="primary" icon="Check" onClick={onClose}>
            {texts.whatsNewDone}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
