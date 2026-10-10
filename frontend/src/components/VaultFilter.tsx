/**
 * "Alle · Mein Tresor · Haushalt": the filter by vault above a list, the same on every page that has one (the inbox, the
 * order page). With numbers, each chip says how many entries it holds ("Alle 4 · Mein Tresor 1 · Haushalt 3").
 */
import { useTranslation } from 'react-i18next'

import type { Vault } from '../api/client'
import { vaultLabel } from '../lib/vaultLabel'
import { Chip } from './docs'
import { VaultIcon } from './VaultIcon'

type Props = {
  vaults: Pick<Vault, 'id' | 'name' | 'icon' | 'personal_of'>[]
  /** The chosen vault's number as text, or empty for all. */
  value: string
  onChange: (value: string) => void
  mineId: number | undefined
  /** How many each holds, by vault id; with `total` for "Alle". */
  counts?: Record<number, number>
  total?: number
  label: string
  /** One more choice after the vaults ("for all vaults", where the list has entries that belong to none). */
  extra?: { value: string; label: string }
}

export function VaultFilter({ vaults, value, onChange, mineId, counts, total, label, extra }: Props) {
  const { t } = useTranslation()
  const number = (n: number | undefined) => (n === undefined ? null : <span className="tabular-nums opacity-80">{n}</span>)
  return (
    <div role="group" aria-label={label} className="scroll-x -mx-1 flex items-center gap-2 overflow-x-auto px-1 pb-1">
      <Chip active={value === ''} onClick={() => onChange('')}>
        {t('order.all')} {number(total)}
      </Chip>
      {vaults.map((v) => (
        <Chip key={v.id} active={value === String(v.id)} onClick={() => onChange(String(v.id))}>
          <VaultIcon icon={v.icon} size={14} /> {vaultLabel(v, mineId, t('vaults.mine'))} {number(counts ? (counts[v.id] ?? 0) : undefined)}
        </Chip>
      ))}
      {extra && (
        <Chip active={value === extra.value} onClick={() => onChange(extra.value)}>
          {extra.label}
        </Chip>
      )}
    </div>
  )
}
