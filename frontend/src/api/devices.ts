/**
 * nexpaper's client for the cards of the shared module geraete 0.1.1 (`vendor/nexgeraete`): its headers and errors,
 * the module's routes under `/api/v1`. The pairing window's QR code is the module's (`POST /api/v1/app-pairing`); with
 * `link_form="pair"` (G58) its link is one the published iPhone app reads too (`nexpaper://pair?server=…&code=…`).
 */
import { api, ApiError } from './client'
import type { DeviceRequest } from '../vendor/nexgeraete'

/** Where the module's browser routes are mounted in nexpaper. */
export const DEVICES_AT = '/api/v1'

/** Where the operator switches the app and new devices on (the card "Schnittstellen"). */
export const SERVER_CONNECTIONS = '/settings/server-connections'

export const deviceRequest: DeviceRequest = async <T,>(path: string, init: Parameters<DeviceRequest>[1] = {}) => {
  try {
    return await api<T>(path, { method: init.method, query: init.query, body: init.body })
  } catch (error) {
    // The cards read the code (and `max`) from `detail`, as FastAPI sends it.
    if (error instanceof ApiError) throw Object.assign(error, { detail: { code: error.code, ...error.values } })
    throw error
  }
}
