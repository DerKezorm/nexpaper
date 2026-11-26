/**
 * My account › Appearance (plan "Einstellungen", Darstellung): first the card "Aussehen" of every app (konten's
 * `AppearanceCard`: light, dark, as the device says, at the account on every device), then nexpaper's own card: how the
 * archive shows the documents, kept with the account too.
 */
import { LayoutGrid, LayoutList, List } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { ApiError, authApi, type ArchiveView, type Profile } from '../../api/client'
import { errorText } from '../../lib/errors'
import { useSay } from '../../lib/say'
import { applyMode } from '../../lib/theme'
import { useAuth } from '../../state/auth'
import { AppearanceCard } from '../../vendor/nexkonten/AccountCards'
import { themeOf } from '../../vendor/nexkonten/konten'
import { Card, Segment } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'

export function AppearanceArea() {
  const { t } = useTranslation()
  const { me, setMe } = useAuth()
  const say = useSay()
  const archive = useAction()
  if (!me) return null
  const before = me.theme || me.profile.mode
  const save = (change: Partial<Profile>) =>
    void archive.run(async () => {
      const profile = await authApi.preferences(change)
      setMe({ ...me, profile })
    })
  return (
    <>
      {/* Shown at once, saved at the account (`PUT /api/v1/me/theme`); a refusal puts the choice back. */}
      <AppearanceCard
        theme={me.theme || me.profile.mode}
        onChange={(theme) => {
          applyMode(theme)
          setMe({ ...me, theme, profile: { ...me.profile, mode: theme } })
          authApi.theme(theme).then(
            (saved) => setMe({ ...me, theme: saved.theme, profile: { ...me.profile, mode: saved.theme } }),
            (error: unknown) => {
              applyMode(themeOf(before))
              setMe(me)
              say(errorText(error instanceof ApiError ? error.code : 'internal_error'))
            },
          )
        }}
      />
      <Card id="archive-look" icon={LayoutList} title={t('looks.archive')}>
        <Segment<ArchiveView>
          label={t('looks.archiveStyle')}
          hints={[t('looks.archiveText')]}
          value={me.profile.view ?? 'list'}
          onChange={(view) => save({ view })}
          options={[
            { value: 'list', label: t('looks.list'), icon: List },
            { value: 'grid', label: t('looks.grid'), icon: LayoutGrid },
          ]}
          testId="archive-look"
        />
        <Outcome problem={archive.problem} />
      </Card>
    </>
  )
}
