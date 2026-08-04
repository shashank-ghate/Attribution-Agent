from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, model_validator


class HealthResponse(BaseModel):
    status: str
    moengage_mode: str
    configured_brands: list[str]
    google_configured: bool = False
    moengage_connected: bool = False
    mock_writes_enabled: bool = False


class UploadResponse(BaseModel):
    upload_id: str
    filename: str
    sheet_name: str
    row_count: int
    brands: list[str]
    channels: list[str]
    campaign_types: list[str]
    preview: list[dict[str, Any]]
    warnings: list[str]


class StartJobRequest(BaseModel):
    sheet_connection_id: str | None = None
    upload_id: str | None = None
    overwrite_existing: bool = True
    row_limit: int | None = Field(default=None, ge=1, le=10000)
    brands: list[str] = Field(min_length=1, max_length=50)
    channels: list[str] = Field(min_length=1, max_length=10)
    sent_date: date | None = None
    sent_date_from: date | None = None
    sent_date_to: date | None = None
    agipl_attribution_brand: str | None = None

    @model_validator(mode="after")
    def validate_sent_date_range(self):
        if self.sent_date and (self.sent_date_from or self.sent_date_to):
            raise ValueError("Use either sent_date or a sent-date range, not both")
        if bool(self.sent_date_from) != bool(self.sent_date_to):
            raise ValueError("Both sent_date_from and sent_date_to are required")
        if not self.sent_date and not self.sent_date_from:
            raise ValueError("Choose a sent date or sent-date range")
        if (
            self.sent_date_from
            and self.sent_date_to
            and self.sent_date_from > self.sent_date_to
        ):
            raise ValueError("sent_date_to must be on or after sent_date_from")
        has_agipl = any(brand.casefold() == "agipl" for brand in self.brands)
        if has_agipl and not (self.agipl_attribution_brand or "").strip():
            raise ValueError("Choose the attribution brand for AGIPL campaigns")
        if (self.agipl_attribution_brand or "").strip().casefold() == "agipl":
            raise ValueError("AGIPL cannot attribute campaigns to itself")
        return self


class StartJobResponse(BaseModel):
    job_id: str
    status: str


class SheetConnectRequest(BaseModel):
    spreadsheet_url: str = Field(min_length=10)
    worksheet_name: str = Field(default="Mastersheet", min_length=1, max_length=100)


class SheetConnectionResponse(BaseModel):
    connection_id: str
    spreadsheet_title: str
    worksheet_title: str
    row_count: int
    brands: list[str]
    channels: list[str]
    campaign_types: list[str]
    sent_dates: list[date]
    preview: list[dict[str, Any]]
    warnings: list[str]
    warning_sent_date_from: date
    warning_sent_date_to: date


class CampaignPreviewResponse(BaseModel):
    row_count: int
    preview: list[dict[str, Any]]


class MoEngageSessionResponse(BaseModel):
    status: Literal["connected", "waiting_for_login", "disconnected", "not_configured"]
    message: str
    profile_id: str = "default"
    profiles: list[str] = Field(default_factory=list)
    login_url: str | None = None


class MoEngageSessionRequest(BaseModel):
    profile_id: str = Field(default="default", min_length=1, max_length=120)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=512)


class RowResultResponse(BaseModel):
    excel_row: int
    brand: str
    channel: str
    campaign_type: str
    campaign_id: str
    campaign_name: str
    date_range: str
    status: str
    unique_users: int | None = None
    total_revenue: float | None = None
    online_unique_users: int | None = None
    offline_unique_users: int | None = None
    online_revenue: float | None = None
    offline_revenue: float | None = None
    message: str | None = None


class JobResponse(BaseModel):
    job_id: str
    filename: str
    status: str
    progress: float
    total_rows: int
    processed_rows: int
    successful_rows: int
    failed_rows: int
    skipped_rows: int
    current_row: int | None
    current_brand: str | None
    error: str | None
    download_ready: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    results: list[RowResultResponse] = Field(default_factory=list)


class HistoryResponse(BaseModel):
    jobs: list[JobResponse]
