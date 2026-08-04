import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import * as reports from './services/reportService'

vi.mock('./services/reportService', async () => {
  const actual = await vi.importActual('./services/reportService')
  return {
    ...actual,
    getHealth: vi.fn(),
    getGoogleConfig: vi.fn(),
    getMoEngageSession: vi.fn(),
    connectGoogleSheet: vi.fn(),
  }
})

describe('App startup', () => {
  beforeEach(() => {
    reports.getHealth.mockResolvedValue({
      status: 'ok',
      moengage_mode: 'browser',
      configured_brands: ['Aldo'],
      mock_writes_enabled: false,
    })
    reports.getGoogleConfig.mockResolvedValue({
      configured: true,
      service_account_email: 'agent@example.test',
      spreadsheet_url: '',
      worksheet_name: 'Mastersheet',
    })
    reports.getMoEngageSession.mockResolvedValue({
      status: 'connected',
      message: 'Connected',
      profile_id: 'railway',
      profiles: ['railway'],
      login_url: 'https://browser.example.test',
    })
  })

  it('shows both backend and MoEngage readiness after startup', async () => {
    render(<App />)
    expect(await screen.findByText('Backend online')).toBeInTheDocument()
    expect(screen.getByText('CONNECTED')).toBeInTheDocument()
    expect(screen.getByText('BROWSER MODE')).toBeInTheDocument()
  })

  it('shows an actionable startup error without crashing the page', async () => {
    reports.getHealth.mockRejectedValue(new Error('Backend unavailable'))
    render(<App />)
    expect(await screen.findByText('Backend unavailable')).toBeInTheDocument()
    expect(screen.getByText('Choose campaigns. Review. Run.')).toBeInTheDocument()
  })

  it('automatically reconnects the configured production sheet', async () => {
    reports.getGoogleConfig.mockResolvedValue({
      configured: true,
      service_account_email: 'agent@example.test',
      spreadsheet_url: 'https://docs.google.com/spreadsheets/d/test-sheet',
      worksheet_name: 'Mastersheet',
    })
    reports.connectGoogleSheet.mockResolvedValue({
      connection_id: 'connection-1',
      spreadsheet_title: 'Agent Apparel Master Sheet_2026',
      worksheet_title: 'Mastersheet',
      row_count: 2552,
      brands: ['Aldo'],
      channels: ['SMS'],
      sent_dates: ['2026-08-02'],
      warnings: [],
      warning_sent_date_from: '2026-07-27',
      warning_sent_date_to: '2026-08-02',
    })
    render(<App />)
    expect(await screen.findByText('Agent Apparel Master Sheet_2026')).toBeInTheDocument()
    await waitFor(() => expect(reports.connectGoogleSheet).toHaveBeenCalledOnce())
  })

  it('opens the Railway login browser directly without a CDP API call', async () => {
    const loginWindow = {}
    window.open = vi.fn().mockReturnValue(loginWindow)
    render(<App />)
    const button = await screen.findByRole('button', {
      name: 'Open Railway login browser',
    })
    fireEvent.click(button)
    expect(window.open).toHaveBeenCalledWith(
      'https://browser.example.test',
      '_blank',
    )
    expect(loginWindow.opener).toBeNull()
  })
})
