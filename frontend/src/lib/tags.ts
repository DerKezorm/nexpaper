/**
 * The tags a field of tags offers: those of the vault the document is in (or ends up in), nothing of other vaults.
 */
import { useEffect, useState } from 'react'

import { catalogApi, type NameGroup } from '../api/client'

/** The names in `groups` that belong to vault `vaultId`; a name of other vaults alone is left out. */
export function tagsOfVault(groups: NameGroup[], vaultId: number): string[] {
  return groups.filter((group) => group.items.some((item) => item.vault_id === vaultId)).map((group) => group.name)
}

/** The names every one of the vaults has (all of them for one vault; nothing for none). */
export function tagsInEvery(lists: string[][]): string[] {
  if (lists.length === 0) return []
  const key = (name: string) => name.normalize('NFC').toLocaleLowerCase()
  const common = lists.slice(1).map((list) => new Set(list.map(key)))
  return lists[0].filter((name) => common.every((set) => set.has(key(name))))
}

/** The tags of these vaults (those every one of them has), loaded when the vaults change. Empty until they are there. */
export function useVaultTags(vaultIds: number[]): string[] {
  const [names, setNames] = useState<string[]>([])
  const wanted = [...new Set(vaultIds)].sort((a, b) => a - b).join(',')
  useEffect(() => {
    let alive = true
    const ids = wanted ? wanted.split(',').map(Number) : []
    if (ids.length === 0) {
      setNames([])
      return
    }
    void Promise.all(ids.map((id) => catalogApi.tags(id).then((groups) => tagsOfVault(Array.isArray(groups) ? groups : [], id))))
      .then((lists) => alive && setNames(tagsInEvery(lists)))
      .catch(() => alive && setNames([]))
    return () => {
      alive = false
    }
  }, [wanted])
  return names
}
