/**
 * My account › Upload: where a phone starts, on the quick upload or in the whole app (it works with the phone block),
 * kept with the account.
 */
import { Smartphone } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { authApi } from '../../api/client'
import { useAuth } from '../../state/auth'
import { Card, CheckboxRow } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'

export function PhoneCard() {
  const { t } = useTranslation()
  const { me, setMe } = useAuth()
  const action = useAction()
  return (
    <Card id="phone-start" icon={Smartphone} title={t('settings.phone.title')} subtitle={t('settings.phone.text')}>
      <CheckboxRow
        label={t('settings.phone.quickStart')}
        hint={t('settings.phone.quickStartHint')}
        checked={me?.profile.quick_start ?? true}
        onChange={(quick_start) => {
          if (!me) return
          setMe({ ...me, profile: { ...me.profile, quick_start } })
          void action.run(async () => setMe({ ...me, profile: await authApi.preferences({ quick_start }) })).then((worked) => worked || setMe(me))
        }}
      />
      <Outcome problem={action.problem} />
    </Card>
  )
}
