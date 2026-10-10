import { Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { applyMode, storedMode, type Mode } from '../lib/theme'

/** Light, dark or as the system, the pill of the sign-in page. Before signing in the choice stays in the browser. */
export function ThemeSwitcher() {
  const { t } = useTranslation()
  const [mode, setMode] = useState<Mode>(storedMode())
  const options = [
    { value: 'system' as const, icon: Monitor, label: t('theme.system') },
    { value: 'light' as const, icon: Sun, label: t('theme.light') },
    { value: 'dark' as const, icon: Moon, label: t('theme.dark') },
  ]
  return (
    <div role="radiogroup" aria-label={t('theme.group')} className="inline-flex rounded-full border border-line bg-sheet p-0.5">
      {options.map(({ value, icon: Icon, label }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={mode === value}
          title={label}
          aria-label={label}
          onClick={() => {
            applyMode(value)
            setMode(value)
          }}
          className={`rounded-full p-1.5 ${mode === value ? 'bg-accent-soft text-accent' : 'text-muted hover:text-ink'}`}
        >
          <Icon size={15} />
        </button>
      ))}
    </div>
  )
}
