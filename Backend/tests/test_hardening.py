import asyncio
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from playwright.async_api import Error as PlaywrightError

from app.config.settings import Settings
from app.core.dependencies import get_report_service
from app.main import app
from app.models.report import (
    CampaignMetrics,
    CampaignRow,
    JobState,
    ReportJob,
    RowResult,
    SheetConnection,
)
from app.schemas.report_schema import StartJobRequest
from app.services.google_sheet_service import GoogleSheetService
from app.services.moengage_browser_service import (
    BrowserAutomationError,
    BrowserUnavailableError,
    MoEngageBrowserService,
)
from app.services.report_service import ReportService
from app.utils.excel_utils import parse_optional_number, parse_tracking_range


class RequestSafetyTests(unittest.TestCase):
    def test_job_requires_brand_channel_and_date_scope(self):
        invalid_payloads = [
            {},
            {"brands": ["Aldo"], "channels": ["SMS"]},
            {
                "brands": [],
                "channels": ["SMS"],
                "sent_date": "2026-08-01",
            },
            {
                "brands": ["Aldo"],
                "channels": [],
                "sent_date": "2026-08-01",
            },
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                StartJobRequest(**payload)

    def test_job_rejects_conflicting_single_and_range_dates(self):
        with self.assertRaisesRegex(ValidationError, "either sent_date"):
            StartJobRequest(
                brands=["Aldo"],
                channels=["SMS"],
                sent_date="2026-08-01",
                sent_date_from="2026-08-01",
                sent_date_to="2026-08-02",
            )

    def test_job_accepts_a_bounded_production_selection(self):
        request = StartJobRequest(
            brands=["Aldo"],
            channels=["SMS"],
            sent_date_from="2026-08-01",
            sent_date_to="2026-08-02",
        )
        self.assertEqual(request.brands, ["Aldo"])


class DataIntegrityTests(unittest.TestCase):
    def test_formatted_sheet_numbers_are_parsed(self):
        cases = {
            "₹4,99,279.00": 499279.0,
            " 1,234 ": 1234.0,
            "(2,500.50)": -2500.5,
            42: 42.0,
            "": None,
            None: None,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(parse_optional_number(value), expected)

    def test_invalid_nonblank_number_is_not_treated_as_empty(self):
        with self.assertRaisesRegex(ValueError, "Invalid numeric metric"):
            parse_optional_number("not available")

    def test_invalid_goal_range_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Could not parse goal date range"):
            parse_tracking_range("definitely not a date", date(2026, 8, 1))
        with self.assertRaisesRegex(ValueError, "Could not parse goal date range"):
            parse_tracking_range("5 Aug 2026 - 1 Aug 2026", date(2026, 8, 5))

    def test_google_worksheet_objects_are_cached(self):
        with tempfile.TemporaryDirectory() as folder:
            service = GoogleSheetService(Path(folder) / "key.json")
            worksheet = object()
            spreadsheet = MagicMock()
            spreadsheet.worksheet.return_value = worksheet
            client = MagicMock()
            client.open_by_key.return_value = spreadsheet
            service._client = MagicMock(return_value=client)

            first = service._worksheet("sheet-1", "Mastersheet")
            second = service._worksheet("sheet-1", "Mastersheet")

            self.assertIs(first, worksheet)
            self.assertIs(second, worksheet)
            client.open_by_key.assert_called_once_with("sheet-1")
            spreadsheet.worksheet.assert_called_once_with("Mastersheet")


class RecoveryAndLifecycleTests(unittest.TestCase):
    def test_browser_readiness_waits_through_transient_cdp_failures(self):
        async def scenario():
            service = MoEngageBrowserService(
                Path("profile"),
                "https://dashboard-03.moengage.com/",
                {},
                "http://browser.internal:9222",
            )
            service._ensure_browser = AsyncMock(side_effect=[
                BrowserUnavailableError("starting"),
                BrowserUnavailableError("starting"),
                None,
            ])

            await service.wait_until_ready(
                timeout_seconds=1,
                retry_interval_seconds=0,
            )

            self.assertEqual(service._ensure_browser.await_count, 3)

        asyncio.run(scenario())

    def test_browser_readiness_timeout_explains_that_no_rows_were_processed(self):
        async def scenario():
            service = MoEngageBrowserService(
                Path("profile"),
                "https://dashboard-03.moengage.com/",
                {},
                "http://browser.internal:9222",
            )
            service._ensure_browser = AsyncMock(
                side_effect=BrowserUnavailableError("still down")
            )

            with self.assertRaisesRegex(BrowserUnavailableError, "No campaign rows"):
                await service.wait_until_ready(timeout_seconds=0)

        asyncio.run(scenario())

    def test_campaign_query_retries_after_browser_restarts(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as folder:
                service = ReportService(Settings(
                    storage_dir=Path(folder),
                    moengage_max_retries=2,
                ))
                row = SimpleNamespace(excel_row=2564)
                expected = CampaignMetrics(
                    unique_users=2,
                    total_revenue=500,
                    online_unique_users=2,
                    online_revenue=500,
                )
                service.moengage.fetch_metrics = AsyncMock(side_effect=[
                    BrowserUnavailableError("Chromium restarted"),
                    expected,
                ])
                service.moengage.wait_until_ready = AsyncMock()

                actual = await service._fetch_metrics_with_browser_recovery(row)

                self.assertIs(actual, expected)
                self.assertEqual(service.moengage.fetch_metrics.await_count, 2)
                service.moengage.wait_until_ready.assert_awaited_once()

        asyncio.run(scenario())

    def test_failed_browser_preflight_does_not_consume_sheet_rows(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as folder:
                service = ReportService(Settings(storage_dir=Path(folder)))
                campaigns = [
                    CampaignRow(
                        excel_row=row_number,
                        campaign_date=date(2026, 8, 1),
                        brand="Aldo",
                        channel="SMS",
                        campaign_type="Online",
                        campaign_id=f"campaign-{row_number}",
                        campaign_name=f"Campaign {row_number}",
                        tracking_goal="1-2 Aug 2026",
                        start_date=date(2026, 8, 1),
                        end_date=date(2026, 8, 2),
                    )
                    for row_number in (2564, 2565)
                ]
                service.google.read_campaigns = AsyncMock(return_value=(campaigns, []))
                service.moengage.wait_until_ready = AsyncMock(
                    side_effect=BrowserUnavailableError("browser did not recover")
                )
                service.moengage.fetch_metrics = AsyncMock()
                connection = SheetConnection(
                    id="connection-1",
                    spreadsheet_id="sheet-1",
                    spreadsheet_url="https://docs.google.com/spreadsheets/d/sheet-1",
                    spreadsheet_title="Master Sheet",
                    worksheet_title="Mastersheet",
                    row_count=2,
                    brands=["Aldo"],
                    channels=["SMS"],
                    campaign_types=["Online"],
                    sent_dates=[date(2026, 8, 1)],
                    preview=[],
                    campaigns=campaigns,
                )
                job = ReportJob(
                    id="job-1", upload_id=connection.id, filename="Master Sheet"
                )

                await service._process_sheet(
                    job,
                    connection,
                    overwrite=True,
                    row_limit=None,
                    brands=["Aldo"],
                    channels=["SMS"],
                    sent_date_from=date(2026, 8, 1),
                    sent_date_to=date(2026, 8, 1),
                )

                self.assertEqual(job.state, JobState.FAILED)
                self.assertEqual(job.total_rows, 2)
                self.assertEqual(job.processed_rows, 0)
                self.assertEqual(job.results, [])
                service.moengage.fetch_metrics.assert_not_awaited()

        asyncio.run(scenario())

    def test_final_target_crash_prepares_clean_tab_for_next_row(self):
        async def scenario():
            service = MoEngageBrowserService(
                Path("profile"),
                "https://dashboard-03.moengage.com/",
                {"workflow": "recorded_behavior"},
                "http://browser.internal:9222",
            )
            service.page = SimpleNamespace(
                url="https://dashboard-03.moengage.com/v4/dashboards/aldo"
            )
            service._ensure_browser = AsyncMock()
            service.status = AsyncMock(return_value=("connected", "Connected"))
            service._query_recorded_behavior = AsyncMock(
                side_effect=[
                    PlaywrightError("Target crashed"),
                    PlaywrightError("Target crashed again"),
                ]
            )
            service._replace_remote_page = AsyncMock()
            row = SimpleNamespace(excel_row=2562)

            with self.assertRaisesRegex(BrowserAutomationError, "tab crashed"):
                await service.query_metric(row, "unique_users")
            self.assertEqual(service._replace_remote_page.await_count, 2)

        asyncio.run(scenario())

    def test_sheet_job_continues_after_one_campaign_failure(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as folder:
                service = ReportService(Settings(storage_dir=Path(folder)))
                campaigns = [
                    CampaignRow(
                        excel_row=row_number,
                        campaign_date=date(2026, 8, 1),
                        brand="Aldo",
                        channel="SMS",
                        campaign_type="Online",
                        campaign_id=f"campaign-{row_number}",
                        campaign_name=f"Campaign {row_number}",
                        tracking_goal="1-2 Aug 2026",
                        start_date=date(2026, 8, 1),
                        end_date=date(2026, 8, 2),
                    )
                    for row_number in (10, 11)
                ]
                service.google.read_campaigns = AsyncMock(
                    return_value=(campaigns, [])
                )
                service.google.write_metrics = AsyncMock()
                service.moengage.fetch_metrics = AsyncMock(side_effect=[
                    RuntimeError("MoEngage temporary failure"),
                    CampaignMetrics(
                        unique_users=3,
                        total_revenue=1200,
                        online_unique_users=3,
                        online_revenue=1200,
                    ),
                ])
                connection = SheetConnection(
                    id="connection-1",
                    spreadsheet_id="sheet-1",
                    spreadsheet_url="https://docs.google.com/spreadsheets/d/sheet-1",
                    spreadsheet_title="Master Sheet",
                    worksheet_title="Mastersheet",
                    row_count=2,
                    brands=["Aldo"],
                    channels=["SMS"],
                    campaign_types=["Online"],
                    sent_dates=[date(2026, 8, 1)],
                    preview=[],
                    campaigns=campaigns,
                )
                job = ReportJob(
                    id="job-1", upload_id=connection.id, filename="Master Sheet"
                )
                service.jobs[job.id] = job

                await service._process_sheet(
                    job,
                    connection,
                    overwrite=True,
                    row_limit=None,
                    brands=["Aldo"],
                    channels=["SMS"],
                    sent_date_from=date(2026, 8, 1),
                    sent_date_to=date(2026, 8, 1),
                )

                self.assertEqual(job.state, JobState.COMPLETED)
                self.assertEqual(job.processed_rows, 2)
                self.assertEqual(job.failed_rows, 1)
                self.assertEqual(job.successful_rows, 1)
                self.assertEqual(job.results[0].status, "failed")
                self.assertEqual(job.results[1].status, "success")
                service.google.write_metrics.assert_awaited_once()

        asyncio.run(scenario())

    def test_shutdown_cancels_active_work_before_closing_browser(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as folder:
                service = ReportService(Settings(storage_dir=Path(folder)))
                service.moengage.browser.close = AsyncMock()
                job = ReportJob(id="job-1", upload_id="sheet", filename="Sheet")
                job.state = JobState.PROCESSING
                task = asyncio.create_task(asyncio.sleep(60))
                service.jobs[job.id] = job
                service.tasks[job.id] = task

                await service.shutdown()

                self.assertEqual(job.state, JobState.CANCELLED)
                self.assertTrue(task.cancelled())
                service.moengage.browser.close.assert_awaited_once()

        asyncio.run(scenario())

    def test_completed_job_history_is_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            service = ReportService(Settings(storage_dir=Path(folder)))
            for index in range(110):
                job = ReportJob(
                    id=f"job-{index}", upload_id="sheet", filename="Sheet"
                )
                job.state = JobState.COMPLETED
                service.jobs[job.id] = job
            service._prune_memory()
            self.assertEqual(len(service.jobs), 100)
            self.assertNotIn("job-0", service.jobs)
            self.assertIn("job-109", service.jobs)

    def test_cancel_terminates_task_and_makes_current_row_retryable(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as folder:
                service = ReportService(Settings(storage_dir=Path(folder)))
                job = ReportJob(id="job-1", upload_id="sheet", filename="Sheet")
                job.state = JobState.PROCESSING
                job.total_rows = 4
                job.current_row = 22
                job.current_brand = "Aldo"
                job.results.append(RowResult(
                    excel_row=22,
                    brand="Aldo",
                    channel="SMS",
                    campaign_type="Online",
                    campaign_id="campaign",
                    campaign_name="Campaign",
                    date_range="2026-08-01 → 2026-08-02",
                    status="processing",
                ))
                task = asyncio.create_task(asyncio.sleep(60))
                service.jobs[job.id] = job
                service.tasks[job.id] = task

                cancelled = service.cancel_job(job.id)
                await asyncio.sleep(0)

                self.assertEqual(cancelled.state, JobState.CANCELLED)
                self.assertTrue(task.cancelled())
                self.assertEqual(cancelled.results[-1].status, "failed")
                self.assertIn("cancelled", cancelled.results[-1].message)
                self.assertEqual(cancelled.failed_rows, 1)
                self.assertEqual(cancelled.processed_rows, 1)
                self.assertIsNotNone(cancelled.finished_at)

        asyncio.run(scenario())


class EnvironmentParsingTests(unittest.TestCase):
    def test_railway_origin_and_browser_timeout_are_loaded(self):
        environment = {
            "CORS_ORIGINS": "https://frontend.example.test",
            "RAILWAY_PUBLIC_DOMAIN": "app.example.test",
            "MOENGAGE_BROWSER_QUERY_TIMEOUT_SECONDS": "240",
        }
        with patch.dict(os.environ, environment, clear=False):
            settings = Settings.from_env()
        self.assertIn("https://frontend.example.test", settings.cors_origins)
        self.assertIn("https://app.example.test", settings.cors_origins)
        self.assertEqual(settings.moengage_browser_query_timeout_seconds, 240)


class ApiFailureBoundaryTests(unittest.TestCase):
    def test_start_endpoint_rejects_unbounded_run(self):
        with TestClient(app) as client:
            response = client.post("/api/jobs", json={"sheet_connection_id": "sheet"})
        self.assertEqual(response.status_code, 422)

    def test_preview_rejects_partial_and_reversed_ranges(self):
        with TestClient(app) as client:
            partial = client.get(
                "/api/google/connections/missing/campaigns",
                params={"sent_date_from": "2026-08-01"},
            )
            reversed_range = client.get(
                "/api/google/connections/missing/campaigns",
                params={
                    "sent_date_from": "2026-08-02",
                    "sent_date_to": "2026-08-01",
                },
            )
        self.assertEqual(partial.status_code, 422)
        self.assertEqual(reversed_range.status_code, 422)

    def test_unknown_job_endpoints_return_not_found(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/jobs/missing").status_code, 404)
            self.assertEqual(
                client.post("/api/jobs/missing/cancel").status_code, 404
            )
            self.assertEqual(
                client.get("/api/jobs/missing/results.csv").status_code, 404
            )

    def test_disconnected_browser_blocks_a_valid_job_before_creation(self):
        service = get_report_service()
        original_status = service.moengage.browser.status
        service.moengage.browser.status = AsyncMock(
            return_value=("disconnected", "Complete MoEngage login")
        )
        try:
            with TestClient(app) as client:
                response = client.post("/api/jobs", json={
                    "sheet_connection_id": "missing",
                    "brands": ["Aldo"],
                    "channels": ["SMS"],
                    "sent_date_from": "2026-08-01",
                    "sent_date_to": "2026-08-02",
                })
            self.assertEqual(response.status_code, 409)
            self.assertIn("Complete MoEngage login", response.json()["detail"])
        finally:
            service.moengage.browser.status = original_status


if __name__ == "__main__":
    unittest.main()
