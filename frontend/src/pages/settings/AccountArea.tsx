/**
 * The areas of "Mein Konto" (`settings/areas.ts`, plan "Einstellungen"): Profile (the account module's card and
 * "Abmelden"), Security (`SecurityBoxes.tsx`), Appearance (`AppearanceArea.tsx`), nexpaper's own Upload (where uploads go,
 * where a phone starts, the own inputs, PDF passwords, upload requests) and AI (the own switch and what the operator set
 * up), Notifications (`NotificationsArea.tsx`) and Connections (`ConnectionsArea.tsx`). Built only from the ui kit.
 */
import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { api, ApiError, authApi, type Me, type ProfileChange } from '../../api/client'
import { AccountButton } from '../../components/AccountButton'
import { Avatar } from '../../components/Avatar'
import { UploadVaultCard } from '../../components/PhoneCards'
import { UploadRequestsCard } from '../../components/UploadRequests'
import { changeLanguage, languageOptions, type LanguageOption } from '../../i18n'
import { confirmOf } from '../../lib/accountButton'
import { providerName } from '../../lib/aiProviders'
import { errorText } from '../../lib/errors'
import { useAiState } from '../../state/ai'
import { useAuth } from '../../state/auth'
import { useWaitingUploads } from '../../state/uploads'
import { SignOutCard, UnconfirmedEmailBox } from '../../vendor/nexkonten/AccountCards'
import { FIELDS, PAGES, screenFields } from '../../vendor/nexkonten/konten'
import { Box, Card, CheckboxRow, ConfirmDialog, Field, Notice, SelectField } from '../../vendor/nexui'
import { useAction } from './actions'
import { AppearanceArea } from './AppearanceArea'
import { ConnectionsArea } from './ConnectionsArea'
import { MyIntakeCards } from './IntakeCards'
import { NotificationsArea } from './NotificationsArea'
import { Outcome } from './Outcome'
import { PdfPasswordsCard } from './PdfPasswordsCard'
import { PhoneCard } from './PersonalCards'
import { SecurityArea } from './SecurityBoxes'
import { useAsk } from './useAsk'

export type AccountPart = 'profile' | 'security' | 'appearance' | 'upload' | 'ai' | 'notifications' | 'connections'

/** One area of the own account. */
export function AccountArea({ part }: { part: AccountPart }) {
  const { me } = useAuth()
  if (!me) return null
  switch (part) {
    case 'profile':
      return (
        <>
          <ProfileCard me={me} />
          <SignOut viaProvider={me.sign_in === 'oidc'} />
        </>
      )
    case 'security':
      return <SecurityArea me={me} />
    case 'appearance':
      return <AppearanceArea />
    case 'upload':
      return (
        <>
          <UploadVaultCard />
          <PhoneCard />
          <MyIntakeCards />
          <PdfPasswordsCard />
          <UploadRequestsCard />
        </>
      )
    case 'ai':
      return <AiCard me={me} />
    case 'notifications':
      return <NotificationsArea me={me} />
    case 'connections':
      return <ConnectionsArea me={me} />
  }
}

/**
 * "Abmelden", the module's card (konten 1.1.0, `SignOutCard`): the one button for it, here in the profile. Uploads of
 * this page that still wait or run are what nexpaper knows as changes not done yet: then it asks first ("Trotzdem
 * abmelden" or "Warten"). Only nexpaper's session ends; whoever came in through a provider stays signed in there.
 */
function SignOut({ viaProvider }: { viaProvider: boolean }) {
  const { t } = useTranslation()
  const { signOut } = useAuth()
  const navigate = useNavigate()
  const pending = useWaitingUploads()
  return (
    <div className="contents" data-testid="sign-out-card">
      <SignOutCard t={t} things={t('settings.things')} provider={viaProvider} pending={pending} onSignOut={() => void signOut().then(() => navigate('/login', { replace: true }))} />
    </div>
  )
}

/** "KI beim Einsortieren": the own switch, and below it what the operator set up for everybody. */
function AiCard({ me }: { me: Me }) {
  const { t } = useTranslation()
  const { setMe } = useAuth()
  const ai = useAiState()
  const action = useAction()
  const mine = me.profile.ai !== false
  const provider = ai?.provider ?? 'none'
  // The own switch only does something when there is an AI for this account: the operator set one up and allowed it
  // for the account. Otherwise it stands locked, says why, and keeps the own choice for later (nothing is changed).
  const noProvider = ai !== null && provider === 'none'
  const notAllowed = me.ai_allowed === false
  const locked = noProvider || notAllowed
  return (
    <Card id="my-ai" icon="Sparkles" title={t('me.ai.title')} subtitle={t('me.ai.text')}>
      <CheckboxRow
        label={t('me.ai.mine')}
        hint={t('me.ai.mineHint')}
        checked={mine && !locked}
        disabled={locked}
        testId="my-ai-switch"
        onChange={(value) => {
          setMe({ ...me, profile: { ...me.profile, ai: value } })
          void action.run(async () => setMe({ ...me, profile: await authApi.preferences({ ai: value }) })).then((worked) => worked || setMe(me))
        }}
      />
      {notAllowed && (
        <div data-ai-not-allowed>
          <Notice tone="warn">{t('me.ai.notAllowed')}</Notice>
        </div>
      )}
      {!notAllowed && noProvider && (
        <div data-ai-none>
          <Notice tone="warn">
            {me.role === 'operator' ? (
              <Trans i18nKey="me.ai.noneOperator" components={{ settings: <Link to="/settings/ai-provider" className="font-semibold underline underline-offset-2" /> }} />
            ) : (
              t('me.ai.none')
            )}
          </Notice>
        </div>
      )}
      {ai && !locked && (
        <Box title={`${t('me.ai.byOperator')} ${providerName(provider, t)}${provider === 'local' && ai.model ? ` (${ai.model})` : ''}`} testId="my-ai-provider">
          <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t(`server.ai.${provider}Note`)}</p>
          {ai.skip_personal !== false && <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t('sorting.ai.skipNote')}</p>}
        </Box>
      )}
      <Outcome problem={action.problem} />
    </Card>
  )
}

/** The files a picture may be (the server takes these). */
const PICTURES = 'image/jpeg,image/png,image/webp,image/gif,image/bmp,image/heic,image/heif,image/avif,.heic,.heif'

/**
 * "Profil" as the shared account module lays it out (`PAGES.profile`, konten 1.1.0), the same in every nex app: the
 * picture in its box, then display name, username and address one under the other, one "Save" for all (a new username
 * or address asks for the password once, `confirmOnSave`), a new address waiting for its link with "Send again" and
 * "Withdraw", the box "Address not confirmed yet" with "Send link" (`email_needs_proof`, E23), the address a provider
 * offers, the language, the role small at the end. The former username stands under the field after a change.
 */
function ProfileCard({ me }: { me: Me }) {
  const { t, i18n } = useTranslation()
  const { setMe } = useAuth()
  const [values, setValues] = useState({ displayName: me.display_name ?? '', username: me.name, email: me.email ?? '' })
  const [password, setPassword] = useState('')
  const [asking, setAsking] = useState(false)
  const [languages, setLanguages] = useState<LanguageOption[]>([])
  const action = useAction()
  const { ask, dialog } = useAsk()
  useEffect(() => {
    let alive = true
    void languageOptions().then((list) => alive && setLanguages(list))
    return () => {
      alive = false
    }
  }, [])
  useEffect(() => {
    setValues({ displayName: me.display_name ?? '', username: me.name, email: me.email ?? '' })
  }, [me.display_name, me.name, me.email])
  const withPassword = me.has_password ?? me.sign_in === 'password'
  const changed = {
    displayName: values.displayName.trim() !== (me.display_name ?? ''),
    username: values.username.trim().toLowerCase() !== me.name.toLowerCase(),
    email: values.email.trim().toLowerCase() !== (me.email ?? '').toLowerCase(),
  }
  const confirms = PAGES.profile.confirmOnSave.some((field) => changed[field])
  const any = changed.displayName || changed.username || changed.email
  const save = (own: string) =>
    void action.run(async () => {
      const change: ProfileChange = {}
      if (changed.displayName) change.display_name = values.displayName.trim()
      if (changed.username) change.name = values.username.trim()
      if (changed.email) change.email = values.email.trim()
      if (confirms) change.password = own
      setMe(await authApi.profile(change))
      setAsking(false)
      setPassword('')
    }, t('me.profile.saved'))
  const fields = screenFields('profile')
  const field = (name: 'displayName' | 'username' | 'email') => fields.find((entry) => entry.field === name)!
  const picture = PAGES.profile.parts.find((entry) => entry.part === 'picture')!
  return (
    <Card id="profile" icon="UserRound" title={t(PAGES.profile.title)}>
      <Box
        title={t(picture.title)}
        hint={t(picture.hint)}
        testId="profile-picture"
        actions={
          <>
            <AccountButton
              name="account.pictureUpload"
              accept={PICTURES}
              busy={action.busy}
              testId="picture"
              aria-label={t('account.pictureUpload')}
              onFile={(file) => void action.run(async () => setMe(await api<Me>('/api/v1/auth/avatar', { method: 'PUT', raw: file })), t('me.profile.saved'))}
            />
            {me.avatar && (
              <AccountButton
                name="account.pictureRemove"
                busy={action.busy}
                onClick={() =>
                  ask({
                    title: t('confirm.avatar.title'),
                    text: t('confirm.avatar.text'),
                    confirm: t('confirm.avatar.confirm'),
                    run: async () => {
                      setMe(await api<Me>('/api/v1/auth/avatar', { method: 'DELETE' }))
                      void action.run(async () => undefined, t('me.profile.removed'))
                    },
                  })
                }
              />
            )}
          </>
        }
      >
        <Avatar person={me} size={56} />
      </Box>
      <form
        className="flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (!any) return
          if (confirms && withPassword) return setAsking(true)
          save('')
        }}
      >
        {(['displayName', 'username', 'email'] as const).map((name) => {
          const spec = field(name)
          const hints = spec.hints.map((hint) => t(hint))
          if (name === 'username' && me.former_name) hints.push(t('account.formerUsername'))
          // An address nobody proved by a link counts, but the mail intake does not trust it; without a server for the
          // link there is no way to prove it here, and that is said under the field.
          if (name === 'email' && me.email && !me.email_pending && !me.email_confirmed && !me.mail_links) hints.push(t('mailAddress.off'))
          return (
            <Field
              key={name}
              label={t(spec.label)}
              type={spec.type === 'email' ? 'email' : 'text'}
              autoComplete={spec.autoComplete}
              maxLength={spec.maxLength || undefined}
              placeholder={name === 'displayName' ? me.name : undefined}
              hints={hints}
              value={values[name]}
              onChange={(event) => setValues({ ...values, [name]: event.target.value })}
            />
          )
        })}
        {me.email_pending && (
          <Box
            title={t('account.emailPending', { email: me.email_pending })}
            testId="mail-pending"
            actions={
              <>
                <AccountButton name="account.emailResend" busy={action.busy} onClick={() => void action.run(async () => setMe(await authApi.emailResend()), t('mailAddress.sent'))} />
                <AccountButton
                  name="account.emailWithdraw"
                  busy={action.busy}
                  onClick={() =>
                    void action.run(async () => {
                      await authApi.emailWithdraw()
                      setMe(await authApi.me())
                    })
                  }
                />
              </>
            }
          />
        )}
        {me.email_needs_proof && me.email && !me.email_pending && (
          <UnconfirmedEmailBox t={t} email={me.email} onSend={async () => setMe(await authApi.emailProve())} errorText={(error) => (error instanceof ApiError ? errorText(error.code, error.values) : errorText('internal_error'))} />
        )}
        <div>
          <AccountButton name="account.save" type="submit" busy={action.busy} disabled={!any} testId="profile-save" />
        </div>
      </form>
      {me.offered_email && (
        <Box
          title={t('account.providerEmailOffer', { provider: me.offered_email_provider || '' })}
          hint={me.offered_email}
          testId="provider-email-offer"
          actions={
            <>
              <AccountButton
                name="account.providerEmailTake"
                busy={action.busy}
                onClick={() => (withPassword ? setValues({ ...values, email: me.offered_email ?? '' }) : void action.run(async () => setMe(await authApi.takeOffered(''))))}
              />
              <AccountButton
                name="account.providerEmailDismiss"
                busy={action.busy}
                onClick={() =>
                  void action.run(async () => {
                    await authApi.declineOffered()
                    setMe(await authApi.me())
                  })
                }
              />
            </>
          }
        />
      )}
      <SelectField
        label={t('account.language')}
        hints={[t('settings.language.hint')]}
        value={i18n.language}
        data-testid="language-select"
        onChange={(event) => {
          const code = event.target.value
          void changeLanguage(code)
          // Kept with the account, so the next browser speaks it too.
          void authApi.language(code).then(setMe, () => undefined)
        }}
        options={languages.map((option) => ({ value: option.code, label: option.name }))}
      />
      <p className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]" data-testid="account-role">
        {t('account.role')}: {t(me.role === 'operator' ? 'account.roleOperator' : 'account.roleMember')}
      </p>
      <Outcome problem={action.problem} done={action.done} values={action.values} />
      {asking && (
        <ConfirmDialog
          title={t('account.save')}
          text={
            changed.email && !values.email.trim()
              ? `${t('confirm.mailAddress.text', { address: me.email })} ${t('account.confirmWithPassword')}`
              : t('account.confirmWithPassword')
          }
          confirm={confirmOf('account.save', t('account.save'))}
          cancel={t('common.cancel')}
          closeLabel={t('common.close')}
          busy={action.busy}
          error={action.problem ? errorText(action.problem, action.values) : undefined}
          confirmDisabled={!password}
          onCancel={() => {
            setAsking(false)
            setPassword('')
          }}
          onConfirm={() => save(password)}
        >
          <Field label={t(FIELDS.password.label)} type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </ConfirmDialog>
      )}
      {dialog}
    </Card>
  )
}
