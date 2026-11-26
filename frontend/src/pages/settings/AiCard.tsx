/**
 * The AI in nexpaper's settings, from the shared module (ki 0.1.0, Entwurf KI-Anbieter, Bauplan E61):
 *
 * - Server › KI-Anbieter: the module's cards (`AiProviderArea`: the service, who may use AI with the main switch and
 *   the way, the limits), then nexpaper's own card "Vorschläge im Eingang": personal vaults never to the AI, and the
 *   operator's own wishes for the proposals (both nexpaper's, kept where they were, through the older route).
 * - Mein Konto › KI: the module's cards (`AiAccountArea`: "KI für mich" with the reason when it does not work, an own
 *   service where the operator chose "Jedes Konto selbst", "Was ging hinaus"), then what nexpaper sends.
 */
import { useEffect, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { aiApi, api, type AiSettings } from '../../api/client'
import { AiAccountArea, AiProviderArea, type AiRequest } from '../../vendor/nexki'
import { Button, Card, CheckboxRow, formatMoment } from '../../vendor/nexui'
import { useAction } from './actions'
import { Outcome } from './Outcome'

/** Where the module's routes stand in nexpaper. */
export const KI_SERVER_AT = '/api/v1/server/ai'
export const KI_ME_AT = '/api/v1/me/ai'

/** The most the operator's own wishes may be, as the server keeps them. */
const WISHES_MAX = 2000
const AREA = 'block min-h-28 w-full rounded-[9px] border border-solid border-[var(--nexui-edge)] bg-[var(--nexui-field)] px-3 py-2 text-sm text-[var(--nexui-text)] outline-none focus:border-[var(--nexui-accent)]'

const kiRequest: AiRequest = (path, init = {}) => api(path, { method: init.method, body: init.body })

/** Server › KI-Anbieter. */
export function AiCard() {
  const { i18n } = useTranslation()
  return (
    <AiProviderArea request={kiRequest} app="nexpaper" base={KI_SERVER_AT} language={i18n.language}>
      <ProposalsCard />
    </AiProviderArea>
  )
}

/** "Vorschläge im Eingang": what nexpaper alone keeps from the AI, and the operator's wishes for its proposals. */
function ProposalsCard() {
  const { t } = useTranslation()
  const [stored, setStored] = useState<AiSettings | null>(null)
  const [wishes, setWishes] = useState<string | null>(null)
  const action = useAction()
  const wishesHint = useId()
  const wishesField = useId()
  useEffect(() => {
    let alive = true
    aiApi.settings().then((found) => alive && setStored(found), () => undefined)
    return () => {
      alive = false
    }
  }, [])
  if (!stored) return null
  const saveWishes = () => {
    if (wishes === null) return
    void action.run(async () => {
      setStored(await aiApi.save({ instructions: wishes }))
      setWishes(null)
    }, t('sorting.ai.instructionsSaved'))
  }
  return (
    <Card id="ai-proposals" icon="ScanText" title={t('me.ai.title')} subtitle={t('me.ai.text')} testId="ai-proposals">
      <CheckboxRow
        label={t('sorting.ai.skipPersonal')}
        hint={t('sorting.ai.skipPersonalHint')}
        checked={stored.skip_personal !== false}
        testId="ai-skip-personal"
        onChange={(skip_personal) => {
          setStored({ ...stored, skip_personal })
          void action.run(async () => setStored(await aiApi.save({ skip_personal })))
        }}
      />
      <div className="flex flex-col gap-1 text-sm">
        <label htmlFor={wishesField} className="font-medium">
          {t('sorting.ai.instructions')}
        </label>
        <textarea
          id={wishesField}
          value={wishes ?? stored.instructions ?? ''}
          onChange={(event) => setWishes(event.target.value)}
          rows={4}
          maxLength={WISHES_MAX}
          placeholder={t('sorting.ai.instructionsPlaceholder')}
          aria-describedby={wishesHint}
          className={AREA}
          data-testid="ai-wishes"
        />
        <span id={wishesHint} className="text-xs text-[var(--nexui-text-muted)]">
          {t('sorting.ai.instructionsHint', { max: WISHES_MAX })}
        </span>
        <div className="mt-1">
          <Button kind="secondary" icon="Check" busy={action.busy} disabled={wishes === null} onClick={saveWishes} testId="ai-wishes-save">
            {t('sorting.ai.instructionsSave')}
          </Button>
        </div>
      </div>
      <p className="m-0 text-xs leading-relaxed text-[var(--nexui-text-muted)]">{t('server.ai.outgoing')}</p>
      <Outcome problem={action.problem} values={action.values} done={action.done} />
    </Card>
  )
}

/** Mein Konto › KI. */
export function MyAi() {
  const { t, i18n } = useTranslation()
  return (
    <AiAccountArea
      request={kiRequest}
      app="nexpaper"
      base={KI_ME_AT}
      language={i18n.language}
      tasks={{ propose: t('me.ai.task') }}
      when={formatMoment}
    >
      <Card id="ai-what" icon="ScanText" title={t('me.ai.title')} subtitle={t('me.ai.text')} testId="ai-what">
        <p className="m-0 text-sm text-[var(--nexui-text-muted)]">{t('server.ai.outgoing')}</p>
      </Card>
    </AiAccountArea>
  )
}
