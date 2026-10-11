import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useAuth } from '../state/auth'

/**
 * Above the devices and keys of the account: a password account without a second factor of its own, signed in at a
 * provider that checks it, is let in without one, but a device token or an API key has no provider behind it and waits
 * until the account sets one up. Making one stays possible (module 1.0.10, Welle E).
 */
export function KeysWait({ className = '' }: { className?: string }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  if (!me?.keys_wait_for_second_factor) return null
  return (
    <p role="note" data-testid="keys-wait" className={'rounded-xl border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-ink-2 ' + className}>
      {t('me.keysWait')}{' '}
      <Link to="/konto?tab=security" className="font-semibold underline">
        {t('me.keysWaitLink')}
      </Link>
    </p>
  )
}
