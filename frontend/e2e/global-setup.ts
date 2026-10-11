/**
 * Before any test: the operator account on the fresh data folder, with the second factor nexpaper asks for from the
 * start (a code from an app, computed here), then "require a second factor" off for the accounts the tests make, and
 * the operator's session saved for every test (`storageState`). Name, password and seed are made up for the run and
 * live only in the temporary data folder.
 */
import { request, type APIRequestContext, type FullConfig } from '@playwright/test'
import crypto from 'node:crypto'

export const OPERATOR = { name: 'tester', password: 'e2e test operator password' }
/** The tab header every change needs. */
export const TAB = { 'X-Nexpaper-Client': 'tab-e2esetup0' }

/** RFC 6238 with HMAC-SHA1, 30 seconds, six digits: the code an authenticator app shows for the seed. */
export function totp(seed: string, moment = Date.now()): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const char of seed.replace(/=+$/, '').toUpperCase()) bits += alphabet.indexOf(char).toString(2).padStart(5, '0')
  const key = Buffer.from(bits.match(/.{8}/g)!.map((byte) => parseInt(byte, 2)))
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(moment / 1000 / 30)))
  const digest = crypto.createHmac('sha1', key).update(counter).digest()
  const offset = digest[digest.length - 1] & 0x0f
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, '0')
}

async function ok(answer: Awaited<ReturnType<APIRequestContext['post']>>, what: string): Promise<void> {
  if (!answer.ok()) throw new Error(`${what} failed: ${answer.status()} ${await answer.text()}`)
}

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0].use.baseURL!
  const context = await request.newContext({ baseURL, extraHTTPHeaders: TAB })
  const made = await context.post('/api/v1/setup', { data: { name: OPERATOR.name, password: OPERATOR.password, language: 'en', code: 'e2e-setup-code' } })
  await ok(made, 'setup')
  // Right after the password the session may only set up the second factor: a code from an app, then the codes kept.
  const begun = await context.post('/api/v1/auth/totp/begin')
  await ok(begun, 'totp begin')
  const { secret } = (await begun.json()) as { secret: string }
  await ok(await context.post('/api/v1/auth/totp/confirm', { data: { code: totp(secret) } }), 'totp confirm')
  await ok(await context.post('/api/v1/auth/setup/done'), 'setup done')
  // The accounts the tests make sign in with a password alone.
  await ok(await context.put('/api/v1/settings', { data: { two_factor_required: false, current_password: OPERATOR.password } }), 'settings')
  await context.storageState({ path: process.env.E2E_STATE! })
  await context.dispose()
}
