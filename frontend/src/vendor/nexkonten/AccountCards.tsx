/**
 * Since 1.1.0: the cards of the module on the pages of every app, built only from the ui kit (plan "Einstellungen"):
 *
 * - ``AppearanceCard``: first on Appearance, "Aussehen" with the ``ThemeSegment`` (light, dark, as the device says),
 *   kept at the account on every device (``profiles.change_theme``, E5, E17);
 * - ``UnconfirmedEmailBox``: in the profile, "Address not confirmed yet" with a small "Send link"
 *   (``profiles.prove_email``; nexpaper had it, now every app);
 * - ``SignOutCard``: "Sign out" with the module's sentence and the app's word for its things, asking first where the
 *   app knows changes that still wait;
 * - ``WhatYouSeeCard``: under Server › Accounts, "What you see" with the app's sentence;
 * - ``PasskeyAddition`` (since E49): in the box "Passkeys" the button "Add a passkey", or what is missing for it.
 *
 * Copied unchanged into frontend/src/vendor/nexkonten/ by bauplaene/konten/tools/sync.py; changed only there.
 */
import { useState, type ReactNode } from 'react'

import { Box, Button, Card, ConfirmDialog, TextLink, ThemeSegment, useNexuiTexts, type ThemeChoice } from '../nexui'
import { APPEARANCE_CARD, BUTTONS, SIGN_OUT_CARD, UNCONFIRMED_BOX, WHAT_YOU_SEE_CARD, buttonSize, passkeyAddition, themeOf } from './konten'
import type { Translate } from './SignInPage'

/** "Aussehen" (Palette): the theme of the account. ``children``: nothing else of the app belongs here; its own cards
 * (paper, lists, themes) follow as cards of their own. */
export function AppearanceCard({
  theme,
  onChange,
  disabled = false,
}: {
  /** The account's ``theme`` ("" or unknown: as the device says). */
  theme: string | null | undefined
  onChange: (theme: ThemeChoice) => void
  disabled?: boolean
}) {
  const kit = useNexuiTexts()
  return (
    <Card id={APPEARANCE_CARD.id} icon={APPEARANCE_CARD.icon} title={kit.appearance}>
      <ThemeSegment value={themeOf(theme)} onChange={onChange} disabled={disabled} testId="appearance-theme" />
    </Card>
  )
}

/** "Address not confirmed yet" with "Send link" (show it where ``showUnconfirmed`` says so). */
export function UnconfirmedEmailBox({
  t,
  email,
  onSend,
  errorText,
}: {
  t: Translate
  email: string
  onSend: () => Promise<void>
  errorText: (error: unknown) => string
}) {
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [problem, setProblem] = useState('')
  const spec = BUTTONS[UNCONFIRMED_BOX.button]
  const send = async () => {
    setBusy(true)
    setProblem('')
    try {
      await onSend()
      setSent(true)
    } catch (error) {
      setProblem(errorText(error))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Box
      title={t(UNCONFIRMED_BOX.title)}
      hint={t(UNCONFIRMED_BOX.hint, { email })}
      testId="email-unconfirmed"
      actions={
        <Button kind={spec.kind} icon={spec.icon} size={buttonSize(UNCONFIRMED_BOX.button)} busy={busy} onClick={() => void send()}>
          {t(UNCONFIRMED_BOX.button)}
        </Button>
      }
    >
      {sent && (
        <p role="status" className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]">
          {t(UNCONFIRMED_BOX.sent, { email })}
        </p>
      )}
      {problem && (
        <p role="alert" className="m-0 text-sm leading-5 text-[var(--nexui-danger)]">
          {problem}
        </p>
      )}
    </Box>
  )
}

/** "Sign out": the module's sentence (``{{things}}``: the app's word, "Notizen"), with a provider the sentence that it
 * stays signed in there. ``pending``: changes that still wait (nexnotes, nextime, nexfolk); then it asks first. */
export function SignOutCard({
  t,
  things,
  provider = false,
  pending = 0,
  onSignOut,
}: {
  t: Translate
  things: string
  provider?: boolean
  pending?: number
  onSignOut: () => void | Promise<void>
}) {
  const kit = useNexuiTexts()
  const [asking, setAsking] = useState(false)
  const spec = BUTTONS[SIGN_OUT_CARD.button]
  const anyway = BUTTONS[SIGN_OUT_CARD.anyway]
  const text: ReactNode = (
    <>
      {t(SIGN_OUT_CARD.text, { things })}
      {provider && <> {t(SIGN_OUT_CARD.provider)}</>}
    </>
  )
  return (
    <Card id={SIGN_OUT_CARD.id} icon={SIGN_OUT_CARD.icon} title={t(SIGN_OUT_CARD.title)} subtitle={text}>
      <div>
        <Button kind={spec.kind} icon={spec.icon} onClick={() => (pending > 0 ? setAsking(true) : void onSignOut())} testId="sign-out">
          {t(SIGN_OUT_CARD.button)}
        </Button>
      </div>
      {asking && (
        <ConfirmDialog
          title={t(SIGN_OUT_CARD.title)}
          text={t(SIGN_OUT_CARD.pending, { count: pending })}
          confirm={{ label: t(SIGN_OUT_CARD.anyway), kind: anyway.kind, icon: anyway.icon }}
          cancel={t(SIGN_OUT_CARD.wait)}
          closeLabel={kit.close}
          onCancel={() => setAsking(false)}
          onConfirm={() => {
            setAsking(false)
            void onSignOut()
          }}
        />
      )}
    </Card>
  )
}

/** "What you see" (ShieldCheck) under Server › Accounts: the app's sentence of what an operator sees and never sees. */
export function WhatYouSeeCard({ t, text }: { t: Translate; text: string }) {
  return (
    <Card id={WHAT_YOU_SEE_CARD.id} icon={WHAT_YOU_SEE_CARD.icon} title={t(WHAT_YOU_SEE_CARD.title)}>
      <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]">{text}</p>
    </Card>
  )
}

/** Since E49: in the box "Passkeys" the button "Add a passkey" where the server can add one (``canAdd`` from
 * ``passkeys.can_add``), else the sentence that the public https address is missing: an operator with the place to
 * enter it (a link to ``signInHref``, Server › Sign-in), a member without. The list of the account's passkeys stays
 * the app's, always shown and removable. */
export function PasskeyAddition({
  t,
  canAdd,
  operator,
  onAdd,
  busy = false,
  signInHref = '/settings/sign-in',
}: {
  t: Translate
  canAdd: boolean
  operator: boolean
  onAdd: () => void
  busy?: boolean
  signInHref?: string
}) {
  const shown = passkeyAddition(canAdd, operator)
  if (shown.button) {
    const add = BUTTONS['account.passkeyAdd']
    return (
      <Button kind={add.kind} icon={add.icon} size={buttonSize('account.passkeyAdd')} busy={busy} onClick={onAdd} testId="passkey-add">
        {t('account.passkeyAdd')}
      </Button>
    )
  }
  return (
    <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]" data-testid="passkey-needs-address">
      {t(shown.note)}
      {shown.place && (
        <>
          {' '}
          <TextLink href={signInHref} testId="passkey-needs-address-place">
            {t(shown.place)}
          </TextLink>
        </>
      )}
    </p>
  )
}
