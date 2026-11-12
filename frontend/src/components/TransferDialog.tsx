/**
 * "Überweisen" (K1): the EPC QR code ("GiroCode") a banking app scans, for one of the document's own IBANs. The server
 * makes the code (`POST /api/v1/documents/{id}/transfer/code`, nothing is stored); the amount and the purpose can be
 * changed here, and the code is drawn anew after a short pause in the typing. Where each part comes from always stands
 * beside it: "aus der E-Rechnung", or "aus dem Text gelesen" with the plea to compare (a forged invoice carries a
 * strange IBAN). "Als bezahlt merken" marks the due date done, when there is one and the person may change the
 * document.
 */
import { Check, Landmark } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, transferApi, type DocumentInfo, type TransferInfo } from '../api/client'
import { errorText } from '../lib/errors'
import { AMOUNT_MAX, PURPOSE_CHARS, REDRAW_MS, spacedIban } from '../lib/transfer'
import { Button } from './Button'
import { Dialog } from './Dialog'
import { AmountInput } from './DocumentFields'

function Origin({ origin }: { origin: string | null | undefined }) {
  const { t } = useTranslation()
  if (!origin) return null
  const careful = origin === 'text'
  return (
    <span className={`block text-xs ${careful ? 'font-semibold text-warn' : 'text-muted'}`} data-testid={`origin-${origin}`}>
      {t(`transfer.from.${origin}`)}
    </span>
  )
}

type Props = {
  document: DocumentInfo
  info: TransferInfo
  /** "Als bezahlt merken": the due date is open and the person may change the document. */
  canMarkPaid: boolean
  onPaid: () => Promise<void>
  onClose: () => void
}

export function TransferDialog({ document: d, info, canMarkPaid, onPaid, onClose }: Props) {
  const { t, i18n } = useTranslation()
  const [iban, setIban] = useState(info.ibans[0]?.iban ?? '')
  const [amount, setAmount] = useState<number | null>(info.amount !== null && info.amount > 0 ? info.amount : null)
  const [purpose, setPurpose] = useState(info.purpose)
  const [svg, setSvg] = useState<string | null>(null)
  const [problem, setProblem] = useState<{ code: string; values?: Record<string, unknown> } | null>(null)
  const [paid, setPaid] = useState(false)
  const [busy, setBusy] = useState(false)
  const chosen = info.ibans.find((x) => x.iban === iban) ?? info.ibans[0]
  const purposeWrong = !PURPOSE_CHARS.test(purpose) || purpose.length > info.purpose_max
  const amountWrong = amount === null || amount < 1 || amount > AMOUNT_MAX
  const changedAmount = amount !== info.amount
  const changedPurpose = purpose !== info.purpose

  const wanted = useMemo(() => ({ iban, amount, purpose: purpose.trim() }), [iban, amount, purpose])
  useEffect(() => {
    if (purposeWrong || amountWrong || !wanted.iban) {
      setSvg(null)
      return
    }
    const stop = new AbortController()
    const timer = window.setTimeout(() => {
      transferApi.code(d.id, wanted.iban, wanted.amount as number, wanted.purpose, stop.signal).then(
        (drawn) => {
          if (stop.signal.aborted) return
          setSvg(drawn)
          setProblem(null)
        },
        (error: unknown) => {
          if (stop.signal.aborted || (error instanceof ApiError && error.code === 'cancelled')) return
          setSvg(null)
          setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
        },
      )
    }, REDRAW_MS)
    return () => {
      window.clearTimeout(timer)
      stop.abort()
    }
  }, [d.id, wanted, purposeWrong, amountWrong])

  const markPaid = async () => {
    setBusy(true)
    try {
      await onPaid()
      setPaid(true)
    } catch (error) {
      setProblem(error instanceof ApiError ? { code: error.code, values: error.values } : { code: 'internal_error' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title={t('transfer.title')} onClose={onClose}>
      <div className="space-y-4" data-testid="transfer">
        <div className="flex flex-col items-center gap-2">
          <div className="flex aspect-square w-56 items-center justify-center rounded-2xl bg-white p-2 shadow-soft" aria-live="polite">
            {svg ? (
              <img src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`} alt={t('transfer.codeAlt')} className="h-full w-full" data-testid="transfer-code" />
            ) : (
              <span className="px-4 text-center text-xs text-[#6b625a]">{amountWrong || purposeWrong ? t('transfer.fixFirst') : t('transfer.drawing')}</span>
            )}
          </div>
          <p className="text-center text-sm text-ink-2">{t('transfer.howTo')}</p>
        </div>

        <dl className="space-y-3 text-sm">
          <div>
            <dt className="font-semibold">{t('transfer.recipient')}</dt>
            <dd>
              <bdi>{info.recipient}</bdi>
              <Origin origin={info.recipient_origin} />
            </dd>
          </div>
          <div>
            <dt className="font-semibold">{t('transfer.iban')}</dt>
            <dd>
              {info.ibans.length > 1 ? (
                <fieldset className="space-y-1">
                  <legend className="mb-1 text-xs text-muted">{t('transfer.chooseIban')}</legend>
                  {info.ibans.map((x) => (
                    <label key={x.iban} className="flex items-center gap-2">
                      <input type="radio" name="iban" checked={iban === x.iban} onChange={() => setIban(x.iban)} className="h-4 w-4 accent-[var(--accent)]" />
                      <span className="font-mono tabular-nums">{spacedIban(x.iban)}</span>
                    </label>
                  ))}
                </fieldset>
              ) : (
                <span className="font-mono tabular-nums">{spacedIban(iban)}</span>
              )}
              <Origin origin={chosen?.origin} />
            </dd>
          </div>
          <div>
            <dt className="font-semibold">{t('transfer.amount')}</dt>
            <dd>
              <AmountInput cents={amount} onChange={setAmount} label={t('transfer.amount')} className="input h-9 max-w-40" language={i18n.language} />
              {amountWrong && <span className="block text-xs text-bad">{t('transfer.amountWrong')}</span>}
              {changedAmount ? <span className="block text-xs text-muted">{t('transfer.from.typed')}</span> : <Origin origin={info.amount_origin} />}
            </dd>
          </div>
          <div>
            <dt className="font-semibold">{t('transfer.purpose')}</dt>
            <dd>
              <input
                value={purpose}
                onChange={(event) => setPurpose(event.target.value.replace(/[\r\n]+/g, ' '))}
                maxLength={info.purpose_max}
                aria-label={t('transfer.purpose')}
                aria-invalid={purposeWrong}
                className={`input h-9 ${purposeWrong ? 'border-bad' : ''}`}
              />
              <span className="mt-0.5 flex justify-between gap-2 text-xs">
                <span className={purposeWrong ? 'text-bad' : 'text-muted'}>
                  {purposeWrong ? t('transfer.purposeWrong') : changedPurpose ? t('transfer.from.typed') : info.purpose_origin ? '' : t('transfer.noPurpose')}
                </span>
                <span className="shrink-0 text-muted tabular-nums">{t('transfer.count', { count: purpose.length, max: info.purpose_max })}</span>
              </span>
              {!changedPurpose && <Origin origin={info.purpose_origin} />}
            </dd>
          </div>
        </dl>

        {problem && (
          <p role="alert" className="rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
            {errorText(problem.code, problem.values)}
          </p>
        )}

        <p className="text-xs text-muted">{t('transfer.nothingKept')}</p>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-4">
          {(canMarkPaid || paid) &&
            (paid ? (
              <span className="mr-auto inline-flex items-center gap-1 rounded-full bg-ok-soft px-2.5 py-1 text-sm font-semibold text-ok" role="status">
                <Check size={14} aria-hidden /> {t('transfer.paid')}
              </span>
            ) : (
              <Button variant="soft" className="mr-auto" disabled={busy} onClick={() => void markPaid()}>
                <Check size={15} aria-hidden /> {t('transfer.markPaid')}
              </Button>
            ))}
          <Button variant="primary" onClick={onClose}>
            {t('common.close')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

/** The button "Überweisen" in the head of the document: only when the document gives a transfer. */
export function TransferButton({ info, onClick }: { info: TransferInfo | null; onClick: () => void }) {
  const { t } = useTranslation()
  if (!info?.ready) return null
  return (
    <Button variant="line" size="sm" onClick={onClick} data-testid="transfer-button">
      <Landmark size={15} aria-hidden /> {t('transfer.button')}
    </Button>
  )
}
