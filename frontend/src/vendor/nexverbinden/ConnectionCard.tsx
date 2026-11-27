/**
 * The card of one partner app under Mein Konto › Verbindungen (Bauplan „Einstellungen“, Platz 3 der Verbindungen; draft "Apps
 * verbinden", one kind of card for every pair): a `Collapsible` card with the partner's logo, the pair's sentence under
 * the title, on the right the state as a `Badge` with the host or since when. Open it shows what flows each way (rows
 * with an arrow: ← comes here, → goes there), the facts of the connection and the buttons of its state:
 *
 * - not connected: the partner's address (filled in by the operator where he named it), where the partner reads or
 *   writes areas of this app the choice of them (all at first, V16, V41), one sentence how it goes, "Mit <partner> verbinden"
 *   (primary) and, where the app has its own form, "Von Hand verbinden";
 * - connected: "Erneuern", "Trennen"; a partner that only uses this app: "Zugriff beenden";
 * - not reachable (the last state stays, since when), refused, resting, switched off: a `Notice` and what helps;
 * - an older connection by an API key typed in by hand: shown as it is, "läuft ab" a week before its key ends.
 *
 * Since 0.1.8: no address field (B3, V42): the operator sets the other apps up; where he has not, the card says so,
 * for the operator with "Einrichten" (Server › Allgemein › Andere nex-Apps). "Von Hand verbinden" for a new connection
 * only for the operator (V46). A refusal that the operator can lift (own network, not set up) names the place and, for
 * the operator, links there, here or in the partner app (B2, V44). A refusal carried from the return page (B6) stands
 * in the card at once, the card open.
 *
 * The app adds its own parts (lists, calendars, a feed's address) as `children`, shown open in every state, connected
 * by click, by hand or not at all (V23, V-9), and its form for connecting by hand as `manual`. The partner's mark comes from the module, light and dark
 * as the page is (V21). Copied unchanged into frontend/src/vendor/nexverbinden/ by bauplaene/verbinden/tools/sync.py.
 */
import { useState, type ReactNode } from 'react'

import { Badge, Box, Button, Buttons, CheckboxRow, Collapsible, ConfirmDialog, Facts, Notice, Row, Rows, inSentence, useNexuiTexts, type Fact } from '../nexui'
import {
  OPERATOR_PAGE,
  STATE_TONES,
  VERBINDEN_BASE,
  VERBINDEN_BUTTONS,
  aboutPair,
  areaActions,
  codeText,
  defaultDay,
  defaultWhen,
  fillVerbinden,
  purposeLabel,
  refusalCode,
  markOf,
  refusalText,
  setUpPlace,
  usePageDark,
  useVerbindenTexts,
  wayOf,
  type PartnerView,
  type VerbindenRequest,
  type VerbindenTexts,
  type WhenFormat,
} from './verbinden'

export type ConnectionCardProps = {
  /** This app's name (`nextime`). */
  app: string
  view: PartnerView
  request: VerbindenRequest
  /** Since 0.1.2 the module brings the partner's mark, light and dark (V21); `logo` only overrides it. */
  logo?: string
  base?: string
  /** The card as it stands after a change. */
  onChange?: (view: PartnerView) => void
  /** The app's own form for connecting by hand (address and key, its older way). */
  manual?: ReactNode
  /** The app's own parts while connected (lists, calendars). */
  children?: ReactNode
  /** The app's word for its areas ("Bereiche", "Kalender"); else the module's. */
  areaWord?: string
  language?: string
  when?: WhenFormat
  /** Sends the browser to the partner's consent page (default `window.location.assign`). */
  navigate?: (url: string) => void
  defaultOpen?: boolean
  /** Since 0.1.8: the signed-in account is an operator (B3: "Einrichten", "Von Hand verbinden" for a new connection). */
  operator?: boolean
  /** Since 0.1.8 (B6): the code of a refusal carried from the return page, shown at once. */
  carried?: string
  testId?: string
}

type Flow = { id: string; text: string; way: 'in' | 'out' }

function flows(texts: VerbindenTexts, grantedBy: string, ids: string[], levels: Record<string, string>, mine: boolean): Flow[] {
  return ids.map((id) => ({ id, text: purposeLabel(texts, grantedBy, id), way: wayOf(levels[id] ?? 'read', mine) }))
}

function FlowBox({ title, items, empty, testId }: { title: string; items: Flow[]; empty: string; testId: string }) {
  return (
    <Box title={title} testId={testId}>
      <Rows label={title}>
        {items.length === 0 ? (
          <Row icon="Check" name={empty} />
        ) : (
          items.map((item) => <Row key={item.id} icon={item.way === 'in' ? 'ArrowLeft' : 'ArrowRight'} name={item.text} testId={`flow-${item.id}`} />)
        )}
      </Rows>
    </Box>
  )
}

function areasText(texts: VerbindenTexts, areas: { name: string }[] | null): string {
  return areas === null ? texts.card.allAreas : areas.map((area) => area.name).join(', ')
}

export function ConnectionCard({
  app,
  view,
  request,
  logo,
  base = VERBINDEN_BASE,
  onChange,
  manual,
  children,
  areaWord,
  language,
  when = defaultWhen,
  navigate = (url) => window.location.assign(url),
  defaultOpen,
  operator = false,
  carried,
  testId,
}: ConnectionCardProps) {
  const { texts, code } = useVerbindenTexts(language)
  const kit = useNexuiTexts()
  const partner = view.partner
  // M-19 (0.1.5): inside a sentence the app's word stands small in English and French (`areasInline`).
  const words = { app, partner, areas: areaWord ?? texts.areaWord, areasInline: inSentence(areaWord ?? texts.areaWord, code) }
  const [byHand, setByHand] = useState(false)
  const [busy, setBusy] = useState(false)
  // B6 (0.1.8): a refusal carried from the return page stands at once, with its code (for the way to set up).
  const [problem, setProblem] = useState<string | undefined>(carried ? codeText(texts, carried, app, partner) : undefined)
  const [problemCode, setProblemCode] = useState<string | undefined>(carried)
  const [tooOld, setTooOld] = useState(false)
  const [leaving, setLeaving] = useState(false)
  // Decisions V16, V41: the areas the partner may read or write here, chosen before the click (all at first).
  const choice = view.areas_choice ?? []
  const [allAreas, setAllAreas] = useState(true)
  const [chosen, setChosen] = useState<string[]>([])
  const at = (iso: string | null) => (iso ? when(iso, code) : '')
  const dark = usePageDark()
  const mark = logo ?? markOf(partner, dark)

  const onlyThem = view.uses.length === 0 && view.grants.length > 0
  const connected = !['none', 'legacy', 'expiring'].includes(view.state)
  const word = view.state === 'connected' && onlyThem ? fillVerbinden(texts.states.usesUs, words) : (texts.states as Record<string, string>)[view.state]
  const tone = tooOld && !connected ? 'warn' : STATE_TONES[view.state]
  // V42 (B3): set up by the operator (or by the connection there is); an older server leaves it out.
  const setUp = view.set_up ?? Boolean(view.address)
  // B2/B3 (0.1.8): where the operator changes it, here or in the partner app; only for the operator.
  const setUpAt = (code: string | null | undefined): string | null => {
    if (!operator) return null
    const place = setUpPlace(code)
    if (place === 'here') return OPERATOR_PAGE
    if (place === 'there' && view.address) return `${view.address}${OPERATOR_PAGE}`
    return null
  }
  const setUpButton = (href: string | null, there: boolean) =>
    href ? (
      <div>
        <Button kind={VERBINDEN_BUTTONS.setUp.kind} icon={VERBINDEN_BUTTONS.setUp.icon} size="sm" href={href} testId="connection-set-up">
          {there ? fillVerbinden(texts.buttons.setUpThere, words) : texts.buttons.setUp}
        </Button>
      </div>
    ) : null

  const start = async () => {
    setBusy(true)
    setProblem(undefined)
    setProblemCode(undefined)
    setTooOld(false)
    try {
      const renewing = view.state === 'connected' || view.state === 'resting'
      const areas = renewing
        ? (view.areas_granted?.map((area) => area.id) ?? null)
        : allAreas || choice.length === 0
          ? null
          : choice.filter((area) => chosen.includes(String(area.id))).map((area) => area.id)
      // V42 (0.1.8): no address from here; the server takes the operator's (or the connection's).
      const { go } = await request<{ go: string }>(`${base}/partners/${encodeURIComponent(partner)}/start`, { method: 'POST', body: { areas } })
      navigate(go)
    } catch (failure) {
      setTooOld(refusalCode(failure) === 'partner_too_old')
      setProblemCode(refusalCode(failure))
      setProblem(refusalText(texts, failure, app, partner))
      setBusy(false)
    }
  }

  const act = async (path: string, method: 'POST' | 'DELETE') => {
    setBusy(true)
    setProblem(undefined)
    setProblemCode(undefined)
    try {
      const changed = await request<PartnerView>(`${base}/partners/${encodeURIComponent(partner)}${path}`, { method })
      onChange?.(changed)
    } catch (failure) {
      setProblemCode(refusalCode(failure))
      setProblem(refusalText(texts, failure, app, partner))
    }
    setBusy(false)
    setLeaving(false)
  }

  const facts: Fact[] = []
  if (connected) {
    if (view.account) facts.push({ label: fillVerbinden(texts.card.account, words), value: view.account, testId: 'connection-account' })
    if (view.uses.length > 0) facts.push({ label: fillVerbinden(texts.card.areasThere, words), value: areasText(texts, view.areas_used) })
    if (view.grants.length > 0) facts.push({ label: fillVerbinden(texts.card.areasHere, words), value: areasText(texts, view.areas_granted) })
    if (view.ok_at) facts.push({ label: texts.card.lastOk, value: at(view.ok_at), testId: 'connection-ok-at' })
    if (view.used_at && view.grants.length > 0) facts.push({ label: fillVerbinden(texts.card.lastUsed, words), value: at(view.used_at) })
    if (view.since) facts.push({ label: texts.card.since, value: at(view.since) })
  } else if (view.legacy) {
    facts.push({ label: texts.card.viaKey, value: fillVerbinden(texts.card.key, { shown: view.legacy.shown ? `${view.legacy.shown}…` : '' }), note: texts.card.byHand })
    if (view.legacy.expires_at) facts.push({ label: texts.card.until, value: defaultDay(view.legacy.expires_at, code), testId: 'connection-until' })
    if (view.ok_at) facts.push({ label: texts.card.lastOk, value: at(view.ok_at) })
  }

  const mine = flows(texts, partner, view.uses, view.uses_levels ?? {}, true)
  const theirs = flows(texts, app, view.grants, view.grants_levels ?? {}, false)
  const status = (
    // V-15 (0.1.6, ui 1.1.3): state and address are one unit that goes under the title when the card is narrow; the
    // state keeps its width, the address shortens.
    <span className="flex min-w-0 max-w-full items-center gap-2" data-testid="connection-summary">
      <span className="shrink-0">
        <Badge tone={tone} testId="connection-state">
          {tooOld && !connected ? texts.states.tooOld : word}
        </Badge>
      </span>
      {view.state === 'unreachable' && view.stale_since ? (
        <span className="min-w-0 truncate text-sm text-[var(--nexui-text-muted)]">{at(view.stale_since)}</span>
      ) : view.state === 'expiring' && view.legacy?.expires_at ? (
        <span className="min-w-0 truncate text-sm text-[var(--nexui-text-muted)]">{defaultDay(view.legacy.expires_at, code)}</span>
      ) : view.host ? (
        <span className="min-w-0 truncate text-sm text-[var(--nexui-text-muted)]">{view.host}</span>
      ) : null}
    </span>
  )

  const nothingChosen = !allAreas && choice.length > 0 && chosen.length === 0
  const areaChoice =
    choice.length > 0 ? (
      <div className="flex flex-col gap-2" data-testid="connection-areas">
        <p className="m-0 text-sm font-medium text-[var(--nexui-text)]" data-testid="connection-areas-question">{fillVerbinden(texts.card.areasChoice, { ...words, actions: areaActions(texts, app, view.grants, view.grants_levels ?? {}) })}</p>
        <CheckboxRow label={fillVerbinden(texts.card.areasChoiceAll, words)} checked={allAreas} onChange={setAllAreas} testId="connection-all-areas" />
        {!allAreas &&
          choice.map((area) => (
            <CheckboxRow
              key={String(area.id)}
              label={area.name}
              checked={chosen.includes(String(area.id))}
              onChange={(on) => setChosen((all) => (on ? [...all, String(area.id)] : all.filter((one) => one !== String(area.id))))}
              testId={`connection-area-${area.id}`}
            />
          ))}
      </div>
    ) : null
  const connectButton = (kind: 'primary' | 'reconnect', size: 'md' | 'sm' = 'md') => (
    <Button kind={VERBINDEN_BUTTONS[kind === 'primary' ? 'connect' : 'reconnect'].kind} icon={VERBINDEN_BUTTONS.connect.icon} size={size} busy={busy} disabled={nothingChosen} onClick={() => void start()} testId="connection-connect">
      {kind === 'primary' ? fillVerbinden(texts.buttons.connect, words) : texts.buttons.reconnect}
    </Button>
  )
  // V46 (0.1.8): a new connection by hand only for the operator; an older one by hand stays the account's to change.
  const manualButton = manual && (operator || view.legacy) ? (
    <Button kind={VERBINDEN_BUTTONS.manual.kind} icon={VERBINDEN_BUTTONS.manual.icon} size="sm" onClick={() => setByHand(!byHand)} testId="connection-manual">
      {texts.buttons.manual}
    </Button>
  ) : null
  const disconnectButton = (label: string, kind: 'disconnect' | 'remove' = 'disconnect') => (
    <Button kind={VERBINDEN_BUTTONS[kind].kind} icon={VERBINDEN_BUTTONS[kind].icon} size="sm" disabled={busy} onClick={() => setLeaving(true)} testId="connection-disconnect">
      {label}
    </Button>
  )

  return (
    <Collapsible
      variant="card"
      id={partner}
      logo={mark}
      icon="Plug"
      title={partner}
      subtitle={aboutPair(texts, app, partner)}
      status={status}
      defaultOpen={defaultOpen ?? (carried ? true : undefined)}
      testId={testId ?? `connection-${partner}`}
    >
      {problem && (
        <Notice tone={tooOld || problemCode === 'declined' ? 'warn' : 'danger'} testId="connection-problem">
          {tooOld ? fillVerbinden(operator ? texts.card.tooOld : texts.card.tooOldMember, words) : problem}
        </Notice>
      )}
      {problem && setUpButton(setUpAt(problemCode), setUpPlace(problemCode) === 'there')}
      {view.state === 'unreachable' && view.problem === 'local_off' && (
        <>
          <Notice tone="warn" title={fillVerbinden(texts.card.localOffTitle, words)} testId="connection-local-off">
            {fillVerbinden(texts.card.localOffText, words)}
          </Notice>
          {!problem && setUpButton(setUpAt('local_off'), false)}
        </>
      )}
      {view.state === 'unreachable' && view.problem !== 'local_off' && (
        <Notice tone="warn" title={fillVerbinden(texts.card.unreachableTitle, words)} testId="connection-unreachable">
          {fillVerbinden(texts.card.unreachableText, { ...words, when: at(view.ok_at) || at(view.stale_since) })}
        </Notice>
      )}
      {view.state === 'refused' && (
        <Notice tone="danger" title={fillVerbinden(texts.card.refusedTitle, words)} testId="connection-refused">
          {fillVerbinden(texts.card.refusedText, words)}
        </Notice>
      )}
      {view.state === 'resting' && (
        <Notice tone="warn" title={texts.card.restingTitle} testId="connection-resting">
          {fillVerbinden(texts.card.restingText, words)}
        </Notice>
      )}
      {view.state === 'off' && (
        <Notice tone="warn" title={fillVerbinden(texts.card.offTitle, words)} testId="connection-off">
          {fillVerbinden(texts.card.offText, words)}
        </Notice>
      )}
      {view.state === 'expiring' && view.legacy?.expires_at && (
        <Notice tone="warn" title={fillVerbinden(texts.card.expiringTitle, { day: defaultDay(view.legacy.expires_at, code) })} testId="connection-expiring">
          {texts.card.expiringText}
        </Notice>
      )}
      {view.state === 'legacy' && <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{texts.card.legacyText}</p>}

      {view.state === 'none' ? (
        <>
          <FlowBox title={texts.card.wouldFlow} items={[...mine, ...theirs]} empty={texts.card.onlyCheck} testId="connection-would-flow" />
          {setUp ? (
            <>
              {areaChoice}
              <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{fillVerbinden(texts.card.how, words)}</p>
              <Buttons>
                {connectButton('primary')}
                {manualButton}
              </Buttons>
            </>
          ) : (
            <>
              {/* V42 (B3): only the operator sets the other app up; the card says so, for him with the way there. */}
              <Notice tone="warn" title={fillVerbinden(texts.card.notSetUpTitle, words)} testId="connection-not-set-up">
                {fillVerbinden(operator ? texts.card.notSetUpOperator : texts.card.notSetUpText, words)}
              </Notice>
              {(operator || manualButton) && (
                <Buttons>
                  {operator && (
                    <Button kind={VERBINDEN_BUTTONS.setUp.kind} icon={VERBINDEN_BUTTONS.setUp.icon} size="sm" href={OPERATOR_PAGE} testId="connection-set-up">
                      {texts.buttons.setUp}
                    </Button>
                  )}
                  {manualButton}
                </Buttons>
              )}
            </>
          )}
          {/* V23, V-9: the app's own parts stand in every state, also before a connection by click (nexfolk's address
              of the calendar feed, its device password). */}
          {children}
        </>
      ) : (
        <>
          {mine.length > 0 && <FlowBox title={fillVerbinden(texts.card.appMay, words)} items={mine} empty={texts.card.onlyCheck} testId="connection-app-may" />}
          {theirs.length > 0 && <FlowBox title={fillVerbinden(texts.card.partnerMay, words)} items={theirs} empty={texts.card.onlyCheck} testId="connection-partner-may" />}
          {facts.length > 0 && <Facts items={facts} testId="connection-facts" />}
          {/* V23: the app's own choice (lists, areas, calendars) stands open in every state, by click or by hand. */}
          {children}
          {(view.state === 'refused' || view.state === 'expiring' || view.state === 'legacy') && areaChoice}
          <Buttons>
            {view.state === 'connected' && !onlyThem && (
              <Button kind={VERBINDEN_BUTTONS.renew.kind} icon={VERBINDEN_BUTTONS.renew.icon} size="sm" busy={busy} onClick={() => void start()} testId="connection-renew">
                {texts.buttons.renew}
              </Button>
            )}
            {view.state === 'unreachable' && (
              <Button kind={VERBINDEN_BUTTONS.check.kind} icon={VERBINDEN_BUTTONS.check.icon} size="sm" busy={busy} onClick={() => void act('/check', 'POST')} testId="connection-check">
                {texts.buttons.check}
              </Button>
            )}
            {view.state === 'resting' && (
              <Button kind={VERBINDEN_BUTTONS.renewNow.kind} icon={VERBINDEN_BUTTONS.renewNow.icon} size="sm" busy={busy} onClick={() => void start()} testId="connection-renew">
                {texts.buttons.renew}
              </Button>
            )}
            {(view.state === 'refused' || view.state === 'expiring') && connectButton('reconnect', 'sm')}
            {view.state === 'legacy' && (
              <Button kind={VERBINDEN_BUTTONS.renew.kind} icon={VERBINDEN_BUTTONS.connect.icon} size="sm" busy={busy} onClick={() => void start()} testId="connection-connect">
                {texts.buttons.reconnect}
              </Button>
            )}
            {(view.state === 'legacy' || view.state === 'expiring') && manualButton}
            {connected &&
              disconnectButton(
                view.state === 'refused' ? texts.buttons.remove : onlyThem ? texts.buttons.endAccess : texts.buttons.disconnect,
                view.state === 'refused' ? 'remove' : 'disconnect',
              )}
          </Buttons>
        </>
      )}
      {byHand && manual}
      {leaving && (
        <ConfirmDialog
          title={fillVerbinden(texts.disconnect.title, words)}
          text={fillVerbinden(texts.disconnect.text, words)}
          confirm={{ label: view.state === 'refused' ? texts.buttons.remove : onlyThem ? texts.buttons.endAccess : texts.buttons.disconnect, kind: 'danger', icon: 'Unplug' }}
          cancel={texts.buttons.cancel}
          closeLabel={kit.close}
          busy={busy}
          onCancel={() => setLeaving(false)}
          onConfirm={() => void act('', 'DELETE')}
          testId="connection-disconnect-dialog"
        />
      )}
    </Collapsible>
  )
}
