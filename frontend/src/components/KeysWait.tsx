import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useAuth } from '../state/auth'
import { Notice } from '../vendor/nexui'

/**
 * Above the devices and keys of the account: a password account without a second factor of its own, signed in at a
 * provider that checks it, is let in without one, but a device token or an API key has no provider behind it and waits
 * until the account sets one up. Making one stays possible (module 1.0.10, Welle E).
 */
export function KeysWait() {
  const { t } = useTranslation()
  const { me } = useAuth()
  if (!me?.keys_wait_for_second_factor) return null
  return (
    <div data-testid="keys-wait">
      <Notice tone="warn">
        {t('me.keysWait')}{' '}
        <Link to="/settings/security" className="font-semibold underline">
          {t('me.keysWaitLink')}
        </Link>
      </Notice>
    </div>
  )
}
