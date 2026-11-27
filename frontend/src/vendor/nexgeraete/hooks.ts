// The module's words in the language of the ui kit, and the row "iPhone und iPad" of NotifyWays. Copied unchanged into
// frontend/src/vendor/nexgeraete/ by bauplaene/geraete/tools/sync.py; changed only there.
import { useEffect, useState } from 'react'

import { NEXUI_TEXTS, languageOf, useNexuiTexts } from '../nexui'
import { DEVICES_BASE, DEVICE_TEXTS, devicesWay, type DeviceListing, type DeviceRequest, type DeviceTexts } from './geraete'

/** The module's words in the kit's language (or the one given). */
export function useDeviceTexts(language?: string): { texts: DeviceTexts; code: 'de' | 'en' | 'fr' } {
  const kit = useNexuiTexts()
  if (language) {
    const code = languageOf(language)
    return { texts: DEVICE_TEXTS[code], code }
  }
  const code = (Object.keys(NEXUI_TEXTS) as (keyof typeof NEXUI_TEXTS)[]).find((key) => NEXUI_TEXTS[key] === kit) ?? 'en'
  return { texts: DEVICE_TEXTS[code], code }
}

/** What `NotifyWays` takes as `devices` ("iPhone und iPad"): the count of the account's devices and on how many
 * notifications are allowed, with the way to Connections (`href`). `undefined` while loading, when the list cannot be
 * read, and while the app has no iPhone app: then the row is left out. */
export function useDevicesWay(
  request: DeviceRequest,
  { base = DEVICES_BASE, href, language }: { base?: string; href?: string; language?: string } = {},
): { href?: string; note: string } | undefined {
  const { texts } = useDeviceTexts(language)
  const [listing, setListing] = useState<DeviceListing | null>(null)
  useEffect(() => {
    let live = true
    request<DeviceListing>(`${base}/app-devices`).then(
      (found) => {
        if (live) setListing(found)
      },
      () => undefined,
    )
    return () => {
      live = false
    }
  }, [request, base])
  return listing ? devicesWay(listing, texts, href) : undefined
}
