/**
 * Messages and the card of the screens before signing in.
 *
 * `Notice`: a framed message, `warn` (something needs doing), `danger` (it failed), `ok` (it worked); a title in its
 * colour, the words under it. `AuthCard`: the card in the middle of the sign-in, setup, invitation and password screens
 * (16 px corners, 24 px inside, at most 384 px wide, `wide` 576 px for the recovery codes), with its title, a line under it and the form; `OrLine` the "or"
 * between the form and the providers.
 */
import type { ReactNode } from 'react'

import { MUTED, NOTICE_TEXT, NOTICE_TONE, PLAIN, type NoticeTone } from './styles'

export function Notice({ tone, title, children, testId }: { tone: NoticeTone; title?: ReactNode; children?: ReactNode; testId?: string }) {
  const role = tone === 'danger' ? 'alert' : tone === 'ok' ? 'status' : 'note'
  return (
    <div role={role} className={`rounded-[12px] border border-solid px-4 py-3 text-sm leading-5 tracking-normal [text-wrap:wrap] ${NOTICE_TONE[tone]}`} data-testid={testId}>
      {title && <p className={`${PLAIN} font-medium ${NOTICE_TEXT[tone]}`}>{title}</p>}
      {children && <div className={`${title ? 'mt-1 text-[var(--nexui-text)]' : NOTICE_TEXT[tone]}`}>{children}</div>}
    </div>
  )
}

export function AuthCard({ title, subtitle, children, footer, wide = false }: { title: string; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  return (
    <div className={`w-full tracking-normal [text-wrap:wrap] ${wide ? 'max-w-xl' : 'max-w-sm'}`}>
      <div className="rounded-[16px] border border-solid border-[var(--nexui-line)] bg-[var(--nexui-surface)] p-6 text-[var(--nexui-text)] shadow-xl shadow-black/20">
        <h1 className={`${PLAIN} text-xl leading-7 font-bold text-[var(--nexui-text)]`}>{title}</h1>
        {subtitle && <div className={`${PLAIN} mt-1 text-sm leading-5 ${MUTED}`}>{subtitle}</div>}
        <div className="mt-5 flex flex-col gap-4">{children}</div>
      </div>
      {footer && <p className={`${PLAIN} mt-3 text-center text-xs leading-4 ${MUTED}`}>{footer}</p>}
    </div>
  )
}

export function OrLine({ children }: { children: ReactNode }) {
  return (
    <div className={`flex items-center gap-3 text-xs leading-4 ${MUTED}`} aria-hidden>
      <span className="h-px flex-1 bg-[var(--nexui-line)]" />
      {children}
      <span className="h-px flex-1 bg-[var(--nexui-line)]" />
    </div>
  )
}
