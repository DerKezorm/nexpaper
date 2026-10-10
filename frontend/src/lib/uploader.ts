/**
 * The queue of uploads the page runs, apart from any screen so that it can be tested: files go to the server one request
 * at a time.
 *
 * * **Small files** (up to `small` bytes) travel together, up to ten in one request (`POST /documents`); each has its own
 *   result.
 * * **A large file** goes in pieces with resumption (`/uploads`): its SHA-256 is made first, the server may answer "you
 *   have this file already" (then nothing is sent), else the pieces follow in order, each at the offset where the server
 *   stands. A broken connection is tried again a few times, each time asking the server how far it is; if it does not
 *   come back the upload is *paused* and goes on from there with `resume` (the file is still in the page). `retry`
 *   starts a failed one anew. `cancel` drops what arrived.
 */
import { ApiError, uploadsApi, type UploadResult, type UploadState, type UploadTarget } from '../api/client'
import { sha256OfFile } from './sha256'

export type Phase = 'waiting' | 'hashing' | 'sending' | 'finishing' | 'done' | 'exists' | 'failed' | 'paused' | 'cancelled'

export type Entry = {
  id: number
  name: string
  size: number
  /** Goes in pieces, with a progress worth showing (else it goes with others in one request). */
  chunked: boolean
  phase: Phase
  /** Bytes made progress with: hashed, then handed over. */
  sent: number
  /** The document made (or the one that was there already). */
  document: { id: number; title: string } | null
  /** The vault the document went to. */
  vaultId: number | null
  /** The new document repeats (`same`) or looks like (`similar`) one the person has. */
  duplicate: { title: string; kind: 'same' | 'similar' } | null
  error: { code: string; values: Record<string, unknown> } | null
  /** Where it goes and where it came from (the quick upload names a vault, the camera and the share menu a source). */
  target?: UploadTarget
}

/** What came of a run: how many were taken, were there already, failed, repeat a document the person has; and the vaults the
 * taken ones went to. */
export type Summary = { done: number; exists: number; failed: number; duplicates: number; vaults: number[]; failures: Failure[] }

/** How many refused files a summary names. */
const MAX_NAMED = 30

/** A file that was not taken, with the code and values of the reason (the sentence is made where it is shown). */
export type Failure = { name: string; code: string; values: Record<string, unknown> }

/** Errors a second try can change (the connection, a busy server, a piece that got lost, a full quota that frees up). The
 * rest (a kind of file that is not taken, an empty one, one that is too large) comes out the same each time: no button. */
const RETRYABLE = new Set([
  'network', 'busy', 'internal_error', 'upload_busy', 'upload_expired', 'checksum_mismatch', 'offset_mismatch', 'exceeds_size',
  'piece_too_large', 'empty_piece', 'incomplete', 'too_many_uploads', 'upload_space', 'disk_full', 'slow_down', 'too_many_attempts',
])

export function canRetry(code: string): boolean {
  return RETRYABLE.has(code)
}

type Config = {
  /** Up to this size a file goes in the one request with others. */
  small: number
  /** The largest piece sent at once (the server may propose less). */
  piece: number
  /** Files in one request. */
  batchFiles: number
  /** Bytes in one request. */
  batchBytes: number
  /** Waits before a new try after a break, in milliseconds; as many entries as there are tries. */
  waits: number[]
  /** Waiting, so that a test need not. */
  sleep: (ms: number) => Promise<void>
}

const MB = 1024 * 1024
export const DEFAULTS: Config = {
  small: 8 * MB,
  piece: 4 * MB,
  batchFiles: 10,
  batchBytes: 32 * MB,
  waits: [1000, 3000, 8000, 20000],
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
}

/** A break the server did not cause, which another try may mend. */
function transient(error: unknown): boolean {
  return error instanceof ApiError && (error.code === 'network' || error.status >= 500 || error.code === 'busy' || error.code === 'upload_busy')
}

export class Uploader {
  private entries: Entry[] = []
  private files = new Map<number, File>()
  private ids = new Map<number, string>()
  private hashes = new Map<number, string>()
  private controllers = new Map<number, AbortController>()
  private listeners = new Set<() => void>()
  private running = false
  private next = 1
  private tally: Summary = { done: 0, exists: 0, failed: 0, duplicates: 0, vaults: [], failures: [] }
  private snapshot_: readonly Entry[] = []
  private config: Config
  private idleListeners = new Set<(summary: Summary) => void>()

  constructor(config: Partial<Config> = {}) {
    this.config = { ...DEFAULTS, ...config }
  }

  /** Told when the queue has gone through everything it had: what came of it. */
  whenIdle(listener: (summary: Summary) => void): () => void {
    this.idleListeners.add(listener)
    return () => this.idleListeners.delete(listener)
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  /** The entries as they stand; a new array after every change (for `useSyncExternalStore`). */
  getSnapshot = (): readonly Entry[] => this.snapshot_

  private emit(): void {
    this.snapshot_ = this.entries.map((entry) => ({ ...entry }))
    for (const listener of this.listeners) listener()
  }

  private update(id: number, change: Partial<Entry>): void {
    const entry = this.entries.find((item) => item.id === id)
    if (!entry) return
    Object.assign(entry, change)
    this.emit()
  }

  add(files: File[], target: UploadTarget = {}): void {
    for (const file of files) {
      const id = this.next++
      this.files.set(id, file)
      this.entries.push({ id, name: file.name, size: file.size, chunked: file.size > this.config.small, phase: 'waiting', sent: 0, document: null, vaultId: null, duplicate: null, error: null, target })
    }
    this.emit()
    void this.run()
  }

  /** A paused upload goes on from where the server stands. */
  resume(id: number): void {
    const entry = this.entries.find((item) => item.id === id)
    if (!entry || entry.phase !== 'paused') return
    this.update(id, { phase: 'waiting', error: null })
    void this.run()
  }

  /** A failed upload starts anew. */
  retry(id: number): void {
    const entry = this.entries.find((item) => item.id === id)
    if (!entry || entry.phase !== 'failed' || !this.files.has(id) || !canRetry(entry.error?.code ?? '')) return
    this.ids.delete(id)
    this.update(id, { phase: 'waiting', error: null, sent: 0, document: null, vaultId: null, duplicate: null })
    void this.run()
  }

  /** Stops an upload and drops what arrived. */
  cancel(id: number): void {
    const entry = this.entries.find((item) => item.id === id)
    if (!entry || !['waiting', 'hashing', 'sending', 'finishing', 'paused'].includes(entry.phase)) return
    this.controllers.get(id)?.abort()
    const uploadId = this.ids.get(id)
    if (uploadId && entry.phase !== 'finishing') void uploadsApi.cancel(uploadId).catch(() => undefined)
    this.ids.delete(id)
    this.files.delete(id)
    this.update(id, { phase: 'cancelled', error: null })
  }

  /** Takes the finished, failed and cancelled ones off the list. */
  clear(): void {
    this.entries = this.entries.filter((entry) => ['waiting', 'hashing', 'sending', 'finishing', 'paused'].includes(entry.phase))
    this.emit()
  }

  get busy(): boolean {
    return this.entries.some((entry) => ['waiting', 'hashing', 'sending', 'finishing'].includes(entry.phase))
  }

  // -- The run: one request at a time ------------------------------------------------------------------------------

  private async run(): Promise<void> {
    if (this.running) return
    this.running = true
    try {
      for (;;) {
        const waiting = this.entries.filter((entry) => entry.phase === 'waiting')
        if (waiting.length === 0) break
        const first = waiting[0]
        if (first.size <= this.config.small) await this.sendTogether(this.group(waiting))
        else await this.sendInPieces(first)
      }
    } finally {
      this.running = false
    }
    const summary = this.tally
    this.tally = { done: 0, exists: 0, failed: 0, duplicates: 0, vaults: [], failures: [] }
    if (summary.done + summary.exists + summary.failed > 0) for (const listener of this.idleListeners) listener(summary)
  }

  /** The small files that wait, from the first on, as many as one request takes (all going to the same place). */
  private group(waiting: Entry[]): Entry[] {
    const group: Entry[] = []
    let bytes = 0
    const same = (a: UploadTarget, b: UploadTarget) => (a.vaultId ?? null) === (b.vaultId ?? null) && (a.source ?? null) === (b.source ?? null)
    for (const entry of waiting) {
      if (entry.size > this.config.small || (group.length > 0 && !same(group[0].target ?? {}, entry.target ?? {}))) break
      if (group.length >= this.config.batchFiles || bytes + entry.size > this.config.batchBytes) break
      group.push(entry)
      bytes += entry.size
    }
    return group
  }

  private async sendTogether(group: Entry[]): Promise<void> {
    const controller = new AbortController()
    for (const entry of group) {
      this.controllers.set(entry.id, controller)
      entry.phase = 'sending'
    }
    this.emit()
    const failAll = (error: unknown) => {
      if (error instanceof ApiError && error.code === 'cancelled') return
      const items = error instanceof ApiError && Array.isArray(error.values.items) ? (error.values.items as UploadResult[]) : null
      group.forEach((entry, index) => {
        if (this.entries.find((item) => item.id === entry.id)?.phase !== 'sending') return
        const item = items?.[index]
        const code = item?.error?.code ?? (error instanceof ApiError ? error.code : 'internal_error')
        const values = item?.error?.max_mb !== undefined ? { max_mb: item.error.max_mb } : items || !(error instanceof ApiError) ? {} : error.values
        this.fail(entry.id, code, values)
      })
    }
    try {
      const answer = await uploadsApi.send(group.map((entry) => this.files.get(entry.id)!).filter(Boolean), controller.signal, group[0].target ?? {})
      group.forEach((entry, index) => {
        if (this.entries.find((item) => item.id === entry.id)?.phase !== 'sending') return
        const item = answer.items[index]
        if (item?.status === 'accepted' && item.document) {
          this.tally.done += 1
          if (item.duplicate) this.tally.duplicates += 1
          this.tally.vaults.push(item.document.vault_id)
          this.update(entry.id, {
            phase: 'done', sent: entry.size, document: { id: item.document.id, title: item.document.title }, vaultId: item.document.vault_id,
            duplicate: item.duplicate ? { title: item.duplicate.title, kind: item.duplicate.kind } : null,
          })
          this.files.delete(entry.id)
        } else {
          this.fail(entry.id, item?.error?.code ?? 'internal_error', item?.error?.max_mb !== undefined ? { max_mb: item.error.max_mb } : {})
        }
      })
    } catch (error) {
      failAll(error)
    } finally {
      for (const entry of group) this.controllers.delete(entry.id)
    }
  }

  private fail(id: number, code: string, values: Record<string, unknown> = {}): void {
    this.tally.failed += 1
    const entry = this.entries.find((item) => item.id === id)
    // Named one by one up to a limit (a run of a thousand refused files is counted past it).
    if (entry && this.tally.failures.length < MAX_NAMED) this.tally.failures.push({ name: entry.name, code, values })
    this.update(id, { phase: 'failed', error: { code, values } })
  }

  private still(id: number, phases: Phase[]): boolean {
    const entry = this.entries.find((item) => item.id === id)
    return !!entry && phases.includes(entry.phase)
  }

  private async sendInPieces(entry: Entry): Promise<void> {
    const file = this.files.get(entry.id)
    if (!file) {
      this.fail(entry.id, 'internal_error')
      return
    }
    const controller = new AbortController()
    this.controllers.set(entry.id, controller)
    const signal = controller.signal
    try {
      let uploadId = this.ids.get(entry.id)
      if (!uploadId) {
        this.update(entry.id, { phase: 'hashing', sent: 0 })
        let hash = this.hashes.get(entry.id)
        if (!hash) {
          hash = await sha256OfFile(file, (done) => this.still(entry.id, ['hashing']) && this.update(entry.id, { sent: done }), signal)
          this.hashes.set(entry.id, hash)
        }
        this.update(entry.id, { phase: 'sending', sent: 0 })
        const started = await this.tries(entry.id, () => uploadsApi.start({ name: file.name, size: file.size }, hash!, signal, entry.target ?? {}), signal)
        if (started.exists && started.document) {
          this.tally.exists += 1
          this.update(entry.id, { phase: 'exists', sent: entry.size, document: { id: started.document.id, title: started.document.title } })
          this.files.delete(entry.id)
          return
        }
        uploadId = started.upload!.id
        this.ids.set(entry.id, uploadId)
        await this.pieces(entry.id, file, started.upload!, signal)
      } else {
        this.update(entry.id, { phase: 'sending' })
        await this.pieces(entry.id, file, await this.tries(entry.id, () => uploadsApi.state(uploadId!, signal), signal), signal)
      }
      if (!this.still(entry.id, ['sending'])) return
      this.update(entry.id, { phase: 'finishing', sent: entry.size })
      const finished = await this.tries(entry.id, () => uploadsApi.finish(uploadId!, signal), signal)
      this.tally.done += 1
      this.tally.vaults.push(finished.document.vault_id)
      if (finished.duplicate) this.tally.duplicates += 1
      this.update(entry.id, {
        phase: 'done', document: { id: finished.document.id, title: finished.document.title }, vaultId: finished.document.vault_id,
        duplicate: finished.duplicate ? { title: finished.duplicate.title, kind: finished.duplicate.kind } : null,
      })
      this.files.delete(entry.id)
      this.ids.delete(entry.id)
      this.hashes.delete(entry.id)
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return
      if (error instanceof ApiError && error.code === 'cancelled') return
      if (error instanceof ApiError && (error.code === 'upload_expired' || error.status === 404)) this.ids.delete(entry.id)
      if (transient(error) && this.ids.has(entry.id)) {
        // Still reachable in principle, and the server keeps what arrived: the upload waits to be resumed.
        this.update(entry.id, { phase: 'paused', error: { code: error instanceof ApiError ? error.code : 'network', values: {} } })
      } else {
        this.fail(entry.id, error instanceof ApiError ? error.code : 'internal_error', error instanceof ApiError ? error.values : {})
      }
    } finally {
      this.controllers.delete(entry.id)
    }
  }

  /** Sends the pieces from where the server stands to the end. After a break that another try may mend it waits, asks the
   * server how far it is, and goes on from there; the answer of a piece that was lost on the way may have been taken. */
  private async pieces(id: number, file: File, state: UploadState, signal: AbortSignal): Promise<void> {
    const uploadId = state.id
    let received = state.received
    const size = Math.min(this.config.piece, state.chunk_size || this.config.piece, state.max_piece || this.config.piece)
    this.update(id, { sent: received })
    let failures = 0
    while (received < file.size) {
      if (!this.still(id, ['sending'])) return
      const end = Math.min(received + size, file.size)
      try {
        received = (await uploadsApi.piece(uploadId, received, file.slice(received, end), signal)).received
        failures = 0
      } catch (error) {
        if (error instanceof ApiError && error.code === 'offset_mismatch' && typeof error.values.received === 'number') {
          received = error.values.received
        } else {
          if (!transient(error) || failures >= this.config.waits.length || signal.aborted) throw error
          await this.config.sleep(this.config.waits[failures])
          failures += 1
          if (signal.aborted || !this.still(id, ['sending'])) throw new ApiError(0, 'cancelled')
          try {
            received = (await uploadsApi.state(uploadId, signal)).received
          } catch (inner) {
            // The server is not back yet: the next piece is tried at the old offset and the server corrects it.
            if (!transient(inner)) throw inner
          }
        }
      }
      this.update(id, { sent: received })
    }
  }

  /** Does the work; after a break that another try may mend it waits and repeats. */
  private async tries<T>(id: number, work: () => Promise<T>, signal: AbortSignal): Promise<T> {
    for (let attempt = 0; ; attempt++) {
      try {
        return await work()
      } catch (error) {
        if (!transient(error) || attempt >= this.config.waits.length || signal.aborted) throw error
        await this.config.sleep(this.config.waits[attempt])
        if (signal.aborted || !this.still(id, ['sending', 'finishing'])) throw new ApiError(0, 'cancelled')
      }
    }
  }
}
