/**
 * Server › Accounts › Manage: the group "Geräte" in the window about one account, for operators. "2 Geräte: iPhone,
 * iPad" with "zuletzt heute, 08:12" (or, while the account is blocked, "ruhen, solange das Konto gesperrt ist"), `sm`
 * danger "Geräte trennen" with a question first, and the sentence that the operator sees only how many, which kind
 * and when last, never what is on them (`GET`/`DELETE <base>/server/accounts/{id}/devices`). Built only from the ui
 * kit.
 *
 * Copied unchanged into frontend/src/vendor/nexgeraete/ by bauplaene/geraete/tools/sync.py; changed only there.
 */
import { useCallback, useEffect, useState } from 'react'

import { Button, ButtonGroup, ConfirmDialog, Notice, useNexuiTexts } from '../nexui'
import { useDeviceTexts } from './hooks'
import {
  BUTTONS,
  DEVICES_BASE,
  countText,
  defaultWhen,
  fillDevices,
  kindsText,
  lastContact,
  refusalText,
  type AccountDevices,
  type DeviceRequest,
  type WhenFormat,
} from './geraete'

export type AccountDevicesPartProps = {
  request: DeviceRequest
  base?: string
  /** The account the window is about. */
  accountId: number | string
  /** Its name as the window shows it ("Mila Example"). */
  name: string
  /** The account is blocked or deleted: its devices rest (G26). */
  blocked?: boolean
  language?: string
  when?: WhenFormat
  /** After "Geräte trennen", with how many went. */
  onChanged?: (removed: number) => void
  testId?: string
}

export function AccountDevicesPart({ request, base = DEVICES_BASE, accountId, name, blocked = false, language, when = defaultWhen, onChanged, testId = 'account-devices' }: AccountDevicesPartProps) {
  const { texts, code } = useDeviceTexts(language)
  const kit = useNexuiTexts()
  const [found, setFound] = useState<AccountDevices | null>(null)
  const [problem, setProblem] = useState<string>()
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()
  const [round, setRound] = useState(0)

  const path = `${base}/server/accounts/${encodeURIComponent(String(accountId))}/devices`
  const load = useCallback(() => request<AccountDevices>(path), [request, path])
  useEffect(() => {
    load().then(setFound, (failure: unknown) => setProblem(refusalText(texts, failure)))
  }, [load, round, texts])

  const drop = async () => {
    setBusy(true)
    setError(undefined)
    try {
      const done = await request<{ removed: number }>(path, { method: 'DELETE' })
      setAsking(false)
      setRound((value) => value + 1)
      onChanged?.(done?.removed ?? 0)
    } catch (failure) {
      setError(refusalText(texts, failure))
    } finally {
      setBusy(false)
    }
  }

  const count = found?.count ?? 0
  const latest = found ? lastContact(found.devices) : null
  const sub = count === 0 ? fillDevices(texts.account.noneSub, { name }) : blocked ? texts.account.resting : latest ? fillDevices(texts.account.lastSeen, { when: when(latest, code) }) : null
  return (
    <ButtonGroup title={texts.account.title} layout="list" testId={testId}>
      {problem && (
        <Notice tone="danger" testId="account-devices-problem">
          {problem}
        </Notice>
      )}
      {found && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2" data-count={count}>
          <div className="min-w-0 flex-1">
            <p className="m-0 text-sm leading-5 font-medium text-[var(--nexui-text)]" data-testid="account-devices-line">
              {count === 0 ? texts.account.none : fillDevices(texts.account.some, { devices: countText(texts, count), kinds: kindsText(texts, found.devices) })}
            </p>
            {sub && (
              <p className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]" data-testid="account-devices-sub">
                {sub}
              </p>
            )}
          </div>
          {count > 0 && (
            <Button kind={BUTTONS.disconnectAll.kind} icon={BUTTONS.disconnectAll.icon} size="sm" onClick={() => setAsking(true)} testId="account-devices-disconnect">
              {texts.account.disconnect}
            </Button>
          )}
        </div>
      )}
      <p className="m-0 text-xs leading-4 text-[var(--nexui-text-muted)]" data-testid="account-devices-privacy">
        {texts.account.privacy}
      </p>
      {asking && (
        <ConfirmDialog
          title={fillDevices(texts.account.ask, { name })}
          text={fillDevices(texts.account.askText, { name })}
          confirm={{ label: texts.account.disconnect, kind: BUTTONS.disconnectAll.kind, icon: BUTTONS.disconnectAll.icon }}
          cancel={texts.account.cancel}
          closeLabel={kit.close}
          busy={busy}
          error={error}
          onCancel={() => setAsking(false)}
          onConfirm={() => void drop()}
          testId="account-devices-dialog"
        />
      )}
    </ButtonGroup>
  )
}
