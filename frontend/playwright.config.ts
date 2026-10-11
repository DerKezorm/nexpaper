/**
 * End to end, headless: the sign-in through a provider (Pflichttests 33 and 34 of the shared sign-in blueprint). The
 * built interface is served by the real backend, as in the container. Own data folder and own ports (the backend on
 * 18566, the stand-in sign-in provider on 18567), so that a running development server (8560, 5571) is never measured.
 *
 *   npx playwright install chromium     once
 *   npm run e2e                         build, start the backend and the stand-in, test
 */
import { defineConfig } from '@playwright/test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const PORT = Number(process.env.E2E_PORT ?? 18566)
const PROVIDER_PORT = Number(process.env.E2E_PROVIDER_PORT ?? 18567)

/** A fresh data folder per run. Made here and not in a global set-up: the server starts first. The workers load this
 * file again and inherit the folder through the environment. */
function dataDir(): string {
  if (process.env.E2E_DATA_DIR) return process.env.E2E_DATA_DIR
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'nexpaper-e2e-'))
  process.env.E2E_DATA_DIR = dir
  return dir
}

const DATA_DIR = dataDir()
/** Where the operator's session is kept for the tests (global-setup.ts signs in once). */
export const SIGNED_IN = path.join(DATA_DIR, 'e2e-operator.json')
process.env.E2E_STATE = SIGNED_IN
process.env.E2E_PROVIDER = `http://127.0.0.1:${PROVIDER_PORT}`
// The project's venv on the development machines, the system Python elsewhere.
const venv = path.join('.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const python = fs.existsSync(path.join('..', 'backend', venv)) ? venv : 'python'

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    headless: true,
    locale: 'en-US',
    storageState: SIGNED_IN,
  },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${PORT} --no-proxy-headers --no-server-header`,
      cwd: path.join('..', 'backend'),
      url: `http://127.0.0.1:${PORT}/api/v1/health`,
      reuseExistingServer: false,
      timeout: 90_000,
      env: {
        NEXPAPER_DATA_DIR: DATA_DIR,
        NEXPAPER_FRONTEND_DIST: path.resolve('dist'),
        NEXPAPER_DISABLE_BACKGROUND: '1',
        NEXPAPER_ARGON2_TIME: '1',
        NEXPAPER_ARGON2_MEMORY_KIB: '8192',
        NEXPAPER_ARGON2_PARALLELISM: '1',
        // Never GitHub from a test: port 9 refuses at once.
        NEXPAPER_UPDATE_URL: 'http://127.0.0.1:9/releases/latest',
        // The code the first account brings; global-setup.ts sends it.
        NEXPAPER_SETUP_TOKEN: 'e2e-setup-code',
        NEXPAPER_COOKIE_SUFFIX: '_e2e',
      },
    },
    // A stand-in sign-in provider (nexoidc.spec.ts): signs in at once whoever POST /oidc/next named.
    {
      command: 'node e2e/fake-provider.mjs',
      url: `http://127.0.0.1:${PROVIDER_PORT}/health`,
      reuseExistingServer: false,
      timeout: 20_000,
      env: { FAKE_PROVIDER_PORT: String(PROVIDER_PORT) },
    },
  ],
})
