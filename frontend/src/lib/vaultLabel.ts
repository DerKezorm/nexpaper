import type { Vault } from '../api/client'

/** A vault as its name is said to the person looking: their own personal vault is "Mein Tresor" (`mine`). */
export function vaultLabel(vault: Pick<Vault, 'name' | 'personal_of'>, mineId: number | undefined, mine: string): string {
  return mine && vault.personal_of !== null && vault.personal_of === mineId ? mine : vault.name
}
