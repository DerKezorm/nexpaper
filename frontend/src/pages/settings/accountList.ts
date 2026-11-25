/** nexpaper's side of the operator's account list of the shared account module (konten 0.3.9): what its server can
 * do, its own right ("AI allowed") and fact ("Documents"), and its rows as the module knows them. */
import { avatarUrl, type AccountLink, type AccountRow } from '../../api/client'
import type { AccountCaps, FactShown, ListedAccount, OwnAction } from '../../vendor/nexkonten/konten'

/** What nexpaper's server can do for the operator (konten 0.3.9, `ACCOUNT_CAPS`): everything of the module but
 * bringing a deleted account back (nexpaper deletes for good, the documents go where the operator says). */
export const APP_CAPS: AccountCaps = {
  rename: true,
  roles: true,
  emailRemove: true,
  resetLink: true,
  factorReset: true,
  signOut: true,
  unlink: true,
  blocking: true,
  remove: true,
  restore: false,
}

/** nexpaper's own right in the dialog "Manage": "AI allowed", a box in the group "Rights", saved at once; it may stand
 * at the own account too. */
export function appOwnActions(row: Pick<AccountRow, 'ai_allowed'>): OwnAction[] {
  return [{ name: 'ai', label: 'server.aiAllowed', group: 'rights', checked: row.ai_allowed !== false, hint: 'server.permissionsHint' }]
}

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
  }
}
