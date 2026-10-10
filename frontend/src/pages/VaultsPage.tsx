/**
 * Vaults: one personal vault per person, shared vaults from the operator. Each card shows who may do what; the rights are
 * changed right there. Below: what others shared one by one, and the open links the person made. As the mock draws it,
 * with the lists from the server in place of its invented ones.
 */
import { FileText, FolderLock, Link2, ListTree, Plus, Settings2, Users, X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { ApiError, documentsApi, sharingApi, vaultsApi, type DocumentInfo, type MyLink, type Person, type Vault, type VaultRight } from '../api/client'
import { Avatar } from '../components/Avatar'
import { Button } from '../components/Button'
import { Dialog } from '../components/Dialog'
import { useConfirm } from '../components/useConfirm'
import { VaultIcon } from '../components/VaultIcon'
import { formatBytes } from '../lib/bytes'
import { shortDate } from '../lib/dates'
import { asAvatarPerson, personName } from '../lib/people'
import { INBOX_CHANGED, iso } from '../lib/say'
import { useAuth } from '../state/auth'
import { Feedback } from './settings/ui'
import { RulesCard } from './settings/SortingCards'

const RIGHTS: VaultRight[] = ['read', 'edit', 'manage']

/** A sentence after something was done: handed to the frame's toast by way of the navigation state. */
function useSay() {
  const navigate = useNavigate()
  const location = useLocation()
  return useCallback((notice: string) => navigate(location.pathname + location.search, { replace: true, state: { notice } }), [navigate, location.pathname, location.search])
}

export function VaultsPage() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const say = useSay()
  const [vaults, setVaults] = useState<Vault[] | null>(null)
  const [people, setPeople] = useState<Person[]>([])
  const [shared, setShared] = useState<DocumentInfo[]>([])
  const [links, setLinks] = useState<MyLink[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const [editing, setEditing] = useState<Vault | null>(null)
  const [creating, setCreating] = useState(false)
  const { ask, dialog } = useConfirm()

  const load = useCallback(async () => {
    try {
      const [vaultList, everybody, documents, mine] = await Promise.all([vaultsApi.list(), vaultsApi.people(), sharedOneByOne(), sharingApi.myLinks()])
      setVaults(vaultList)
      setPeople(everybody)
      setShared(documents)
      setLinks(mine.filter((l) => l.status === 'active'))
      setProblem(null)
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    }
  }, [])
  useEffect(() => {
    void load()
  }, [load])
  // Uploads finished, a document filed or deleted: the counts of the cards follow at once.
  useEffect(() => {
    const again = () => void load()
    window.addEventListener(INBOX_CHANGED, again)
    return () => window.removeEventListener(INBOX_CHANGED, again)
  }, [load])

  const personById = useMemo(() => new Map(people.map((p) => [p.id, p])), [people])
  if (!me) return null
  const mineId = me.id
  // Where uploads go: the vault the person chose, or their own when they chose none (or one they lost since).
  const chosen = me.profile.default_vault
  const uploadsTo = (vaults ?? []).some((v) => v.id === chosen && v.my_right !== 'read') ? chosen : (vaults ?? []).find((v) => v.personal_of === mineId)?.id

  /** Withdraws one of the person's links, after asking. */
  const withdraw = (link: MyLink) =>
    ask({
      title: t('confirm.link.title'),
      text: t('confirm.link.text', { title: iso(link.document_title) }),
      confirm: t('confirm.link.confirm'),
      run: async () => {
        await sharingApi.revokeLink(link.document_id, link.id)
        setLinks((current) => current.filter((l) => l.id !== link.id))
        say(t('share.withdrawn'))
      },
    })

  return (
    <div className="page space-y-6 pt-6 pb-28 lg:pt-8 lg:pb-12">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight">{t('vaults.title')}</h1>
          <p className="max-w-2xl text-sm text-muted">{t('vaults.intro')}</p>
        </div>
        {me.role === 'operator' && (
          <Button variant="soft" size="sm" onClick={() => setCreating(true)}>
            <Plus size={15} aria-hidden /> {t('vaults.create')}
          </Button>
        )}
      </div>

      <Feedback problem={problem} />

      <div className="grid gap-4 md:grid-cols-2">
        {(vaults ?? []).map((v) => {
          const own = v.personal_of === mineId
          const owner = v.personal_of !== null ? personById.get(v.personal_of) : undefined
          return (
            <section key={v.id} className="card p-5" aria-label={own ? t('vaults.mine') : v.name}>
              <div className="flex items-start gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-accent-soft text-accent">
                  <VaultIcon icon={v.icon} size={20} />
                </span>
                <div className="min-w-0 flex-1">
                  <h2 className="font-display text-xl font-semibold">{own ? t('vaults.mine') : v.name}</h2>
                  <p className="text-sm text-muted">
                    {v.personal_of !== null ? (own ? t('vaults.personalMine') : t('vaults.personalOf', { name: owner ? personName(owner) : v.name })) : t('vaults.shared')} ·{' '}
                    {t('vaults.documents', { count: v.documents, n: v.documents.toLocaleString(i18n.language) })} · {formatBytes(v.size, i18n.language, 1000)}
                  </p>
                </div>
                {v.my_right === 'manage' && (
                  <button type="button" onClick={() => setEditing(v)} className="rounded-full p-2 text-muted hover:bg-sheet-2 hover:text-ink" aria-label={`${t('vaults.changeRights')}: ${own ? t('vaults.mine') : v.name}`}>
                    <Settings2 size={17} />
                  </button>
                )}
              </div>
              <ul className="mt-4 space-y-1.5">
                {v.members.map((m) => (
                  <li key={m.user_id} className="flex items-center gap-2.5 text-sm">
                    <Avatar person={asAvatarPerson({ id: m.user_id, name: m.name, display_name: m.display_name })} size={24} />
                    <span className="flex-1">{m.user_id === mineId ? t('vaults.you') : m.display_name || m.name}</span>
                    <span className="rounded-full bg-sheet-2 px-2 py-0.5 text-xs font-semibold text-ink-2">{t(`rights.${m.right}.name`)}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-3">
                <Link to="/" className="text-sm font-semibold text-accent">
                  {t('vaults.viewDocuments')}
                </Link>
                {v.id === uploadsTo && <span className="ml-auto text-xs text-muted">{t('vaults.defaultHint')}</span>}
              </div>
            </section>
          )
        })}
      </div>

      {shared.length > 0 && (
        <section>
          <h2 className="mb-2 flex items-center gap-2 px-1 text-xs font-bold tracking-wide text-muted uppercase">
            <Users size={14} aria-hidden /> {t('vaults.sharedWithMe')}
          </h2>
          <ul className="card divide-y divide-line p-0">
            {shared.map((d) => (
              <li key={d.id}>
                <Link to={`/dokument/${d.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-sheet-2/60">
                  <span className="flex h-12 w-9 shrink-0 items-center justify-center rounded-[3px] bg-white text-muted shadow-[0_1px_3px_rgb(0_0_0/0.18)]">
                    <FileText size={16} aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1 text-sm">
                    <span className="block truncate font-semibold">{d.title}</span>
                    <span className="text-muted">
                      {t('vaults.sharedBy', {
                        owner: d.owner ? personName(d.owner) : '?',
                        sender: d.sender?.name ?? t('vaults.noSender'),
                        date: d.date ? shortDate(d.date, i18n.language) : '',
                      })}
                    </span>
                  </span>
                  {/* The right is a fact about the document, not something to press: a pill like the members' on the cards. */}
                  <span title={t(`rights.${d.my_right}.text`)} className="shrink-0 rounded-full bg-sheet-2 px-2 py-0.5 text-xs font-semibold text-ink-2">
                    {t(`vaults.myRight.${d.my_right}`)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {links.length > 0 && (
        <section>
          <h2 className="mb-2 flex items-center gap-2 px-1 text-xs font-bold tracking-wide text-muted uppercase">
            <Link2 size={14} aria-hidden /> {t('vaults.openLinks')}
          </h2>
          <ul className="card divide-y divide-line p-0">
            {links.map((l) => (
              <li key={l.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                <Link2 size={16} className="text-accent" aria-hidden />
                <span className="flex-1">
                  <span className="block font-semibold">{t('vaults.linkFor', { title: l.document_title, to: l.recipient })}</span>
                  <span className="text-muted">{t('vaults.linkMeta', { until: shortDate(l.until, i18n.language), count: l.opened_count })}</span>
                </span>
                <Button size="sm" variant="ghost" onClick={() => withdraw(l)}>
                  {t('vaults.withdraw')}
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* The rules of the vaults the person manages (B6); the operator's for the whole server are under Settings. */}
      <RulesCard />

      <p className="text-xs text-muted">{t('vaults.note')}</p>
      <Link to="/ordnung" className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent">
        <ListTree size={15} aria-hidden /> {t('order.link')}
      </Link>
      {dialog}

      {editing && (
        <Members
          vault={editing}
          people={people}
          mineId={mineId}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            say(t('vaults.saved'))
            void load()
          }}
        />
      )}
      {creating && (
        <Create
          onClose={() => setCreating(false)}
          onCreated={(name) => {
            setCreating(false)
            say(t('vaults.created', { name }))
            void load()
          }}
        />
      )}
    </div>
  )
}

/** The documents others shared with the person one by one, all of them (the server filters, page by page). */
async function sharedOneByOne(): Promise<DocumentInfo[]> {
  const found: DocumentInfo[] = []
  let after = 0
  for (let page = 0; page < 20; page += 1) {
    const answer = await documentsApi.list({ via_share: true, after, limit: 500 })
    found.push(...answer.items)
    if (answer.next === null) break
    after = answer.next
  }
  return found
}

type Row = { user_id: number; right: VaultRight }

/** Who is in a vault and with which right. Changes are collected and sent on "Save"; the owner of a personal vault stays. */
function Members({ vault, people, mineId, onClose, onSaved }: { vault: Vault; people: Person[]; mineId: number; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const [rows, setRows] = useState<Row[]>(vault.members.map((m) => ({ user_id: m.user_id, right: m.right })))
  const [problem, setProblem] = useState<string | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [busy, setBusy] = useState(false)
  const byId = new Map(people.map((p) => [p.id, p]))
  for (const m of vault.members) if (!byId.has(m.user_id)) byId.set(m.user_id, { id: m.user_id, name: m.name, display_name: m.display_name })
  const free = people.filter((p) => !rows.some((r) => r.user_id === p.id))
  const own = vault.personal_of === mineId

  const { ask, dialog } = useConfirm()
  /** Saves; when somebody is taken out of the vault, asks first, as they lose it. */
  const save = () => {
    const dropped = vault.members.filter((m) => !rows.some((r) => r.user_id === m.user_id))
    if (dropped.length === 0) return write()
    ask({
      title: t('confirm.members.title'),
      text: t('confirm.members.text', { names: dropped.map((m) => iso(personName(byId.get(m.user_id) ?? m))).join(', '), count: dropped.length }),
      confirm: t('confirm.members.confirm'),
      run: async () => {
        await vaultsApi.setMembers(vault.id, rows)
        onSaved()
      },
    })
  }
  const write = async () => {
    setBusy(true)
    setProblem(null)
    try {
      // All at once, in one write: a refusal (the last manager, somebody gone) leaves the vault as it was.
      await vaultsApi.setMembers(vault.id, rows)
      onSaved()
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
      setValues(error instanceof ApiError ? error.values : {})
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title={own ? t('vaults.membersMine') : t('vaults.membersOf', { name: vault.name })} onClose={onClose}>
      <ul className="space-y-2">
        {rows.map((row) => {
          const person = byId.get(row.user_id)
          const name = person ? personName(person) : '?'
          return (
            <li key={row.user_id} className="flex items-center gap-2.5 rounded-xl bg-sheet-2/60 px-3 py-2 text-sm">
              {person && <Avatar person={asAvatarPerson(person)} size={26} />}
              <span className="flex-1 font-semibold">{row.user_id === mineId ? t('vaults.you') : name}</span>
              {row.user_id === vault.personal_of ? (
                <span className="text-xs text-muted">{t('vaults.ownerNote')}</span>
              ) : (
                <>
                  <select
                    value={row.right}
                    aria-label={t('vaults.right', { name })}
                    onChange={(e) => setRows(rows.map((r) => (r.user_id === row.user_id ? { ...r, right: e.target.value as VaultRight } : r)))}
                    className="input h-8 w-32 text-sm"
                  >
                    {RIGHTS.map((r) => (
                      <option key={r} value={r}>
                        {t(`rights.${r}.name`)}
                      </option>
                    ))}
                  </select>
                  <button type="button" onClick={() => setRows(rows.filter((r) => r.user_id !== row.user_id))} className="rounded-full p-1 text-muted hover:text-ink" aria-label={`${t('vaults.remove')}: ${name}`}>
                    <X size={15} />
                  </button>
                </>
              )}
            </li>
          )
        })}
      </ul>
      {free.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {free.map((p) => (
            <Button key={p.id} size="sm" variant="line" onClick={() => setRows([...rows, { user_id: p.id, right: 'read' }])}>
              <Plus size={14} aria-hidden /> {personName(p)}
            </Button>
          ))}
        </div>
      )}
      <dl className="mt-5 space-y-1 rounded-2xl border border-line p-4 text-xs">
        {RIGHTS.map((r) => (
          <div key={r} className="flex gap-2">
            <dt className="w-24 font-semibold">{t(`rights.${r}.name`)}</dt>
            <dd className="text-ink-2">{t(`rights.${r}.text`)}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-4">
        <Feedback problem={problem} values={values} />
      </div>
      {dialog}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          {t('common.cancel')}
        </Button>
        <Button variant="primary" onClick={() => void save()} disabled={busy}>
          {t('common.save')}
        </Button>
      </div>
    </Dialog>
  )
}

/** A shared vault, for the operator. */
function Create({ onClose, onCreated }: { onClose: () => void; onCreated: (name: string) => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const create = async () => {
    if (!name.trim()) return
    setBusy(true)
    setProblem(null)
    try {
      const made = await vaultsApi.create(name.trim(), 'folder')
      onCreated(made.name)
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog title={t('vaults.createTitle')} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void create()
        }}
      >
        <p className="-mt-2 mb-4 text-sm text-ink-2">{t('vaults.createText')}</p>
        <label className="text-sm">
          <span className="font-semibold">{t('vaults.nameLabel')}</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder={t('vaults.namePlaceholder')} className="input mt-1" autoFocus />
        </label>
        <div className="mt-3">
          <Feedback problem={problem} />
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" type="submit" disabled={busy || !name.trim()}>
            <FolderLock size={16} aria-hidden /> {t('vaults.createButton')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
