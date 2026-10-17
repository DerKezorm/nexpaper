/**
 * The e-invoice a document carries (ZUGFeRD, Factur-X, XRechnung): in the inbox the short note
 * that its fields come from the data of the invoice, on the document page the box with number, buyer reference, due
 * date, IBAN, the lines and the totals. Both load the data only for a document that carries one.
 */
import { FileCode2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { einvoiceApi, type DocumentInfo, type EInvoice } from '../api/client'
import { shortDate } from '../lib/dates'
import { money } from '../lib/money'

// eslint-disable-next-line react-refresh/only-export-components
export function useEInvoice(document: Pick<DocumentInfo, 'id' | 'einvoice' | 'current_version'>): EInvoice | null {
  const [found, setFound] = useState<EInvoice | null>(null)
  useEffect(() => {
    if (!document.einvoice) {
      setFound(null)
      return
    }
    let alive = true
    einvoiceApi.read(document.id).then(
      (data) => alive && setFound(data),
      () => alive && setFound(null),
    )
    return () => {
      alive = false
    }
  }, [document.id, document.einvoice, document.current_version])
  return found
}

/** "E-Rechnung erkannt", above the fields of the inbox. */
export function EInvoiceNotice({ invoice }: { invoice: EInvoice | null }) {
  const { t, i18n } = useTranslation()
  if (!invoice) return null
  const values = { format: invoice.format, number: invoice.number, due: invoice.due ? shortDate(invoice.due, i18n.language) : '' }
  return (
    <div className="rounded-2xl bg-accent-soft/70 p-4 text-sm" data-testid="einvoice-notice">
      <p className="flex items-center gap-2 font-semibold text-accent">
        <FileCode2 size={15} aria-hidden /> {t('sorting.einvoice.recognised')}
      </p>
      <p className="mt-1 text-ink-2">{t(invoice.due ? 'sorting.einvoice.recognisedText' : 'sorting.einvoice.recognisedTextNoDue', values)}</p>
    </div>
  )
}

/** The box on the document page. */
export function EInvoiceBox({ invoice }: { invoice: EInvoice | null }) {
  const { t, i18n } = useTranslation()
  if (!invoice) return null
  const cash = (cents: number | null) => money(cents, i18n.language, invoice.currency || 'EUR')
  const total = invoice.payable ?? invoice.gross
  return (
    <div className="mt-2 rounded-2xl bg-sheet-2/70 p-4 text-sm" data-testid="einvoice-box">
      <p className="flex items-center gap-2 font-semibold">
        <FileCode2 size={15} className="text-accent" aria-hidden /> {t('sorting.einvoice.title', { format: invoice.format })}
      </p>
      <dl className="mt-3 grid grid-cols-[8rem_1fr] gap-y-1 text-ink-2">
        <dt className="text-muted">{t('sorting.einvoice.number')}</dt>
        <dd className="font-semibold text-ink">
          <bdi>{invoice.number}</bdi>
        </dd>
        {invoice.buyer_ref && (
          <>
            <dt className="text-muted">{t('sorting.einvoice.buyerRef')}</dt>
            <dd>
              <bdi>{invoice.buyer_ref}</bdi>
            </dd>
          </>
        )}
        {invoice.due && (
          <>
            <dt className="text-muted">{t('sorting.einvoice.due')}</dt>
            <dd>{shortDate(invoice.due, i18n.language)}</dd>
          </>
        )}
        {invoice.iban && (
          <>
            <dt className="text-muted">{t('sorting.einvoice.iban')}</dt>
            <dd className="font-mono text-xs">{invoice.iban.replace(/(.{4})/g, '$1 ').trim()}</dd>
          </>
        )}
      </dl>
      {(invoice.lines.length > 0 || total !== null) && (
        <table className="mt-3 w-full text-xs">
          <tbody>
            {invoice.lines.map((line, index) => (
              <tr key={index} className="border-t border-line">
                <td className="py-1.5">
                  {line.quantity ? `${line.quantity} × ` : ''}
                  <bdi>{line.text}</bdi>
                </td>
                <td className="py-1.5 text-right tabular-nums">{cash(line.total)}</td>
              </tr>
            ))}
            {(invoice.net !== null || invoice.tax !== null) && (
              <tr className="border-t border-line text-muted">
                <td className="py-1.5">{t('sorting.einvoice.netTax')}</td>
                <td className="py-1.5 text-right tabular-nums">
                  {cash(invoice.net)} · {cash(invoice.tax)}
                </td>
              </tr>
            )}
            {total !== null && (
              <tr className="border-t border-line font-semibold">
                <td className="py-1.5">{t('sorting.einvoice.total')}</td>
                <td className="py-1.5 text-right tabular-nums">{cash(total)}</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      {invoice.xml_only && <p className="mt-2 text-xs text-muted">{t('sorting.einvoice.xmlOnly')}</p>}
    </div>
  )
}
