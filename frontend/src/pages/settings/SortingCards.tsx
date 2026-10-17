/**
 * Filing, the cards under Settings, Ablage: the kinds (the operator's short list) and the rules. The rules card
 * is also on the vaults page, for everybody who manages a vault: there it shows the rules of those vaults; under
 * Settings the operator sees the rules for the whole server too and may make them. A rule reads as a sentence ("Wenn
 * Absender ist „Stadtwerke Lindenau“ → Art Rechnung, Tag strom"), with how often it applied, a switch, its place in
 * the order and a way to delete it.
 */
import { ArrowRight, ChevronDown, ChevronUp, ListTree, Plus, Tags, Trash2, Wand2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { catalogApi, kindsApi, rulesApi, vaultsApi, type DocumentKind, type Rule, type RuleAction, type RuleCondition, type Vault } from '../../api/client'
import { SenderPicker } from '../../components/SenderPicker'
import { useConfirm } from '../../components/useConfirm'
import { amountText, money, parseAmount } from '../../lib/money'
import { listOf } from '../../lib/say'
import { Button, Card, Feedback, useAction } from './ui'

/** The kinds are kept on the order page now (all of them, with their documents); here is the way there. */
export function KindsCard() {
  const { t } = useTranslation()
  return (
    <Card icon={Tags} title={t('sorting.kinds.title')} text={t('sorting.kinds.text')} id="kinds">
      <Link to="/ordnung?tab=kinds" className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent">
        <ListTree size={15} aria-hidden /> {t('sorting.kinds.open')}
      </Link>
    </Card>
  )
}

type Names = { kinds: DocumentKind[]; vaults: Vault[]; senders: string[] }

/** A rule as a sentence: "Absender ist „Stadtwerke Lindenau“" and "Art Rechnung, Tag strom, Tresor Haushalt". */
// eslint-disable-next-line react-refresh/only-export-components
export function useRuleWords() {
  const { t, i18n } = useTranslation()
  const quoted = (value: string) => t('sorting.rules.quoted', { value })
  const kindName = (id: number, names: Names) => names.kinds.find((k) => k.id === id)?.name ?? t('sorting.rules.gone')
  const vaultName = (id: number, names: Names) => names.vaults.find((v) => v.id === id)?.name ?? t('sorting.rules.gone')
  const condition = (c: RuleCondition, names: Names) => {
    const head = `${t(`sorting.rules.field.${c.field}`)} ${t(`sorting.rules.op.${c.op}`)}`
    if (c.field === 'sender' || c.field === 'text') return `${head} ${c.values.map(quoted).join(` ${t('sorting.rules.or')} `)}`
    if (c.field === 'kind') return `${head} ${kindName(c.value, names)}`
    if (c.field === 'source') return `${head} ${t(`docs.source.${c.value}`, { defaultValue: c.value })}`
    return `${head} ${money(c.value, i18n.language)}`
  }
  const action = (a: RuleAction, names: Names) => {
    const head = t(`sorting.rules.target.${a.field}`)
    if (a.field === 'vault') return `${head} ${vaultName(a.value, names)}`
    if (a.field === 'kind') return `${head} ${kindName(a.value, names)}`
    if (a.field === 'title') return `${head} ${quoted(a.value)}`
    return `${head} ${a.value}`
  }
  return {
    when: (rule: Rule, names: Names) => rule.when.map((c) => condition(c, names)).join(', '),
    then: (rule: Rule, names: Names) => rule.then.map((a) => action(a, names)).join(', '),
  }
}

type WhenField = RuleCondition['field']
type ThenField = RuleAction['field']
const WHEN_FIELDS: WhenField[] = ['sender', 'text', 'kind', 'source', 'amount']
const THEN_FIELDS: ThenField[] = ['vault', 'kind', 'tag', 'sender', 'title']
const OPS: Record<WhenField, RuleCondition['op'][]> = { sender: ['is', 'contains'], text: ['contains'], kind: ['is'], source: ['is'], amount: ['over', 'under'] }
const SOURCES = ['upload', 'camera', 'mail', 'folder', 'share', 'paperless', 'api']

/** The rules: under Settings (`server`) those of the whole server and of the vaults the operator manages; on the vaults
 * page those of the vaults the person manages. */
export function RulesCard({ server = false }: { server?: boolean }) {
  const { t } = useTranslation()
  const words = useRuleWords()
  const [rules, setRules] = useState<Rule[] | null>(null)
  const [names, setNames] = useState<Names>({ kinds: [], vaults: [], senders: [] })
  const [adding, setAdding] = useState(false)
  const action = useAction()
  const { ask, dialog } = useConfirm()

  const load = useCallback(async () => {
    const [own, everywhere] = await Promise.all([rulesApi.list().catch(() => []), server ? rulesApi.serverList().catch(() => []) : Promise.resolve([])])
    setRules([...listOf<Rule>(everywhere), ...listOf<Rule>(own)])
  }, [server])
  useEffect(() => {
    void load()
    void Promise.all([kindsApi.list().catch(() => []), vaultsApi.list().catch(() => []), catalogApi.senders().catch(() => [])]).then(([kinds, vaults, senders]) =>
      setNames({ kinds: listOf(kinds), vaults: listOf(vaults), senders: listOf<{ name: string }>(senders).map((g) => g.name) }),
    )
  }, [load])

  const managed = names.vaults.filter((v) => v.my_right === 'manage')
  if (!rules) return null
  if (!server && managed.length === 0 && rules.length === 0) return null

  const apiOf = (rule: Rule) =>
    rule.vault_id === null
      ? { change: rulesApi.serverChange, remove: rulesApi.serverRemove }
      : { change: rulesApi.change, remove: rulesApi.remove }
  const siblings = (rule: Rule) => rules.filter((r) => r.vault_id === rule.vault_id)
  const vaultLabel = (rule: Rule) =>
    rule.vault_id === null ? t('sorting.rules.everywhere') : t('sorting.rules.inVault', { vault: names.vaults.find((v) => v.id === rule.vault_id)?.name ?? t('sorting.rules.gone') })

  return (
    <Card icon={Wand2} title={t('sorting.rules.title')} text={t(server ? 'sorting.rules.text' : 'sorting.rules.textVaults')} id="rules">
      {rules.length === 0 && <p className="text-sm text-muted">{t('sorting.rules.empty')}</p>}
      <ul className="space-y-2">
        {rules.map((rule) => {
          const group = siblings(rule)
          const at = group.indexOf(rule)
          const calls = apiOf(rule)
          return (
            <li key={rule.id} className="flex items-center gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-3 text-sm" data-testid="rule">
              <span className="min-w-0 flex-1">
                <span className="font-semibold">{t('sorting.rules.if')}</span> <bdi>{words.when(rule, names)}</bdi> <ArrowRight size={13} className="inline text-muted" aria-hidden /> <bdi>{words.then(rule, names)}</bdi>
                <span className="block text-xs text-muted">
                  {t('sorting.rules.hits', { count: rule.hits })}
                  {(server || managed.length > 1) && ` · ${vaultLabel(rule)}`}
                </span>
              </span>
              {group.length > 1 && (
                <span className="flex flex-col">
                  <button type="button" disabled={at === 0} onClick={() => void action.run(async () => { await calls.change(rule.id, { position: at }); await load() })} className="rounded p-0.5 text-muted hover:text-ink disabled:opacity-30" aria-label={t('sorting.rules.up')}>
                    <ChevronUp size={14} aria-hidden />
                  </button>
                  <button type="button" disabled={at === group.length - 1} onClick={() => void action.run(async () => { await calls.change(rule.id, { position: at + 2 }); await load() })} className="rounded p-0.5 text-muted hover:text-ink disabled:opacity-30" aria-label={t('sorting.rules.down')}>
                    <ChevronDown size={14} aria-hidden />
                  </button>
                </span>
              )}
              <button
                type="button"
                role="switch"
                aria-checked={rule.on}
                aria-label={t('sorting.rules.switch')}
                onClick={() => void action.run(async () => {
                  setRules(rules.map((r) => (r.id === rule.id ? { ...r, on: !r.on } : r)))
                  await calls.change(rule.id, { on: !rule.on })
                  await load()
                })}
                className={`relative h-6 w-10 shrink-0 rounded-full transition ${rule.on ? 'bg-accent' : 'bg-line'}`}
              >
                <span className={`absolute top-1 h-4 w-4 rounded-full bg-sheet shadow transition-all ${rule.on ? 'left-5' : 'left-1'}`} />
              </button>
              <button
                type="button"
                onClick={() =>
                  ask({
                    title: t('confirm.rule.title'),
                    text: t('confirm.rule.text'),
                    confirm: t('confirm.rule.confirm'),
                    run: async () => {
                      await calls.remove(rule.id)
                      await load()
                    },
                  })
                }
                className="rounded-full p-1.5 text-muted hover:text-ink"
                aria-label={t('sorting.rules.delete')}
              >
                <Trash2 size={14} aria-hidden />
              </button>
            </li>
          )
        })}
      </ul>
      {adding ? (
        <RuleForm
          server={server}
          names={names}
          managed={managed}
          onCancel={() => setAdding(false)}
          onSave={(scope, when, then) =>
            void action.run(async () => {
              const draft = { when: [when], then: [then] }
              await (scope === null ? rulesApi.serverCreate(draft) : rulesApi.create(scope, draft))
              setAdding(false)
              await load()
            })
          }
          busy={action.busy}
        />
      ) : (
        (server || managed.length > 0) && (
          <Button className="mt-4" onClick={() => setAdding(true)}>
            <Plus size={15} aria-hidden /> {t('sorting.rules.add')}
          </Button>
        )
      )}
      <Feedback problem={action.problem} values={action.values} />
      {dialog}
    </Card>
  )
}

function RuleForm({ server, names, managed, onCancel, onSave, busy }: { server: boolean; names: Names; managed: Vault[]; onCancel: () => void; onSave: (scope: number | null, when: RuleCondition, then: RuleAction) => void; busy: boolean }) {
  const { t, i18n } = useTranslation()
  const [scope, setScope] = useState<string>(server ? 'all' : String(managed[0]?.id ?? ''))
  const [whenField, setWhenField] = useState<WhenField>('sender')
  const [op, setOp] = useState<RuleCondition['op']>('is')
  const [whenValue, setWhenValue] = useState('')
  const [thenField, setThenField] = useState<ThenField>('vault')
  const [thenValue, setThenValue] = useState('')
  const writable = names.vaults.filter((v) => v.my_right === 'edit' || v.my_right === 'manage')
  const vaultLabel = (v: Vault) => (v.personal_of !== null ? t('docs.inbox.personalVault', { name: v.name }) : v.name)
  // A rule names the kinds of the server and, for a rule of a vault, that vault's own.
  const kindChoices = names.kinds.filter((k) => !k.vault_id || String(k.vault_id) === scope)

  const condition = (): RuleCondition | null => {
    const value = whenValue.trim()
    if (whenField === 'sender') return value ? { field: 'sender', op: op as 'is' | 'contains', values: [value] } : null
    if (whenField === 'text') return value ? { field: 'text', op: 'contains', values: [value] } : null
    if (whenField === 'kind') return value ? { field: 'kind', op: 'is', value: Number(value) } : null
    if (whenField === 'source') return value ? { field: 'source', op: 'is', value } : null
    const cents = parseAmount(value)
    return typeof cents === 'number' ? { field: 'amount', op: op as 'over' | 'under', value: cents } : null
  }
  const consequence = (): RuleAction | null => {
    const value = thenValue.trim()
    if (!value) return null
    if (thenField === 'vault' || thenField === 'kind') return { field: thenField, value: Number(value) }
    return { field: thenField, value }
  }
  const chooseWhen = (field: WhenField) => {
    setWhenField(field)
    setOp(OPS[field][0])
    setWhenValue(field === 'kind' ? String(kindChoices[0]?.id ?? '') : field === 'source' ? 'upload' : '')
  }
  const chooseThen = (field: ThenField) => {
    setThenField(field)
    setThenValue(field === 'vault' ? String(writable[0]?.id ?? '') : field === 'kind' ? String(kindChoices[0]?.id ?? '') : '')
  }
  useEffect(() => {
    if (thenField === 'vault' && !thenValue && writable[0]) setThenValue(String(writable[0].id))
  }, [thenField, thenValue, writable])
  // A kind chosen for another scope is not one of this scope's: the first of its choices stands in.
  useEffect(() => {
    const fits = (value: string) => kindChoices.some((k) => String(k.id) === value)
    if (whenField === 'kind' && !fits(whenValue)) setWhenValue(String(kindChoices[0]?.id ?? ''))
    if (thenField === 'kind' && !fits(thenValue)) setThenValue(String(kindChoices[0]?.id ?? ''))
  }, [scope, kindChoices, whenField, thenField, whenValue, thenValue])
  const ready = condition() !== null && consequence() !== null && (scope === 'all' ? server : scope !== '')

  return (
    <form
      className="mt-4 space-y-3 rounded-2xl border border-dashed border-line p-4 text-sm"
      onSubmit={(event) => {
        event.preventDefault()
        const when = condition()
        const then = consequence()
        if (!when || !then) return
        onSave(scope === 'all' ? null : Number(scope), when, then)
      }}
    >
      {(server || managed.length > 1) && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-12 font-semibold">{t('sorting.rules.scope')}</span>
          <select value={scope} onChange={(event) => setScope(event.target.value)} className="input h-9 min-w-40 flex-1" aria-label={t('sorting.rules.scope')}>
            {server && <option value="all">{t('sorting.rules.everywhere')}</option>}
            {managed.map((v) => (
              <option key={v.id} value={String(v.id)}>
                {vaultLabel(v)}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-12 font-semibold">{t('sorting.rules.if')}</span>
        <select value={whenField} onChange={(event) => chooseWhen(event.target.value as WhenField)} className="input h-9 w-36" aria-label={t('sorting.rules.if')}>
          {WHEN_FIELDS.map((field) => (
            <option key={field} value={field}>
              {t(`sorting.rules.field.${field}`)}
            </option>
          ))}
        </select>
        <select value={op} onChange={(event) => setOp(event.target.value as RuleCondition['op'])} className="input h-9 w-36" aria-label={t(`sorting.rules.field.${whenField}`)}>
          {OPS[whenField].map((value) => (
            <option key={value} value={value}>
              {t(`sorting.rules.op.${value}`)}
            </option>
          ))}
        </select>
        {whenField === 'kind' ? (
          <select value={whenValue} onChange={(event) => setWhenValue(event.target.value)} className="input h-9 min-w-40 flex-1" aria-label={t('sorting.rules.field.kind')}>
            {kindChoices.map((k) => (
              <option key={k.id} value={String(k.id)}>
                {k.name}
              </option>
            ))}
          </select>
        ) : whenField === 'source' ? (
          <select value={whenValue} onChange={(event) => setWhenValue(event.target.value)} className="input h-9 min-w-40 flex-1" aria-label={t('sorting.rules.field.source')}>
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {t(`docs.source.${s}`)}
              </option>
            ))}
          </select>
        ) : whenField === 'sender' && op === 'is' ? (
          <div className="min-w-40 flex-1">
            <SenderPicker value={whenValue} onChange={setWhenValue} names={names.senders} label={t('sorting.rules.field.sender')} className="input h-9" />
          </div>
        ) : (
          <input
            value={whenValue}
            onChange={(event) => setWhenValue(event.target.value)}
            placeholder={whenField === 'amount' ? amountText(10000, i18n.language) : t('sorting.rules.valuePlaceholder')}
            maxLength={100}
            aria-label={t(`sorting.rules.field.${whenField}`)}
            className="input h-9 min-w-40 flex-1"
          />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-12 font-semibold">{t('sorting.rules.then')}</span>
        <select value={thenField} onChange={(event) => chooseThen(event.target.value as ThenField)} className="input h-9 w-36" aria-label={t('sorting.rules.then')}>
          {THEN_FIELDS.map((field) => (
            <option key={field} value={field}>
              {t(`sorting.rules.target.${field}`)}
            </option>
          ))}
        </select>
        {thenField === 'vault' ? (
          <select value={thenValue} onChange={(event) => setThenValue(event.target.value)} className="input h-9 min-w-40 flex-1" aria-label={t('sorting.rules.target.vault')}>
            {writable.map((v) => (
              <option key={v.id} value={String(v.id)}>
                {vaultLabel(v)}
              </option>
            ))}
          </select>
        ) : thenField === 'kind' ? (
          <select value={thenValue} onChange={(event) => setThenValue(event.target.value)} className="input h-9 min-w-40 flex-1" aria-label={t('sorting.rules.target.kind')}>
            {kindChoices.map((k) => (
              <option key={k.id} value={String(k.id)}>
                {k.name}
              </option>
            ))}
          </select>
        ) : thenField === 'sender' ? (
          <div className="min-w-40 flex-1">
            <SenderPicker value={thenValue} onChange={setThenValue} names={names.senders} label={t('sorting.rules.target.sender')} className="input h-9" />
          </div>
        ) : (
          <input
            value={thenValue}
            onChange={(event) => setThenValue(event.target.value)}
            placeholder={thenField === 'title' ? t('sorting.rules.titlePlaceholder') : ''}
            maxLength={thenField === 'title' ? 120 : thenField === 'tag' ? 40 : 160}
            aria-label={t(`sorting.rules.target.${thenField}`)}
            className="input h-9 min-w-40 flex-1"
          />
        )}
      </div>
      {thenField === 'title' && <p className="text-xs text-muted">{t('sorting.rules.titleHint')}</p>}
      <div className="flex gap-2">
        <Button primary type="submit" busy={busy} disabled={!ready}>
          {t('sorting.rules.create')}
        </Button>
        <Button onClick={onCancel}>{t('sorting.rules.cancel')}</Button>
      </div>
      <p className="text-xs text-muted">{t('sorting.rules.hint')}</p>
    </form>
  )
}
