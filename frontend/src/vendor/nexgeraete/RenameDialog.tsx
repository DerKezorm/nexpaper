/**
 * "Gerät umbenennen": one field "Name" with the hint why a name of one's own helps (since iOS 16 an iPhone tells the app
 * only its model), "Abbrechen" and "Sichern". `PATCH <base>/app-devices/{id} {name}` answers the device. Built only
 * from the ui kit.
 *
 * Copied unchanged into frontend/src/vendor/nexgeraete/ by bauplaene/geraete/tools/sync.py; changed only there.
 */
import { useState } from 'react'

import { Button, Dialog, Field, useNexuiTexts } from '../nexui'
import { useDeviceTexts } from './hooks'
import { BUTTONS, DEVICES_BASE, NAME_MAX, refusalText, type Device, type DeviceRequest } from './geraete'

export type RenameDialogProps = {
  request: DeviceRequest
  base?: string
  device: Device
  language?: string
  onClose: () => void
  onRenamed: (device: Device) => void
  testId?: string
}

export function RenameDialog({ request, base = DEVICES_BASE, device, language, onClose, onRenamed, testId = 'device-rename-dialog' }: RenameDialogProps) {
  const { texts } = useDeviceTexts(language)
  const kit = useNexuiTexts()
  const [name, setName] = useState(device.name)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  const submit = async () => {
    setBusy(true)
    setError(undefined)
    try {
      onRenamed(await request<Device>(`${base}/app-devices/${encodeURIComponent(String(device.id))}`, { method: 'PATCH', body: { name: name.trim() } }))
    } catch (failure) {
      setError(refusalText(texts, failure))
      setBusy(false)
    }
  }

  return (
    <Dialog title={texts.rename.title} onClose={onClose} closeLabel={kit.close} testId={testId}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(event) => {
          event.preventDefault()
          if (!busy && name.trim()) void submit()
        }}
      >
        <Field
          label={texts.rename.name}
          hints={[texts.rename.hint]}
          error={error}
          value={name}
          maxLength={NAME_MAX}
          required
          autoComplete="off"
          onChange={(event) => setName(event.target.value)}
          data-testid="device-rename-name"
        />
        <div className="flex flex-wrap justify-end gap-2">
          <Button kind={BUTTONS.cancel.kind} icon={BUTTONS.cancel.icon} onClick={onClose} testId="device-rename-cancel">
            {texts.rename.cancel}
          </Button>
          <Button type="submit" kind={BUTTONS.save.kind} icon={BUTTONS.save.icon} busy={busy} disabled={!name.trim()} testId="device-rename-save">
            {texts.rename.save}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
