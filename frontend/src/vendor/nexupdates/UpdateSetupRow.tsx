/**
 * U1: the box on the setup of a new installation, "Nach neuen Versionen sehen", ticked by default. The app keeps the
 * value with its setup form and sends it along; the server stores it only where nothing is stored yet
 * (`nexupdates.at_setup`). Built only from the ui kit (`CheckboxRow`); the hint names the address asked. Since 0.1.2
 * an app without a bell (U19: it asks only when an operator opens "Über") passes `bell={false}` and the hint says so;
 * since 0.1.3 such an app that pairs devices (module geraete) passes `devices` too (U24: also once a day while a device
 * of an operator wants to hear of new versions).
 *
 * Copied unchanged into frontend/src/vendor/nexupdates/ by bauplaene/updates/tools/sync.py; changed only there.
 */
import { CheckboxRow, fill } from '../nexui'
import { GITHUB, hostOf, useUpdatesTexts } from './updates'

export type UpdateSetupRowProps = {
  app: string
  /** Ticked by default (U1): the app starts its form with `true`. */
  checked: boolean
  onChange: (on: boolean) => void
  /** The address asked, where the app names its own (`<APP>_UPDATE_URL`). */
  url?: string
  disabled?: boolean
  /** Since 0.1.2: false for an app without a bell (nexfolk, nextasks, nextime, nexdiary): another hint. */
  bell?: boolean
  /** Since 0.1.3 (U24): the app pairs devices (module geraete); without a bell another hint. */
  devices?: boolean
  language?: string
  testId?: string
}

export function UpdateSetupRow({ app, checked, onChange, url = GITHUB, disabled, bell = true, devices = false, language, testId = 'setup-update-check' }: UpdateSetupRowProps) {
  const texts = useUpdatesTexts(language)
  return (
    <CheckboxRow
      label={texts.setupLabel}
      hint={fill(bell ? texts.setupHint : devices ? texts.setupHintDevices : texts.setupHintNoBell, { app, host: hostOf(url) })}
      checked={checked}
      onChange={onChange}
      disabled={disabled}
      testId={testId}
    />
  )
}
