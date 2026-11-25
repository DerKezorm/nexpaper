/**
 * Since 1.1.0: a value to copy (an address, a key shown once, a link): the value in fixed-width letters in a frame, a
 * `sm` button "Copy" (Copy) right of it, which says "Copied" (Check) for a moment and tells readers too. The value is a
 * read-only field named by `label`: a click selects it all, so it can be copied by hand where the browser lets no page
 * write to the clipboard (no HTTPS).
 */
import { useEffect, useRef, useState } from 'react'

import { Button } from './Button'
import { useNexuiTexts } from './texts'

/** Writes to the clipboard; false where the browser does not allow it. */
async function toClipboard(value: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value)
      return true
    }
  } catch {
    // falls through to the old way
  }
  try {
    const area = document.createElement('textarea')
    area.value = value
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.append(area)
    area.select()
    const done = document.execCommand?.('copy') ?? false
    area.remove()
    return done
  } catch {
    return false
  }
}

export function CopyRow({ value, label, testId }: { value: string; label: string; testId?: string }) {
  const texts = useNexuiTexts()
  const field = useRef<HTMLInputElement>(null)
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 2000)
    return () => window.clearTimeout(timer)
  }, [copied])
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-[12px] border border-solid border-[var(--nexui-line)] py-1 pr-1 pl-3" data-part="copy-row" data-testid={testId}>
      <input
        ref={field}
        readOnly
        value={value}
        aria-label={label}
        onFocus={(event) => event.target.select()}
        className="h-8 min-w-0 flex-1 border-0 bg-transparent p-0 font-mono text-xs leading-4 tracking-normal text-[var(--nexui-text)] outline-none"
      />
      <Button
        kind="secondary"
        size="sm"
        icon={copied ? 'Check' : 'Copy'}
        onClick={() =>
          void toClipboard(value).then((done) => {
            if (done) setCopied(true)
            else field.current?.select()
          })
        }
      >
        {copied ? texts.copied : texts.copy}
      </Button>
      <span role="status" className="sr-only">
        {copied ? texts.copied : ''}
      </span>
    </div>
  )
}
