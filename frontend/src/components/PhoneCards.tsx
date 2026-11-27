/**
 * The cards of the phone block under My account: the iPhone shortcut (Devices and apps) and where uploads go (Upload).
 *
 * **The shortcut.** iOS imports only shortcuts Apple signed, which needs a Mac or the iCloud account of whoever shares it;
 * nexpaper cannot ship one. So the card explains how to build it in four steps, makes the key it needs and shows the
 * address and the header to copy, once, in a window as the key module shows a new key (schluessel 1.2.0, B23): Escape
 * and a click beside it leave it open, the close button asks first, "Fertig" ends it. The key is an API key that only uploads ("iPhone-Kurzbefehl", 120 requests a minute,
 * 50 files an hour): a shortcut needs no more, and its value sits in the shortcut, which iCloud keeps. It stands with
 * the API keys below and is deleted there. While the operator has not switched API keys on, the card says so. When the
 * operator shared a finished shortcut by an iCloud link, the card offers "Kurzbefehl laden"; that shortcut asks for the
 * address and the key when it is added (Import Questions), and the card warns never to put one's own key into a shortcut
 * that is shared.
 */
import { Apple, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { apiKeysApi, authApi, phoneApi, vaultsApi, type Shortcut, type Vault } from '../api/client'
import { useAction } from '../pages/settings/actions'
import { Outcome } from '../pages/settings/Outcome'
import { useAuth } from '../state/auth'
import { BUTTONS, fillKeys, useKeyTexts } from '../vendor/nexschluessel'
import { Button, Buttons, Card, ConfirmDialog, CopyRow, Dialog, Notice, Segment, useNexuiTexts } from '../vendor/nexui'

/** Sent on `window` when a card made an API key, so that the list of keys shows it at once. */
export const KEYS_CHANGED = 'nexpaper:api-keys-changed'

export function ShortcutCard() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [shortcut, setShortcut] = useState<Shortcut | null>(null)
  const [allowed, setAllowed] = useState<boolean | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)
  const action = useAction()
  useEffect(() => {
    phoneApi.shortcut().then(setShortcut, () => undefined)
    apiKeysApi.list().then((found) => setAllowed(found.allowed === true), () => setAllowed(false))
  }, [])
  const link = shortcut?.link ?? ''
  const steps = link ? ['link1', 'link2', 'link3'] : ['build1', 'build2', 'build3', 'build4', 'link3']
  return (
    <Card id="shortcut" icon={Apple} title={t('phone.iphone.title')} subtitle={t('phone.iphone.text')}>
      {!link && shortcut && <p className="m-0 text-sm">{t('phone.iphone.build')}</p>}
      <ol className="m-0 list-decimal space-y-1 pl-5 text-sm" data-testid="shortcut-steps">
        {steps.map((step) => (
          <li key={step}>{t(`phone.iphone.${step}`)}</li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center gap-3">
        {link && (
          <Button kind="secondary" icon="Download" href={link} testId="shortcut-link">
            {t('phone.iphone.load')}
          </Button>
        )}
        {!token && allowed && (
          <Button
            kind="primary"
            icon="KeyRound"
            busy={action.busy}
            testId="shortcut-make-key"
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
        <span className="text-xs text-[var(--nexui-text-muted)]">{t('phone.iphone.android')}</span>
      </div>
      {allowed === false && (
        <div data-testid="shortcut-off">
          <Notice tone="warn">
            {t('phone.iphone.off')}{' '}
            {me?.role === 'operator' && (
              <Link to="/settings/server-connections#interfaces" className="font-semibold underline underline-offset-4">
                {t('apiKeys.offOperator')}
              </Link>
            )}
          </Notice>
        </div>
      )}
      <div data-testid="shortcut-warning">
        <Notice tone="warn">{t('phone.iphone.warning')}</Notice>
      </div>
      {token && shortcut && (
        <ShortcutKey
          address={shortcut.upload_url}
          token={token}
          asking={asking}
          onAsk={setAsking}
          onDone={() => {
            setAsking(false)
            setToken(null)
          }}
        />
      )}
      <Outcome problem={action.problem} />
    </Card>
  )
}

/** The new key of the shortcut, shown once in a window as the key module shows a new key (schluessel 1.2.0, B23), with
 * the module's question before closing it without "Fertig". */
function ShortcutKey({ address, token, asking, onAsk, onDone }: { address: string; token: string; asking: boolean; onAsk: (asking: boolean) => void; onDone: () => void }) {
  const { t, i18n } = useTranslation()
  const kit = useNexuiTexts()
  const { texts } = useKeyTexts(i18n.language)
  return (
    <>
      <Dialog title={fillKeys(texts.key.made, { name: t('phone.iphone.keyName') })} onClose={() => onAsk(true)} closeLabel={kit.close} dismissable={false} testId="shortcut-key">
        <div className="flex flex-col gap-4">
          <p className="m-0 text-sm leading-5 text-[var(--nexui-text)]">{t('phone.iphone.shown')}</p>
          <CopyRow value={address} label={t('phone.iphone.address')} />
          <CopyRow value={`Bearer ${token}`} label={t('phone.iphone.header')} />
          <Buttons end>
            <Button kind={BUTTONS.done.kind} icon={BUTTONS.done.icon} onClick={onDone} testId="shortcut-key-done">
              {t('phone.iphone.done')}
            </Button>
          </Buttons>
        </div>
      </Dialog>
      {asking && (
        <ConfirmDialog
          title={texts.key.closeMadeTitle}
          text={texts.key.closeMadeText}
          confirm={{ label: texts.key.closeMade, kind: BUTTONS.done.kind, icon: BUTTONS.done.icon }}
          cancel={texts.key.closeMadeBack}
          closeLabel={kit.close}
          onCancel={() => onAsk(false)}
          onConfirm={onDone}
          testId="shortcut-close-made"
        />
      )}
    </>
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
    <Card id="upload-vault" icon={Upload} title={t('phone.vault.title')} subtitle={t('phone.vault.text')}>
      <Segment
        label={t('phone.vault.title')}
        hideLabel
        value={String(chosen ?? '')}
        options={writable.map((vault) => ({ value: String(vault.id), label: vault.personal_of === me.id ? t('phone.quick.mine') : vault.name }))}
        onChange={(value) => {
          const id = Number(value)
          const before = me
          setMe({ ...me, profile: { ...me.profile, default_vault: id } })
          void action.run(async () => setMe({ ...me, profile: await authApi.preferences({ default_vault: id }) })).then((worked) => worked || setMe(before))
        }}
      />
      <Outcome problem={action.problem} />
    </Card>
  )
}
