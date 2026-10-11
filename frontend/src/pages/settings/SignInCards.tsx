/**
 * Settings, Sign-in: three cards one below the other, as the shared sign-in blueprint lays them out for every nex app
 * (Bauplan 04). Order, wording and behaviour come from there; the parts (card, switch, field, button, question) and
 * the colours are nexpaper's own.
 *
 * 1. Sign-in: password sign-in (locked on while no provider is active), the public address, the second factor.
 * 2. Sign-in providers: the list with its marks, the drag handle, and the form as a dialog.
 * 3. authentik in one step: address, token, "Set up", the blueprint, and the steps with the reason of a failure.
 */
import { Download, GripVertical, KeyRound, Shield, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'

import { ApiError, oidcApi, type AddressQuestion, type AuthentikResult, type OidcProvider, type OidcProviderForm } from '../../api/client'
import { Dialog } from '../../components/Dialog'
import { errorText } from '../../lib/errors'
import { useAuth } from '../../state/auth'
import {
  authentikIssuerChange,
  authentikProposal,
  authentikProxyWarning,
  authentikReasonKey,
  authentikRedirect,
  authentikStale,
  authentikStepKey,
  oidcErrorKey,
  oidcFormErrorKey,
  slugFromLabel,
  type AuthentikAddress,
} from '../../vendor/nexoidc/oidc'
import type { useServerSettings } from './ServerCards'
import { Button, Card, Confirm, CopyLink, Feedback, Input, Toggle, useAction } from './ui'

type Server = ReturnType<typeof useServerSettings>

/** The whole part: the list is loaded once and shared, the button changes it too. */
export function SignInPart({ server }: { server: Server }) {
  const [providers, setProviders] = useState<OidcProvider[] | null>(null)
  const load = useCallback(async () => setProviders(await oidcApi.providers()), [])
  useEffect(() => {
    void load().catch(() => setProviders([]))
  }, [load])
  const active = (providers ?? []).some((entry) => entry.enabled)
  const publicUrl = server.settings?.public_url ?? ''
  return (
    <>
      <SignInCard server={server} anyActive={active} />
      <ProvidersCard providers={providers} reload={load} publicUrl={publicUrl} />
      <AuthentikCard publicUrl={publicUrl} reload={load} addressChanged={server.reload} />
    </>
  )
}

// --- Card 1: sign-in -------------------------------------------------------------------------------------------------

function SignInCard({ server, anyActive }: { server: Server; anyActive: boolean }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [address, setAddress] = useState<string | null>(null)
  // The server stopped before saving the address: this much stays behind at the providers (module 1.0.10).
  const [asking, setAsking] = useState<AddressQuestion | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  // Turning "require a second factor" off makes signing in weaker: the operator's password first.
  const [weaker, setWeaker] = useState(false)
  const s = server.settings
  if (!s) return null
  // Without an own second factor the operator would be the first one sent away: first the own one.
  const ownFirst = !s.two_factor_required && me?.sign_in === 'password' && !me?.two_factor
  // A sign-in through a provider whose switch says it checks the second factor itself is not sent away; both hints
  // name that switch by the words of the shared module.
  const trusts = { trusts: t('oidc.admin.trustsSecondFactor') }
  return (
    <Card id="sign-in" icon={Shield} title={t('oidc.admin.signInTitle')}>
      <Toggle
        label={t('oidc.admin.password')}
        hint={t('oidc.admin.passwordHint')}
        checked={s.password_login}
        // Without an active provider nobody but the operator could come in: the switch stays on.
        disabled={s.password_login && !anyActive}
        onChange={(password_login) => void server.save({ password_login })}
      />
      <form
        className="flex flex-wrap items-start gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          setSaved(null)
          void server.saveAddress((address ?? s.public_url).trim()).then((question) => {
            setAsking(question)
            if (question === null) setSaved(t('settings.saved'))
          })
        }}
      >
        <Input
          label={t('oidc.admin.address')}
          value={address ?? s.public_url}
          onChange={setAddress}
          placeholder="https://paper.example.com"
          hint={t('oidc.admin.addressHint')}
          className="min-w-60 flex-1"
        />
        <Button type="submit" busy={server.busy} className="mt-6">
          {t('common.save')}
        </Button>
      </form>
      <Toggle
        label={t('server.twoFactorRequired')}
        hint={ownFirst ? t('server.ownSecondFactorFirst', trusts) : t('server.twoFactorRequiredHint', trusts)}
        checked={s.two_factor_required}
        disabled={ownFirst}
        onChange={(on) => (on ? void server.save({ two_factor_required: true }) : setWeaker(true))}
      />
      <Feedback problem={server.problem} done={server.done ?? saved} />
      {asking && (
        <Confirm
          title={t('oidc.admin.address')}
          text={addressQuestionText(t, asking)}
          confirm={t('common.save')}
          onCancel={() => setAsking(null)}
          onConfirm={async () => {
            await server.saveAddress((address ?? s.public_url).trim(), true)
            setAsking(null)
            setSaved(t('settings.saved'))
          }}
        />
      )}
      {weaker && (
        <Confirm
          title={t('server.confirm.two_factor_off.title')}
          text={t('server.confirm.two_factor_off.text')}
          confirm={t('server.confirm.two_factor_off.button')}
          danger
          password={me?.sign_in === 'password'}
          onCancel={() => setWeaker(false)}
          onConfirm={async (current_password) => {
            await server.saveNow({ two_factor_required: false, current_password })
            setWeaker(false)
          }}
        />
      )}
    </Card>
  )
}

/** The question before a new public address is saved: what stays behind at authentik, and at providers made by hand. */
// eslint-disable-next-line react-refresh/only-export-components
export function addressQuestionText(t: TFunction, question: AddressQuestion): string {
  return [
    question.count > 0 ? t('oidc.admin.addressChangeConfirm', { address: question.address }) : '',
    question.hand > 0 ? t('oidc.admin.addressChangeHand', { count: question.hand }) : '',
  ]
    .filter(Boolean)
    .join(' ')
}

// --- Card 2: the provider list ---------------------------------------------------------------------------------------

/** The same issuer, however written at the end (the server's `same_issuer` for an issuer without a placeholder). */
function sameIssuer(a: string, b: string): boolean {
  return a.trim().replace(/\/+$/, '') === b.trim().replace(/\/+$/, '')
}

function ProvidersCard({ providers, reload, publicUrl }: { providers: OidcProvider[] | null; reload: () => Promise<void>; publicUrl: string }) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState<OidcProvider | 'new' | null>(null)
  const [removing, setRemoving] = useState<{ entry: OidcProvider; count: number; only: number } | null>(null)
  const [dragged, setDragged] = useState<number | null>(null)
  const { busy, problem, done, run } = useAction()
  const list = providers ?? []
  const readOnly = list.some((entry) => !entry.editable)

  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= list.length) return
    const ids = list.map((entry) => entry.id)
    const [taken] = ids.splice(from, 1)
    ids.splice(to, 0, taken)
    void run(async () => {
      await oidcApi.orderProviders(ids)
      await reload()
    })
  }

  return (
    <Card id="sign-in-providers" icon={KeyRound} title={t('oidc.admin.providersTitle')} text={t('oidc.admin.providersText')}>
      {providers !== null && list.length === 0 && <p className="text-sm text-muted">{t('oidc.admin.empty')}</p>}
      {list.length > 0 && (
        <ul className="divide-y divide-line rounded-xl border border-line" data-testid="provider-list">
          {list.map((entry, index) => (
            <li
              key={entry.id}
              className={`flex flex-wrap items-center gap-2 px-3 py-3 text-sm ${dragged === index ? 'opacity-50' : ''}`}
              draggable={!readOnly}
              onDragStart={() => setDragged(index)}
              onDragEnd={() => setDragged(null)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                if (dragged !== null) move(dragged, index)
                setDragged(null)
              }}
            >
              {!readOnly && list.length > 1 && (
                <button
                  type="button"
                  className="cursor-grab rounded p-1 text-muted hover:text-ink"
                  aria-label={t('server.providers.order', { name: entry.label })}
                  onKeyDown={(event) => {
                    if (event.key === 'ArrowUp') move(index, index - 1)
                    if (event.key === 'ArrowDown') move(index, index + 1)
                  }}
                >
                  <GripVertical size={16} aria-hidden />
                </button>
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold">{entry.label}</span>
                <span className="block truncate text-xs text-muted">{entry.issuer}</span>
              </span>
              <span className="flex flex-wrap items-center gap-1.5 text-xs font-semibold">
                <span className={`rounded-full px-2 py-0.5 ${entry.enabled ? 'bg-ok-soft text-ok' : 'border border-line text-muted'}`}>
                  {entry.enabled ? t('oidc.admin.active') : t('oidc.admin.inactive')}
                </span>
                {entry.managed === 'authentik' && <span className="rounded-full border border-accent/40 px-2 py-0.5 text-accent">{t('oidc.admin.managed')}</span>}
              </span>
              {entry.editable && (
                <span className="flex gap-1.5">
                  <Button small onClick={() => setEditing(entry)}>
                    {t('oidc.admin.edit')}
                  </Button>
                  <Button
                    small
                    danger
                    busy={busy}
                    onClick={() =>
                      void run(async () => {
                        const impact = await oidcApi.providerImpact(entry.id)
                        setRemoving({ entry, count: impact.count, only: impact.only })
                      })
                    }
                  >
                    {t('oidc.admin.remove')}
                  </Button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {!readOnly && (
        <div>
          <Button primary onClick={() => setEditing('new')}>
            {t('oidc.admin.add')}
          </Button>
        </div>
      )}
      <Feedback problem={problem} done={done} />
      {editing !== null && (
        <ProviderDialog
          entry={editing === 'new' ? null : editing}
          publicUrl={publicUrl}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null)
            await reload()
          }}
        />
      )}
      {removing && (
        <Confirm
          title={t('oidc.admin.remove')}
          text={t('oidc.admin.removeConfirm', { name: removing.entry.label, count: removing.count, only: removing.only })}
          confirm={t('oidc.admin.remove')}
          danger
          onCancel={() => setRemoving(null)}
          onConfirm={async () => {
            await oidcApi.removeProvider(removing.entry.id)
            setRemoving(null)
            await reload()
          }}
        />
      )}
    </Card>
  )
}

const EMPTY: OidcProviderForm = {
  label: '',
  slug: '',
  issuer: '',
  client_id: '',
  client_secret: '',
  scopes: 'openid profile email',
  enabled: true,
  auto_create: false,
  trusts_second_factor: true,
}

type FieldName = 'label' | 'slug' | 'issuer' | 'client_id' | 'client_secret' | 'scopes' | 'id'

/** The provider form as a dialog, the fields in the blueprint's order. */
function ProviderDialog({ entry, publicUrl, onClose, onSaved }: { entry: OidcProvider | null; publicUrl: string; onClose: () => void; onSaved: () => Promise<void> }) {
  const { t } = useTranslation()
  const [form, setForm] = useState<OidcProviderForm>(
    entry
      ? {
          label: entry.label,
          issuer: entry.issuer,
          client_id: entry.client_id,
          client_secret: '',
          scopes: entry.scopes,
          enabled: entry.enabled,
          auto_create: entry.auto_create,
          trusts_second_factor: entry.trusts_second_factor,
        }
      : EMPTY,
  )
  // The short name follows the name on the button until it is typed itself.
  const [slugTyped, setSlugTyped] = useState(false)
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState(false)
  const [fieldError, setFieldError] = useState<{ field: FieldName; text: string } | null>(null)
  const [confirmIssuer, setConfirmIssuer] = useState<number | null>(null)

  const slug = entry ? entry.slug : slugTyped ? (form.slug ?? '') : slugFromLabel(form.label)
  const base = (publicUrl || window.location.origin).replace(/\/+$/, '')
  const redirect = entry ? entry.redirect_uri : `${base}/api/v1/oidc/${slug || '…'}/callback`

  const set = (change: Partial<OidcProviderForm>) => setForm((current) => ({ ...current, ...change }))

  const errorFor = (error: unknown): { field: FieldName; text: string } => {
    if (!(error instanceof ApiError)) return { field: 'id', text: errorText('internal_error') }
    const field = (typeof error.values.field === 'string' ? error.values.field : 'id') as FieldName
    const key = oidcFormErrorKey(error.code) ?? oidcErrorKey(error.code)
    return { field, text: key ? t(key) : errorText(error.code, error.values) }
  }

  const save = async () => {
    setBusy(true)
    setFieldError(null)
    try {
      const body = { ...form, slug: entry ? undefined : slug }
      if (entry) await oidcApi.saveProvider(entry.id, body)
      else await oidcApi.addProvider(body)
      await onSaved()
    } catch (error) {
      setFieldError(errorFor(error))
    } finally {
      setBusy(false)
    }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    // Another issuer is another provider: say first how many accounts will have to link again.
    if (entry && entry.links > 0 && !sameIssuer(entry.issuer, form.issuer)) {
      try {
        const impact = await oidcApi.providerImpact(entry.id, form.issuer.trim())
        if (impact.issuer_change > 0) return setConfirmIssuer(impact.issuer_change)
      } catch (error) {
        return setFieldError(errorFor(error))
      }
    }
    await save()
  }

  const problemAt = (field: FieldName) => (fieldError?.field === field ? <FieldProblem text={fieldError.text} /> : null)

  return (
    <Dialog title={entry ? `${t('oidc.admin.edit')}: ${entry.label}` : t('oidc.admin.add')} onClose={() => !busy && onClose()} wide>
      <form className="space-y-3" onSubmit={(event) => void submit(event)} data-testid="provider-form">
        <Input label={t('oidc.admin.label')} value={form.label} onChange={(label) => set({ label })} />
        {problemAt('label')}
        {entry ? (
          <p className="text-xs text-muted">
            {t('oidc.admin.slug')}: <code className="font-mono text-ink-2">{entry.slug}</code>
          </p>
        ) : (
          <>
            <Input
              label={t('oidc.admin.slug')}
              value={slug}
              onChange={(value) => {
                setSlugTyped(true)
                set({ slug: value })
              }}
              hint={t('oidc.admin.slugHint')}
            />
            {problemAt('slug')}
          </>
        )}
        <Input
          label={t('oidc.admin.issuer')}
          value={form.issuer}
          onChange={(issuer) => set({ issuer })}
          placeholder="https://auth.example.com/application/o/nexpaper/"
          hint={t('oidc.admin.issuerHint')}
        />
        {problemAt('issuer')}
        <Input label={t('oidc.admin.clientId')} value={form.client_id} onChange={(client_id) => set({ client_id })} />
        {problemAt('client_id')}
        <Input
          label={t('oidc.admin.secret')}
          value={form.client_secret}
          onChange={(client_secret) => set({ client_secret })}
          type="password"
          autoComplete="new-password"
          placeholder={entry?.has_secret ? t('oidc.admin.secretKept') : ''}
        />
        {problemAt('client_secret')}
        <div className="space-y-1 text-sm">
          <span className="text-xs font-semibold text-ink-2">{t('oidc.admin.redirect')}</span>
          <CopyLink value={redirect} label={t('oidc.admin.redirect')} />
        </div>
        <Toggle label={t('oidc.admin.enabled')} checked={form.enabled} onChange={(enabled) => set({ enabled })} />
        <Toggle label={t('oidc.admin.autoCreate')} hint={t('oidc.admin.autoCreateHint')} checked={form.auto_create} onChange={(auto_create) => set({ auto_create })} />
        <Toggle
          label={t('oidc.admin.trustsSecondFactor')}
          hint={t('oidc.admin.trustsSecondFactorHint')}
          checked={form.trusts_second_factor}
          onChange={(trusts_second_factor) => set({ trusts_second_factor })}
        />
        <details open={more || fieldError?.field === 'scopes'} onToggle={(event) => setMore((event.target as HTMLDetailsElement).open)}>
          <summary className="cursor-pointer text-xs font-semibold text-muted">{t('server.providers.more')}</summary>
          <div className="mt-2">
            <Input label={t('oidc.admin.scopes')} value={form.scopes} onChange={(scopes) => set({ scopes })} />
            {problemAt('scopes')}
          </div>
        </details>
        {problemAt('id')}
        <div className="flex justify-end gap-2 pt-2">
          <Button onClick={onClose} busy={busy}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" primary busy={busy}>
            {t('common.save')}
          </Button>
        </div>
      </form>
      {confirmIssuer !== null && (
        <Confirm
          title={t('oidc.admin.issuer')}
          text={t('oidc.admin.issuerChangeConfirm', { count: confirmIssuer })}
          confirm={t('common.save')}
          danger
          onCancel={() => setConfirmIssuer(null)}
          onConfirm={async () => {
            setConfirmIssuer(null)
            await save()
          }}
        />
      )}
    </Dialog>
  )
}

function FieldProblem({ text }: { text: string }) {
  return (
    <p role="alert" className="-mt-1 text-xs text-bad">
      {text}
    </p>
  )
}

// --- Card 3: authentik in one step ------------------------------------------------------------------------------------

function AuthentikCard({
  publicUrl,
  reload,
  addressChanged,
}: {
  publicUrl: string
  reload: () => Promise<void>
  /** The public address was set here: card 1 reads it again. */
  addressChanged: () => Promise<unknown>
}) {
  const { t } = useTranslation()
  const [authentik, setAuthentik] = useState({ url: '', token: '' })
  const [steps, setSteps] = useState<AuthentikResult | null>(null)
  // The button stopped before it wrote anything: another issuer, this many accounts would have to link again.
  const [asking, setAsking] = useState<number | null>(null)
  // "Use it only" stopped before it saved: the new address leaves redirect addresses behind.
  const [addressAsking, setAddressAsking] = useState<AddressQuestion | null>(null)
  // What the card shows about the public address (module 1.0.10); null while it loads.
  const [address, setAddress] = useState<AuthentikAddress | null>(null)
  const { busy, problem, run } = useAction()
  // The address the browser uses, which the card proposes while nexpaper has none of its own.
  const proposal = authentikProposal(window.location.origin, import.meta.env.BASE_URL)

  const loadAddress = useCallback(async () => {
    try {
      setAddress(await oidcApi.address())
    } catch {
      setAddress(null)
    }
  }, [])
  // The address of card 1 is read again here whenever it changed.
  useEffect(() => {
    void loadAddress()
  }, [loadAddress, publicUrl])
  const unset = address !== null && !address.public_url
  const stale = authentikStale(address)

  const start = (confirm: boolean) => {
    // What the last attempt said goes first: an old failure must not stand above the new answer.
    setSteps(null)
    setAsking(null)
    return run(async () => {
      const answer = await oidcApi.authentik(authentik.url, authentik.token, confirm, unset ? proposal : '')
      // Not a failure: the button waits for the operator's yes (Bauplan 04, card 3), nothing was changed.
      const count = authentikIssuerChange(answer)
      if (count !== null) {
        setAsking(count)
        return
      }
      setSteps(answer)
      if (answer.address) setAddress(answer.address)
      // The token goes only once everything worked; after a failure the operator corrects the address.
      if (answer.ok) setAuthentik((current) => ({ ...current, token: '' }))
      // The address may have been saved on the way, even when a later step failed.
      await Promise.all([reload(), loadAddress(), answer.public_url ? addressChanged() : undefined])
    })
  }

  /** "Use it only": the proposal becomes the public address, nothing is set up. */
  const adoptOnly = (confirm: boolean) => {
    setSteps(null)
    return run(async () => {
      try {
        setAddress(await oidcApi.saveAddress(proposal, confirm))
        setAddressAsking(null)
        await addressChanged()
      } catch (error) {
        if (!(error instanceof ApiError) || error.code !== 'public_url_change') throw error
        setAddressAsking({ count: Number(error.values.count ?? 0), address: String(error.values.address ?? ''), hand: Number(error.values.hand ?? 0) })
      }
    })
  }

  return (
    <Card id="sign-in-authentik" icon={Sparkles} title={t('oidc.authentik.title')} text={t('oidc.authentik.text')}>
      {unset && address && (
        <div className="space-y-1 rounded-xl border border-warn/40 bg-warn-soft px-3 py-2 text-xs text-ink-2" data-testid="authentik-no-address">
          <p>{t('oidc.authentik.noAddress')}</p>
          <p className="font-mono text-sm break-all text-ink" data-testid="authentik-proposal">
            {proposal}
          </p>
          <p>
            {t('oidc.admin.redirect')}: <span className="font-mono break-all text-ink">{authentikRedirect(proposal, address)}</span>
          </p>
          {authentikProxyWarning(proposal, address) && <p data-testid="authentik-proxy-warning">{t('oidc.authentik.proxyWarning', { address: address.seen })}</p>}
        </div>
      )}
      {stale && (
        <p className="rounded-xl border border-warn/40 bg-warn-soft px-3 py-2 text-xs text-ink-2" data-testid="authentik-stale">
          {t('oidc.authentik.stale', { address: stale })}
        </p>
      )}
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault()
          void start(false)
        }}
      >
        <Input label={t('oidc.authentik.url')} value={authentik.url} onChange={(url) => setAuthentik({ ...authentik, url })} placeholder="https://auth.example.com" />
        <Input label={t('oidc.authentik.token')} value={authentik.token} onChange={(token) => setAuthentik({ ...authentik, token })} type="password" autoComplete="new-password" />
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
          <Button type="submit" primary busy={busy} disabled={!authentik.url.trim() || !authentik.token.trim()}>
            {unset ? t('oidc.authentik.adopt') : t('oidc.authentik.run')}
          </Button>
          {unset && (
            <Button busy={busy} onClick={() => void adoptOnly(false)}>
              {t('oidc.authentik.adoptOnly')}
            </Button>
          )}
          <a href="/api/v1/oidc/authentik/blueprint" className="inline-flex h-10 items-center justify-center gap-2 rounded-full border border-line px-4 text-sm font-semibold text-ink-2 hover:bg-sheet-2">
            <Download size={16} aria-hidden />
            {t('oidc.authentik.blueprint')}
          </a>
        </div>
      </form>
      {busy && (
        <p role="status" className="text-xs text-muted">
          {t('oidc.authentik.asking')}
        </p>
      )}
      {steps && (
        <ol className="space-y-1.5 text-sm" data-testid="authentik-steps">
          {steps.steps.map((step) => {
            const name = authentikStepKey(step.key)
            const why = step.ok ? null : authentikReasonKey(step.reason)
            return (
              <li key={step.key} className="flex gap-2">
                <span className={step.ok ? 'text-ok' : 'text-bad'} aria-hidden="true">
                  {step.ok ? '✓' : '✗'}
                </span>
                <span>
                  <span className={step.ok ? 'text-ink' : 'font-semibold text-bad'}>{name ? t(name) : step.key}</span>
                  {why && <span className="block text-xs text-muted">{t(why, { status: step.status ?? 0, count: steps.count ?? 0 })}</span>}
                </span>
              </li>
            )
          })}
        </ol>
      )}
      <Feedback problem={problem} />
      {asking !== null && (
        <Confirm
          title={t('oidc.authentik.title')}
          text={t('oidc.admin.issuerChangeConfirm', { count: asking })}
          confirm={unset ? t('oidc.authentik.adopt') : t('oidc.authentik.run')}
          onCancel={() => setAsking(null)}
          onConfirm={async () => {
            await start(true)
          }}
        />
      )}
      {addressAsking && (
        <Confirm
          title={t('oidc.admin.address')}
          text={addressQuestionText(t, addressAsking)}
          confirm={t('oidc.authentik.adoptOnly')}
          onCancel={() => setAddressAsking(null)}
          onConfirm={async () => {
            await adoptOnly(true)
          }}
        />
      )}
    </Card>
  )
}
