/**
 * "Share" on a document: with people of this server (one document, a right) on the left, by a link
 * to the outside on the right. The dialog loads what it shows itself (who it is shared with, the links, the people, the
 * operator's rules) and changes it through the API at once; the document page that opens it comes with its block.
 *
 * A new link is copied right away. Every link can be copied again ("Kopieren") by the person who made it and by the
 * managers of the vault: the server keeps the address sealed and hands it out on request (and notes it in the history).
 * Where the clipboard refuses, the address stands in a field to copy by hand.
 */
import { Link2, Users, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, sharingApi, vaultsApi, type DocumentInfo, type DocumentLink, type DocumentShare, type Person, type SharingRules, type Vault } from '../api/client'
import { copyText } from '../lib/copy'
import { dayInDays, daysUntil, shortDate } from '../lib/dates'
import { asAvatarPerson, personName } from '../lib/people'
import { CopyLink, Feedback } from '../pages/settings/ui'
import { Avatar } from './Avatar'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { useConfirm } from './useConfirm'
import { iso } from '../lib/say'

type Props = {
  document: Pick<DocumentInfo, 'id' | 'vault_id' | 'title'>
  onClose: () => void
  /** What was done, in a sentence, for the page to show (a toast); the dialog itself shows problems. */
  say?: (text: string) => void
}

export function ShareDialog({ document, onClose, say }: Props) {
  const { t, i18n } = useTranslation()
  const [shares, setShares] = useState<DocumentShare[]>([])
  const [links, setLinks] = useState<DocumentLink[]>([])
  const [people, setPeople] = useState<Person[]>([])
  const [vault, setVault] = useState<Vault | null>(null)
  const [rules, setRules] = useState<SharingRules | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  /** An address the clipboard did not take, shown under its link to copy by hand. */
  const [shown, setShown] = useState<{ id: number; url: string } | null>(null)

  const [person, setPerson] = useState('')
  const [right, setRight] = useState<'read' | 'edit'>('read')
  const [to, setTo] = useState('')
  const [until, setUntil] = useState('')
  const [download, setDownload] = useState(true)
  const { ask, dialog } = useConfirm()

  const fail = useCallback((error: unknown) => {
    setProblem(error instanceof ApiError ? error.code : 'internal_error')
    setValues(error instanceof ApiError ? error.values : {})
  }, [])
  const run = useCallback(
    async (work: () => Promise<void>) => {
      setProblem(null)
      try {
        await work()
      } catch (error) {
        fail(error)
      }
    },
    [fail],
  )
  const loadLinks = useCallback(() => sharingApi.links(document.id).then(setLinks), [document.id])

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const [sharedWith, ruleSet, everybody, vaults] = await Promise.all([sharingApi.shares(document.id), sharingApi.rules(), vaultsApi.people(), vaultsApi.list()])
        if (!alive) return
        setShares(sharedWith)
        setRules(ruleSet)
        setPeople(everybody)
        setVault(vaults.find((v) => v.id === document.vault_id) ?? null)
        setUntil(dayInDays(Math.min(7, ruleSet.link_max_days)))
        if (ruleSet.links_allowed) {
          const found = await sharingApi.links(document.id)
          if (alive) setLinks(found)
        }
      } catch (error) {
        if (alive) fail(error)
      }
    }
    void load()
    return () => {
      alive = false
    }
  }, [document.id, document.vault_id, fail])

  const inVault = new Set(vault?.members.map((m) => m.user_id) ?? [])
  const others = people.filter((p) => !inVault.has(p.id) && !shares.some((s) => s.user.id === p.id))
  const inVaultNames = (vault?.members ?? []).map((m) => m.display_name || m.name).join(', ')
  const days = until ? daysUntil(until) : 0
  const latest = rules ? dayInDays(rules.link_max_days) : undefined

  const share = () =>
    run(async () => {
      const id = Number(person)
      if (!id) return
      const done = await sharingApi.share(document.id, id, right)
      setShares((current) => [...current.filter((s) => s.user.id !== id), done])
      setPerson('')
      say?.(t('share.shared', { name: personName(done.user) }))
    })
  /** Ends the share of one person, after asking. */
  const stop = (target: DocumentShare) =>
    ask({
      title: t('confirm.unshare.title'),
      text: t('confirm.unshare.text', { name: iso(personName(target.user)), title: iso(document.title) }),
      confirm: t('confirm.unshare.confirm'),
      run: async () => {
        await sharingApi.unshare(document.id, target.user.id)
        setShares((current) => current.filter((s) => s.user.id !== target.user.id))
        say?.(t('share.unshared', { name: personName(target.user) }))
      },
    })
  const makeLink = () =>
    run(async () => {
      if (!to.trim()) return
      const link = await sharingApi.makeLink(document.id, to.trim(), Math.max(1, days), download)
      setTo('')
      await loadLinks()
      const copied = await copyText(link.url)
      setShown(copied ? null : { id: link.id, url: link.url })
      say?.(copied ? t('share.madeCopied') : t('share.madeShown'))
    })
  const copy = (link: DocumentLink) =>
    run(async () => {
      const { url } = await sharingApi.address(document.id, link.id)
      const copied = await copyText(url)
      setShown(copied ? null : { id: link.id, url })
      if (copied) say?.(t('share.copied'))
    })
  const preview = (link: DocumentLink) => {
    // The tab opens at the click (one opened later would be taken for a popup); the address follows.
    const tab = window.open('', '_blank')
    void run(async () => {
      try {
        const { url } = await sharingApi.address(document.id, link.id)
        if (tab) {
          tab.opener = null
          tab.location.href = url
        }
      } catch (error) {
        tab?.close()
        throw error
      }
    })
  }
  /** Withdraws a link, after asking. */
  const revoke = (link: DocumentLink) =>
    ask({
      title: t('confirm.link.title'),
      text: t('confirm.link.text', { title: iso(document.title) }),
      confirm: t('confirm.link.confirm'),
      run: async () => {
        await sharingApi.revokeLink(document.id, link.id)
        if (shown?.id === link.id) setShown(null)
        await loadLinks()
        say?.(t('share.withdrawn'))
      },
    })

  const shownLinks = links.filter((l) => l.status !== 'revoked')
  return (
    <Dialog title={t('share.title')} onClose={onClose} wide>
      <div className="grid gap-6 sm:grid-cols-2">
        <div>
          <p className="flex items-center gap-2 font-semibold">
            <Users size={16} aria-hidden /> {t('share.people')}
          </p>
          {vault && <p className="mt-1 text-xs text-muted">{t('share.peopleText', { vault: vault.name, names: inVaultNames })}</p>}
          <ul className="mt-3 space-y-2">
            {shares.map((s) => (
              <li key={s.user.id} className="flex items-center gap-2 rounded-xl bg-sheet-2/60 px-3 py-2 text-sm">
                <Avatar person={asAvatarPerson(s.user)} size={24} />
                <span className="flex-1 font-semibold">{personName(s.user)}</span>
                <span className="text-muted">{t(`rights.${s.right}.name`)}</span>
                <button type="button" onClick={() => stop(s)} className="rounded-full p-1 text-muted hover:text-ink" aria-label={`${t('share.stop')}: ${personName(s.user)}`}>
                  <X size={14} />
                </button>
              </li>
            ))}
          </ul>
          {others.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <select value={person} onChange={(e) => setPerson(e.target.value)} aria-label={t('share.choose')} className="input h-9 w-full min-w-0">
                <option value="">{t('share.choose')}</option>
                {others.map((p) => (
                  <option key={p.id} value={p.id}>
                    {personName(p)}
                  </option>
                ))}
              </select>
              <select value={right} onChange={(e) => setRight(e.target.value as 'read' | 'edit')} aria-label={t('share.right')} className="input h-9 min-w-0 flex-1">
                <option value="read">{t('rights.read.name')}</option>
                <option value="edit">{t('rights.edit.name')}</option>
              </select>
              <Button size="sm" variant="soft" onClick={() => void share()} disabled={!person}>
                {t('share.do')}
              </Button>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted">{people.length > 1 ? t('share.everyone') : t('share.noPeople')}</p>
          )}
        </div>

        <div>
          <p className="flex items-center gap-2 font-semibold">
            <Link2 size={16} aria-hidden /> {t('share.link')}
          </p>
          {rules && !rules.links_allowed ? (
            <p className="mt-2 text-sm text-muted">{t('share.linksOff')}</p>
          ) : (
            <>
              <p className="mt-1 text-xs text-muted">{t('share.linkText')}</p>
              <ul className="mt-3 space-y-2">
                {shownLinks.map((l) => {
                  const live = l.status === 'active'
                  return (
                    <li key={l.id} className="rounded-xl bg-sheet-2/60 px-3 py-2 text-sm">
                      <div className="flex items-center gap-2">
                        <span className="flex-1 font-semibold">{l.recipient}</span>
                        {l.can_copy && live && (
                          <button type="button" onClick={() => void copy(l)} className="text-xs font-semibold text-accent" aria-label={t('share.copyFor', { name: l.recipient })}>
                            {t('share.copy')}
                          </button>
                        )}
                        <button type="button" onClick={() => revoke(l)} className="text-xs font-semibold text-muted hover:text-ink">
                          {t('share.withdraw')}
                        </button>
                      </div>
                      <p className="text-xs text-muted">
                        {t('share.linkMeta', { until: shortDate(l.until, i18n.language), count: l.opened_count })}
                        {l.status === 'expired' && ` · ${t('share.expired')}`}
                        {l.status === 'off' && ` · ${t('share.off')}`}
                        {l.status === 'ended' && ` · ${t('share.ended')}`}
                        {l.can_copy && live && (
                          <>
                            {' · '}
                            <button type="button" onClick={() => preview(l)} className="underline" aria-label={t('share.previewFor', { name: l.recipient })}>
                              {t('share.preview')}
                            </button>
                          </>
                        )}
                      </p>
                      {shown?.id === l.id && (
                        <div className="mt-2">
                          <CopyLink value={shown.url} label={t('share.copyHere')} />
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
              <div className="mt-3 space-y-2">
                <input value={to} onChange={(e) => setTo(e.target.value)} maxLength={100} placeholder={t('share.forWhom')} aria-label={t('share.forWhom')} className="input h-9" />
                <div className="flex items-center gap-2 text-sm">
                  <label htmlFor="share-until" className="text-muted">
                    {t('share.validUntil')}
                  </label>
                  <input id="share-until" type="date" value={until} min={dayInDays(1)} max={latest} onChange={(e) => setUntil(e.target.value)} className="input h-9 flex-1" />
                </div>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={download} onChange={(e) => setDownload(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
                  {t('share.allowDownload')}
                </label>
                <Button size="sm" variant="soft" onClick={() => void makeLink()} disabled={!to.trim() || !until}>
                  <Link2 size={14} aria-hidden /> {t('share.makeLink')}
                </Button>
                {rules && <p className="text-xs text-muted">{t('share.maxDays', { days: rules.link_max_days })}</p>}
              </div>
            </>
          )}
        </div>
      </div>
      <div className="mt-4">
        <Feedback problem={problem} values={values} />
      </div>
      {dialog}
    </Dialog>
  )
}
