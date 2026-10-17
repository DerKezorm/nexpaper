/**
 * The cards of the phone block under My account: the iPhone shortcut (Devices and apps) and where uploads go (Upload).
 *
 * **The shortcut.** iOS imports only shortcuts Apple signed, which needs a Mac or the iCloud account of whoever shares it;
 * nexpaper cannot ship one. So the card explains how to build it in four steps, makes the key it needs and shows the
 * address and the header to copy. The key is an API key that only uploads ("iPhone-Kurzbefehl", 120 requests a minute,
 * 50 files an hour): a shortcut needs no more, and its value sits in the shortcut, which iCloud keeps. It stands with
 * the API keys below and is deleted there. While the operator has not switched API keys on, the card says so. When the
 * operator shared a finished shortcut by an iCloud link, the card offers "Kurzbefehl laden"; that shortcut asks for the
 * address and the key when it is added (Import Questions), and the card warns never to put one's own key into a shortcut
 * that is shared.
 */
import { Apple, Smartphone, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { apiKeysApi, authApi, phoneApi, vaultsApi, type Shortcut, type Vault } from '../api/client'

/** Sent on `window` when a card made an API key, so that the list of keys shows it at once. */
export const KEYS_CHANGED = 'nexpaper:api-keys-changed'
import { Button, Card, CopyLink, Feedback, useAction } from '../pages/settings/ui'
import { useAuth } from '../state/auth'

export function ShortcutCard() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [shortcut, setShortcut] = useState<Shortcut | null>(null)
  const [allowed, setAllowed] = useState<boolean | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const action = useAction()
  useEffect(() => {
    phoneApi.shortcut().then(setShortcut, () => undefined)
    apiKeysApi.list().then((found) => setAllowed(found.allowed === true), () => setAllowed(false))
  }, [])
  const link = shortcut?.link ?? ''
  const steps = link ? ['link1', 'link2', 'link3'] : ['build1', 'build2', 'build3', 'build4', 'link3']
  return (
    <Card id="shortcut" icon={Apple} title={t('phone.iphone.title')} text={t('phone.iphone.text')}>
      {!link && shortcut && <p className="text-sm text-ink-2">{t('phone.iphone.build')}</p>}
      <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-2" data-testid="shortcut-steps">
        {steps.map((step) => (
          <li key={step}>{t(`phone.iphone.${step}`)}</li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center gap-3">
        {link && (
          <a href={link} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-full border border-line px-4 text-sm font-semibold text-ink-2 hover:bg-sheet-2" data-testid="shortcut-link">
            <Smartphone size={16} aria-hidden /> {t('phone.iphone.load')}
          </a>
        )}
        {!token && allowed && (
          <Button
            busy={action.busy}
            onClick={() =>
              void action.run(async () => {
                const made = await apiKeysApi.make(t('phone.iphone.keyName'), null, 'upload')
                setToken(made.secret)
                window.dispatchEvent(new Event(KEYS_CHANGED))
              })
            }
          >
            {t('phone.iphone.key')}
          </Button>
        )}
        <span className="text-xs text-muted">{t('phone.iphone.android')}</span>
      </div>
      {allowed === false && (
        <p className="rounded-xl bg-sheet-2 px-4 py-3 text-sm text-ink-2" data-testid="shortcut-off">
          {t('phone.iphone.off')}{' '}
          {me?.role === 'operator' && (
            <Link to="/einstellungen?tab=api" className="font-semibold text-accent underline decoration-accent/40 underline-offset-4">
              {t('apiKeys.offOperator')}
            </Link>
          )}
        </p>
      )}
      <p className="rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink" role="note" data-testid="shortcut-warning">
        {t('phone.iphone.warning')}
      </p>
      {token && shortcut && (
        <div className="space-y-2 rounded-xl border border-accent/40 bg-accent-soft/50 p-4 text-sm" data-testid="shortcut-key">
          <p className="font-semibold">{t('phone.iphone.shown')}</p>
          <p className="text-xs text-muted">{t('phone.iphone.address')}</p>
          <CopyLink value={shortcut.upload_url} label={t('phone.iphone.address')} />
          <p className="text-xs text-muted">{t('phone.iphone.header')}</p>
          <CopyLink value={`Bearer ${token}`} label={t('phone.iphone.header')} />
          <Button small onClick={() => setToken(null)}>
            {t('phone.iphone.done')}
          </Button>
        </div>
      )}
      <Feedback problem={action.problem} />
    </Card>
  )
}

/** "Wohin deine Uploads gehen": the vaults the person may add to; kept with the account. */
export function UploadVaultCard() {
  const { t } = useTranslation()
  const { me, setMe } = useAuth()
  const [vaults, setVaults] = useState<Vault[] | null>(null)
  const action = useAction()
  useEffect(() => {
    vaultsApi.list().then((found) => setVaults(Array.isArray(found) ? found : []), () => setVaults([]))
  }, [])
  if (!me || !vaults) return null
  const writable = vaults.filter((vault) => vault.my_right === 'edit' || vault.my_right === 'manage')
  const own = writable.find((vault) => vault.personal_of === me.id)
  const chosen = writable.some((vault) => vault.id === me.profile.default_vault) ? me.profile.default_vault : (own?.id ?? null)
  return (
    <Card id="upload-vault" icon={Upload} title={t('phone.vault.title')} text={t('phone.vault.text')}>
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={t('phone.vault.title')}>
        {writable.map((vault) => (
          <button
            key={vault.id}
            type="button"
            role="radio"
            aria-checked={vault.id === chosen}
            onClick={() => {
              if (vault.id === chosen) return
              const before = me
              setMe({ ...me, profile: { ...me.profile, default_vault: vault.id } })
              void action.run(async () => setMe({ ...me, profile: await authApi.preferences({ default_vault: vault.id }) })).then((worked) => worked || setMe(before))
            }}
            className={`rounded-full border px-4 py-2 text-sm font-semibold ${vault.id === chosen ? 'border-accent/50 bg-accent-soft text-accent' : 'border-line text-ink-2 hover:text-ink'}`}
          >
            {vault.personal_of === me.id ? t('phone.quick.mine') : vault.name}
          </button>
        ))}
      </div>
      <Feedback problem={action.problem} />
    </Card>
  )
}
