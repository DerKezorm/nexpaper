/**
 * The operator's place for the iPhone shortcut (Settings, API): the iCloud link of a finished "Nach nexpaper" shortcut,
 * which My account then offers to everybody as "Kurzbefehl laden". Only an iCloud link to a shortcut is taken.
 */
import { Apple } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { phoneApi } from '../../api/client'
import { Button, Card, Feedback, Input, useAction } from './ui'

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
  return (
    <Card id="shortcut-link" icon={Apple} title={t('phone.settings.title')} text={t('phone.settings.text')}>
      <form
        className="flex flex-wrap items-start gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          const value = link.trim()
          void action.run(async () => {
            const stored = await phoneApi.setShortcutLink(value)
            setLink(stored.link)
            setSaved(stored.link)
          }, value ? t('phone.settings.saved') : t('phone.settings.removed'))
        }}
      >
        <Input label={t('phone.settings.link')} value={link} onChange={setLink} placeholder="https://www.icloud.com/shortcuts/…" className="min-w-72 flex-1" />
        <Button type="submit" busy={action.busy} disabled={link.trim() === saved} className="mt-6">
          {t('phone.settings.save')}
        </Button>
      </form>
      <Feedback problem={action.problem} done={action.done} />
    </Card>
  )
}
