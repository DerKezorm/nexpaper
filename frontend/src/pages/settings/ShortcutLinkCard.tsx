/**
 * The operator's place for the iPhone shortcut (My account › Connections, before Server › API): the iCloud link of a
 * finished "Nach nexpaper" shortcut, which "Aus anderen Apps auf dem iPhone" then offers to everybody as "Kurzbefehl
 * laden". Only an iCloud link to a shortcut is taken.
 */
import { Apple } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { phoneApi } from '../../api/client'
import { Button, Card, Field } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'

export function ShortcutLinkCard() {
  const { t } = useTranslation()
  const [link, setLink] = useState<string | null>(null)
  const [saved, setSaved] = useState('')
  const action = useAction()
  useEffect(() => {
    phoneApi.shortcutLink().then(
      (found) => {
        setLink(found.link ?? '')
        setSaved(found.link ?? '')
      },
      () => setLink(''),
    )
  }, [])
  if (link === null) return null
  const save = () => {
    const value = link.trim()
    void action.run(async () => {
      const stored = await phoneApi.setShortcutLink(value)
      setLink(stored.link)
      setSaved(stored.link)
    }, value ? t('phone.settings.saved') : t('phone.settings.removed'))
  }
  return (
    <Card id="shortcut-link" icon={Apple} title={t('phone.settings.title')} subtitle={t('phone.settings.text')}>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        <Field
          label={t('phone.settings.link')}
          value={link}
          onChange={(event) => setLink(event.target.value)}
          placeholder="https://www.icloud.com/shortcuts/…"
          action={
            <Button kind="secondary" icon="Check" type="submit" busy={action.busy} disabled={link.trim() === saved}>
              {t('phone.settings.save')}
            </Button>
          }
        />
      </form>
      <Outcome problem={action.problem} done={action.done} />
    </Card>
  )
}
