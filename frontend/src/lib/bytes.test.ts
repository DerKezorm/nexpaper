/** A size as a person reads it: units of 1024, one decimal from GB up unless the number is round. */
import { formatBytes } from './bytes'

describe('formatBytes', () => {
  it('writes the units in 1024 steps, in the separator of the language', () => {
    expect(formatBytes(0, 'de')).toBe('0 B')
    expect(formatBytes(1536, 'en')).toBe('2 KB')
    expect(formatBytes(52428800, 'en')).toBe('50 MB')
    expect(formatBytes(1288490189, 'de')).toBe('1,2 GB')
    expect(formatBytes(1288490189, 'en')).toBe('1.2 GB')
  })

  it('counts as a disk does when asked to, for the size of files', () => {
    expect(formatBytes(1.2e9, 'de', 1000)).toBe('1,2 GB')
    expect(formatBytes(900e6, 'de', 1000)).toBe('900 MB')
    expect(formatBytes(84e6, 'en', 1000)).toBe('84 MB')
    expect(formatBytes(1.2e9, 'de')).toBe('1,1 GB')
  })

  it('leaves out the decimal of a round number and never goes below zero', () => {
    expect(formatBytes(5 * 1024 ** 3, 'de')).toBe('5 GB')
    expect(formatBytes(-5, 'de')).toBe('0 B')
  })
})
