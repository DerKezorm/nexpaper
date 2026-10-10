/** Bytes for the tests: random ones, their SHA-256 by the platform's own implementation, and a few comparisons. */

export function randomBytes(length: number): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(length)
  for (let at = 0; at < length; at += 65536) crypto.getRandomValues(out.subarray(at, Math.min(at + 65536, length)))
  return out
}

export async function sha256Hex(data: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', data as BufferSource)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export function concat(parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0))
  let at = 0
  for (const part of parts) {
    out.set(part, at)
    at += part.length
  }
  return out
}

export function same(a: Uint8Array, b: Uint8Array): boolean {
  return a.length === b.length && a.every((byte, index) => byte === b[index])
}
