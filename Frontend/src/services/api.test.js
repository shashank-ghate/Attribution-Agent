import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from './api'

describe('apiRequest', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn()
  })

  it('returns a successful response', async () => {
    const response = { ok: true }
    fetch.mockResolvedValue(response)
    await expect(apiRequest('/health')).resolves.toBe(response)
    expect(fetch).toHaveBeenCalledWith('/api/health', {})
  })

  it('uses the backend detail for JSON errors', async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 409,
      json: vi.fn().mockResolvedValue({ detail: 'A job is already running' }),
    })
    await expect(apiRequest('/jobs')).rejects.toThrow('A job is already running')
  })

  it('uses an HTTP fallback for proxy and non-JSON errors', async () => {
    fetch.mockResolvedValue({
      ok: false,
      status: 502,
      json: vi.fn().mockRejectedValue(new SyntaxError('not JSON')),
    })
    await expect(apiRequest('/health')).rejects.toThrow('Request failed (502)')
  })

  it('propagates a network failure without hiding its message', async () => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(apiRequest('/health')).rejects.toThrow('Failed to fetch')
  })
})
