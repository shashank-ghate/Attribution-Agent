import { useEffect, useMemo, useState } from 'react'
import './App.css'
import {
  cancelReport,
  connectGoogleSheet,
  getCampaignPreview,
  getGoogleConfig,
  getHealth,
  getMoEngageSession,
  getReport,
  getResultsDownloadUrl,
  retryFailedReport,
  resetMoEngageSession,
  startMoEngageSession,
  startReport,
  uploadGoogleCredentials,
} from './services/reportService'

const terminalStates = new Set(['completed', 'failed', 'cancelled'])
const moengageDashboardUrl = import.meta.env.VITE_MOENGAGE_DASHBOARD_URL || 'https://dashboard.moengage.com/'

function Icon({ name, className = 'size-5' }) {
  const paths = {
    sheet: <><path d="M6 2h9l4 4v16H6z"/><path d="M15 2v5h5M9 11h7M9 15h7M9 19h4"/></>,
    spark: <><path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></>,
    check: <path d="M5 12l4 4L19 6"/>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
    close: <path d="M6 6l12 12M18 6L6 18"/>,
    refresh: <><path d="M20 7h-5V2"/><path d="M20 7a9 9 0 10.5 9"/></>,
    browser: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01"/></>,
    link: <><path d="M10 13a5 5 0 007 0l2-2a5 5 0 00-7-7l-1 1"/><path d="M14 11a5 5 0 00-7 0l-2 2a5 5 0 007 7l1-1"/></>,
    brand: <><path d="M20 13l-7 7-9-9V4h7z"/><path d="M8.5 8.5h.01"/></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/></>,
    channel: <><path d="M4 5h16v11H8l-4 4z"/><path d="M8 9h8M8 12h5"/></>,
    upload: <><path d="M12 16V4m-5 5 5-5 5 5"/><path d="M4 15v5h16v-5"/></>,
    download: <><path d="M12 4v12m-5-5 5 5 5-5"/><path d="M4 20h16"/></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/></>,
  }
  return <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

function Badge({ children, tone = 'slate' }) {
  const tones = {
    slate: 'bg-slate-100 text-slate-600',
    blue: 'bg-blue-50 text-blue-700',
    green: 'bg-emerald-50 text-emerald-700',
    red: 'bg-red-50 text-red-700',
    amber: 'bg-amber-50 text-amber-700',
  }
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold ${tones[tone]}`}>{children}</span>
}

function ChoicePills({ values, selected, onChange, disabled = false }) {
  function toggle(value) {
    onChange(selected.includes(value) ? selected.filter((item) => item !== value) : [...selected, value])
  }
  return <div className="flex flex-wrap gap-2">
    {values.map((value) => {
      const active = selected.includes(value)
      return <button
        key={value}
        type="button"
        disabled={disabled}
        aria-pressed={active}
        onClick={() => toggle(value)}
        className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-2 text-xs font-semibold transition ${active ? 'border-blue-600 bg-blue-600 text-white shadow-sm' : 'border-slate-200 bg-white text-slate-600 hover:border-blue-300 hover:text-blue-700'} disabled:cursor-not-allowed disabled:opacity-60`}
      >
        {active && <Icon name="check" className="size-3.5" />}{value}
      </button>
    })}
  </div>
}

function LockedWorkflow({ reason }) {
  return <>
    <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-col justify-between gap-3 border-b border-slate-100 pb-5 sm:flex-row sm:items-center">
        <div><div className="flex items-center gap-2"><span className="grid size-7 place-items-center rounded-lg bg-violet-50 text-xs font-bold text-violet-700">03</span><h2 className="text-base font-semibold">Choose campaigns to process</h2></div><p className="mt-2 text-xs text-slate-500">The filters stay visible so you always know what becomes available after setup.</p></div>
        <Badge tone="amber"><Icon name="lock" className="mr-1 size-3" />SETUP REQUIRED</Badge>
      </div>
      <div className="relative mt-5">
        <div className="grid gap-4 opacity-55 xl:grid-cols-3" aria-hidden="true">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5"><div className="mb-4 flex items-center gap-2 text-sm font-semibold"><Icon name="brand" className="size-4 text-blue-700" />Brand</div><ChoicePills values={["ALDO", "VS", "BBW"]} selected={[]} onChange={() => {}} disabled /></div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5"><div className="mb-4 flex items-center gap-2 text-sm font-semibold"><Icon name="calendar" className="size-4 text-blue-700" />Sent date range</div><div className="grid grid-cols-2 gap-2"><input type="date" disabled className="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm" /><input type="date" disabled className="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm" /></div></div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5"><div className="mb-4 flex items-center gap-2 text-sm font-semibold"><Icon name="channel" className="size-4 text-blue-700" />Channel</div><ChoicePills values={["WhatsApp", "SMS", "RCS"]} selected={[]} onChange={() => {}} disabled /></div>
        </div>
        <div className="mt-4 flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-900"><Icon name="lock" className="size-4 shrink-0" /><span>{reason}</span></div>
      </div>
    </section>
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-start gap-4"><div className="grid size-11 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700"><Icon name="download" /></div><div><div className="flex items-center gap-2"><h2 className="text-sm font-semibold">Results & output</h2><Badge tone="slate">WAITING FOR SETUP</Badge></div><p className="mt-2 max-w-2xl text-xs leading-5 text-slate-500">Successful results will appear here live, write automatically to the correct AA–AF cells, and remain downloadable as a CSV report.</p></div></div>
    </section>
  </>
}

const formatNumber = (value) => value == null ? '—' : new Intl.NumberFormat('en-IN').format(value)
const formatCurrency = (value) => value == null ? '—' : new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
const formatDate = (value) => value ? new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(`${value}T00:00:00`)) : 'Not selected'
const normalizeMoEngageProfile = (value) => {
  const normalized = (value || 'default').trim().toLowerCase().replace(/[^a-z0-9@._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '')
  return normalized || 'default'
}

function App() {
  const [health, setHealth] = useState(null)
  const [googleConfig, setGoogleConfig] = useState(null)
  const [moengage, setMoengage] = useState({ status: 'disconnected', message: '' })
  const [moengageProfile, setMoengageProfile] = useState('default')
  const [moengagePassword, setMoengagePassword] = useState('')
  const [sheetUrl, setSheetUrl] = useState('')
  const [worksheet, setWorksheet] = useState('Mastersheet')
  const [sheet, setSheet] = useState(null)
  const [selectedBrands, setSelectedBrands] = useState([])
  const [agiplAttributionBrand, setAgiplAttributionBrand] = useState('')
  const [selectedChannels, setSelectedChannels] = useState([])
  const [sentDateFrom, setSentDateFrom] = useState('')
  const [sentDateTo, setSentDateTo] = useState('')
  const [campaignPreview, setCampaignPreview] = useState(null)
  const [job, setJob] = useState(null)
  const [overwrite, setOverwrite] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  function setConnectedSheet(data) {
    setSheet(data)
    setSelectedBrands([])
    setAgiplAttributionBrand('')
    setSelectedChannels([])
    setSentDateFrom(data.warning_sent_date_from || '')
    setSentDateTo(data.warning_sent_date_to || '')
    setCampaignPreview(null)
    setJob(null)
  }

  useEffect(() => {
    Promise.all([getHealth(), getGoogleConfig(), getMoEngageSession()])
      .then(async ([healthData, googleData, moeData]) => {
        setHealth(healthData)
        setGoogleConfig(googleData)
        setMoengage(moeData)
        setMoengageProfile(moeData.profile_id || 'default')
        setSheetUrl(googleData.spreadsheet_url || '')
        setWorksheet(googleData.worksheet_name || 'Mastersheet')
        if (googleData.configured && googleData.spreadsheet_url) {
          setBusy('sheet')
          try {
            setConnectedSheet(await connectGoogleSheet(googleData.spreadsheet_url, googleData.worksheet_name || 'Mastersheet'))
          } catch (err) {
            setError(err.message)
          } finally {
            setBusy('')
          }
        }
      })
      .catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    if (!job?.job_id || terminalStates.has(job.status)) return undefined
    const timer = window.setInterval(async () => {
      try { setJob(await getReport(job.job_id)) } catch (err) { setError(err.message) }
    }, 900)
    return () => window.clearInterval(timer)
  }, [job?.job_id, job?.status])

  useEffect(() => {
    if (!sheet || !selectedBrands.length || !selectedChannels.length || !sentDateFrom || !sentDateTo || sentDateFrom > sentDateTo || job) {
      return undefined
    }
    let cancelled = false
    const requestKey = JSON.stringify([selectedBrands, selectedChannels, sentDateFrom, sentDateTo])
    getCampaignPreview(sheet.connection_id, { brands: selectedBrands, channels: selectedChannels, sentDateFrom, sentDateTo })
      .then((data) => { if (!cancelled) setCampaignPreview({ ...data, requestKey }) })
      .catch((err) => { if (!cancelled) setError(err.message) })
    return () => { cancelled = true }
  }, [sheet, selectedBrands, selectedChannels, sentDateFrom, sentDateTo, job])

  const hasAgipl = selectedBrands.some((brand) => brand.toLowerCase() === 'agipl')
  const agiplBrandOptions = (sheet?.brands || []).filter((brand) => brand.toLowerCase() !== 'agipl')

  function updateSelectedBrands(brands) {
    setSelectedBrands(brands)
    if (!brands.some((brand) => brand.toLowerCase() === 'agipl')) {
      setAgiplAttributionBrand('')
    }
  }

  const dateRangeValid = Boolean(sentDateFrom && sentDateTo && sentDateFrom <= sentDateTo)
  const filtersComplete = selectedBrands.length > 0 && selectedChannels.length > 0 && dateRangeValid && (!hasAgipl || Boolean(agiplAttributionBrand))
  const filterKey = JSON.stringify([selectedBrands, selectedChannels, sentDateFrom, sentDateTo])
  const previewBusy = filtersComplete && campaignPreview?.requestKey !== filterKey
  const rows = job?.results?.length ? job.results : filtersComplete && !previewBusy ? campaignPreview?.preview || [] : []
  const matchingRows = filtersComplete && !previewBusy ? campaignPreview?.row_count || 0 : 0
  const selectedMoengageProfile = normalizeMoEngageProfile(moengageProfile)
  const moengageMode = health?.moengage_mode
  const apiConfigured = moengageMode === 'api' && Boolean(health?.configured_brands?.length)
  const browserConnected = moengageMode === 'browser' && moengage.status === 'connected' && moengage.profile_id === selectedMoengageProfile
  const mockEnabled = moengageMode === 'mock' && health?.mock_writes_enabled
  const isMoeReady = apiConfigured || browserConnected || mockEnabled
  const modeLabel = moengageMode === 'api' ? (apiConfigured ? 'API READY' : 'API SETUP') : moengageMode === 'mock' ? (mockEnabled ? 'DEMO' : 'DEMO DISABLED') : 'BROWSER MODE'
  const canRun = sheet && isMoeReady && !job && filtersComplete && matchingRows > 0 && !previewBusy
  const earliestSentDate = sheet?.sent_dates?.length ? sheet.sent_dates[sheet.sent_dates.length - 1] : ''
  const latestSentDate = sheet?.sent_dates?.[0] || ''
  const summary = useMemo(() => ({
    campaigns: job ? job.total_rows : matchingRows,
    completed: job?.successful_rows || 0,
    issues: (job?.failed_rows || 0) + (sheet?.warnings?.length || 0),
  }), [sheet, job, matchingRows])

  async function connectSheet(event) {
    event.preventDefault()
    setError('')
    setBusy('sheet')
    try { setConnectedSheet(await connectGoogleSheet(sheetUrl, worksheet)) }
    catch (err) { setError(err.message) }
    finally { setBusy('') }
  }

  async function installGoogleCredential(event) {
    const file = event.target.files?.[0]
    if (!file) return
    setError('')
    setBusy('credential')
    try {
      setGoogleConfig(await uploadGoogleCredentials(file))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
      event.target.value = ''
    }
  }

  function disconnectSheet() {
    setSheet(null)
    setSelectedBrands([])
    setAgiplAttributionBrand('')
    setSelectedChannels([])
    setSentDateFrom('')
    setSentDateTo('')
    setCampaignPreview(null)
    setJob(null)
  }

  function openMoEngage() {
    setError('')
    setMoengage({ status: 'external', message: 'Target dashboard opened. If prompted, choose Continue with Google and select your Gmail account.' })
  }

  async function startAutomationBrowser() {
    setError('')
    setBusy('moengage')
    const password = moengagePassword
    setMoengagePassword('')
    try {
      const session = await startMoEngageSession(moengageProfile, password)
      setMoengage(session)
      setMoengageProfile(session.profile_id)
    } catch (err) { setError(err.message) }
    finally { setBusy('') }
  }

  async function resetAutomationBrowser() {
    if (!window.confirm(`Clear the saved browser session for “${moengageProfile}” and open a fresh login?`)) return
    setError('')
    setBusy('reset-moengage')
    const password = moengagePassword
    setMoengagePassword('')
    try {
      const session = await resetMoEngageSession(moengageProfile, password)
      setMoengage(session)
      setMoengageProfile(session.profile_id)
    } catch (err) { setError(err.message) }
    finally { setBusy('') }
  }

  async function verifyAutomationBrowser() {
    setError('')
    setBusy('verify')
    try {
      const session = await getMoEngageSession()
      setMoengage(session)
      setMoengageProfile(session.profile_id || moengageProfile)
    } catch (err) { setError(err.message) }
    finally { setBusy('') }
  }

  async function runAutomation() {
    setError('')
    setBusy('run')
    try {
      const started = await startReport(sheet.connection_id, {
        overwriteExisting: overwrite,
        brands: selectedBrands,
        channels: selectedChannels,
        sentDateFrom,
        sentDateTo,
        agiplAttributionBrand,
      })
      setJob(await getReport(started.job_id))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  async function stopAutomation() {
    try { setJob(await cancelReport(job.job_id)) } catch (err) { setError(err.message) }
  }

  async function retryFailedAutomation() {
    setError('')
    setBusy('retry')
    try {
      const started = await retryFailedReport(job.job_id)
      setJob(await getReport(started.job_id))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  return <div className="min-h-screen bg-[#f6f8fb] text-slate-900">
    <header className="border-b border-slate-200/80 bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1500px] items-center justify-between px-5 lg:px-8">
        <div className="flex items-center gap-3">
          <div className="grid size-9 place-items-center rounded-xl bg-[#172554] text-white"><Icon name="spark" /></div>
          <div><p className="text-[15px] font-bold tracking-tight">Attribution Desk</p><p className="text-[10px] font-medium uppercase tracking-[.16em] text-slate-400">Live sheet automation</p></div>
        </div>
        <div className="flex items-center gap-3">
          <span className={`size-2 rounded-full ${health?.status === 'ok' ? 'bg-emerald-500' : 'bg-red-500'}`} />
          <span className="hidden text-xs text-slate-500 sm:block">Backend {health?.status === 'ok' ? 'online' : 'offline'}</span>
          <Badge tone={isMoeReady ? 'green' : 'amber'}>{modeLabel}</Badge>
        </div>
      </div>
    </header>

    <main className="mx-auto max-w-[1500px] px-5 py-8 lg:px-8 lg:py-10">
      <section className="mb-8">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[.18em] text-blue-700"><span className="h-px w-7 bg-blue-600" /> Campaign operations</div>
        <h1 className="text-3xl font-semibold tracking-[-.035em] text-slate-950 md:text-[42px]">Choose campaigns. Review. Run.</h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-500">Select the brand, sent date range, and channel. The desk shows the exact matching campaigns before anything is written to Google Sheets.</p>
      </section>

      {error && <div className="mb-5 flex items-center justify-between rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error"><Icon name="close" className="size-4" /></button></div>}

      <section className="mb-5 grid gap-4 lg:grid-cols-2">
        <div className={`rounded-2xl border bg-white p-6 shadow-sm ${sheet ? 'border-emerald-200' : 'border-slate-200'}`}>
          <div className="flex items-start justify-between">
            <div className="flex gap-4"><div className="grid size-11 place-items-center rounded-xl bg-emerald-50 text-emerald-700"><Icon name="sheet" /></div><div><div className="flex items-center gap-2"><p className="text-sm font-semibold">Google Sheet</p>{sheet && <Badge tone="green">CONNECTED</Badge>}</div><p className="mt-1 text-xs text-slate-500">Live source and destination</p></div></div>
            <span className="text-xs font-semibold text-slate-300">01</span>
          </div>
          {!googleConfig?.configured ? <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900"><p className="font-semibold">Google access needs one-time setup</p><div className="mt-3 grid gap-2 text-[11px] leading-5 sm:grid-cols-3"><div className="rounded-lg bg-white/70 p-3"><span className="mr-1 font-bold text-amber-700">1.</span>Download a service-account JSON key from your Google Cloud project.</div><div className="rounded-lg bg-white/70 p-3"><span className="mr-1 font-bold text-amber-700">2.</span>Upload it here. The key stays only on this machine.</div><div className="rounded-lg bg-white/70 p-3"><span className="mr-1 font-bold text-amber-700">3.</span>Share the master sheet with the email shown next.</div></div><div className="mt-3 flex flex-wrap items-center gap-2"><label className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-amber-700 px-4 py-2 text-xs font-semibold text-white"><Icon name="upload" className="size-4" />{busy === 'credential' ? 'Validating key…' : 'Upload Google key'}<input type="file" accept="application/json,.json" disabled={busy === 'credential'} onChange={installGoogleCredential} className="hidden" /></label>{googleConfig?.spreadsheet_url && <a href={googleConfig.spreadsheet_url} target="_blank" rel="noopener noreferrer" className="rounded-lg border border-amber-300 bg-white px-4 py-2 font-semibold">Open master sheet</a>}</div></div>
            : !sheet ? <form onSubmit={connectSheet} className="mt-5 space-y-3"><div className="rounded-xl border border-blue-200 bg-blue-50 p-3"><p className="text-[10px] font-semibold uppercase tracking-wider text-blue-600">Share the sheet as Editor with</p><div className="mt-1 flex items-center justify-between gap-3"><code className="truncate text-xs font-semibold text-blue-900">{googleConfig.service_account_email}</code><button type="button" onClick={() => navigator.clipboard.writeText(googleConfig.service_account_email)} className="shrink-0 text-[11px] font-semibold text-blue-700">Copy email</button></div></div><input value={sheetUrl} onChange={(event) => setSheetUrl(event.target.value)} required placeholder="Paste Google Sheet URL" className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm focus:border-blue-500" /><div className="flex gap-2"><input value={worksheet} onChange={(event) => setWorksheet(event.target.value)} placeholder="Worksheet tab" className="min-w-0 flex-1 rounded-xl border border-slate-200 px-4 py-3 text-sm" /><button disabled={busy === 'sheet'} className="rounded-xl bg-emerald-600 px-5 text-sm font-semibold text-white disabled:opacity-50">{busy === 'sheet' ? 'Loading campaigns…' : 'Connect sheet'}</button></div></form>
              : <div className="mt-5 flex items-center justify-between rounded-xl bg-slate-50 p-4"><div><p className="text-sm font-semibold">{sheet.spreadsheet_title}</p><p className="mt-1 text-xs text-slate-500">{sheet.worksheet_title} · {formatNumber(sheet.row_count)} campaign rows</p></div><button onClick={disconnectSheet} className="text-xs font-semibold text-blue-700">Change</button></div>}
        </div>

        <div className={`rounded-2xl border bg-white p-6 shadow-sm ${isMoeReady ? 'border-emerald-200' : 'border-slate-200'}`}>
          <div className="flex items-start justify-between">
            <div className="flex gap-4"><div className="grid size-11 place-items-center rounded-xl bg-blue-50 text-blue-700"><Icon name="browser" /></div><div><div className="flex items-center gap-2"><p className="text-sm font-semibold">{moengageMode === 'api' ? 'MoEngage API' : 'MoEngage session'}</p>{isMoeReady && <Badge tone="green">CONNECTED</Badge>}</div><p className="mt-1 text-xs text-slate-500">{moengageMode === 'api' ? 'Production metrics connection' : 'Saved automation browser'}</p></div></div>
            <span className="text-xs font-semibold text-slate-300">02</span>
          </div>
          <div className="mt-5 rounded-xl bg-slate-50 p-4">
            {moengageMode === 'browser' && <div className="mb-3 space-y-3">
              <div><label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Google email / previously used profile</label><input type="email" list="moengage-profiles" value={moengageProfile === 'default' ? '' : moengageProfile} disabled={Boolean(job) || busy === 'moengage' || busy === 'reset-moengage'} onChange={(event) => { setMoengageProfile(event.target.value); setMoengagePassword('') }} placeholder="Enter a new email or choose a used profile" autoComplete="username" className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs font-medium text-slate-700 focus:border-blue-500" /><datalist id="moengage-profiles">{(moengage.profiles || []).filter((profile) => profile !== 'default').map((profile) => <option key={profile} value={profile} />)}</datalist></div>
              <div><label className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Password — never saved</label><input type="password" value={moengagePassword} disabled={Boolean(job) || busy === 'moengage' || busy === 'reset-moengage'} onChange={(event) => setMoengagePassword(event.target.value)} placeholder="Enter password for this login only" autoComplete="off" className="mt-1.5 w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-xs font-medium text-slate-700 focus:border-blue-500" /><p className="mt-1.5 text-[10px] text-slate-400">The Google browser profile and signed-in session can be reused. This password is sent once to the local backend, cleared from the form immediately, and never written to disk. Complete MFA manually if Google asks.</p></div>
            </div>}
            <p className="text-xs leading-5 text-slate-600">{moengageMode === 'mock' ? (mockEnabled ? 'Mock mode is enabled for local development.' : 'Mock writes are blocked because demo values are not real results.') : moengageMode === 'api' ? (apiConfigured ? `${health.configured_brands.length} brand API configuration(s) ready.` : 'Add the real MOENGAGE_BRAND_CONFIG_JSON Railway variable before running campaigns.') : isMoeReady ? moengage.message : 'Choose a login profile, open the automation browser, and complete Google login. The session is saved only for that profile.'}</p>
            <div className="mt-3 flex flex-wrap gap-2">{moengageMode === 'browser' && <button onClick={startAutomationBrowser} disabled={busy === 'moengage' || busy === 'reset-moengage' || !moengageProfile.trim() || !moengagePassword || Boolean(job)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"><Icon name="browser" className="size-4" />{busy === 'moengage' ? 'Signing in…' : 'Login with this profile'}</button>}{moengageMode === 'browser' && <button onClick={verifyAutomationBrowser} disabled={busy === 'verify' || moengage.profile_id !== selectedMoengageProfile} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 disabled:opacity-50"><Icon name="refresh" className="size-4" />Verify login</button>}{moengageMode === 'browser' && <button type="button" onClick={resetAutomationBrowser} disabled={busy === 'reset-moengage' || !moengageProfile.trim() || !moengagePassword || Boolean(job)} className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-4 py-2 text-xs font-semibold text-red-600 disabled:opacity-50"><Icon name="close" className="size-4" />{busy === 'reset-moengage' ? 'Resetting…' : 'Clear profile & login'}</button>}{moengageMode === 'browser' && <a href={moengageDashboardUrl} target="_blank" rel="noopener noreferrer" onClick={openMoEngage} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-xs font-semibold text-slate-700"><Icon name="link" className="size-4" />Open manually</a>}</div>
          </div>
        </div>
      </section>

      {sheet ? <>
        {sheet.warnings?.length > 0 && <section className="mb-5 rounded-2xl border border-amber-300 bg-amber-50 p-5 shadow-sm" role="alert">
          <div className="flex items-start gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-amber-100 font-bold text-amber-800">!</div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold text-amber-950">Last week’s campaigns have blank or invalid inputs</h2><Badge tone="amber">{sheet.warnings.length} {sheet.warnings.length === 1 ? 'ISSUE' : 'ISSUES'}</Badge></div>
              <p className="mt-1 text-xs leading-5 text-amber-800">Only campaigns sent from {formatDate(sheet.warning_sent_date_from)} through {formatDate(sheet.warning_sent_date_to)} are checked. Older sheet gaps and blank result cells in AA–AF are ignored.</p>
              <ul className="mt-3 max-h-40 list-disc space-y-1 overflow-y-auto pl-5 text-xs text-amber-900">
                {sheet.warnings.slice(0, 20).map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}
              </ul>
              {sheet.warnings.length > 20 && <p className="mt-2 text-[11px] font-semibold text-amber-800">Plus {sheet.warnings.length - 20} more issues. Correct the sheet and reconnect it to refresh this check.</p>}
            </div>
          </div>
        </section>}
        <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col justify-between gap-3 border-b border-slate-100 pb-5 sm:flex-row sm:items-center">
            <div><div className="flex items-center gap-2"><span className="grid size-7 place-items-center rounded-lg bg-violet-50 text-xs font-bold text-violet-700">03</span><h2 className="text-base font-semibold">Choose campaigns to process</h2></div><p className="mt-2 text-xs text-slate-500">Brand, start date, end date, and channel are required. Nothing runs until you confirm below.</p></div>
            {filtersComplete ? <Badge tone={matchingRows ? 'green' : 'amber'}>{previewBusy ? 'CHECKING…' : `${formatNumber(matchingRows)} MATCHING CAMPAIGNS`}</Badge> : <Badge tone="slate">COMPLETE FILTERS</Badge>}
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-3">
            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
              <div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2 text-sm font-semibold"><Icon name="brand" className="size-4 text-blue-700" />Brand</div><button type="button" disabled={Boolean(job)} onClick={() => updateSelectedBrands(selectedBrands.length === sheet.brands.length ? [] : sheet.brands)} className="text-[11px] font-semibold text-blue-700 disabled:opacity-50">{selectedBrands.length === sheet.brands.length ? 'Clear' : 'Select all'}</button></div>
              <ChoicePills values={sheet.brands} selected={selectedBrands} onChange={updateSelectedBrands} disabled={Boolean(job)} />
              {!selectedBrands.length && <p className="mt-3 text-[11px] text-amber-700">Choose at least one brand.</p>}
            </div>

            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
              <div className="mb-4 flex items-center gap-2 text-sm font-semibold"><Icon name="calendar" className="size-4 text-blue-700" />Campaign sent date range</div>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">From<input type="date" value={sentDateFrom} min={earliestSentDate} max={sentDateTo || latestSentDate} disabled={Boolean(job)} onChange={(event) => setSentDateFrom(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm font-medium normal-case tracking-normal text-slate-700 focus:border-blue-500 disabled:opacity-60" /></label>
                <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">To<input type="date" value={sentDateTo} min={sentDateFrom || earliestSentDate} max={latestSentDate} disabled={Boolean(job)} onChange={(event) => setSentDateTo(event.target.value)} className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm font-medium normal-case tracking-normal text-slate-700 focus:border-blue-500 disabled:opacity-60" /></label>
              </div>
              {sentDateFrom && sentDateTo && sentDateFrom > sentDateTo ? <p className="mt-3 text-[11px] text-red-600">End date must be on or after the start date.</p> : <p className="mt-3 text-[11px] text-slate-400">Both dates are included. Available range: {formatDate(earliestSentDate)}–{formatDate(latestSentDate)}.</p>}
            </div>

            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
              <div className="mb-4 flex items-center justify-between"><div className="flex items-center gap-2 text-sm font-semibold"><Icon name="channel" className="size-4 text-blue-700" />Channel</div><button type="button" disabled={Boolean(job)} onClick={() => setSelectedChannels(selectedChannels.length === sheet.channels.length ? [] : sheet.channels)} className="text-[11px] font-semibold text-blue-700 disabled:opacity-50">{selectedChannels.length === sheet.channels.length ? 'Clear' : 'Select all'}</button></div>
              <ChoicePills values={sheet.channels} selected={selectedChannels} onChange={setSelectedChannels} disabled={Boolean(job)} />
              {!selectedChannels.length && <p className="mt-3 text-[11px] text-amber-700">Choose at least one channel.</p>}
            </div>
          </div>

          {hasAgipl && <div className="mt-4 rounded-2xl border border-violet-200 bg-violet-50/70 p-5">
            <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-start">
              <div><div className="flex items-center gap-2 text-sm font-semibold text-violet-950"><Icon name="brand" className="size-4 text-violet-700" />AGIPL attribution brand</div><p className="mt-2 text-xs leading-5 text-violet-700">Choose the brand whose transactions should be counted. The query will still run only inside AGIPL_Master_DB.</p></div>
              <Badge tone={agiplAttributionBrand ? 'green' : 'amber'}>{agiplAttributionBrand ? 'SELECTED' : 'REQUIRED'}</Badge>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {agiplBrandOptions.map((brand) => {
                const active = agiplAttributionBrand === brand
                return <button key={brand} type="button" disabled={Boolean(job)} aria-pressed={active} onClick={() => setAgiplAttributionBrand(active ? '' : brand)} className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-2 text-xs font-semibold transition ${active ? 'border-violet-600 bg-violet-600 text-white shadow-sm' : 'border-violet-200 bg-white text-violet-700 hover:border-violet-400'} disabled:cursor-not-allowed disabled:opacity-60`}>{active && <Icon name="check" className="size-3.5" />}{brand}</button>
              })}
            </div>
            {!agiplAttributionBrand && <p className="mt-3 text-[11px] font-medium text-amber-700">Select one attribution brand before starting the AGIPL run.</p>}
          </div>}
        </section>

        <section className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[
            ['Selected brands', selectedBrands.length || '—', hasAgipl && agiplAttributionBrand ? `${selectedBrands.join(', ')} · AGIPL → ${agiplAttributionBrand}` : selectedBrands.join(', ') || 'choose brands'],
            ['Campaigns matched', previewBusy ? '…' : formatNumber(summary.campaigns), filtersComplete ? 'ready for review' : 'complete the filters'],
            ['Sent date range', dateRangeValid ? `${formatDate(sentDateFrom)} – ${formatDate(sentDateTo)}` : '—', 'inclusive campaign send dates'],
            ['Channels', selectedChannels.length || '—', selectedChannels.join(', ') || 'choose channels'],
          ].map(([label, value, helper]) => <div key={label} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-xs text-slate-500">{label}</p><p className="mt-2 truncate text-xl font-semibold">{value}</p><p className="mt-1 truncate text-[11px] text-slate-400">{helper}</p></div>)}
        </section>

        <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-col justify-between gap-4 md:flex-row md:items-center">
            <div className="flex-1">
              <div className="flex items-center gap-2"><p className="text-sm font-semibold">{job?.status === 'processing' ? `Processing row ${job.current_row} · ${job.current_brand}` : job ? `Automation ${job.status}` : filtersComplete ? matchingRows ? 'Selection ready to run' : previewBusy ? 'Checking the live sheet…' : 'No matching campaigns' : 'Complete the campaign filters'}</p>{job?.status === 'completed' && <Badge tone="green">DONE</Badge>}</div>
              {job && <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${job.progress}%` }} /></div>}
              <p className="mt-2 text-[11px] text-slate-400">{job ? `${formatNumber(job.processed_rows)} of ${formatNumber(job.total_rows)} rows · ${job.failed_rows} failed` : matchingRows ? `${formatNumber(matchingRows)} rows will be processed. Values are written to AA–AF after each successful query.` : 'Choose a brand, sent date range, and channel to see the exact run size.'}</p>
            </div>
              {canRun ? <div className="flex flex-col gap-3 sm:flex-row sm:items-center"><label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} className="accent-blue-600" />Overwrite existing values</label><button onClick={runAutomation} disabled={busy === 'run'} className="inline-flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50">{busy === 'run' ? 'Starting…' : `Run ${formatNumber(matchingRows)} campaigns`} <Icon name="arrow" className="size-4" /></button></div>
              : job?.status === 'processing' ? <button onClick={stopAutomation} className="rounded-xl border border-red-200 px-4 py-2 text-xs font-semibold text-red-600">Stop run</button>
                : job && terminalStates.has(job.status) ? <button onClick={() => setJob(null)} className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-blue-700">Start another run</button>
                  : !isMoeReady ? <Badge tone="amber">{moengageMode === 'api' ? 'CONFIGURE MOENGAGE API TO RUN' : 'CONNECT MOENGAGE TO RUN'}</Badge> : null}
          </div>
        </section>

        <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
            <div className="flex items-start gap-4"><div className="grid size-11 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700"><Icon name="download" /></div><div><div className="flex flex-wrap items-center gap-2"><span className="grid size-7 place-items-center rounded-lg bg-violet-50 text-xs font-bold text-violet-700">04</span><h2 className="text-base font-semibold">Results & output</h2>{job?.status === 'completed' && <Badge tone="green">OUTPUT READY</Badge>}{job?.status === 'processing' && <Badge tone="blue">UPDATING LIVE</Badge>}</div><p className="mt-2 max-w-2xl text-xs leading-5 text-slate-500">Each successful campaign appears in the table below and is written immediately to its correct Google Sheet cells. Download the complete run as CSV whenever you need a separate report.</p></div></div>
            <div className="flex flex-wrap gap-2">{job && terminalStates.has(job.status) && job.failed_rows > 0 && <button type="button" onClick={retryFailedAutomation} disabled={busy === 'retry'} className="inline-flex items-center gap-2 rounded-xl bg-red-600 px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50"><Icon name="refresh" className="size-4" />{busy === 'retry' ? 'Starting retry…' : `Retry ${job.failed_rows} failed`}</button>}{job?.job_id && <a href={getResultsDownloadUrl(job.job_id)} className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-xs font-semibold text-white"><Icon name="download" className="size-4" />Download results CSV</a>}{googleConfig?.spreadsheet_url && <a href={googleConfig.spreadsheet_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs font-semibold text-slate-700"><Icon name="sheet" className="size-4" />Open Google Sheet</a>}</div>
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-3"><div className="rounded-xl bg-slate-50 p-4"><p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Rows written</p><p className="mt-1 text-xl font-semibold text-emerald-700">{formatNumber(job?.successful_rows || 0)}</p><p className="mt-1 text-[11px] text-slate-400">Successful Google Sheet updates</p></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Needs review</p><p className="mt-1 text-xl font-semibold text-red-600">{formatNumber(job?.failed_rows || 0)}</p><p className="mt-1 text-[11px] text-slate-400">Failed rows include the exact error</p></div><div className="rounded-xl bg-slate-50 p-4"><p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Destination</p><p className="mt-1 text-sm font-semibold">Mastersheet · AA–AF</p><p className="mt-1 text-[11px] text-slate-400">Online, offline, and overall columns</p></div></div>
        </section>

        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex justify-between border-b border-slate-100 px-5 py-4"><div><h2 className="text-sm font-semibold">{job ? 'Run results' : 'Campaign preview'}</h2><p className="mt-1 text-[11px] text-slate-400">{job ? 'Values and per-row status update while automation runs' : filtersComplete ? 'Exact rows matching your selection' : 'Complete the filters to preview rows'}</p></div><Badge tone="blue">{rows.length} shown</Badge></div>
          {rows.length ? <div className="overflow-x-auto"><table className="w-full min-w-[1660px] text-left"><thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-400"><tr className="border-b border-slate-200"><th rowSpan="2" className="px-5 py-3">Row</th><th rowSpan="2" className="px-4 py-3">Campaign</th><th rowSpan="2" className="px-4 py-3">Status</th><th rowSpan="2" className="px-4 py-3">Sent date</th><th rowSpan="2" className="px-4 py-3">Brand</th><th rowSpan="2" className="px-4 py-3">Channel</th><th rowSpan="2" className="px-4 py-3">Type</th><th rowSpan="2" className="px-4 py-3">Goal range</th><th colSpan="3" className="border-l border-slate-200 px-4 py-2 text-center text-slate-600">Unique users</th><th colSpan="3" className="border-l border-slate-200 px-4 py-2 text-center text-slate-600">Revenue</th></tr><tr><th className="border-l border-slate-200 px-3 py-2 text-right">Total</th><th className="bg-blue-50/70 px-3 py-2 text-right text-blue-600">Online</th><th className="bg-amber-50/70 px-3 py-2 text-right text-amber-600">Offline</th><th className="border-l border-slate-200 px-3 py-2 text-right">Total</th><th className="bg-blue-50/70 px-3 py-2 text-right text-blue-600">Online</th><th className="bg-amber-50/70 px-3 py-2 text-right text-amber-600">Offline</th></tr></thead><tbody className="divide-y divide-slate-100 text-xs">{rows.map((row) => <tr key={`${row.excel_row}-${row.campaign_id}`} className="hover:bg-slate-50/70"><td className="px-5 py-3 font-mono text-slate-400">{row.excel_row}</td><td className="max-w-[280px] px-4 py-3"><p className="truncate font-semibold">{row.campaign_name}</p><p className="truncate font-mono text-[10px] text-slate-400">{row.campaign_id}</p>{row.message && <p className="text-[10px] text-red-600">{row.message}</p>}</td><td className="px-4 py-3"><Badge tone={row.status === 'success' ? 'green' : row.status === 'failed' ? 'red' : row.status === 'processing' ? 'blue' : 'slate'}>{row.status || 'Preview'}</Badge></td><td className="px-4 py-3 text-slate-600">{row.sent_date ? formatDate(row.sent_date) : '—'}</td><td className="px-4 py-3 font-semibold">{row.brand}</td><td className="px-4 py-3"><Badge>{row.channel}</Badge></td><td className="px-4 py-3"><Badge tone={row.campaign_type === 'Online' ? 'blue' : row.campaign_type === 'Offline' ? 'amber' : 'slate'}>{row.campaign_type}</Badge></td><td className="px-4 py-3 text-slate-500">{row.date_range}</td><td className="border-l border-slate-100 px-3 py-3 text-right font-semibold">{formatNumber(row.unique_users)}</td><td className="bg-blue-50/30 px-3 py-3 text-right text-blue-800">{formatNumber(row.online_unique_users)}</td><td className="bg-amber-50/30 px-3 py-3 text-right text-amber-800">{formatNumber(row.offline_unique_users)}</td><td className="border-l border-slate-100 px-3 py-3 text-right font-semibold">{formatCurrency(row.total_revenue)}</td><td className="bg-blue-50/30 px-3 py-3 text-right text-blue-800">{formatCurrency(row.online_revenue)}</td><td className="bg-amber-50/30 px-5 py-3 text-right text-amber-800">{formatCurrency(row.offline_revenue)}</td></tr>)}</tbody></table></div>
            : <div className="grid min-h-44 place-items-center px-5 py-10 text-center"><div><div className="mx-auto grid size-11 place-items-center rounded-full bg-slate-100 text-slate-400"><Icon name="channel" /></div><p className="mt-3 text-sm font-semibold text-slate-600">{previewBusy ? 'Checking matching campaigns…' : filtersComplete ? 'No campaigns match this selection' : 'Your campaign preview will appear here'}</p><p className="mt-1 text-xs text-slate-400">{filtersComplete ? 'Try another brand, date range, or channel.' : 'Complete the brand, date range, and channel filters above.'}</p></div></div>}
        </section>
      </> : <LockedWorkflow reason={googleConfig?.configured ? 'Share the sheet with the service-account email above, then click Connect sheet to load the real brands and dates.' : 'Upload the Google service-account key in step 01 to unlock the live brand, sent-date, and channel filters.'} />}

      <footer className="mt-8 flex justify-between border-t border-slate-200 py-5 text-[11px] text-slate-400"><span>Credentials stay on this machine</span><span>Google Sheets ↔ MoEngage</span></footer>
    </main>
  </div>
}

export default App
