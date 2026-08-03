import { API_BASE, apiRequest } from './api'

export const getHealth = async () => (await apiRequest('/health')).json()

export async function startReport(sheetConnectionId, options) {
  return (await apiRequest('/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sheet_connection_id: sheetConnectionId,
      overwrite_existing: options.overwriteExisting,
      brands: options.brands,
      channels: options.channels,
      sent_date_from: options.sentDateFrom,
      sent_date_to: options.sentDateTo,
      agipl_attribution_brand: options.agiplAttributionBrand || null,
    }),
  })).json()
}

export const getReport = async (jobId) => (await apiRequest(`/jobs/${jobId}`)).json()
export const getResultsDownloadUrl = (jobId) => `${API_BASE}/jobs/${jobId}/results.csv`
export const cancelReport = async (jobId) => (await apiRequest(`/jobs/${jobId}/cancel`, { method: 'POST' })).json()
export const retryFailedReport = async (jobId) => (await apiRequest(`/jobs/${jobId}/retry-failed`, { method: 'POST' })).json()
export const getGoogleConfig = async () => (await apiRequest('/google/config')).json()
export async function uploadGoogleCredentials(file) {
  const body = new FormData()
  body.append('credential', file)
  return (await apiRequest('/google/credentials', { method: 'POST', body })).json()
}
export async function connectGoogleSheet(spreadsheetUrl, worksheetName) {
  return (await apiRequest('/google/connect', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ spreadsheet_url: spreadsheetUrl, worksheet_name: worksheetName }),
  })).json()
}
export async function getCampaignPreview(connectionId, filters) {
  const params = new URLSearchParams({
    sent_date_from: filters.sentDateFrom,
    sent_date_to: filters.sentDateTo,
    limit: '100',
  })
  filters.brands.forEach((brand) => params.append('brands', brand))
  filters.channels.forEach((channel) => params.append('channels', channel))
  return (await apiRequest(`/google/connections/${connectionId}/campaigns?${params}`)).json()
}
export const getMoEngageSession = async () => (await apiRequest('/moengage/session')).json()
export const startMoEngageSession = async (profileId, password) => (await apiRequest('/moengage/session/start', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ profile_id: profileId || 'default', password }),
})).json()
export const resetMoEngageSession = async (profileId, password) => (await apiRequest('/moengage/session/reset', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ profile_id: profileId || 'default', password }),
})).json()
