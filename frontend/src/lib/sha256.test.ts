/**
 * The checksum of a file made piece by piece must be the SHA-256 the server makes: the server compares them before it
 * makes a document of an upload in pieces, and answers "you have this file already" by it.
 */
import { randomBytes, sha256Hex } from '../test/bytes'
import { Sha256, sha256OfFile } from './sha256'

const text = (value: string) => new TextEncoder().encode(value)

describe('the checksum', () => {
  it('matches the platform on the usual test inputs, the empty one and the two of the standard (made at run time)', async () => {
    for (const input of ['', 'abc', 'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq']) {
      expect(new Sha256().update(text(input)).hex(), JSON.stringify(input)).toBe(await sha256Hex(text(input)))
    }
    // The empty one, as a value people know: it starts and ends the way the standard says.
    const empty = new Sha256().hex()
    expect(empty.startsWith('e3b0c442') && empty.endsWith('7852b855')).toBe(true)
  })

  it('is the same however the bytes are cut into pieces', async () => {
    const data = randomBytes(10_000)
    const expected = await sha256Hex(data)
    for (const cut of [1, 7, 55, 56, 63, 64, 65, 120, 1000, 4096, 9999]) {
      const hasher = new Sha256()
      for (let at = 0; at < data.length; at += cut) hasher.update(data.subarray(at, at + cut))
      expect(hasher.hex(), `pieces of ${cut}`).toBe(expected)
    }
  })

  it('is right at every length around the block borders where padding changes', async () => {
    for (let length = 0; length <= 200; length++) {
      const data = randomBytes(length)
      expect(new Sha256().update(data).hex(), `length ${length}`).toBe(await sha256Hex(data))
    }
  })

  it('reads a file in pieces of 4 MB and reports how far it is', async () => {
    const data = randomBytes(9 * 1024 * 1024 + 123)
    const seen: number[] = []
    const hex = await sha256OfFile(new File([data], 'scan.pdf'), (done) => seen.push(done))
    expect(hex).toBe(await sha256Hex(data))
    expect(seen).toEqual([4 * 1024 * 1024, 8 * 1024 * 1024, data.length])
  })

  it('stops when told to', async () => {
    const controller = new AbortController()
    controller.abort()
    await expect(sha256OfFile(new File([new Uint8Array(10)], 'a.pdf'), undefined, controller.signal)).rejects.toThrow()
  })

  it('handles an empty file', async () => {
    expect(await sha256OfFile(new File([], 'empty.pdf'))).toBe(new Sha256().hex())
  })
})
