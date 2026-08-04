from __future__ import annotations

import csv
import io
from dataclasses import asdict

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile

from app.config.settings import settings
from app.core.dependencies import get_report_service
from app.models.report import JobState, ReportJob
from app.schemas.report_schema import (
    HealthResponse,
    HistoryResponse,
    JobResponse,
    CampaignPreviewResponse,
    MoEngageSessionRequest,
    MoEngageSessionResponse,
    SheetConnectRequest,
    SheetConnectionResponse,
    StartJobRequest,
    StartJobResponse,
)
from app.services.report_service import ReportService


router = APIRouter()


def ensure_browser_can_switch(service: ReportService) -> None:
    if any(job.state in {JobState.QUEUED, JobState.PROCESSING} for job in service.jobs.values()):
        raise HTTPException(
            status_code=409,
            detail="Wait for the current automation job to finish or cancel it before switching login profiles.",
        )


def job_response(job: ReportJob, include_results: bool = True) -> JobResponse:
    results = job.results[-250:] if include_results else []
    return JobResponse(
        job_id=job.id,
        filename=job.filename,
        status=job.state.value,
        progress=job.progress,
        total_rows=job.total_rows,
        processed_rows=job.processed_rows,
        successful_rows=job.successful_rows,
        failed_rows=job.failed_rows,
        skipped_rows=job.skipped_rows,
        current_row=job.current_row,
        current_brand=job.current_brand,
        error=job.error,
        download_ready=bool(job.output_path and job.output_path.exists()),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        results=[asdict(result) for result in results],
    )


@router.get("/health", response_model=HealthResponse)
async def health(service: ReportService = Depends(get_report_service)):
    browser_status, _ = await service.moengage.browser.status()
    return HealthResponse(
        status="ok",
        moengage_mode=settings.moengage_mode,
        configured_brands=service.moengage.configured_brands(),
        google_configured=service.google.configured,
        moengage_connected=browser_status == "connected",
        mock_writes_enabled=settings.allow_mock_writes,
    )


@router.get("/google/config")
async def google_config(service: ReportService = Depends(get_report_service)):
    return {
        "configured": service.google.configured,
        "service_account_email": service.google.service_account_email(),
        "spreadsheet_url": settings.google_spreadsheet_url,
        "worksheet_name": settings.google_worksheet_name,
    }


@router.post("/google/credentials")
async def upload_google_credentials(
    credential: UploadFile = File(...),
    service: ReportService = Depends(get_report_service),
):
    if not (credential.filename or "").lower().endswith(".json"):
        raise HTTPException(status_code=422, detail="Choose a .json service-account key")
    try:
        client_email = service.google.install_credentials(await credential.read())
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "configured": True,
        "service_account_email": client_email,
        "spreadsheet_url": settings.google_spreadsheet_url,
        "worksheet_name": settings.google_worksheet_name,
    }


@router.post("/google/connect", response_model=SheetConnectionResponse)
async def connect_google_sheet(payload: SheetConnectRequest, service: ReportService = Depends(get_report_service)):
    try:
        connection = await service.connect_sheet(payload.spreadsheet_url, payload.worksheet_name)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SheetConnectionResponse(
        connection_id=connection.id, spreadsheet_title=connection.spreadsheet_title,
        worksheet_title=connection.worksheet_title, row_count=connection.row_count,
        brands=connection.brands, channels=connection.channels,
        campaign_types=connection.campaign_types, sent_dates=connection.sent_dates,
        preview=connection.preview, warnings=connection.warnings,
        warning_sent_date_from=connection.warning_sent_date_from,
        warning_sent_date_to=connection.warning_sent_date_to,
    )


@router.get(
    "/google/connections/{connection_id}/campaigns",
    response_model=CampaignPreviewResponse,
)
async def preview_google_sheet_campaigns(
    connection_id: str,
    brands: list[str] = Query(default=[]),
    channels: list[str] = Query(default=[]),
    sent_date: date | None = None,
    sent_date_from: date | None = None,
    sent_date_to: date | None = None,
    limit: int = Query(default=100, ge=1, le=250),
    service: ReportService = Depends(get_report_service),
):
    if bool(sent_date_from) != bool(sent_date_to):
        raise HTTPException(status_code=422, detail="Both sent-date range values are required")
    if sent_date_from and sent_date_to and sent_date_from > sent_date_to:
        raise HTTPException(status_code=422, detail="End date must be on or after start date")
    try:
        row_count, preview = service.preview_sheet_campaigns(
            connection_id, brands, channels, sent_date, limit,
            sent_date_from, sent_date_to,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CampaignPreviewResponse(row_count=row_count, preview=preview)


@router.post("/moengage/session/start", response_model=MoEngageSessionResponse)
async def start_moengage_session(
    payload: MoEngageSessionRequest,
    service: ReportService = Depends(get_report_service),
):
    ensure_browser_can_switch(service)
    try:
        profile_id = await service.moengage.select_profile(payload.profile_id)
        message = await service.moengage.browser.start_login(
            payload.profile_id,
            payload.password.get_secret_value(),
        )
        return MoEngageSessionResponse(
            status="waiting_for_login", message=message, profile_id=profile_id,
            profiles=service.moengage.available_profiles(),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/moengage/session", response_model=MoEngageSessionResponse)
async def moengage_session(service: ReportService = Depends(get_report_service)):
    status, message = await service.moengage.browser.status()
    return MoEngageSessionResponse(
        status=status, message=message, profile_id=service.moengage.active_profile,
        profiles=service.moengage.available_profiles(),
    )


@router.post("/moengage/session/reset", response_model=MoEngageSessionResponse)
async def reset_moengage_session(
    payload: MoEngageSessionRequest,
    service: ReportService = Depends(get_report_service),
):
    ensure_browser_can_switch(service)
    try:
        profile_id = await service.moengage.reset_profile(payload.profile_id)
        message = await service.moengage.browser.start_login(
            payload.profile_id,
            payload.password.get_secret_value(),
        )
        return MoEngageSessionResponse(
            status="waiting_for_login",
            message="A fresh browser profile is open. Choose Continue with Google, then select the required account. " + message,
            profile_id=profile_id,
            profiles=service.moengage.available_profiles(),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/jobs", response_model=StartJobResponse, status_code=202)
async def start_job(payload: StartJobRequest, service: ReportService = Depends(get_report_service)):
    if settings.moengage_mode == "mock" and not settings.allow_mock_writes:
        raise HTTPException(
            status_code=409,
            detail=(
                "Mock metrics are disabled because they are not real MoEngage results. "
                "Configure MOENGAGE_MODE=api for production."
            ),
        )
    if settings.moengage_mode == "api":
        configured = {brand.casefold() for brand in service.moengage.configured_brands()}
        missing = sorted(
            {brand for brand in payload.brands if brand.casefold() not in configured},
            key=str.casefold,
        )
        if missing:
            raise HTTPException(
                status_code=409,
                detail="Missing MoEngage API configuration for: " + ", ".join(missing),
            )
    try:
        if payload.sheet_connection_id:
            job = service.create_sheet_job(
                payload.sheet_connection_id,
                payload.overwrite_existing,
                payload.row_limit,
                payload.brands,
                payload.channels,
                payload.sent_date,
                payload.sent_date_from,
                payload.sent_date_to,
                payload.agipl_attribution_brand,
            )
        elif payload.upload_id:
            job = service.create_job(
                payload.upload_id,
                payload.overwrite_existing,
                payload.row_limit,
                payload.brands,
                payload.channels,
                payload.sent_date,
                payload.sent_date_from,
                payload.sent_date_to,
                payload.agipl_attribution_brand,
            )
        else:
            raise KeyError("sheet_connection_id is required")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return StartJobResponse(job_id=job.id, status=job.state.value)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, service: ReportService = Depends(get_report_service)):
    try:
        return job_response(service.get_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/results.csv")
async def download_job_results(
    job_id: str,
    service: ReportService = Depends(get_report_service),
):
    try:
        job = service.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Sheet Row", "Campaign", "Campaign ID", "Brand", "Channel", "Type",
        "Goal Range", "Status", "Unique Users - Total", "Unique Users - Online",
        "Unique Users - Offline", "Revenue - Total", "Revenue - Online",
        "Revenue - Offline", "Message",
    ])
    for result in job.results:
        writer.writerow([
            result.excel_row, result.campaign_name, result.campaign_id, result.brand,
            result.channel, result.campaign_type, result.date_range, result.status,
            result.unique_users if result.unique_users is not None else "",
            result.online_unique_users if result.online_unique_users is not None else "",
            result.offline_unique_users if result.offline_unique_users is not None else "",
            result.total_revenue if result.total_revenue is not None else "",
            result.online_revenue if result.online_revenue is not None else "",
            result.offline_revenue if result.offline_revenue is not None else "",
            result.message or "",
        ])
    filename = f"attribution-results-{job.id[:8]}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: str, service: ReportService = Depends(get_report_service)):
    try:
        return job_response(service.cancel_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/jobs/{job_id}/retry-failed",
    response_model=StartJobResponse,
    status_code=202,
)
async def retry_failed_job(job_id: str, service: ReportService = Depends(get_report_service)):
    try:
        job = service.retry_failed_sheet_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StartJobResponse(job_id=job.id, status=job.state.value)


@router.get("/jobs", response_model=HistoryResponse)
async def list_jobs(service: ReportService = Depends(get_report_service)):
    jobs = sorted(service.jobs.values(), key=lambda job: job.created_at, reverse=True)
    return HistoryResponse(jobs=[job_response(job, include_results=False) for job in jobs[:30]])
