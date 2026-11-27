/**
 * nexpaper's client for the cards of the shared module geraete 0.1.0 (`vendor/nexgeraete`): its headers and errors,
 * the module's routes under `/api/v1`. One exception: the pairing window asks for its QR code at nexpaper's
 * `POST /api/v1/devices/app-pairing` (`backend/app/routers/app_devices.py`), which makes the module's pairing with a
 * link the published iPhone app reads too (`nexpaper://pair?server=…&code=…`); it answers as the module's route does.
 */
import { api, ApiError } from './client'
import type { DeviceRequest } from '../vendor/nexgeraete'

/** Where the module's browser routes are mounted in nexpaper. */
export const DEVICES_AT = '/api/v1'

/** The pairing of the module, and where nexpaper makes it. */
const MODULE_PAIRING = `${DEVICES_AT}/app-pairing`
const PAIRING = `${DEVICES_AT}/devices/app-pairing`

/** Where the operator switches the app and new devices on (the card "Schnittstellen"). */
export const SERVER_CONNECTIONS = '/settings/server-connections'

export const deviceRequest: DeviceRequest = async <T,>(path: string, init: Parameters<DeviceRequest>[1] = {}) => {
  const target = path === MODULE_PAIRING && init.method === 'POST' ? PAIRING : path
  try {
    return await api<T>(target, { method: init.method, query: init.query, body: init.body })
  } catch (error) {
    // The cards read the code (and `max`) from `detail`, as FastAPI sends it.
    if (error instanceof ApiError) throw Object.assign(error, { detail: { code: error.code, ...error.values } })
    throw error
  }
}
