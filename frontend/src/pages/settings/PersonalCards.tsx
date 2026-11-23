/**
 * What is personal, as cards for "My account": the language, light or dark and the look of the archive, and where a
 * phone starts. Each is kept with the account (never only in this browser).
 */
import { Globe, LayoutGrid, LayoutList, List, Monitor, Moon, Palette, Smartphone, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { authApi, type ArchiveView, type Profile } from '../../api/client'
import { changeLanguage, languageOptions, type LanguageOption } from '../../i18n'
import { applyMode, storedMode, type Mode } from '../../lib/theme'
import { useAuth } from '../../state/auth'
import { Card, Feedback, Segment, Toggle, useAction } from './ui'

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

/**
 * "Darstellung" as in nexnotes: a card for light, dark or as the system (nexnotes' segmented choice with words), and a
 * card for how the archive shows the documents (nexnotes' choice of the list style, with a sign each). nexpaper keeps
 * both with the account, so the hints say "on all your devices".
 */
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
    { value: 'light', label: t('theme.light'), icon: Sun },
    { value: 'dark', label: t('theme.dark'), icon: Moon },
    { value: 'system', label: t('theme.system'), icon: Monitor },
  ]
  const views: { value: ArchiveView; label: string; icon: typeof Sun }[] = [
    { value: 'list', label: t('looks.list'), icon: List },
    { value: 'grid', label: t('looks.grid'), icon: LayoutGrid },
  ]
  const view = me?.profile.view ?? 'list'
  return (
    <>
      <Card id="looks" icon={Palette} title={t('looks.title')}>
        <div className="text-sm">
          <span className="font-medium">{t('looks.mode')}</span> <span className="text-xs text-muted">{t('looks.everywhere')}</span>
          <div className="mt-1.5">
            <div className="inline-flex items-center gap-0.5 rounded-[9px] border border-line bg-sheet p-0.5" role="radiogroup" aria-label={t('looks.mode')}>
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
                  className={'inline-flex items-center gap-1.5 rounded-[7px] px-2 py-1.5 text-sm transition-colors ' + (mode === value ? 'bg-accent font-semibold text-accent-ink' : 'text-muted hover:text-ink')}
                >
                  <Icon className="h-3.5 w-3.5" strokeWidth={2.2} aria-hidden />
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
        <Feedback problem={action.problem} />
      </Card>
      <Card id="archive-look" icon={LayoutList} title={t('looks.archive')}>
        <div className="text-sm">
          <span className="font-medium" id="archive-look-label">
            {t('looks.archiveStyle')}
          </span>{' '}
          <span className="text-xs text-muted">{t('looks.archiveText')}</span>
          <div role="radiogroup" aria-labelledby="archive-look-label" className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {views.map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={view === value}
                onClick={() => view !== value && save({ view: value })}
                className={'flex flex-col items-center gap-1.5 rounded-[10px] border px-2 py-3 text-[13px] ' + (view === value ? 'chosen border-accent font-semibold' : 'border-line text-ink-2 hover:text-ink')}
              >
                <Icon className="h-5 w-5" strokeWidth={1.8} aria-hidden />
                {label}
              </button>
            ))}
          </div>
        </div>
      </Card>
    </>
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
