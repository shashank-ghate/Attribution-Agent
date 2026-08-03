from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class JobState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CampaignRow:
    excel_row: int
    campaign_date: date
    brand: str
    channel: str
    campaign_type: str
    campaign_id: str
    campaign_name: str
    tracking_goal: str
    start_date: date
    end_date: date
    existing_unique_users: float | None = None
    existing_revenue: float | None = None
    existing_online_unique_users: float | None = None
    existing_offline_unique_users: float | None = None
    existing_online_revenue: float | None = None
    existing_offline_revenue: float | None = None
    attribution_brand: str | None = None


@dataclass
class CampaignMetrics:
    unique_users: int
    total_revenue: float
    online_unique_users: int | None = None
    offline_unique_users: int | None = None
    online_revenue: float | None = None
    offline_revenue: float | None = None


@dataclass
class RowResult:
    excel_row: int
    brand: str
    channel: str
    campaign_type: str
    campaign_id: str
    campaign_name: str
    date_range: str
    status: str = "pending"
    unique_users: int | None = None
    total_revenue: float | None = None
    online_unique_users: int | None = None
    offline_unique_users: int | None = None
    online_revenue: float | None = None
    offline_revenue: float | None = None
    message: str | None = None


@dataclass
class UploadRecord:
    id: str
    original_name: str
    path: Path
    sheet_name: str
    row_count: int
    brands: list[str]
    channels: list[str]
    campaign_types: list[str]
    preview: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SheetConnection:
    id: str
    spreadsheet_id: str
    spreadsheet_url: str
    spreadsheet_title: str
    worksheet_title: str
    row_count: int
    brands: list[str]
    channels: list[str]
    campaign_types: list[str]
    sent_dates: list[date]
    preview: list[dict[str, Any]]
    campaigns: list[CampaignRow] = field(default_factory=list, repr=False)
    warnings: list[str] = field(default_factory=list)
    warning_sent_date_from: date | None = None
    warning_sent_date_to: date | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ReportJob:
    id: str
    upload_id: str
    filename: str
    state: JobState = JobState.QUEUED
    total_rows: int = 0
    processed_rows: int = 0
    successful_rows: int = 0
    failed_rows: int = 0
    skipped_rows: int = 0
    current_row: int | None = None
    current_brand: str | None = None
    results: list[RowResult] = field(default_factory=list)
    output_path: Path | None = None
    error: str | None = None
    agipl_attribution_brand: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def progress(self) -> float:
        if not self.total_rows:
            return 0.0
        return round((self.processed_rows / self.total_rows) * 100, 1)
