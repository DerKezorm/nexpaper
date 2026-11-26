/** nexpaper's side of the operator's account list of the shared account module (konten 1.1.0): what its server can do,
 * its own fact ("Documents") and its rows as the module knows them. */
import { avatarUrl, type AccountLink, type AccountRow } from '../../api/client'
import { capsOf, type AccountCaps, type FactShown, type ListedAccount } from '../../vendor/nexkonten/konten'

/** What nexpaper's server can do for the operator (`ACCOUNT_CAPS`, konten 1.1.0): everything of its own, the module's
 * standard functions (several operators, block, delete with 30 days to bring back) and nexpaper's row of `FEATURES`
 * (the storage limit, "AI allowed"). The documents of a deleted account go where the operator says, at the end. */
export const APP_CAPS: AccountCaps = capsOf('nexpaper', {
  rename: true,
  emailRemove: true,
  resetLink: true,
  factorReset: true,
  signOut: true,
  unlink: true,
})

/** nexpaper's own fact in the dialog "Manage": the documents of the account's own vault, the trash included. */
export function appOwnFacts(row: Pick<AccountRow, 'documents'>, lang: string): FactShown[] {
  return [{ fact: 'documents', label: 'server.documentsFact', raw: (row.documents ?? 0).toLocaleString(lang) }]
}

/** One row of nexpaper's answer as the module's list knows it (the names of the interface stay). ``emailConfirmed``
 * is "proven by a link": that is what "confirmed" means to nexpaper's people (the intake trusts only such an address). */
export function listedOf(row: AccountRow, ownId: number | undefined, links: readonly AccountLink[] = []): ListedAccount {
  return {
    id: row.id,
    username: row.name,
    displayName: row.display_name ?? '',
    email: row.email ?? '',
    emailConfirmed: row.email_confirmed,
    emailDuplicate: row.email_duplicate,
    operator: row.role === 'operator',
    self: row.self ?? row.id === ownId,
    hasPassword: row.has_password,
    authenticator: row.totp,
    passkeys: row.passkeys ?? 0,
    providers: links.filter((link) => link.account_id === row.id).map((link) => ({ id: link.provider_id, label: link.label })),
    blocked: Boolean(row.blocked),
    blockedAt: row.blocked_at ?? null,
    locked: row.locked,
    lastSeenAt: row.last_seen_at ?? null,
    picture: avatarUrl(row),
    deletedAt: row.deleted_at ?? null,
    purgeAt: row.purge_at ?? null,
    storageLimit: row.storage_limit ?? null,
    storageUsed: row.storage_used ?? 0,
    rights: row.rights ?? (row.ai_allowed !== false ? ['ai'] : []),
  }
}
