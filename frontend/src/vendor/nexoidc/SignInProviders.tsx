/**
 * Since 1.2.0: the cards "Sign-in providers" and "authentik in one step" on the page Server › Sign-in of every app, as
 * nexnotes had them (``pages/settings/SignInCards.tsx``), built only from the ui kit (plan "Einstellungen", Anmeldung):
 *
 * - "Sign-in providers" (KeyRound): one row per provider with the grip to drag (``IconButton`` GripVertical; the arrow
 *   keys move it too), its name and issuer, the badges active/off and "set up through authentik", a small "Edit"
 *   (secondary) and "Remove" (danger); below "Add provider" (primary, Plus). The form is a dialog in the order of the
 *   blueprint. A provider the app cannot change (``editable`` false) makes the list read only.
 * - "authentik in one step" (Sparkles): address and API token, "Set up" (or "Use it and set up" while the app has no
 *   public address, with "Use it only"), the link to the blueprint (grey words without an address), the steps with
 *   the reason of a failure.
 *
 * The logic is the module's (``oidc.ts``, the server's routes); the app hands over how it calls them (``calls``), its
 * name (placeholders), its API prefix (``/api``, nexpaper ``/api/v1``), its words (``t``, namespace ``oidc``) and how
 * it reads a failure (``errorOf``). No coupling (nexsuite) any more.
 *
 * Copied unchanged into frontend/src/vendor/nexoidc/ by bauplaene/oidc/tools/sync.py; changed only there.
 */
import { CircleCheck, CircleX } from 'lucide-react'
import { useCallback, useEffect, useState, type DragEvent, type FormEvent, type ReactNode } from 'react'

import {
  Badge,
  Button,
  Buttons,
  Card,
  CheckboxRow,
  Collapsible,
  ConfirmDialog,
  CopyRow,
  Dialog,
  Field,
  IconButton,
  Notice,
  Row,
  Rows,
  TextLink,
  useNexuiTexts,
  type IconName,
} from '../nexui'
import {
  OIDC_BUTTONS,
  authentikDone,
  authentikIssuerChange,
  authentikProposal,
  authentikProxyWarning,
  authentikReasonKey,
  authentikRedirect,
  authentikStale,
  authentikStepKey,
  issuerPlaceholder,
  movedOrder,
  oidcErrorKey,
  oidcFormErrorKey,
  redirectPreview,
  slugFromLabel,
  type AuthentikAddress,
  type OidcButton,
} from './oidc'

/** The app's ``t`` (i18next), with the values of a sentence. */
export type Translate = (key: string, values?: Record<string, unknown>) => string

/** A provider as ``GET <api>/oidc/admin/providers`` lists it. */
export interface OidcProviderRow {
  id: number | string
  slug: string
  label: string
  issuer: string
  client_id: string
  has_secret: boolean
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
  /** "" by hand, "authentik" through the button. */
  managed: string
  redirect_uri: string
  links: number
  editable: boolean
}

/** The provider form. ``slug`` counts only when adding; an empty ``client_secret`` keeps the stored one. */
export interface OidcProviderForm {
  label: string
  slug?: string
  issuer: string
  client_id: string
  client_secret: string
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
}

export interface OidcImpact {
  issuer_change: number
  count: number
  only: number
}

export interface AuthentikStep {
  key: string
  ok: boolean
  reason?: string
  status?: number
}

export interface AuthentikResult {
  /** The server always sends it; an answer without it counts by its steps (``authentikDone``). */
  ok?: boolean
  steps: AuthentikStep[]
  count?: number
  public_url?: string
  address?: AuthentikAddress | null
}

/** What saving the public address would leave behind at authentik (409 ``public_url_change``). */
export interface AddressQuestion {
  count: number
  hand: number
  address: string
}

/** How the cards call the app's server (the module's routes under the app's prefix). */
export interface OidcAdminCalls {
  providers: () => Promise<OidcProviderRow[]>
  add: (form: OidcProviderForm) => Promise<unknown>
  save: (id: OidcProviderRow['id'], form: OidcProviderForm) => Promise<unknown>
  remove: (id: OidcProviderRow['id']) => Promise<unknown>
  impact: (id: OidcProviderRow['id'], issuer?: string) => Promise<OidcImpact>
  order: (ids: OidcProviderRow['id'][]) => Promise<unknown>
  authentik: (url: string, token: string, confirmIssuerChange: boolean, publicUrl: string) => Promise<AuthentikResult>
  authentikAddress: () => Promise<AuthentikAddress>
  authentikSaveAddress: (publicUrl: string, confirm: boolean) => Promise<AuthentikAddress>
}

/** A failure as the app reads it: the module's code and the values of the answer (``field``, ``count`` …). */
export type ErrorOf = (error: unknown) => { code: string; values: Record<string, unknown> } | null

interface Shared {
  t: Translate
  /** The app's name (``nexnotes``): the issuer's placeholder. */
  app: string
  calls: OidcAdminCalls
  errorOf: ErrorOf
  /** ``/api``, nexpaper ``/api/v1``: where the module's routes live (redirect, blueprint). */
  apiPrefix?: string
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

function OidcButtonOf({
  name,
  t,
  children,
  ...rest
}: {
  name: OidcButton
  t: Translate
  children?: ReactNode
  type?: 'button' | 'submit'
  busy?: boolean
  disabled?: boolean
  onClick?: () => void
  testId?: string
  'aria-label'?: string
}) {
  const spec: { kind: 'primary' | 'secondary' | 'danger'; icon: string; size?: 'sm' } = OIDC_BUTTONS[name]
  return (
    <Button kind={spec.kind} icon={spec.icon as IconName} size={spec.size ?? 'md'} {...rest}>
      {children ?? t(name)}
    </Button>
  )
}

function Problem({ text }: { text: string }) {
  return text ? (
    <p role="alert" className="m-0 text-sm leading-5 text-[var(--nexui-danger)]">
      {text}
    </p>
  ) : null
}

function failureText(t: Translate, errorOf: ErrorOf, error: unknown): string {
  const found = errorOf(error)
  const key = found ? (oidcFormErrorKey(found.code) ?? oidcErrorKey(found.code)) : null
  return key ? t(key, found?.values) : t('oidc.admin.failed')
}

/** The two cards together: the list is loaded once and shared, the authentik button changes it too. ``onAddress``:
 * the button stored the public address; the app reads its settings again. */
export function SignInProviders({
  publicUrl,
  onAddress,
  ...shared
}: Shared & { publicUrl: string; onAddress: () => Promise<void> | void }) {
  const [providers, setProviders] = useState<OidcProviderRow[] | null>(null)
  const { calls } = shared
  const load = useCallback(async () => setProviders(await calls.providers()), [calls])
  useEffect(() => {
    let live = true
    calls.providers().then(
      (rows) => live && setProviders(rows),
      () => live && setProviders([]),
    )
    return () => {
      live = false
    }
  }, [calls])
  return (
    <>
      <ProvidersCard {...shared} providers={providers} reload={load} publicUrl={publicUrl} />
      <AuthentikCard {...shared} publicUrl={publicUrl} reload={load} onAddress={onAddress} />
    </>
  )
}

/** The card "Sign-in providers". */
export function ProvidersCard({
  t,
  app,
  calls,
  errorOf,
  apiPrefix = '/api',
  providers,
  reload,
  publicUrl,
}: Shared & { providers: OidcProviderRow[] | null; reload: () => Promise<void>; publicUrl: string }) {
  const kit = useNexuiTexts()
  const [editing, setEditing] = useState<OidcProviderRow | 'new' | null>(null)
  const [removing, setRemoving] = useState<{ entry: OidcProviderRow; count: number; only: number } | null>(null)
  const [dragged, setDragged] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const list = providers ?? []
  const readOnly = list.some((entry) => !entry.editable)

  const run = async (work: () => Promise<void>) => {
    setBusy(true)
    setProblem('')
    try {
      await work()
    } catch (error) {
      setProblem(failureText(t, errorOf, error))
    } finally {
      setBusy(false)
    }
  }

  const move = (from: number, to: number) => {
    const order = movedOrder(
      list.map((entry) => entry.id),
      from,
      to,
    )
    if (!order) return
    void run(async () => {
      await calls.order(order)
      await reload()
    })
  }

  // Dropped on a row: the row under the pointer, found among the list's items.
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    const item = (event.target as Element).closest('li')
    const items = item?.parentElement ? [...item.parentElement.children] : []
    const to = item ? items.indexOf(item) : -1
    if (dragged !== null && to >= 0) move(dragged, to)
    setDragged(null)
  }

  return (
    <Card id="sign-in-providers" icon="KeyRound" title={t('oidc.admin.providersTitle')} subtitle={t('oidc.admin.providersText')}>
      {providers !== null && list.length === 0 && <p className="m-0 text-sm leading-5 text-[var(--nexui-text-muted)]">{t('oidc.admin.empty')}</p>}
      {list.length > 0 && (
        <div onDragOver={(event) => event.preventDefault()} onDrop={drop} data-testid="provider-list">
          <Rows label={t('oidc.admin.providersTitle')}>
            {list.map((entry, index) => (
              <Row
                key={entry.id}
                testId={`provider-${entry.slug}`}
                lead={
                  !readOnly && list.length > 1 ? (
                    <IconButton
                      icon="GripVertical"
                      aria-label={t('oidc.admin.order', { name: entry.label })}
                      draggable
                      onDragStart={() => setDragged(index)}
                      onDragEnd={() => setDragged(null)}
                      onKeyDown={(event) => {
                        if (event.key === 'ArrowUp') {
                          event.preventDefault()
                          move(index, index - 1)
                        }
                        if (event.key === 'ArrowDown') {
                          event.preventDefault()
                          move(index, index + 1)
                        }
                      }}
                    />
                  ) : null
                }
                name={entry.label}
                sub={entry.issuer}
                badge={
                  <>
                    <Badge tone={entry.enabled ? 'on' : 'off'}>{entry.enabled ? t('oidc.admin.active') : t('oidc.admin.inactive')}</Badge>
                    {entry.managed === 'authentik' && <Badge tone="accent">{t('oidc.admin.managed')}</Badge>}
                  </>
                }
                action={
                  entry.editable ? (
                    <Buttons>
                      {/* Named "<action>: <provider>" (as before 1.2.0, since E37), so that a screen reader tells the rows apart. */}
                      <OidcButtonOf name="oidc.admin.edit" t={t} aria-label={`${t('oidc.admin.edit')}: ${entry.label}`} onClick={() => setEditing(entry)} />
                      <OidcButtonOf
                        name="oidc.admin.remove"
                        t={t}
                        aria-label={`${t('oidc.admin.remove')}: ${entry.label}`}
                        busy={busy}
                        onClick={() =>
                          void run(async () => {
                            const impact = await calls.impact(entry.id)
                            setRemoving({ entry, count: impact.count, only: impact.only })
                          })
                        }
                      />
                    </Buttons>
                  ) : null
                }
              />
            ))}
          </Rows>
        </div>
      )}
      {!readOnly && (
        <div>
          <OidcButtonOf name="oidc.admin.add" t={t} onClick={() => setEditing('new')} testId="provider-add" />
        </div>
      )}
      <Problem text={problem} />
      {editing !== null && (
        <ProviderDialog
          t={t}
          app={app}
          calls={calls}
          errorOf={errorOf}
          apiPrefix={apiPrefix}
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
        <ConfirmDialog
          title={t('oidc.admin.remove')}
          text={t('oidc.admin.removeConfirm', { name: removing.entry.label, count: removing.count, only: removing.only })}
          confirm={{ label: t('oidc.admin.remove'), kind: OIDC_BUTTONS.removeConfirm.kind, icon: OIDC_BUTTONS.removeConfirm.icon }}
          cancel={t('oidc.admin.cancel')}
          closeLabel={kit.close}
          busy={busy}
          onCancel={() => setRemoving(null)}
          onConfirm={() =>
            void run(async () => {
              await calls.remove(removing.entry.id)
              setRemoving(null)
              await reload()
            })
          }
        />
      )}
    </Card>
  )
}

/** The same issuer, however written at the end (the server's ``same_issuer`` for an issuer without a placeholder). */
function sameIssuer(a: string, b: string): boolean {
  return a.trim().replace(/\/+$/, '') === b.trim().replace(/\/+$/, '')
}

/** The provider form as a dialog, fields in the blueprint's order. */
function ProviderDialog({
  t,
  app,
  calls,
  errorOf,
  apiPrefix = '/api',
  entry,
  publicUrl,
  onClose,
  onSaved,
}: Shared & { entry: OidcProviderRow | null; publicUrl: string; onClose: () => void; onSaved: () => Promise<void> }) {
  const kit = useNexuiTexts()
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
  const [busy, setBusy] = useState(false)
  const [fieldError, setFieldError] = useState<{ field: FieldName; text: string } | null>(null)
  const [confirmIssuer, setConfirmIssuer] = useState<number | null>(null)
  const [more, setMore] = useState(false)

  const slug = entry ? entry.slug : slugTyped ? (form.slug ?? '') : slugFromLabel(form.label)
  const redirect = entry ? entry.redirect_uri : redirectPreview(publicUrl, window.location.origin, apiPrefix, slug)
  const set = (change: Partial<OidcProviderForm>) => setForm((current) => ({ ...current, ...change }))

  const errorFor = (error: unknown): { field: FieldName; text: string } => {
    const found = errorOf(error)
    const field = (typeof found?.values.field === 'string' ? found.values.field : 'id') as FieldName
    return { field, text: failureText(t, errorOf, error) }
  }

  const save = async () => {
    setBusy(true)
    setFieldError(null)
    try {
      const body: OidcProviderForm = entry ? form : { ...form, slug }
      if (entry) await calls.save(entry.id, body)
      else await calls.add(body)
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
        const impact = await calls.impact(entry.id, form.issuer.trim())
        if (impact.issuer_change > 0) return setConfirmIssuer(impact.issuer_change)
      } catch (error) {
        return setFieldError(errorFor(error))
      }
    }
    await save()
  }

  const problemAt = (field: FieldName) => (fieldError?.field === field ? fieldError.text : undefined)

  return (
    <Dialog title={entry ? `${t('oidc.admin.edit')}: ${entry.label}` : t('oidc.admin.add')} onClose={() => !busy && onClose()} closeLabel={kit.close} wide testId="provider-dialog">
      <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)} data-testid="provider-form">
        <Field label={t('oidc.admin.label')} value={form.label} onChange={(event) => set({ label: event.target.value })} error={problemAt('label')} />
        {entry ? (
          <p className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]">
            {t('oidc.admin.slug')}: <code className="font-mono">{entry.slug}</code>
          </p>
        ) : (
          <Field
            label={t('oidc.admin.slug')}
            value={slug}
            onChange={(event) => {
              setSlugTyped(true)
              set({ slug: event.target.value })
            }}
            hints={[t('oidc.admin.slugHint')]}
            error={problemAt('slug')}
          />
        )}
        <Field
          label={t('oidc.admin.issuer')}
          value={form.issuer}
          onChange={(event) => set({ issuer: event.target.value })}
          placeholder={issuerPlaceholder(app)}
          hints={[t('oidc.admin.issuerHint')]}
          error={problemAt('issuer')}
        />
        <Field label={t('oidc.admin.clientId')} value={form.client_id} onChange={(event) => set({ client_id: event.target.value })} error={problemAt('client_id')} />
        <Field
          label={t('oidc.admin.secret')}
          value={form.client_secret}
          onChange={(event) => set({ client_secret: event.target.value })}
          type="password"
          autoComplete="new-password"
          placeholder={entry?.has_secret ? t('oidc.admin.secretKept') : ''}
          error={problemAt('client_secret')}
        />
        <div className="flex flex-col gap-1">
          {/* Seen as a heading; readers hear it as the name of the field (CopyRow's label). */}
          <span aria-hidden className="text-sm leading-5 font-medium text-[var(--nexui-text)]">
            {t('oidc.admin.redirect')}
          </span>
          <CopyRow label={t('oidc.admin.redirect')} value={redirect} testId="provider-redirect" />
        </div>
        <CheckboxRow label={t('oidc.admin.enabled')} checked={form.enabled} onChange={(enabled) => set({ enabled })} />
        <CheckboxRow label={t('oidc.admin.autoCreate')} hint={t('oidc.admin.autoCreateHint')} checked={form.auto_create} onChange={(auto_create) => set({ auto_create })} />
        <CheckboxRow
          label={t('oidc.admin.trustsSecondFactor')}
          hint={t('oidc.admin.trustsSecondFactorHint')}
          checked={form.trusts_second_factor}
          onChange={(trusts_second_factor) => set({ trusts_second_factor })}
        />
        <Collapsible title={t('oidc.admin.more')} open={more || fieldError?.field === 'scopes'} onOpenChange={setMore} id="provider-more">
          <Field label={t('oidc.admin.scopes')} value={form.scopes} onChange={(event) => set({ scopes: event.target.value })} error={problemAt('scopes')} />
        </Collapsible>
        <Problem text={problemAt('id') ?? ''} />
        <Buttons end>
          <OidcButtonOf name="oidc.admin.cancel" t={t} onClick={onClose} busy={busy} />
          <OidcButtonOf name="oidc.admin.save" t={t} type="submit" busy={busy} />
        </Buttons>
      </form>
      {confirmIssuer !== null && (
        <ConfirmDialog
          title={t('oidc.admin.issuer')}
          text={t('oidc.admin.issuerChangeConfirm', { count: confirmIssuer })}
          confirm={{ label: t('oidc.admin.save'), kind: OIDC_BUTTONS.issuerChange.kind, icon: OIDC_BUTTONS.issuerChange.icon }}
          cancel={t('oidc.admin.cancel')}
          closeLabel={kit.close}
          onCancel={() => setConfirmIssuer(null)}
          onConfirm={() => {
            setConfirmIssuer(null)
            void save()
          }}
        />
      )}
    </Dialog>
  )
}

/** The card "authentik in one step". ``basePath``: the app's base (Vite's ``import.meta.env.BASE_URL``), for the
 * address the card suggests; ``blueprintUrl``: where the blueprint downloads (``<apiPrefix>/oidc/authentik/blueprint``
 * by default). */
export function AuthentikCard({
  t,
  calls,
  errorOf,
  apiPrefix = '/api',
  publicUrl,
  reload,
  onAddress,
  basePath = '',
  blueprintUrl,
}: Shared & {
  publicUrl: string
  reload: () => Promise<void>
  onAddress: () => Promise<void> | void
  basePath?: string
  blueprintUrl?: string
}) {
  const kit = useNexuiTexts()
  const [authentik, setAuthentik] = useState({ url: '', token: '' })
  const [steps, setSteps] = useState<AuthentikResult | null>(null)
  const [asking, setAsking] = useState<number | null>(null)
  const [askingAddress, setAskingAddress] = useState<AddressQuestion | null>(null)
  const [unusable, setUnusable] = useState(false)
  const [address, setAddress] = useState<AuthentikAddress | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')

  const loadAddress = useCallback(() => calls.authentikAddress().then(setAddress, () => setAddress(null)), [calls])
  useEffect(() => {
    void loadAddress()
  }, [publicUrl, loadAddress])

  // Without a public address of its own the app suggests the one this browser uses; the operator confirms it with the
  // button (never a guess from the request: the server sees http behind a proxy that ends TLS).
  const proposal = authentikProposal(window.location.origin, basePath)
  const noAddress = address !== null && !address.public_url
  const stale = authentikStale(address)
  const blueprint = blueprintUrl ?? `${apiPrefix.replace(/\/+$/, '')}/oidc/authentik/blueprint`

  const run = async (work: () => Promise<void>) => {
    setBusy(true)
    setProblem('')
    try {
      await work()
    } catch (error) {
      setProblem(failureText(t, errorOf, error))
    } finally {
      setBusy(false)
    }
  }

  const start = (confirmIssuerChange: boolean) => {
    setSteps(null)
    setAsking(null)
    setUnusable(false)
    void run(async () => {
      const answer = await calls.authentik(authentik.url, authentik.token, confirmIssuerChange, noAddress ? proposal : '')
      const question = authentikIssuerChange(answer)
      // Another issuer is a question, not a failure: only the question shows, no line of steps behind it.
      setSteps(question === null ? answer : null)
      setAsking(question)
      if (answer.address) setAddress(answer.address)
      // The token goes only once everything worked; after a failure the operator corrects the address and tries again.
      if (authentikDone(answer)) setAuthentik((current) => ({ ...current, token: '' }))
      await reload()
      if (answer.public_url) await onAddress()
      await loadAddress()
    })
  }

  const adoptOnly = (confirm: boolean) => {
    setSteps(null)
    setUnusable(false)
    void run(async () => {
      try {
        setAddress(await calls.authentikSaveAddress(proposal, confirm))
        setAskingAddress(null)
        await onAddress()
      } catch (error) {
        const found = errorOf(error)
        if (found?.code === 'public_url_change') {
          setAskingAddress({ count: Number(found.values.count ?? 0), hand: Number(found.values.hand ?? 0), address: String(found.values.address ?? '') })
          return
        }
        if (found?.code === 'public_url_invalid') {
          setUnusable(true)
          return
        }
        throw error
      }
    })
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    start(false)
  }

  const addressText = askingAddress
    ? [
        askingAddress.count > 0 ? t('oidc.admin.addressChangeConfirm', { address: askingAddress.address }) : '',
        askingAddress.hand > 0 ? t('oidc.admin.addressChangeHand', { count: askingAddress.hand }) : '',
      ]
        .filter(Boolean)
        .join(' ')
    : ''

  return (
    <Card id="sign-in-authentik" icon="Sparkles" title={t('oidc.authentik.title')} subtitle={t('oidc.authentik.text')}>
      {noAddress && address && (
        <Notice tone="warn" testId="authentik-no-address">
          <span className="flex flex-col gap-1">
            <span>{t('oidc.authentik.noAddress')}</span>
            <code className="font-mono break-all" data-testid="authentik-proposal">
              {proposal}
            </code>
            <span>
              {t('oidc.admin.redirect')}: <code className="font-mono break-all">{authentikRedirect(proposal, address)}</code>
            </span>
            {authentikProxyWarning(proposal, address) && <span data-testid="authentik-proxy-warning">{t('oidc.authentik.proxyWarning', { address: address.seen })}</span>}
          </span>
        </Notice>
      )}
      {stale && (
        <Notice tone="warn" testId="authentik-stale">
          {t('oidc.authentik.stale', { address: stale })}
        </Notice>
      )}
      <form className="flex flex-col gap-4" onSubmit={submit} data-testid="authentik-form">
        <Field label={t('oidc.authentik.url')} value={authentik.url} onChange={(event) => setAuthentik({ ...authentik, url: event.target.value })} placeholder="https://auth.example.com" type="url" />
        <Field
          label={t('oidc.authentik.token')}
          value={authentik.token}
          onChange={(event) => setAuthentik({ ...authentik, token: event.target.value })}
          type="password"
          autoComplete="new-password"
        />
        <div className="flex flex-wrap items-center gap-3">
          <OidcButtonOf
            name={noAddress ? 'oidc.authentik.adopt' : 'oidc.authentik.run'}
            t={t}
            type="submit"
            busy={busy}
            disabled={!authentik.url.trim() || !authentik.token.trim()}
            testId="authentik-run"
          />
          {noAddress && <OidcButtonOf name="oidc.authentik.adoptOnly" t={t} busy={busy} onClick={() => adoptOnly(false)} />}
          {noAddress ? (
            <span className="text-sm leading-5 text-[var(--nexui-text-muted)]" data-testid="authentik-blueprint">
              {t('oidc.authentik.blueprint')}
            </span>
          ) : (
            <TextLink href={blueprint} testId="authentik-blueprint">
              {t('oidc.authentik.blueprint')}
            </TextLink>
          )}
        </div>
      </form>
      {unusable && <Problem text={t('oidc.authentik.why.unusable')} />}
      {busy && (
        <p role="status" className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]">
          {t('oidc.authentik.asking')}
        </p>
      )}
      {steps && (
        <ol className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm" data-testid="authentik-steps">
          {steps.steps.map((step) => {
            const name = authentikStepKey(step.key)
            const why = step.ok ? null : authentikReasonKey(step.reason)
            const Icon = step.ok ? CircleCheck : CircleX
            return (
              <li key={step.key} className="flex gap-2" data-ok={step.ok}>
                <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0" style={{ color: step.ok ? 'var(--nexui-ok)' : 'var(--nexui-danger)' }} />
                <span>
                  <span className={step.ok ? 'text-[var(--nexui-text)]' : 'font-medium text-[var(--nexui-danger)]'}>{name ? t(name) : step.key}</span>
                  {why && <span className="block text-xs text-[var(--nexui-text-muted)]">{t(why, { status: step.status ?? 0, count: steps.count ?? 0 })}</span>}
                </span>
              </li>
            )
          })}
        </ol>
      )}
      <Problem text={problem} />
      {asking !== null && (
        <ConfirmDialog
          title={t('oidc.admin.issuer')}
          text={t('oidc.admin.issuerChangeConfirm', { count: asking })}
          confirm={{ label: t('oidc.authentik.run'), kind: OIDC_BUTTONS.issuerChange.kind, icon: OIDC_BUTTONS['oidc.authentik.run'].icon }}
          cancel={t('oidc.admin.cancel')}
          closeLabel={kit.close}
          onCancel={() => setAsking(null)}
          onConfirm={() => start(true)}
        />
      )}
      {askingAddress && (
        <ConfirmDialog
          title={t('oidc.admin.address')}
          text={addressText}
          confirm={{ label: t('oidc.authentik.adoptOnly'), kind: OIDC_BUTTONS['oidc.authentik.adoptOnly'].kind, icon: OIDC_BUTTONS['oidc.authentik.adoptOnly'].icon }}
          cancel={t('oidc.admin.cancel')}
          closeLabel={kit.close}
          onCancel={() => setAskingAddress(null)}
          onConfirm={() => adoptOnly(true)}
        />
      )}
    </Card>
  )
}
