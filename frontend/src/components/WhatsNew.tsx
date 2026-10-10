/**
 * "What's new", as in nexlore: a banner above the page after an update, for every account, and the window with the
 * written text of the version. Each account puts it away for itself (`POST /api/v1/me/whats-new/seen`); the server keeps
 * which version it read, so it does not come back on another device.
 */
import { Sparkles, X } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { authApi } from '../api/client'
import { useWhatsNew, type WhatsNewEntry } from '../lib/whatsNew'
import { useAuth } from '../state/auth'
import { LogoMark } from './Logo'

export function WhatsNewWindow({ version, entry, onClose }: { version: string; entry: WhatsNewEntry; onClose: () => void }) {
  const { t } = useTranslation()
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const element = dialog.current
    if (element && !element.open) element.showModal()
  }, [])
  return (
    <dialog
      ref={dialog}
      aria-labelledby={titleId}
      data-testid="whats-new-window"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose()
      }}
      className="card m-auto max-h-[90dvh] w-[min(32rem,calc(100vw-2rem))] p-0 text-ink backdrop:bg-scrim"
    >
      <div className="p-6">
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <LogoMark size={34} />
            <h2 id={titleId} className="font-display text-xl font-semibold">
              {t('whatsNew.title', { version })}
            </h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-full p-2 text-muted hover:bg-sheet-2" aria-label={t('common.close')}>
            <X size={18} />
          </button>
        </div>
        <p className="mb-4 text-sm text-ink-2">{entry.lead}</p>
        <ul className="space-y-4">
          {entry.sections.map((part) => (
            <li key={part.title}>
              <h3 className="font-semibold">{part.title}</h3>
              <p className="text-sm text-ink-2">{part.body}</p>
              <p className="mt-1 text-xs text-muted">
                <span className="font-bold">{t('whatsNew.where')}</span> {part.where}
              </p>
            </li>
          ))}
        </ul>
        {entry.small.length > 0 && (
          <section className="mt-5">
            <h3 className="text-xs font-bold tracking-wide text-muted uppercase">{entry.smallTitle}</h3>
            <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-ink-2">
              {entry.small.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>
        )}
        <div className="mt-6 flex justify-end">
          <button type="button" onClick={onClose} className="inline-flex h-10 items-center rounded-full bg-accent px-4 text-sm font-semibold text-accent-ink hover:brightness-105">
            {t('whatsNew.done')}
          </button>
        </div>
      </div>
    </dialog>
  )
}

/** Above the page, as long as the running version has a text the account has not read or put away. */
export function WhatsNewBanner() {
  const { t, i18n } = useTranslation()
  const { me, refresh } = useAuth()
  const unread = !!me && me.whats_new_seen !== me.version
  const { entry } = useWhatsNew(me?.version, i18n.language, unread)
  const [open, setOpen] = useState(false)
  const [gone, setGone] = useState(false)
  if (!me || !unread || !entry || gone) return null

  function putAway() {
    setGone(true)
    void authApi.whatsNewSeen().then(() => refresh(), () => undefined)
  }

  return (
    <div className="page pt-4">
      <div className="flex items-center gap-3 rounded-2xl bg-accent-soft px-4 py-2.5 text-sm" role="status" data-testid="whats-new-banner">
        <Sparkles size={16} className="shrink-0 text-accent" />
        <span className="min-w-0 flex-1 font-semibold">{t('whatsNew.banner', { version: me.version })}</span>
        <button type="button" onClick={() => setOpen(true)} className="h-8 rounded-full bg-accent px-3.5 text-xs font-semibold text-accent-ink hover:brightness-105">
          {t('whatsNew.show')}
        </button>
        <button type="button" onClick={putAway} aria-label={t('whatsNew.putAway')} title={t('whatsNew.putAway')} className="rounded-full p-1 text-muted hover:text-ink">
          <X size={15} />
        </button>
      </div>
      {open && (
        <WhatsNewWindow
          version={me.version}
          entry={entry}
          onClose={() => {
            setOpen(false)
            putAway()
          }}
        />
      )}
    </div>
  )
}
