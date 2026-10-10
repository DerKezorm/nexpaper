import { afterEach, describe, expect, it, vi } from 'vitest'

import { copyText } from './copy'

describe('copyText', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('takes the clipboard API in a secure context', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    vi.stubGlobal('isSecureContext', true)
    expect(await copyText('ABCD-EFGH-JKLM')).toBe(true)
    expect(writeText).toHaveBeenCalledWith('ABCD-EFGH-JKLM')
  })

  it('falls back to the copy command over plain http, where the API is missing', async () => {
    vi.stubGlobal('navigator', {})
    vi.stubGlobal('isSecureContext', false)
    let copied = ''
    const exec = vi.fn(() => {
      copied = document.querySelector('textarea')?.value ?? ''
      return true
    })
    Object.defineProperty(document, 'execCommand', { value: exec, configurable: true })
    expect(await copyText('https://paper.example.com/invite/abc')).toBe(true)
    expect(exec).toHaveBeenCalledWith('copy')
    expect(copied).toBe('https://paper.example.com/invite/abc')
    expect(document.querySelector('textarea')).toBeNull()
  })

  it('says so when nothing worked', async () => {
    vi.stubGlobal('navigator', {})
    vi.stubGlobal('isSecureContext', false)
    Object.defineProperty(document, 'execCommand', { value: () => false, configurable: true })
    expect(await copyText('x')).toBe(false)
  })
})
