from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import gspread
from dateutil import parser as date_parser
from google.oauth2.service_account import Credentials

from app.models.report import CampaignMetrics, CampaignRow
from app.services.excel_service import ExcelService, WorkbookValidationError
from app.utils.excel_utils import normalize_campaign_type, normalize_channel, parse_tracking_range


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


def previous_completed_week(reference_date: date | None = None) -> tuple[date, date]:
    """Return the previous Monday-through-Sunday period."""
    reference_date = reference_date or date.today()
    start = reference_date - timedelta(days=reference_date.weekday() + 7)
    return start, start + timedelta(days=6)


class GoogleSheetService:
    INPUT_HEADERS = (
        "Date",
        "Channel",
        "Brand",
        "Campaign Name",
        "Campaign Channel Type",
        "Track Goals for",
        "Campaign ID",
    )

    def __init__(self, credential_file: Path):
        self.credential_file = credential_file

    @property
    def configured(self) -> bool:
        return self.credential_file.exists()

    def service_account_email(self) -> str | None:
        if not self.configured:
            return None
        try:
            return json.loads(self.credential_file.read_text()).get("client_email")
        except (OSError, ValueError):
            return None

    def install_credentials(self, content: bytes) -> str:
        if len(content) > 128 * 1024:
            raise WorkbookValidationError("Google credential file is unexpectedly large")
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkbookValidationError("Choose a valid Google service-account JSON file") from exc
        if payload.get("type") != "service_account":
            raise WorkbookValidationError("This is not a Google service-account key")
        required = {"client_email", "private_key", "token_uri"}
        missing = sorted(key for key in required if not payload.get(key))
        if missing:
            raise WorkbookValidationError(
                "Google service-account key is missing: " + ", ".join(missing)
            )
        try:
            Credentials.from_service_account_info(payload, scopes=SCOPES)
        except (ValueError, TypeError) as exc:
            raise WorkbookValidationError("Google service-account key could not be validated") from exc

        self.credential_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.credential_file.with_suffix(".json.tmp")
        temporary.write_bytes(content)
        temporary.chmod(0o600)
        temporary.replace(self.credential_file)
        return str(payload["client_email"])

    def _client(self):
        if not self.configured:
            raise WorkbookValidationError(
                f"Google service-account file not found at {self.credential_file}. "
                "Add the JSON key and share the Google Sheet with its client_email."
            )
        credentials = Credentials.from_service_account_file(self.credential_file, scopes=SCOPES)
        return gspread.authorize(credentials)

    @staticmethod
    def spreadsheet_id(value: str) -> str:
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", value)
        if match:
            return match.group(1)
        if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", value.strip()):
            return value.strip()
        raise WorkbookValidationError("Enter a valid Google Sheets URL or spreadsheet ID")

    def connect_sync(
        self,
        url: str,
        worksheet_name: str,
        warning_sent_date_from: date | None = None,
        warning_sent_date_to: date | None = None,
    ):
        try:
            spreadsheet = self._client().open_by_key(self.spreadsheet_id(url))
        except PermissionError as exc:
            email = self.service_account_email() or "the service-account email shown in the app"
            raise WorkbookValidationError(
                "Google denied access to this spreadsheet. Open the sheet, click Share, "
                f"add {email} as an Editor, then try Connect sheet again."
            ) from exc
        except gspread.SpreadsheetNotFound as exc:
            raise WorkbookValidationError(
                "The spreadsheet was not found. Check that the Google Sheet URL is correct "
                "and that it has been shared with the service account."
            ) from exc
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound as exc:
            raise WorkbookValidationError(f"Worksheet {worksheet_name!r} was not found") from exc
        rows, warnings = self._read_worksheet(
            worksheet, warning_sent_date_from, warning_sent_date_to
        )
        return spreadsheet, worksheet, rows, warnings

    async def connect(
        self,
        url: str,
        worksheet_name: str,
        warning_sent_date_from: date | None = None,
        warning_sent_date_to: date | None = None,
    ):
        return await asyncio.to_thread(
            self.connect_sync,
            url,
            worksheet_name,
            warning_sent_date_from,
            warning_sent_date_to,
        )

    def _read_worksheet(
        self,
        worksheet,
        warning_sent_date_from: date | None = None,
        warning_sent_date_to: date | None = None,
    ) -> tuple[list[CampaignRow], list[str]]:
        values = worksheet.get("A:AF", value_render_option="FORMATTED_VALUE")
        if not values:
            raise WorkbookValidationError("Google Sheet is empty")
        headers = {str(value).strip(): index + 1 for index, value in enumerate(values[0]) if str(value).strip()}
        missing = sorted(ExcelService.REQUIRED_HEADERS - set(headers))
        if missing:
            raise WorkbookValidationError("Missing required columns: " + ", ".join(missing))
        campaigns, warnings = [], []

        def cell(row, header):
            index = headers[header] - 1
            return row[index] if index < len(row) else ""

        for row_number, row in enumerate(values[1:], start=2):
            input_values = {
                header: str(cell(row, header) or "").strip()
                for header in self.INPUT_HEADERS
            }
            if not any(input_values.values()):
                continue
            raw_date = cell(row, "Date")
            warning_in_scope = True
            if warning_sent_date_from and warning_sent_date_to:
                try:
                    warning_date = date_parser.parse(raw_date, dayfirst=True).date()
                    warning_in_scope = (
                        warning_sent_date_from
                        <= warning_date
                        <= warning_sent_date_to
                    )
                except (ValueError, TypeError, OverflowError):
                    # A row without a usable sent date cannot be assigned to the
                    # requested weekly problem window.
                    warning_in_scope = False
            blank_headers = [
                header for header, value in input_values.items() if not value
            ]
            if blank_headers:
                if warning_in_scope:
                    warnings.append(
                        f"Row {row_number}: blank required cell(s): "
                        + ", ".join(blank_headers)
                    )
                continue
            campaign_id = input_values["Campaign ID"]
            try:
                campaign_date = date_parser.parse(raw_date, dayfirst=True).date()
                brand = input_values["Brand"]
                channel = normalize_channel(cell(row, "Channel"))
                campaign_type = normalize_campaign_type(cell(row, "Campaign Channel Type"))
                tracking_goal = cell(row, "Track Goals for")
                start_date, end_date = parse_tracking_range(tracking_goal, campaign_date)
                metric_value = lambda header: (
                    float(cell(row, header).replace(",", "")) if cell(row, header) else None
                )
                campaigns.append(CampaignRow(
                    excel_row=row_number,
                    campaign_date=campaign_date,
                    brand=brand,
                    channel=channel,
                    campaign_type=campaign_type,
                    campaign_id=campaign_id,
                    campaign_name=cell(row, "Campaign Name").strip(),
                    tracking_goal=tracking_goal,
                    start_date=start_date,
                    end_date=end_date,
                    existing_unique_users=metric_value("Campaign Purchased Customers"),
                    existing_revenue=metric_value("Influenced Revenue"),
                    existing_online_unique_users=metric_value("Campaign Purchased Customers - Online"),
                    existing_offline_unique_users=metric_value("Campaign Purchased Customers - Offline"),
                    existing_online_revenue=metric_value("Influenced Revenue - Online"),
                    existing_offline_revenue=metric_value("Influenced Revenue - Offline"),
                ))
            except (ValueError, TypeError, OverflowError) as exc:
                if warning_in_scope:
                    warnings.append(f"Row {row_number}: {exc}")
        if not campaigns:
            raise WorkbookValidationError("No processable campaign rows were found")
        return campaigns, warnings

    async def read_campaigns(self, spreadsheet_id: str, worksheet_name: str):
        def read():
            sheet = self._client().open_by_key(spreadsheet_id).worksheet(worksheet_name)
            return self._read_worksheet(sheet)
        return await asyncio.to_thread(read)

    async def write_metrics(self, spreadsheet_id: str, worksheet_name: str, row: CampaignRow, metrics: CampaignMetrics):
        columns = {
            "Campaign Purchased Customers": "AA", "Campaign Purchased Customers - Online": "AB",
            "Campaign Purchased Customers - Offline": "AC", "Influenced Revenue": "AD",
            "Influenced Revenue - Online": "AE", "Influenced Revenue - Offline": "AF",
        }
        values = ExcelService.metric_values(row.campaign_type, metrics)
        def write():
            worksheet = self._client().open_by_key(spreadsheet_id).worksheet(worksheet_name)
            worksheet.batch_update(
                [
                    {"range": f"{columns[header]}{row.excel_row}", "values": [[value]]}
                    for header, value in values.items()
                ],
                value_input_option="USER_ENTERED",
            )
        await asyncio.to_thread(write)
