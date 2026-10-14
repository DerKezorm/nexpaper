/**
 * My account, Reminders (the mock's `Reminders.tsx`): how and when the person hears of deadlines, and for which vaults.
 * Each person sets it for themselves; who is reminded at all is everybody who may change things in the vault. A change
 * is saved at once. Mail (and the weekly overview, which is a mail) is greyed out with its reason when it cannot go.
 */
import { Bell, Clock, Eye, FolderLock, Mail, Smartphone } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'

import { deadlinesApi, remindersApi, type Deadline, type Me, type ReminderLead, type Reminders, type RemindersChange } from '../../api/client'
import { LogoMark } from '../../components/Logo'
import { VaultIcon } from '../../components/VaultIcon'
import { weekday } from '../../lib/deadlines'
import { useSay } from '../../lib/say'
import { Button, Card, Feedback, Segment, SubHead, Toggle, useAction } from './ui'

const LEADS: (keyof ReminderLead)[] = ['due', 'cancel', 'warranty']

/** "Mi, 30.09." or "Wed, Sep 30": a day of this year with its weekday, as the messages name it. */
function useShortDay(): (day: string) => string {
  const { t, i18n } = useTranslation()
  return (day: string) => {
    const name = (t('deadlines.weekdays', { returnObjects: true }) as string[])[weekday(day)] ?? ''
    const [y, m, d] = day.split('-').map(Number)
    const date = i18n.language.startsWith('de')
      ? `${String(d).padStart(2, '0')}.${String(m).padStart(2, '0')}.`
      : new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(y, m - 1, d)))
    return `${name}, ${date}`
  }
}

export function RemindersPart({ me }: { me: Me }) {
  const { t } = useTranslation()
  const say = useSay()
  const [r, setR] = useState<Reminders | null>(null)
  const action = useAction()
  const probe = useAction()

  useEffect(() => {
    let alive = true
    remindersApi.get().then(
      (found) => alive && setR(found),
      () => undefined,
    )
    return () => {
      alive = false
    }
  }, [])

  if (!r) return null

  const save = (change: RemindersChange) => {
    // Shown at once; what the server answers is what stands (a refused change goes back with its reason).
    setR({ ...r, ...change, lead: { ...r.lead, ...(change.lead ?? {}) } } as Reminders)
    void action.run(async () => {
      try {
        setR(await remindersApi.save(change))
      } catch (caught) {
        setR(await remindersApi.get())
        throw caught
      }
    })
  }
  const test = () => void probe.run(async () => {
    await remindersApi.test()
    say(t('reminders.tested'))
  })

  const single = r.rhythm !== 'weekly'
  const weekly = r.rhythm !== 'single'
  const mailOk = r.mail_problem === null
  const mailWhy = r.mail_problem ? t(`reminders.mailWhy.${r.mail_problem}`) : ''
  return (
    <>
      <Card icon={Bell} title={t('reminders.how.title')} text={t('reminders.how.text')}>
        <SubHead title={t('reminders.when')} />
        <div>
          <Segment
            label={t('reminders.rhythmLabel')}
            value={r.rhythm}
            onChange={(rhythm) => save({ rhythm })}
            options={[
              { value: 'single', label: t('reminders.rhythm.single') },
              { value: 'weekly', label: t('reminders.rhythm.weekly'), disabled: !mailOk && r.rhythm !== 'weekly' },
              { value: 'both', label: t('reminders.rhythm.both'), disabled: !mailOk && r.rhythm !== 'both' },
            ]}
          />
          <p className="mt-2 text-sm text-muted">{t(`reminders.rhythmHint.${r.rhythm}`)}</p>
        </div>
        {!mailOk && r.rhythm === 'single' && <p className="text-xs text-muted">{mailWhy}</p>}
        <SubHead title={t('reminders.where')} />
        <div className="space-y-2">
          {single && (
            <Toggle
              label={t('reminders.push')}
              hint={r.push_devices ? t('reminders.pushHint', { count: r.push_devices }) : t('reminders.pushNone')}
              checked={r.push}
              onChange={(push) => save({ push })}
            />
          )}
          {single && (
            <Toggle
              label={mailOk ? t('reminders.mailTo', { address: r.mail_address }) : t('reminders.mail')}
              hint={mailOk ? t('reminders.mailHint') : mailWhy}
              checked={r.mail}
              disabled={!mailOk && !r.mail}
              onChange={(mail) => save({ mail })}
            />
          )}
          {weekly &&
            (mailOk ? (
              <p className="flex items-center gap-2 rounded-xl border border-line bg-sheet-2/50 px-4 py-3 text-sm">
                <Mail size={16} className="shrink-0 text-accent" aria-hidden />
                <span>
                  <Trans i18nKey="reminders.weeklyTo" values={{ address: r.mail_address }} components={{ b: <span className="font-semibold" /> }} />
                </span>
              </p>
            ) : (
              <p className="flex items-center gap-2 rounded-xl border border-line bg-sheet-2/50 px-4 py-3 text-sm text-warn">
                <Mail size={16} className="shrink-0" aria-hidden /> {t('reminders.weeklyNot')} {mailWhy}
              </p>
            ))}
          {single && !r.push && !(r.mail && mailOk) && <p className="text-sm font-semibold text-warn">{t('reminders.nothingWay')}</p>}
        </div>
        <div className="pt-1">
          <Button onClick={test} busy={probe.busy}>
            {t('reminders.test')}
          </Button>
        </div>
        <Feedback problem={action.problem ?? probe.problem} values={action.problem ? action.values : probe.values} />
      </Card>

      {single && (
        <Card icon={Clock} title={t('reminders.early.title')} text={t('reminders.early.text', { zone: r.time_zone })}>
          <div className="space-y-2">
            {LEADS.map((key) => {
              const label = t(`reminders.lead.${key}`)
              return (
                <div key={key} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-sheet-2/50 px-4 py-2.5 text-sm">
                  <span className="font-semibold">{label}</span>
                  <select value={r.lead[key]} onChange={(event) => save({ lead: { [key]: Number(event.target.value) } })} className="input h-9 w-auto" aria-label={t('reminders.leadAria', { label })}>
                    {r.options[key].map((n) => (
                      <option key={n} value={n}>
                        {t('reminders.before', { count: n })}
                      </option>
                    ))}
                  </select>
                </div>
              )
            })}
            <Toggle label={t('reminders.sameDay')} hint={t('reminders.sameDayHint')} checked={r.same_day} onChange={(same_day) => save({ same_day })} />
          </div>
        </Card>
      )}

      <Card icon={FolderLock} title={t('reminders.vaults.title')} text={t('reminders.vaults.text')}>
        <div className="space-y-2">
          {r.vaults.map((v) => (
            <Toggle
              key={v.id}
              label={v.personal ? t('reminders.myVault') : v.name}
              hint={v.personal ? t('reminders.myVaultHint') : v.others ? t('reminders.othersToo') : t('reminders.onlyYou')}
              checked={!v.muted}
              onChange={(on) => save({ muted: on ? r.muted.filter((x) => x !== v.id) : [...r.muted, v.id] })}
            />
          ))}
          {r.shared > 0 && (
            <Toggle label={t('reminders.shared')} hint={t('reminders.sharedHint', { count: r.shared })} checked={!r.muted_shared} onChange={(on) => save({ muted_shared: !on })} />
          )}
        </div>
        {r.read_only.length > 0 && (
          <p className="flex flex-wrap items-center gap-x-2 pt-1 text-sm text-muted">
            {t('reminders.readOnly')}
            {r.read_only.map((v) => (
              <span key={v.id} className="inline-flex items-center gap-1">
                <VaultIcon icon={v.icon} size={13} /> {v.personal_of_other || v.personal ? t('reminders.personal', { name: v.name }) : v.name}
              </span>
            ))}
          </p>
        )}
      </Card>

      <Card icon={Eye} title={t('reminders.preview.title')} text={t('reminders.preview.text')}>
        <Preview me={me} r={r} />
      </Card>
    </>
  )
}

function Preview({ me, r }: { me: Me; r: Reminders }) {
  const { t, i18n } = useTranslation()
  const shortDay = useShortDay()
  const [all, setAll] = useState<Deadline[]>([])
  useEffect(() => {
    let alive = true
    deadlinesApi.list({ limit: 50 }).then(
      (found) => alive && setAll([...found.overdue.items, ...found.soon.items, ...found.later.items]),
      () => undefined,
    )
    return () => {
      alive = false
    }
  }, [])
  // The mock shows a contract; without one, the next deadline of any kind.
  const ahead = all.filter((x) => x.days >= 0)
  const shown = ahead.find((x) => x.what === 'cancel') ?? ahead[0]
  const week = all.filter((x) => x.days >= 0 && x.days <= 6)
  const overdue = all.filter((x) => x.days < 0)
  const longDate = (day: string) => new Intl.DateTimeFormat(i18n.language, { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${day}T00:00:00Z`))
  const lead = shown ? (shown.what === 'pay' ? r.lead.due : shown.what === 'warranty' ? r.lead.warranty : r.lead.cancel) : 0
  // As the reminder says it on its day: as many days ahead as the person chose.
  const days = lead
  const line = (x: Deadline) => `${shortDay(x.date)} · ${t(`reminders.week.short.${x.what}`)}: ${x.title}`
  return (
    <div className="grid gap-5 md:grid-cols-2">
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-ink-2">
          <Smartphone size={15} aria-hidden /> {t('reminders.preview.push')}
        </p>
        <div className="rounded-[1.4rem] bg-[#2b2622] p-4 shadow-soft">
          <div className="rounded-2xl bg-white/90 p-3 text-[#1c1814] backdrop-blur dark:bg-white/85">
            <div className="flex items-center gap-2 text-xs text-[#6b625a]">
              <LogoMark size={18} />
              <span className="font-semibold tracking-wide uppercase">nexpaper</span>
              <span className="ml-auto">{t('reminders.preview.time')}</span>
            </div>
            {shown && (
              <>
                <p className="mt-1.5 text-sm font-semibold">
                  {t(`reminders.words.${shown.what}`, { day: shortDay(shown.date) })}: {shown.title}
                </p>
                <p className="text-sm text-[#4a423b]">
                  {days > 1 ? t('reminders.words.days', { count: days }) : days === 1 ? t('reminders.words.tomorrow') : t('reminders.words.today')}
                  {shown.what === 'cancel' && shown.renews_to && ` ${t('reminders.words.renews', { date: longDate(shown.renews_to) })}`}
                </p>
              </>
            )}
          </div>
        </div>
      </div>
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-ink-2">
          <Mail size={15} aria-hidden /> {t('reminders.preview.mail')}
        </p>
        <div className="overflow-hidden rounded-2xl border border-line bg-sheet text-sm">
          <div className="border-b border-line bg-sheet-2/70 px-4 py-2.5">
            <p className="text-xs text-muted">nexpaper</p>
            <p className="font-semibold">
              {t('reminders.week.subject', { count: week.length })}
              {overdue.length > 0 && t('reminders.week.overdue', { count: overdue.length })}
            </p>
          </div>
          <div className="space-y-3 px-4 py-3">
            <p>{t('reminders.week.hello', { name: me.display_name || me.name })}</p>
            {overdue.length > 0 && (
              <div>
                <p className="text-xs font-bold tracking-wide text-warn uppercase">{t('reminders.week.overdueHead')}</p>
                <ul className="mt-1 space-y-0.5">
                  {overdue.map((x) => (
                    <li key={`${x.document_id}-${x.kind}`}>{line(x)}</li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <p className="text-xs font-bold tracking-wide text-muted uppercase">{t('reminders.week.weekHead')}</p>
              <ul className="mt-1 space-y-0.5">
                {week.map((x) => (
                  <li key={`${x.document_id}-${x.kind}`}>{line(x)}</li>
                ))}
                {week.length === 0 && <li className="text-muted">{t('reminders.week.nothing')}</li>}
              </ul>
            </div>
            <p className="font-semibold text-accent underline">{t('reminders.week.all')}</p>
            <p className="text-xs text-muted">{t('reminders.week.why')}</p>
          </div>
        </div>
      </div>
    </div>
  )
}
