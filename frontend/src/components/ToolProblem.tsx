/** What went wrong with a page tool, in the red box the settings use (`lib/toolErrors`). */
import { useTranslation } from 'react-i18next'

import { toolText } from '../lib/toolErrors'

export function ToolProblem({ code }: { code: string | null }) {
  useTranslation() // the sentence follows the language
  if (!code) return null
  return (
    <p role="alert" className="mt-3 rounded-xl border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {toolText(code)}
    </p>
  )
}
