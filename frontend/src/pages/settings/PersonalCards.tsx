/**
 * What is personal, as cards for "My account": the language, light or dark and the look of the archive, and where a
 * phone starts. Each is kept with the account (never only in this browser).
 */
import { Globe, Monitor, Moon, Palette, Smartphone, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { authApi, type ArchiveView, type Profile } from '../../api/client'
import { changeLanguage, languageOptions, type LanguageOption } from '../../i18n'
import { applyMode, storedMode, type Mode } from '../../lib/theme'
import { useAuth } from '../../state/auth'
import { Card, Feedback, Segment, SubHead, Toggle, useAction } from './ui'

export function LanguageCard() {
  const { t, i18n } = useTranslation()
  const { setMe } = useAuth()
  const [options, setOptions] = useState<LanguageOption[]>([])
  useEffect(() => {
    let alive = true
    void languageOptions().then((list) => alive && setOptions(list))
    return () => {
      alive = false
    }
  }, [])
  return (
    <Card icon={Globe} title={t('settings.language.title')} text={t('settings.language.text')}>
      <Segment
        label={t('settings.language.title')}
        value={i18n.language}
        onChange={(code) => {
          void changeLanguage(code)
          // Kept with the account, so the next browser speaks it too.
          void authApi.language(code).then(setMe, () => undefined)
        }}
        options={options.map((option) => ({ value: option.code, label: option.name }))}
      />
    </Card>
  )
}

/** Light, dark or as the system, and how the archive shows the documents; both kept with the account. */
export function LooksCard() {
  const { t } = useTranslation()
  const { me, setMe } = useAuth()
  const [mode, setMode] = useState<Mode>(me?.profile.mode ?? storedMode())
  const action = useAction()
  const save = (change: Partial<Profile>) => {
    void action.run(async () => {
      const profile = await authApi.preferences(change)
      if (me) setMe({ ...me, profile })
    })
  }
  const modes: { value: Mode; label: string; icon: typeof Sun }[] = [
    { value: 'system', label: t('theme.system'), icon: Monitor },
    { value: 'light', label: t('theme.light'), icon: Sun },
    { value: 'dark', label: t('theme.dark'), icon: Moon },
  ]
  return (
    <Card icon={Palette} title={t('looks.title')} text={t('looks.text')}>
      <div role="radiogroup" aria-label={t('looks.title')} className="grid gap-3 sm:grid-cols-3">
        {modes.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={mode === value}
            onClick={() => {
              setMode(value)
              applyMode(value)
              save({ mode: value })
            }}
            className={`flex items-center gap-3 rounded-2xl border p-4 text-left text-sm font-semibold ${mode === value ? 'border-accent/50 bg-accent-soft text-accent' : 'border-line text-ink-2 hover:text-ink'}`}
          >
            <Icon size={18} aria-hidden /> {label}
          </button>
        ))}
      </div>
      <SubHead title={t('looks.archive')} text={t('looks.archiveText')} />
      <Segment
        label={t('looks.archive')}
        value={me?.profile.view ?? 'list'}
        onChange={(view: ArchiveView) => save({ view })}
        options={[
          { value: 'list', label: t('looks.list') },
          { value: 'grid', label: t('looks.grid') },
        ]}
      />
      <Feedback problem={action.problem} />
    </Card>
  )
}

/** Where a phone starts: on the quick upload, or in the whole app. It works with the phone block. */
export function PhoneCard() {
  const { t } = useTranslation()
  const { me, setMe } = useAuth()
  const action = useAction()
  return (
    <Card icon={Smartphone} title={t('settings.phone.title')} text={t('settings.phone.text')}>
      <Toggle
        label={t('settings.phone.quickStart')}
        hint={t('settings.phone.quickStartHint')}
        checked={me?.profile.quick_start ?? true}
        onChange={(quick_start) => {
          if (!me) return
          setMe({ ...me, profile: { ...me.profile, quick_start } })
          void action.run(async () => setMe({ ...me, profile: await authApi.preferences({ quick_start }) })).then((worked) => worked || setMe(me))
        }}
      />
      <Feedback problem={action.problem} />
    </Card>
  )
}
