/**
 * Since 1.1.0: the first card under Notifications in every app that notifies, "Which way" (Bell, `id="notify-ways"`).
 * One box per way the app has, and only those:
 *
 * - "Mail": the address, a badge confirmed or not, `sm` "Change in profile".
 * - "This browser": a badge On/Off, "Turn on notifications" (primary) or "Turn off" (danger), "Send a test
 *   notification" (secondary); `note` says what stands in the way (blocked, no service worker, not on the Home Screen).
 * - "Browsers with notifications": the list, this browser marked, `sm` danger "Remove" per browser; `action` adds the
 *   app's own button to a row (rename, its own switch).
 * - "iPhone and iPad": where the app on the phone is connected (under Connections).
 *
 * Only words and buttons: whether a way is on and what a click does are the caller's. `children` adds the app's own
 * boxes at the end of the card (nexmail's states of this device, the iPhone's Home-Screen hint).
 */
import type { ReactNode } from 'react'

import { Button } from './Button'
import { Badge, Box, Card, Row, Rows } from './Card'
import { useNexuiTexts, type NexuiTexts } from './texts'

export type NotifyBrowser = {
  id: string
  name: string
  /** Small and grey: since when, last reached. */
  detail?: ReactNode
  /** This browser. */
  current?: boolean
  /** The app's own button in the row, before "Remove". */
  action?: ReactNode
}

export function NotifyWays({
  subtitle,
  mail,
  browser,
  browsers,
  devices,
  texts: own,
  children,
}: {
  subtitle?: ReactNode
  mail?: { address: string; confirmed: boolean; href?: string; onChange?: () => void }
  browser?: {
    on: boolean
    onTurnOn: () => void
    onTurnOff: () => void
    onProbe?: () => void
    busy?: boolean
    probing?: boolean
    /** It cannot be turned on here (blocked, unsupported). */
    disabled?: boolean
    note?: ReactNode
  }
  browsers?: { items: readonly NotifyBrowser[]; onRemove: (id: string) => void; busy?: boolean }
  devices?: { href?: string; onOpen?: () => void; note?: ReactNode }
  texts?: Partial<NexuiTexts>
  children?: ReactNode
}) {
  const texts = { ...useNexuiTexts(), ...own }
  return (
    <Card id="notify-ways" icon="Bell" title={texts.notifyTitle} subtitle={subtitle}>
      {mail && (
        <Box
          title={texts.notifyMail}
          badge={<Badge tone={mail.confirmed ? 'on' : 'warn'}>{mail.confirmed ? texts.notifyConfirmed : texts.notifyUnconfirmed}</Badge>}
          hint={mail.address}
          actions={
            (mail.href !== undefined || mail.onChange) && (
              <Button kind="secondary" size="sm" icon="UserPen" href={mail.href} onClick={mail.onChange} testId="notify-mail-change">
                {texts.notifyChangeInProfile}
              </Button>
            )
          }
          testId="notify-mail"
        />
      )}
      {browser && (
        <Box
          title={texts.notifyThisBrowser}
          badge={<Badge tone={browser.on ? 'on' : 'off'}>{browser.on ? texts.notifyOn : texts.notifyOff}</Badge>}
          hint={browser.note}
          actions={
            <>
              {browser.on ? (
                <Button kind="danger" icon="BellOff" busy={browser.busy} onClick={browser.onTurnOff} testId="notify-browser-off">
                  {texts.notifyTurnOff}
                </Button>
              ) : (
                <Button kind="primary" icon="Bell" busy={browser.busy} disabled={browser.disabled} onClick={browser.onTurnOn} testId="notify-browser-on">
                  {texts.notifyTurnOn}
                </Button>
              )}
              {browser.on && browser.onProbe && (
                <Button kind="secondary" icon="Send" busy={browser.probing} onClick={browser.onProbe} testId="notify-probe">
                  {texts.notifyProbe}
                </Button>
              )}
            </>
          }
          testId="notify-browser"
        />
      )}
      {browsers && (
        <Box title={texts.notifyBrowsers} hint={browsers.items.length === 0 ? texts.notifyNoBrowsers : undefined} testId="notify-browsers">
          {browsers.items.length > 0 && (
            <Rows label={texts.notifyBrowsers}>
              {browsers.items.map((item) => (
                <Row
                  key={item.id}
                  icon="Globe"
                  name={item.name}
                  badge={item.current ? <Badge tone="on">{texts.notifyCurrent}</Badge> : undefined}
                  detail={item.detail}
                  action={
                    <span className="flex flex-wrap items-center gap-2">
                      {item.action}
                      <Button kind="danger" size="sm" icon="Trash2" busy={browsers.busy} onClick={() => browsers.onRemove(item.id)} testId={`notify-remove-${item.id}`}>
                        {texts.remove}
                      </Button>
                    </span>
                  }
                  testId="notify-browser-row"
                />
              ))}
            </Rows>
          )}
        </Box>
      )}
      {devices && (
        <Box
          title={texts.notifyDevices}
          hint={devices.note ?? texts.notifyDevicesHint}
          actions={
            (devices.href !== undefined || devices.onOpen) && (
              <Button kind="secondary" size="sm" icon="ArrowRight" href={devices.href} onClick={devices.onOpen} testId="notify-devices">
                {texts.notifyToConnections}
              </Button>
            )
          }
          testId="notify-devices-box"
        />
      )}
      {children}
    </Card>
  )
}
