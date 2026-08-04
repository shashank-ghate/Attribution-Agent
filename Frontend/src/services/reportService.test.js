import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as service from './reportService'

function jsonResponse(payload = {}) {
  return { ok: true, json: vi.fn().mockResolvedValue(payload) }
}

describe('reportService', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
  })

  it('sends the exact safe job payload', async () => {
    await service.startReport('sheet-1', {
      overwriteExisting: false,
      brands: ['Aldo'],
      channels: ['SMS'],
      sentDateFrom: '2026-08-01',
      sentDateTo: '2026-08-02',
      agiplAttributionBrand: '',
    })
    const [, options] = fetch.mock.calls[0]
    expect(JSON.parse(options.body)).toEqual({
      sheet_connection_id: 'sheet-1',
      overwrite_existing: false,
      brands: ['Aldo'],
      channels: ['SMS'],
      sent_date_from: '2026-08-01',
      sent_date_to: '2026-08-02',
      agipl_attribution_brand: null,
    })
  })

  it('encodes all campaign preview filters', async () => {
    await service.getCampaignPreview('sheet/id', {
      brands: ['Aldo', 'BBW'],
      channels: ['SMS', 'WhatsApp'],
      sentDateFrom: '2026-08-01',
      sentDateTo: '2026-08-02',
    })
    const url = new URL(fetch.mock.calls[0][0], 'https://example.test')
    expect(url.pathname).toBe('/api/google/connections/sheet/id/campaigns')
    expect(url.searchParams.getAll('brands')).toEqual(['Aldo', 'BBW'])
    expect(url.searchParams.getAll('channels')).toEqual(['SMS', 'WhatsApp'])
    expect(url.searchParams.get('limit')).toBe('100')
  })

  it.each([
    ['getHealth', () => service.getHealth(), '/api/health', 'GET'],
    ['getReport', () => service.getReport('job-1'), '/api/jobs/job-1', 'GET'],
    ['cancelReport', () => service.cancelReport('job-1'), '/api/jobs/job-1/cancel', 'POST'],
    ['retryFailedReport', () => service.retryFailedReport('job-1'), '/api/jobs/job-1/retry-failed', 'POST'],
    ['getGoogleConfig', () => service.getGoogleConfig(), '/api/google/config', 'GET'],
    ['getMoEngageSession', () => service.getMoEngageSession(), '/api/moengage/session', 'GET'],
  ])('%s calls the correct endpoint', async (_name, call, url, method) => {
    await call()
    const [actualUrl, options = {}] = fetch.mock.calls[0]
    expect(actualUrl).toBe(url)
    expect(options.method || 'GET').toBe(method)
  })

  it('does not send an absent MoEngage password', async () => {
    await service.startMoEngageSession('railway', '')
    const body = JSON.parse(fetch.mock.calls[0][1].body)
    expect(body).toEqual({ profile_id: 'railway' })
  })

  it('builds a same-origin CSV URL', () => {
    expect(service.getResultsDownloadUrl('job-1')).toBe('/api/jobs/job-1/results.csv')
  })
})
