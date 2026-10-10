/**
 * Copies text. The browser's clipboard API works only in a secure context (HTTPS or localhost); a self-hosted app is
 * often reached over plain http in the home network, where it is missing and a copy button did nothing. Then a
 * hidden text field and the older copy command do it. True when the text reached the clipboard.
 */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Refused (no permission, page not in focus): the older way below may still work.
    }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.top = '0'
  area.style.left = '-9999px'
  area.style.opacity = '0'
  const before = document.activeElement as HTMLElement | null
  document.body.appendChild(area)
  area.focus()
  area.select()
  let done: boolean
  try {
    done = document.execCommand('copy')
  } catch {
    done = false
  }
  area.remove()
  before?.focus?.()
  return done
}
