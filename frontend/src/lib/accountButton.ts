/** The confirming button of a dialog of the account pages, kind and symbol from the module (`BUTTONS`). */
import { BUTTONS, type ButtonName } from '../vendor/nexkonten/konten'
import type { Confirm, IconName } from '../vendor/nexui'

export function confirmOf(name: ButtonName, label: string): Confirm {
  const spec = BUTTONS[name]
  return { label, kind: spec.kind, icon: spec.icon as IconName }
}
