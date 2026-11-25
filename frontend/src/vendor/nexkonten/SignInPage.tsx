/**
 * Since 1.1.0: the page Server › Sign-in of every app, built only from the ui kit (plan "Einstellungen", Anmeldung):
 *
 * 1. the emergency hammer's notice, only while it is down (``SecondFactorOffNotice``);
 * 2. "Ready for the internet?" (``ReadinessCard``): the card's symbol in the colour of the worst point, every point a
 *    ``Collapsible`` (closed: title and state symbol; open: what it means and what to do), all closed at first;
 * 3. "Sign-in" (``SignInCard``): password sign-in, the public address (``Field action`` "Save"), the second factor for
 *    everybody (on only with an own factor, off only with the password), passkeys allowed with its hint;
 * 4. then what the app puts after it: the module oidc's "Sign-in providers" and "authentik in one step".
 *
 * The app hands over its words (``t``, i18next with the namespaces ``account`` and ``oidc`` loaded), what its server
 * answered and how it calls it; the module decides order, wording, kinds and sizes of the buttons.
 *
 * Copied unchanged into frontend/src/vendor/nexkonten/ by bauplaene/konten/tools/sync.py; changed only there.
 */
import { CircleCheck, CircleX, TriangleAlert } from 'lucide-react'
import { useState, type CSSProperties, type FormEvent, type ReactNode } from 'react'

import { Badge, Button, Card, CheckboxRow, Collapsible, ConfirmDialog, Field, Notice, useNexuiTexts } from '../nexui'
import {
  BUTTONS,
  READY_CARD,
  SIGN_IN_CARD,
  buttonSize,
  confirmLine,
  publicUrlPlaceholder,
  readyState,
  type Readiness,
  type ReadyPoint,
  type ReadyState,
} from './konten'

/** The app's ``t`` (i18next), with the values of a sentence. */
export type Translate = (key: string, values?: Record<string, unknown>) => string

/** The operator's switches as the server's ``signin.view`` gives them. */
export interface SignInView {
  password_login: boolean
  factor_required: boolean
  passkeys_allowed: boolean
  password_may_go_off: boolean
  factor_may_go_on: boolean
  second_factor_off?: boolean
}

export type SignInChange = Partial<Pick<SignInView, 'password_login' | 'factor_required' | 'passkeys_allowed'>>

/** What saving the public address would leave behind at authentik (module oidc, 409 ``public_url_change``). */
export interface AddressQuestion {
  count: number
  hand: number
  address: string
}

/** The colours of the states, from the kit's variables. */
const STATE_COLOUR: Record<ReadyState, string> = { ok: 'var(--nexui-ok)', warn: 'var(--nexui-warn)', bad: 'var(--nexui-danger)' }
const STATE_ICON = { ok: CircleCheck, warn: TriangleAlert, bad: CircleX } as const
const STATE_BADGE = { ok: 'on', warn: 'warn', bad: 'danger' } as const

function Problem({ text }: { text: string }) {
  return text ? (
    <p role="alert" className="m-0 text-sm leading-5 text-[var(--nexui-danger)]">
      {text}
    </p>
  ) : null
}

/** The emergency hammer is down (``<APP>_SECOND_FACTOR_OFF``): plainly at the top of the page. */
export function SecondFactorOffNotice({ t, on }: { t: Translate; on: boolean | undefined }) {
  if (!on) return null
  return (
    <Notice tone="danger" title={t('account.secondFactorOff')} testId="second-factor-off">
      {t('account.secondFactorOffHint')}
    </Notice>
  )
}

/** One point of "Ready for the internet?". */
function ReadyItem({
  t,
  point,
  open,
  onOpenChange,
}: {
  t: Translate
  point: ReadyPoint
  open?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  const Icon = STATE_ICON[point.state]
  const count = typeof point.values.count === 'number' ? { count: point.values.count } : {}
  const folding = open === undefined ? {} : { open, onOpenChange }
  return (
    <Collapsible
      id={`ready-${point.key}`}
      title={t(point.title, point.values)}
      status={
        <span role="img" aria-label={t(READY_CARD.state[point.state])} data-state={point.state} style={{ color: STATE_COLOUR[point.state], display: 'inline-flex' }}>
          <Icon aria-hidden className="h-4 w-4" strokeWidth={2} />
        </span>
      }
      {...folding}
    >
      <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]" data-testid={`ready-text-${point.key}`}>
        {t(point.text, { ...point.values, ...count })}
      </p>
    </Collapsible>
  )
}

/** "Ready for the internet?": the card's symbol in the colour of the worst point (green, orange, red), a badge with
 * how many are open, then every point closed. ``open``/``onOpenChange``: an app that remembers which are open per
 * device; else each point keeps it itself. */
export function ReadinessCard({
  t,
  readiness,
  open,
  onOpenChange,
}: {
  t: Translate
  readiness: Readiness | null
  open?: Readonly<Record<string, boolean>>
  onOpenChange?: (key: string, open: boolean) => void
}) {
  if (!readiness) return null
  const state = readyState(readiness.points)
  const tone = { '--nexui-accent': STATE_COLOUR[state], '--nexui-accent-text': STATE_COLOUR[state], display: 'contents' } as CSSProperties
  const opened = readiness.points.filter((point) => point.state !== 'ok').length
  return (
    <div style={tone} data-ready={state}>
      <Card id={READY_CARD.id} icon={READY_CARD.icon} title={t(READY_CARD.title)} subtitle={t(READY_CARD.text)}>
        <div>
          <Badge tone={STATE_BADGE[state]} testId="ready-summary">
            {opened ? t(READY_CARD.open, { count: opened }) : t(READY_CARD.allGood)}
          </Badge>
        </div>
        {readiness.points.map((point) => (
          <ReadyItem
            key={point.key}
            t={t}
            point={point}
            {...(onOpenChange ? { open: open?.[point.key] ?? false, onOpenChange: (now: boolean) => onOpenChange(point.key, now) } : {})}
          />
        ))}
      </Card>
    </div>
  )
}

/** The card "Sign-in". ``app``: the app's name (the placeholder of the address); ``onChange`` saves switches (with the
 * operator's password when the second factor goes off); ``onSaveAddress`` saves the public address and answers the
 * module oidc's question (``public_url_change``) or null when saved; ``errorText`` turns a failure into a sentence. */
export function SignInCard({
  t,
  app,
  view,
  publicUrl,
  operatorHasPassword,
  onChange,
  onSaveAddress,
  errorText,
  saved,
}: {
  t: Translate
  app: string
  view: SignInView | null
  publicUrl: string
  operatorHasPassword: boolean
  onChange: (change: SignInChange, password?: string) => Promise<void>
  onSaveAddress: (url: string, confirm: boolean) => Promise<AddressQuestion | null>
  errorText: (error: unknown) => string
  /** The app's word for a saved change ("Gespeichert."), shown for a moment. */
  saved?: string
}) {
  const kit = useNexuiTexts()
  const [address, setAddress] = useState<string | null>(null)
  const [asking, setAsking] = useState<{ question: AddressQuestion; url: string } | null>(null)
  const [turningOff, setTurningOff] = useState(false)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const [askProblem, setAskProblem] = useState('')
  const [done, setDone] = useState(false)
  if (!view) return null
  const card = SIGN_IN_CARD

  const run = async (work: () => Promise<void>, inDialog = false): Promise<boolean> => {
    setBusy(true)
    setProblem('')
    setAskProblem('')
    setDone(false)
    try {
      await work()
      setDone(true)
      return true
    } catch (error) {
      ;(inDialog ? setAskProblem : setProblem)(errorText(error))
      return false
    } finally {
      setBusy(false)
    }
  }

  const saveAddress = (url: string, confirm: boolean) =>
    run(async () => {
      const question = await onSaveAddress(url, confirm)
      setAsking(question ? { question, url } : null)
      if (!question) setAddress(null)
    })

  const submitAddress = (event: FormEvent) => {
    event.preventDefault()
    void saveAddress((address ?? publicUrl).trim(), false)
  }

  const factorLocked = !view.factor_required && !view.factor_may_go_on
  const question = asking?.question
  const addressText = question
    ? [
        question.count > 0 ? t('oidc.admin.addressChangeConfirm', { address: question.address }) : '',
        question.hand > 0 ? t('oidc.admin.addressChangeHand', { count: question.hand }) : '',
      ]
        .filter(Boolean)
        .join(' ')
    : ''
  const save = BUTTONS['account.save']
  const off = BUTTONS[card.factorRequired.offButton]

  return (
    <Card id={card.id} icon={card.icon} title={t(card.title)}>
      <CheckboxRow
        label={t(card.passwordLogin.label)}
        hint={t(card.passwordLogin.hint)}
        checked={view.password_login}
        // Without an active provider nobody but the operator could come in: the box stays ticked.
        disabled={busy || (view.password_login && !view.password_may_go_off)}
        onChange={(password_login) => void run(() => onChange({ password_login }))}
        testId="sign-in-password"
      />
      <form onSubmit={submitAddress} data-testid="sign-in-address">
        <Field
          label={t(card.publicUrl.label)}
          value={address ?? publicUrl}
          onChange={(event) => setAddress(event.target.value)}
          placeholder={publicUrlPlaceholder(app)}
          type="url"
          inputMode="url"
          autoComplete="url"
          hints={[t(card.publicUrl.hint)]}
          action={
            <Button type="submit" kind={save.kind} icon={save.icon} size={buttonSize('account.save')} busy={busy}>
              {t(card.publicUrl.button)}
            </Button>
          }
        />
      </form>
      <CheckboxRow
        label={t(card.factorRequired.label)}
        hint={factorLocked ? t(card.factorRequired.locked) : t(card.factorRequired.hint)}
        checked={view.factor_required}
        disabled={busy || factorLocked}
        onChange={(factor_required) => {
          if (factor_required) void run(() => onChange({ factor_required }))
          else setTurningOff(true)
        }}
        testId="sign-in-factor"
      />
      <CheckboxRow
        label={t(card.passkeysAllowed.label)}
        hint={t(card.passkeysAllowed.hint)}
        checked={view.passkeys_allowed}
        disabled={busy}
        onChange={(passkeys_allowed) => void run(() => onChange({ passkeys_allowed }))}
        testId="sign-in-passkeys"
      />
      <Problem text={problem} />
      {done && saved && !problem && (
        <p role="status" className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]">
          {saved}
        </p>
      )}
      {asking && (
        <ConfirmDialog
          title={t(card.publicUrl.label)}
          text={addressText}
          confirm={{ label: t('account.save'), kind: save.kind, icon: save.icon }}
          cancel={t('account.cancel')}
          closeLabel={kit.close}
          busy={busy}
          onCancel={() => setAsking(null)}
          onConfirm={() => void saveAddress(asking.url, true)}
        />
      )}
      {turningOff && (
        <ConfirmDialog
          title={t(card.factorRequired.offTitle)}
          text={t(card.factorRequired.offText)}
          confirm={{ label: t(card.factorRequired.offButton), kind: off.kind, icon: off.icon }}
          cancel={t('account.cancel')}
          closeLabel={kit.close}
          busy={busy}
          error={askProblem}
          confirmDisabled={operatorHasPassword && !password}
          onCancel={() => {
            setTurningOff(false)
            setPassword('')
            setAskProblem('')
          }}
          onConfirm={() =>
            void run(() => onChange({ factor_required: false }, password), true).then((ok) => {
              if (ok) {
                setTurningOff(false)
                setPassword('')
              }
            })
          }
          testId="sign-in-factor-off"
        >
          {operatorHasPassword ? (
            <Field
              label={t('account.password')}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              hints={[t(confirmLine(true))]}
            />
          ) : (
            <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]">{t(confirmLine(false))}</p>
          )}
        </ConfirmDialog>
      )}
    </Card>
  )
}

/** The whole page in its order: the notice, "Ready for the internet?", "Sign-in", then ``providers`` (the module oidc's
 * ``ProvidersCard`` and ``AuthentikCard``, which the app places there). */
export function SignInPage({
  t,
  readiness,
  open,
  onOpenChange,
  providers,
  ...card
}: Parameters<typeof SignInCard>[0] & {
  readiness: Readiness | null
  open?: Readonly<Record<string, boolean>>
  onOpenChange?: (key: string, open: boolean) => void
  providers?: ReactNode
}) {
  return (
    <>
      <SecondFactorOffNotice t={t} on={card.view?.second_factor_off} />
      <ReadinessCard t={t} readiness={readiness} {...(open ? { open } : {})} {...(onOpenChange ? { onOpenChange } : {})} />
      <SignInCard t={t} {...card} />
      {providers}
    </>
  )
}
