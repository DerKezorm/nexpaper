/**
 * Every test file: a stub of `fetch` (`vi.stubGlobal('fetch', ...)`) is counted by `wait.ts`, so that `idle()` knows
 * when the fake API has answered, and it can be made slow with TEST_API_DELAY_MS to prove that no test depends on
 * how fast an answer comes.
 */
import { newTest, tracked } from './wait'

beforeEach(newTest)

const stub = vi.stubGlobal.bind(vi)
vi.stubGlobal = ((name: string, value: unknown) => stub(name, name === 'fetch' && typeof value === 'function' ? tracked(value as (...args: never[]) => unknown) : value)) as typeof vi.stubGlobal
