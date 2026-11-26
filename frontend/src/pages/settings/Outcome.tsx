/**
 * What a change in a card of the settings came to, in the kit's boxes: what went wrong (`Notice danger`, the sentence
 * of the server's code with its values), or that it worked (`Notice ok`). Nothing when there is nothing to say.
 */
import { errorText } from '../../lib/errors'
import { Notice } from '../../vendor/nexui'

export function Outcome({ problem, done = null, values, testId }: { problem: string | null; done?: string | null; values?: Record<string, unknown>; testId?: string }) {
  if (!problem && !done) return null
  return (
    <div aria-live="polite" data-testid={testId}>
      {problem ? <Notice tone="danger">{errorText(problem, values)}</Notice> : <Notice tone="ok">{done}</Notice>}
    </div>
  )
}
