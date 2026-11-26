/**
 * Server › General, place 4: "Web Push" (plan "Einstellungen", E13, E33: only where there is something to set): ready
 * and how many devices, the contact for the push services, the key pair with a renewal and a test, more push services
 * beyond the known ones, and what goes out. The person's own devices are under My account › Notifications ("Auf welchem
 * Weg"), the switch for the notice of a new sign-in under Security.
 */
import { BellRing } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { pushApi, type PushSettings } from '../../api/client'
import { useAuth } from '../../state/auth'
import { Badge, Box, Button, Card, Field } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'
import { useAsk } from './useAsk'

const AREA = 'block min-h-24 w-full rounded-[9px] border border-solid border-[var(--nexui-edge)] bg-[var(--nexui-field)] px-3 py-2 font-mono text-[0.85rem] text-[var(--nexui-text)] outline-none focus:border-[var(--nexui-accent)]'

export function PushServerCard() {
  const { t } = useTranslation()
  const { me } = useAuth()
  const [stored, setStored] = useState<PushSettings | null>(null)
  const [contact, setContact] = useState('')
  const [hosts, setHosts] = useState('')
  const action = useAction()
  const hintId = useId()
  const areaId = useId()
  const { ask, dialog } = useAsk()

  const take = (found: PushSettings) => {
    setStored(found)
    setContact(found.contact)
    setHosts(found.hosts.join('\n'))
  }
  useEffect(() => {
    let alive = true
    pushApi.settings().then((found) => alive && take(found), () => undefined)
    return () => {
      alive = false
    }
  }, [])
  if (!stored) return null

  const lines = () => hosts.split('\n').map((line) => line.trim()).filter(Boolean)
  return (
    <Card id="push-server" icon={BellRing} title={t('server.push.title')} subtitle={t('server.push.text')}>
      <div>
        <Badge tone="on" testId="push-ready">
          {t('server.push.ready', { count: stored.devices })}
        </Badge>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void action.run(async () => take(await pushApi.saveSettings({ contact: contact.trim() })), t('server.push.saved'))
        }}
      >
        <Field
          label={t('server.push.contact')}
          value={contact}
          onChange={(event) => setContact(event.target.value)}
          placeholder={stored.contact_used}
          hints={[t('server.push.contactHint')]}
          action={
            <Button kind="secondary" icon="Check" type="submit" busy={action.busy}>
              {t('common.save')}
            </Button>
          }
        />
      </form>
      <Box
        title={t('server.push.keys')}
        hint={t('server.push.keysText')}
        testId="push-keys"
        actions={
          <>
            <Button
              kind="danger"
              icon="RefreshCw"
              onClick={() =>
                ask({
                  title: t('server.push.renewTitle'),
                  text: t('server.push.renewText'),
                  confirm: t('server.push.renew'),
                  icon: 'RefreshCw',
                  password: me?.sign_in === 'password',
                  run: async (password) => {
                    take(await pushApi.renew(password))
                    void action.run(async () => undefined, t('server.push.renewed'))
                  },
                })
              }
            >
              {t('server.push.renew')}
            </Button>
            <Button
              kind="secondary"
              icon="Send"
              busy={action.busy}
              onClick={() =>
                void action.run(async () => {
                  await pushApi.probe()
                  take(await pushApi.settings())
                }, t('me.push.probed'))
              }
            >
              {t('server.push.probe')}
            </Button>
          </>
        }
      >
        <code className="block rounded-[9px] bg-[var(--nexui-field)] px-3 py-1.5 font-mono text-xs break-all">{stored.key}</code>
      </Box>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          void action.run(async () => take(await pushApi.saveSettings({ hosts: lines() })), t('server.push.saved'))
        }}
      >
        <label htmlFor={areaId} className="text-sm font-medium">
          {t('server.push.hosts')}
        </label>
        <textarea
          id={areaId}
          value={hosts}
          onChange={(event) => setHosts(event.target.value)}
          rows={2}
          spellCheck={false}
          autoCapitalize="off"
          autoComplete="off"
          maxLength={6000}
          placeholder="push.example.com"
          aria-describedby={hintId}
          className={AREA}
        />
        <span id={hintId} className="text-xs text-[var(--nexui-text-muted)]">
          {t('server.push.hostsHint')}
        </span>
        <div>
          <Button kind="secondary" icon="Check" type="submit" busy={action.busy}>
            {t('server.push.save')}
          </Button>
        </div>
      </form>
      <p className="m-0 text-xs leading-relaxed text-[var(--nexui-text-muted)]">{t('server.push.out')}</p>
      <Outcome problem={action.problem} values={action.values} done={action.done} />
      {dialog}
    </Card>
  )
}
