/**
 * "<Partner> möchte sich mit <App> verbinden", the page at the app's route `/connect/app`: another nex app of the
 * catalog asks, for the signed-in account, to connect both ways (V3: one consent for both directions). The page shows
 * who asks and from where (the host stands out), what the asking app may do here and what this app gets there, the
 * areas to give (all, or some ticked one by one; the app's word for them), then "Ablehnen" (secondary, X) on the left
 * and "Verbinden erlauben" (primary, Check) on the right (MCP 20, since 0.1.4). Either way the browser goes to the address the server answers: the asking app's own return,
 * which the server checked against that app's description. A refusal of the server stands as a `Notice`.
 *
 * Since 0.1.8: the account at the top with its picture, "Kim Example (kim)" (B1, V43); a direction in which an app
 * may do nothing has no box (B4, V45); where the app that asks cannot connect here but is known (B6, V47), the server
 * answers with a way back and the page goes there at once, so the refusal stands in the card where "Verbinden" was
 * clicked. The page of its own ("Das hat nicht geklappt") is left only where there is no safe way back.
 *
 * Copied unchanged into frontend/src/vendor/nexverbinden/ by bauplaene/verbinden/tools/sync.py; changed only there.
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import { AuthCard, Avatar, Box, Button, Buttons, CheckboxRow, Notice, Row, Rows, inSentence } from '../nexui'
import {
  CONSENT_PARAMS,
  PAGE_FRAME,
  accountLine,
  placeholderOf,
  VERBINDEN_BASE,
  VERBINDEN_BUTTONS,
  fillVerbinden,
  purposeLabel,
  refusalText,
  useVerbindenTexts,
  wayOf,
  type AccountCard,
  type ConsentBack,
  type ConsentInfo,
  type PurposeInfo,
  type VerbindenRequest,
  type VerbindenTexts,
} from './verbinden'

export type ConsentPageProps = {
  request: VerbindenRequest
  base?: string
  /** The query of the page (`?client_id=…`); without, `window.location.search`. */
  search?: string
  areaWord?: string
  language?: string
  navigate?: (url: string) => void
  testId?: string
}

function MayBox({ title, texts, grantedBy, items, mine }: { title: string; texts: VerbindenTexts; grantedBy: string; items: PurposeInfo[]; mine: boolean }) {
  return (
    <Box title={title} testId={mine ? 'consent-app-may' : 'consent-partner-may'}>
      <Rows label={title}>
        {items.length === 0 ? (
          <Row icon="Check" name={texts.card.onlyCheck} />
        ) : (
          items.map((item) => <Row key={item.id} icon={wayOf(item.level, mine) === 'in' ? 'ArrowLeft' : 'ArrowRight'} name={purposeLabel(texts, grantedBy, item.id)} />)
        )}
      </Rows>
    </Box>
  )
}

/** B1: who is signed in, with the picture (the letter where there is none). */
function AccountRow({ texts, card }: { texts: VerbindenTexts; card: AccountCard }) {
  const shown = placeholderOf(card.name || card.username)
  return (
    <div className="flex min-w-0 items-center gap-3" data-testid="consent-account">
      <Avatar src={card.picture} letter={shown.letter} hue={shown.hue} color={card.color} testId="consent-account-picture" />
      <div className="min-w-0">
        <p className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]">{texts.consent.account}</p>
        <p className="m-0 truncate text-sm leading-5 font-medium text-[var(--nexui-text)]" data-testid="consent-account-name">
          {accountLine(card)}
        </p>
      </div>
    </div>
  )
}

export function ConsentPage({ request, base = VERBINDEN_BASE, search, areaWord, language, navigate = (url) => window.location.assign(url), testId = 'connect-consent' }: ConsentPageProps) {
  const { texts, code } = useVerbindenTexts(language)
  const asked = search ?? window.location.search
  const params = useMemo(() => {
    const found = new URLSearchParams(asked)
    return Object.fromEntries(CONSENT_PARAMS.flatMap((name) => (found.get(name) ? [[name, found.get(name) as string]] : []))) as Record<string, string>
  }, [asked])
  const complete = CONSENT_PARAMS.every((name) => Boolean(params[name]))
  const [info, setInfo] = useState<ConsentInfo | null>(null)
  const [problem, setProblem] = useState<string | undefined>(complete ? undefined : texts.consent.broken)
  const [sendProblem, setSendProblem] = useState<string>()
  const [allAreas, setAllAreas] = useState(true)
  const [areas, setAreas] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  // 0.1.9: the way to another page is read when needed, not a dependency of the request; the default (a new function
  // on every render) asked the server again after every answer, without end.
  // An app may give a new function on every render (`navigate={(url) => leave.to(url)}`); the request does not hang on it.
  const go = useRef(navigate)
  useEffect(() => {
    go.current = navigate
  }, [navigate])

  useEffect(() => {
    if (!complete) return
    request<ConsentInfo | ConsentBack>(`${base}/consent?${new URLSearchParams(params).toString()}`).then(
      (found) => {
        // B6 (0.1.8): the app that asks cannot connect here; back to its card with the refusal.
        if ('back' in found) go.current(found.back)
        else setInfo(found)
      },
      (failure: unknown) => setProblem(refusalText(texts, failure, '')),
    )
  }, [request, base, params, complete, texts])

  const answer = async (allow: boolean) => {
    if (!info || busy) return
    setBusy(true)
    setSendProblem(undefined)
    try {
      const chosen = info.areas.filter((area) => areas.includes(String(area.id))).map((area) => area.id)
      const body = { ...params, allow, areas: allAreas || info.areas.length === 0 ? null : chosen }
      const { redirect } = await request<{ redirect: string }>(`${base}/consent`, { method: 'POST', body })
      go.current(redirect)
    } catch (failure) {
      setSendProblem(refusalText(texts, failure, info.app))
      setBusy(false)
    }
  }

  if (problem || !info) {
    return (
      <div className={PAGE_FRAME} data-testid={testId}>
        <AuthCard title={problem ? texts.consent.failed : texts.consent.loading}>
          {problem && (
            <Notice tone="danger" testId="consent-problem">
              {problem}
            </Notice>
          )}
        </AuthCard>
      </div>
    )
  }
  const words = { app: info.app, partner: info.partner, account: info.account, host: info.partner_host, areas: areaWord ?? texts.areaWord, areasInline: inSentence(areaWord ?? texts.areaWord, code) }
  const toggle = (id: string, on: boolean) => setAreas((all) => (on ? [...all, id] : all.filter((one) => one !== id)))
  const nothingChosen = !allAreas && info.areas.length > 0 && areas.length === 0
  const card = info.account_card ?? { name: '', username: info.account, picture: null, color: null }
  // B4 (0.1.8, V45): a direction in which an app may do nothing has no box; where neither may do anything (no pair of
  // the catalog), one box says that only the connection is checked.
  const neither = info.partner_may.length === 0 && info.app_may.length === 0
  return (
    <div className={PAGE_FRAME} data-testid={testId}>
      <AuthCard wide title={fillVerbinden(texts.consent.title, words)} subtitle={fillVerbinden(texts.consent.subtitle, words)} footer={fillVerbinden(texts.consent.footer, words)}>
        <AccountRow texts={texts} card={card} />
        {(info.partner_may.length > 0 || neither) && <MayBox title={fillVerbinden(texts.card.partnerMay, words)} texts={texts} grantedBy={info.app} items={info.partner_may} mine={false} />}
        {info.app_may.length > 0 && <MayBox title={fillVerbinden(texts.card.appMay, words)} texts={texts} grantedBy={info.partner} items={info.app_may} mine />}
        {info.areas.length > 0 && (
          <div className="flex flex-col gap-2" data-testid="consent-areas">
            <CheckboxRow label={fillVerbinden(texts.consent.allAreas, words)} checked={allAreas} onChange={setAllAreas} testId="consent-all-areas" />
            {!allAreas &&
              info.areas.map((area) => (
                <CheckboxRow key={String(area.id)} label={area.name} checked={areas.includes(String(area.id))} onChange={(on) => toggle(String(area.id), on)} testId={`consent-area-${area.id}`} />
              ))}
          </div>
        )}
        {info.replaces && <Notice tone="warn">{fillVerbinden(texts.consent.replaces, words)}</Notice>}
        {sendProblem && (
          <Notice tone="danger" testId="consent-send-problem">
            {sendProblem}
          </Notice>
        )}
        <Buttons end>
          <Button kind={VERBINDEN_BUTTONS.decline.kind} icon={VERBINDEN_BUTTONS.decline.icon} disabled={busy} onClick={() => void answer(false)} testId="consent-decline">
            {texts.buttons.decline}
          </Button>
          <Button kind={VERBINDEN_BUTTONS.allow.kind} icon={VERBINDEN_BUTTONS.allow.icon} busy={busy} disabled={nothingChosen} onClick={() => void answer(true)} testId="consent-allow">
            {texts.buttons.allow}
          </Button>
        </Buttons>
      </AuthCard>
    </div>
  )
}
