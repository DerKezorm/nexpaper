/**
 * Upload requests (U1), the side of the person who asks: the button "Um ein Dokument bitten" in the inbox, its dialog
 * (from whom, valid until, how many files; the address is copied right away), and the list of the own requests with how
 * many files came and when the last one came, to copy again or to withdraw (after asking). The same list stands under
 * My account, Upload. Everything goes through `/api/v1/upload-requests`; the page a stranger sees is
 * `pages/UploadRequestPage.tsx`.
 *
 * Off (the operator's switch) or without a public address, the dialog says what is missing instead of a form.
 */
import { Inbox, Send } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { errorText } from '../lib/errors'
import { ApiError, uploadRequestsApi, type RequestRules, type UploadRequestInfo } from '../api/client'
import { copyText } from '../lib/copy'
import { dayInDays, daysUntil, shortDate } from '../lib/dates'
import { iso, moment } from '../lib/say'
import { Card, CopyLink, Feedback } from '../pages/settings/ui'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { useConfirm } from './useConfirm'

/** What the list and the dialog share: the rules, the own requests, the address shown to copy by hand, the problem. */
function useRequests() {
  const [rules, setRules] = useState<RequestRules | null>(null)
  const [items, setItems] = useState<UploadRequestInfo[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const fail = useCallback((error: unknown) => {
    setProblem(error instanceof ApiError ? error.code : 'internal_error')
    setValues(error instanceof ApiError ? error.values : {})
  }, [])
  const load = useCallback(async () => {
    try {
      const [found, list] = await Promise.all([uploadRequestsApi.rules(), uploadRequestsApi.mine()])
      setRules(found)
      setItems(Array.isArray(list) ? list : [])
    } catch (error) {
      fail(error)
    }
  }, [fail])
  useEffect(() => {
    void load()
  }, [load])
  return { rules, items, setItems, load, problem, setProblem, values, fail }
}

type Shared = ReturnType<typeof useRequests>

/** A refusal of the server in a sentence: the requests' own words first, else the app's. */
function Problem({ state }: { state: Shared }) {
  const { t } = useTranslation()
  if (!state.problem) return null
  return (
    <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {t(`uploadRequest.errors.${state.problem}`, { ...state.values, defaultValue: errorText(state.problem, state.values) })}
    </p>
  )
}

/** The own requests, newest first. */
function RequestList({ state, say }: { state: Shared; say?: (text: string) => void }) {
  const { t, i18n } = useTranslation()
  const { ask, dialog } = useConfirm()
  const [shown, setShown] = useState<{ id: number; url: string } | null>(null)
  const copy = async (item: UploadRequestInfo) => {
    state.setProblem(null)
    try {
      const { url } = await uploadRequestsApi.address(item.id)
      const copied = await copyText(url)
      setShown(copied ? null : { id: item.id, url })
      if (copied) say?.(t('uploadRequest.copied'))
    } catch (error) {
      state.fail(error)
    }
  }
  const withdraw = (item: UploadRequestInfo) =>
    ask({
      title: t('uploadRequest.confirm.title'),
      text: t('uploadRequest.confirm.text', { name: iso(item.name) }),
      confirm: t('uploadRequest.confirm.confirm'),
      run: async () => {
        await uploadRequestsApi.revoke(item.id)
        state.setItems((had) => had.filter((r) => r.id !== item.id))
        if (shown?.id === item.id) setShown(null)
        say?.(t('uploadRequest.withdrawn'))
      },
    })
  if (state.items.length === 0) return <p className="text-sm text-muted">{t('uploadRequest.listEmpty')}</p>
  return (
    <>
      <ul className="space-y-2" aria-label={t('uploadRequest.listTitle')} data-testid="request-list">
        {state.items.map((item) => {
          const live = item.status === 'active'
          return (
            <li key={item.id} className="rounded-xl bg-sheet-2/60 px-3 py-2 text-sm">
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-semibold">
                  <bdi>{item.name}</bdi>
                </span>
                {live && (
                  <button type="button" onClick={() => void copy(item)} className="text-xs font-semibold text-accent" aria-label={t('uploadRequest.copyFor', { name: item.name })}>
                    {t('uploadRequest.copy')}
                  </button>
                )}
                <button type="button" onClick={() => withdraw(item)} className="text-xs font-semibold text-muted hover:text-ink" aria-label={t('uploadRequest.withdrawFor', { name: item.name })}>
                  {t('uploadRequest.withdraw')}
                </button>
              </div>
              <p className="text-xs text-muted">
                {t('uploadRequest.meta', { until: shortDate(item.until, i18n.language), received: item.received, count: item.max_files })}
                {item.last_used_at && ` · ${t('uploadRequest.lastUsed', { when: moment(item.last_used_at, i18n.language) })}`}
                {!live && ` · ${t(`uploadRequest.status.${item.status}`)}`}
              </p>
              {shown?.id === item.id && (
                <div className="mt-2">
                  <CopyLink value={shown.url} label={t('uploadRequest.copyHere')} />
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {dialog}
    </>
  )
}

/** Why no request can be made now, in a sentence; null when one can. */
function blockedText(rules: RequestRules | null, t: (key: string, values?: Record<string, unknown>) => string): string | null {
  if (!rules) return null
  if (!rules.allowed) return t('uploadRequest.off')
  if (!rules.public_url_set) return t('uploadRequest.noAddress')
  return null
}

/** The dialog "Um ein Dokument bitten": the form, the address once made, and the own requests below. */
export function UploadRequestDialog({ onClose, say }: { onClose: () => void; say?: (text: string) => void }) {
  const { t } = useTranslation()
  const state = useRequests()
  const { rules } = state
  const [name, setName] = useState('')
  const [until, setUntil] = useState(dayInDays(7))
  const [files, setFiles] = useState('10')
  const [made, setMade] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!rules) return
    setUntil(dayInDays(Math.min(7, rules.max_days)))
    setFiles(String(rules.default_files))
  }, [rules])
  const blocked = blockedText(rules, t)
  const count = Number(files)
  const days = until ? daysUntil(until) : 0
  const usable = !!name.trim() && days >= 1 && Number.isInteger(count) && count >= 1 && count <= (rules?.max_files ?? 50)
  const make = async () => {
    if (!usable || busy) return
    setBusy(true)
    state.setProblem(null)
    try {
      const done = await uploadRequestsApi.make(name.trim(), days, count)
      setName('')
      const copied = await copyText(done.url)
      setMade(done.url)
      say?.(copied ? t('uploadRequest.madeCopied') : t('uploadRequest.madeShown'))
      await state.load()
    } catch (error) {
      state.fail(error)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog title={t('uploadRequest.title')} onClose={onClose} wide>
      <p className="text-sm text-ink-2">{t('uploadRequest.text')}</p>
      {blocked ? (
        <p className="mt-3 rounded-xl border border-warn/40 bg-warn-soft px-3 py-2 text-sm text-warn" role="status" data-testid="request-blocked">
          {blocked}
        </p>
      ) : (
        rules && (
          <div className="mt-4 space-y-3">
            <label className="block text-sm">
              <span className="text-xs font-semibold text-muted">{t('uploadRequest.from')}</span>
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} placeholder={t('uploadRequest.fromPlaceholder')} className="input mt-1 h-10" />
            </label>
            <div className="flex flex-wrap gap-3">
              <label className="min-w-40 flex-1 text-sm">
                <span className="text-xs font-semibold text-muted">{t('uploadRequest.until')}</span>
                <input type="date" value={until} min={dayInDays(1)} max={dayInDays(rules.max_days)} onChange={(e) => setUntil(e.target.value)} className="input mt-1 h-10" />
              </label>
              <label className="w-36 text-sm">
                <span className="text-xs font-semibold text-muted">{t('uploadRequest.files')}</span>
                <input type="number" inputMode="numeric" min={1} max={rules.max_files} value={files} onChange={(e) => setFiles(e.target.value)} className="input mt-1 h-10" />
              </label>
            </div>
            <p className="text-xs text-muted">{t('uploadRequest.limits', { days: rules.max_days, files: rules.max_files })}</p>
            <Button onClick={() => void make()} disabled={!usable || busy}>
              <Send size={15} aria-hidden /> {t('uploadRequest.make')}
            </Button>
            {made && (
              <div data-testid="request-made">
                <p className="mb-1 text-sm font-semibold">{t('uploadRequest.madeTitle')}</p>
                <CopyLink value={made} label={t('uploadRequest.copyHere')} />
                <p className="mt-1 text-xs text-muted">{t('uploadRequest.madeHint')}</p>
              </div>
            )}
          </div>
        )
      )}
      <div className="mt-5">
        <p className="mb-2 font-semibold">{t('uploadRequest.listTitle')}</p>
        <RequestList state={state} say={say} />
      </div>
      <div className="mt-3">
        <Problem state={state} />
      </div>
    </Dialog>
  )
}

/** The button in the inbox that opens the dialog. */
export function UploadRequestButton({ say }: { say?: (text: string) => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="inline-flex h-9 items-center gap-1.5 rounded-full border border-line px-3 text-sm font-semibold text-ink-2 hover:bg-sheet-2" data-testid="request-open">
        <Send size={15} aria-hidden /> {t('uploadRequest.button')}
      </button>
      {open && <UploadRequestDialog onClose={() => setOpen(false)} say={say} />}
    </>
  )
}

/** My account, Upload: the own requests, with the same button. */
export function UploadRequestsCard() {
  const { t } = useTranslation()
  const state = useRequests()
  const [open, setOpen] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  return (
    <Card icon={Inbox} title={t('uploadRequest.cardTitle')} text={t('uploadRequest.cardText')}>
      <RequestList state={state} say={setDone} />
      <div>
        <Button variant="soft" size="sm" onClick={() => setOpen(true)}>
          <Send size={14} aria-hidden /> {t('uploadRequest.button')}
        </Button>
      </div>
      <Problem state={state} />
      <Feedback problem={null} done={done} />
      {open && (
        <UploadRequestDialog
          onClose={() => {
            setOpen(false)
            void state.load()
          }}
          say={setDone}
        />
      )}
    </Card>
  )
}
