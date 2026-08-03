from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import UploadFile

from app.config.settings import Settings
from app.models.report import JobState, ReportJob, RowResult, SheetConnection, UploadRecord
from app.services.excel_service import ExcelService
from app.services.google_sheet_service import GoogleSheetService, previous_completed_week
from app.services.moengage_service import MoEngageService


class ReportService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.excel = ExcelService()
        self.moengage = MoEngageService(settings)
        self.google = GoogleSheetService(settings.google_service_account_file)
        self.uploads: dict[str, UploadRecord] = {}
        self.sheet_connections: dict[str, SheetConnection] = {}
        self.jobs: dict[str, ReportJob] = {}
        self.tasks: dict[str, asyncio.Task] = {}

    async def connect_sheet(self, spreadsheet_url: str, worksheet_name: str) -> SheetConnection:
        warning_sent_date_from, warning_sent_date_to = previous_completed_week()
        spreadsheet, worksheet, rows, warnings = await self.google.connect(
            spreadsheet_url,
            worksheet_name,
            warning_sent_date_from,
            warning_sent_date_to,
        )
        connection_id = uuid.uuid4().hex
        connection = SheetConnection(
            id=connection_id,
            spreadsheet_id=spreadsheet.id,
            spreadsheet_url=spreadsheet_url,
            spreadsheet_title=spreadsheet.title,
            worksheet_title=worksheet.title,
            row_count=len(rows),
            brands=sorted({row.brand for row in rows}),
            channels=sorted({row.channel for row in rows}),
            campaign_types=sorted({row.campaign_type for row in rows}),
            sent_dates=sorted({row.campaign_date for row in rows}, reverse=True),
            preview=[self._campaign_dict(row) for row in rows[:12]],
            campaigns=rows,
            warnings=warnings[:100],
            warning_sent_date_from=warning_sent_date_from,
            warning_sent_date_to=warning_sent_date_to,
        )
        self.sheet_connections[connection_id] = connection
        return connection

    def create_sheet_job(
        self,
        connection_id: str,
        overwrite_existing: bool,
        row_limit: int | None,
        brands: list[str] | None = None,
        channels: list[str] | None = None,
        sent_date: date | None = None,
        sent_date_from: date | None = None,
        sent_date_to: date | None = None,
        agipl_attribution_brand: str | None = None,
    ) -> ReportJob:
        connection = self.sheet_connections.get(connection_id)
        if not connection:
            raise KeyError("Google Sheet connection not found or server was restarted")
        job_id = uuid.uuid4().hex
        job = ReportJob(
            id=job_id,
            upload_id=connection_id,
            filename=connection.spreadsheet_title,
            agipl_attribution_brand=agipl_attribution_brand,
        )
        self.jobs[job_id] = job
        self.tasks[job_id] = asyncio.create_task(
            self._process_sheet(
                job, connection, overwrite_existing, row_limit, brands, channels,
                sent_date, sent_date_from, sent_date_to, agipl_attribution_brand,
            )
        )
        return job

    def retry_failed_sheet_job(self, job_id: str) -> ReportJob:
        original = self.get_job(job_id)
        if original.state not in {
            JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED
        }:
            raise ValueError("Wait for the current run to finish before retrying failed campaigns")
        failed_rows = {
            result.excel_row for result in original.results if result.status == "failed"
        }
        if not failed_rows:
            raise ValueError("This run has no failed campaigns to retry")
        connection = self.sheet_connections.get(original.upload_id)
        if not connection:
            raise KeyError("Google Sheet connection not found or server was restarted")
        retry_id = uuid.uuid4().hex
        retry = ReportJob(
            id=retry_id,
            upload_id=original.upload_id,
            filename=f"{original.filename} · failed retry",
            agipl_attribution_brand=original.agipl_attribution_brand,
        )
        self.jobs[retry_id] = retry
        self.tasks[retry_id] = asyncio.create_task(
            self._process_sheet(
                retry, connection, True, None,
                agipl_attribution_brand=original.agipl_attribution_brand,
                row_numbers=failed_rows,
            )
        )
        return retry

    async def _process_sheet(
        self,
        job: ReportJob,
        connection: SheetConnection,
        overwrite: bool,
        row_limit: int | None,
        brands: list[str] | None = None,
        channels: list[str] | None = None,
        sent_date: date | None = None,
        sent_date_from: date | None = None,
        sent_date_to: date | None = None,
        agipl_attribution_brand: str | None = None,
        row_numbers: set[int] | None = None,
    ):
        job.state = JobState.PROCESSING
        job.started_at = datetime.now(timezone.utc)
        try:
            campaigns, _ = await self.google.read_campaigns(connection.spreadsheet_id, connection.worksheet_title)
            campaigns = self._filter_campaigns(
                campaigns, brands, channels, sent_date, sent_date_from, sent_date_to
            )
            if row_numbers is not None:
                campaigns = [
                    campaign for campaign in campaigns
                    if campaign.excel_row in row_numbers
                ]
            if row_limit:
                campaigns = campaigns[:row_limit]
            job.total_rows = len(campaigns)
            for campaign in campaigns:
                if job.state == JobState.CANCELLED:
                    break
                job.current_row, job.current_brand = campaign.excel_row, campaign.brand
                query_campaign = (
                    replace(campaign, attribution_brand=agipl_attribution_brand)
                    if campaign.brand.casefold() == "agipl"
                    else campaign
                )
                result = RowResult(
                    excel_row=campaign.excel_row, brand=campaign.brand, channel=campaign.channel,
                    campaign_type=campaign.campaign_type, campaign_id=campaign.campaign_id,
                    campaign_name=campaign.campaign_name,
                    date_range=f"{campaign.start_date.isoformat()} → {campaign.end_date.isoformat()}", status="processing",
                )
                job.results.append(result)
                if not overwrite and self._has_complete_existing_metrics(campaign):
                    result.status, result.message = "skipped", "Existing Google Sheet values preserved"
                    self._copy_existing_metrics(result, campaign)
                    job.skipped_rows += 1
                else:
                    try:
                        metrics = await self.moengage.fetch_metrics(query_campaign)
                        await self.google.write_metrics(connection.spreadsheet_id, connection.worksheet_title, campaign, metrics)
                        result.status = "success"
                        self._copy_metrics(result, metrics)
                        job.successful_rows += 1
                    except Exception as exc:
                        result.status, result.message = "failed", str(exc)
                        job.failed_rows += 1
                job.processed_rows += 1
            if job.state != JobState.CANCELLED:
                job.state = JobState.COMPLETED
        except Exception as exc:
            job.state, job.error = JobState.FAILED, str(exc)
        finally:
            job.current_row = job.current_brand = None
            job.finished_at = datetime.now(timezone.utc)

    async def save_upload(self, file: UploadFile) -> UploadRecord:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".xlsx", ".xlsm"}:
            raise ValueError("Only .xlsx and .xlsm workbooks are supported")
        upload_id = uuid.uuid4().hex
        path = self.settings.storage_dir / "uploads" / f"{upload_id}{suffix}"
        size = 0
        with path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > self.settings.max_upload_mb * 1024 * 1024:
                    destination.close()
                    path.unlink(missing_ok=True)
                    raise ValueError(f"File exceeds {self.settings.max_upload_mb} MB limit")
                destination.write(chunk)
        try:
            sheet_name, rows, warnings = await asyncio.to_thread(self.excel.read_campaigns, path)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        preview = [self._campaign_dict(row) for row in rows[:12]]
        record = UploadRecord(
            id=upload_id,
            original_name=file.filename or path.name,
            path=path,
            sheet_name=sheet_name,
            row_count=len(rows),
            brands=sorted({row.brand for row in rows}),
            channels=sorted({row.channel for row in rows}),
            campaign_types=sorted({row.campaign_type for row in rows}),
            preview=preview,
            warnings=warnings[:100],
        )
        self.uploads[upload_id] = record
        return record

    def create_job(
        self,
        upload_id: str,
        overwrite_existing: bool,
        row_limit: int | None,
        brands: list[str] | None = None,
        channels: list[str] | None = None,
        sent_date: date | None = None,
        sent_date_from: date | None = None,
        sent_date_to: date | None = None,
        agipl_attribution_brand: str | None = None,
    ) -> ReportJob:
        upload = self.uploads.get(upload_id)
        if not upload:
            raise KeyError("Upload not found or server was restarted")
        job_id = uuid.uuid4().hex
        job = ReportJob(
            id=job_id,
            upload_id=upload_id,
            filename=upload.original_name,
            agipl_attribution_brand=agipl_attribution_brand,
        )
        self.jobs[job_id] = job
        self.tasks[job_id] = asyncio.create_task(
            self._process(
                job, upload, overwrite_existing, row_limit, brands, channels,
                sent_date, sent_date_from, sent_date_to, agipl_attribution_brand,
            )
        )
        return job

    async def _process(
        self,
        job: ReportJob,
        upload: UploadRecord,
        overwrite: bool,
        row_limit: int | None,
        brands: list[str] | None = None,
        channels: list[str] | None = None,
        sent_date: date | None = None,
        sent_date_from: date | None = None,
        sent_date_to: date | None = None,
        agipl_attribution_brand: str | None = None,
    ):
        job.state = JobState.PROCESSING
        job.started_at = datetime.now(timezone.utc)
        updates = []
        try:
            _, campaigns, _ = await asyncio.to_thread(self.excel.read_campaigns, upload.path)
            campaigns = self._filter_campaigns(
                campaigns, brands, channels, sent_date, sent_date_from, sent_date_to
            )
            if row_limit:
                campaigns = campaigns[:row_limit]
            job.total_rows = len(campaigns)
            for campaign in campaigns:
                if job.state == JobState.CANCELLED:
                    break
                job.current_row = campaign.excel_row
                job.current_brand = campaign.brand
                query_campaign = (
                    replace(campaign, attribution_brand=agipl_attribution_brand)
                    if campaign.brand.casefold() == "agipl"
                    else campaign
                )
                result = RowResult(
                    excel_row=campaign.excel_row,
                    brand=campaign.brand,
                    channel=campaign.channel,
                    campaign_type=campaign.campaign_type,
                    campaign_id=campaign.campaign_id,
                    campaign_name=campaign.campaign_name,
                    date_range=f"{campaign.start_date.isoformat()} → {campaign.end_date.isoformat()}",
                    status="processing",
                )
                job.results.append(result)
                if not overwrite and self._has_complete_existing_metrics(campaign):
                    result.status = "skipped"
                    self._copy_existing_metrics(result, campaign)
                    result.message = "Existing values preserved"
                    job.skipped_rows += 1
                else:
                    try:
                        metrics = await self.moengage.fetch_metrics(query_campaign)
                        updates.append((campaign, metrics))
                        result.status = "success"
                        self._copy_metrics(result, metrics)
                        job.successful_rows += 1
                    except Exception as exc:
                        result.status = "failed"
                        result.message = str(exc)
                        job.failed_rows += 1
                job.processed_rows += 1

            output = self.settings.storage_dir / "outputs" / f"{job.id}_updated.xlsx"
            await asyncio.to_thread(self.excel.write_metrics, upload.path, output, updates)
            job.output_path = output
            if job.state != JobState.CANCELLED:
                job.state = JobState.COMPLETED
        except Exception as exc:
            job.state = JobState.FAILED
            job.error = str(exc)
        finally:
            job.current_row = None
            job.current_brand = None
            job.finished_at = datetime.now(timezone.utc)

    def cancel_job(self, job_id: str) -> ReportJob:
        job = self.get_job(job_id)
        if job.state in {JobState.QUEUED, JobState.PROCESSING}:
            job.state = JobState.CANCELLED
        return job

    def get_job(self, job_id: str) -> ReportJob:
        if job_id not in self.jobs:
            raise KeyError("Job not found")
        return self.jobs[job_id]

    @staticmethod
    def _copy_metrics(result: RowResult, metrics):
        result.unique_users = metrics.unique_users
        result.total_revenue = metrics.total_revenue
        result.online_unique_users = metrics.online_unique_users
        result.offline_unique_users = metrics.offline_unique_users
        result.online_revenue = metrics.online_revenue
        result.offline_revenue = metrics.offline_revenue

    @staticmethod
    def _copy_existing_metrics(result: RowResult, campaign):
        result.unique_users = int(campaign.existing_unique_users)
        result.total_revenue = float(campaign.existing_revenue)
        result.online_unique_users = (
            int(campaign.existing_online_unique_users)
            if campaign.existing_online_unique_users is not None else None
        )
        result.offline_unique_users = (
            int(campaign.existing_offline_unique_users)
            if campaign.existing_offline_unique_users is not None else None
        )
        result.online_revenue = campaign.existing_online_revenue
        result.offline_revenue = campaign.existing_offline_revenue

    @staticmethod
    def _has_complete_existing_metrics(campaign) -> bool:
        if campaign.existing_unique_users is None or campaign.existing_revenue is None:
            return False
        if campaign.campaign_type == "Overall":
            return all(value is not None for value in (
                campaign.existing_online_unique_users,
                campaign.existing_offline_unique_users,
                campaign.existing_online_revenue,
                campaign.existing_offline_revenue,
            ))
        if campaign.campaign_type == "Online":
            return (
                campaign.existing_online_unique_users is not None
                and campaign.existing_online_revenue is not None
            )
        if campaign.campaign_type == "Offline":
            return (
                campaign.existing_offline_unique_users is not None
                and campaign.existing_offline_revenue is not None
            )
        return False

    @staticmethod
    def _filter_brands(campaigns, brands: list[str] | None):
        allowed = {brand.strip().casefold() for brand in brands or [] if brand.strip()}
        if not allowed:
            return campaigns
        return [campaign for campaign in campaigns if campaign.brand.casefold() in allowed]

    @staticmethod
    def _filter_campaigns(
        campaigns,
        brands: list[str] | None = None,
        channels: list[str] | None = None,
        sent_date: date | None = None,
        sent_date_from: date | None = None,
        sent_date_to: date | None = None,
    ):
        selected = ReportService._filter_brands(campaigns, brands)
        allowed_channels = {
            channel.strip().casefold() for channel in channels or [] if channel.strip()
        }
        if allowed_channels:
            selected = [
                campaign
                for campaign in selected
                if campaign.channel.casefold() in allowed_channels
            ]
        if sent_date:
            selected = [
                campaign for campaign in selected if campaign.campaign_date == sent_date
            ]
        else:
            if sent_date_from:
                selected = [
                    campaign for campaign in selected
                    if campaign.campaign_date >= sent_date_from
                ]
            if sent_date_to:
                selected = [
                    campaign for campaign in selected
                    if campaign.campaign_date <= sent_date_to
                ]
        return selected

    def preview_sheet_campaigns(
        self,
        connection_id: str,
        brands: list[str] | None = None,
        channels: list[str] | None = None,
        sent_date: date | None = None,
        limit: int = 100,
        sent_date_from: date | None = None,
        sent_date_to: date | None = None,
    ):
        connection = self.sheet_connections.get(connection_id)
        if not connection:
            raise KeyError("Google Sheet connection not found or server was restarted")
        campaigns = self._filter_campaigns(
            connection.campaigns, brands, channels, sent_date,
            sent_date_from, sent_date_to,
        )
        return len(campaigns), [
            self._campaign_dict(row) for row in campaigns[:limit]
        ]

    @staticmethod
    def _campaign_dict(row):
        return {
            "excel_row": row.excel_row,
            "brand": row.brand,
            "channel": row.channel,
            "campaign_type": row.campaign_type,
            "campaign_id": row.campaign_id,
            "campaign_name": row.campaign_name,
            "sent_date": row.campaign_date.isoformat(),
            "date_range": f"{row.start_date.isoformat()} → {row.end_date.isoformat()}",
        }
