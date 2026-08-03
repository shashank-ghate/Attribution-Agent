"""Collect MoEngage metrics for the orange VS rows from 16 July 2026.

The script deliberately does not write Google Sheets. It checkpoints every
completed row so a browser/UI interruption can be resumed without rerunning
finished campaigns. The reviewed results are written through the Sheets API.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date

from app.config.settings import settings
from app.models.report import CampaignRow
from app.services.moengage_service import MoEngageService


CHECKPOINT = settings.storage_dir / "vs-orange-results.json"

CAMPAIGNS = [
    (2299, "WhatsApp", "Online", "6a5869e832cbfe6f229e8b36", "Online_TILI_ATC_CX (WA FB)"),
    (2300, "WhatsApp", "Online", "6a586a9b55e4173a5280ed4d", "Online_TILI_Event_CX (WA FB)"),
    (2301, "WhatsApp", "Offline", "6a586b0a55e4173a5280ed60", "Online_TILI_Non-Shoppers_CX (WA FB)"),
    (2302, "WhatsApp", "Online", "6a586b68823af6531def4d02", "Online_TILI_VSL_Cross-Cat_CX (WA FB)"),
    (2303, "WhatsApp", "Online", "6a586bd4fecd0aecdc61d958", "Online_TILI_Non-Txn_CX (WA FB)"),
    (2304, "WhatsApp", "Online", "6a586cd5be8417a4ff003385", "Online_TILI_Repeat_CX (WA FB)"),
    (2333, "SMS", "Online", "6a586d47131f40e315003af5", "Online_TILI_ATC_CX (SMS FB)"),
    (2334, "SMS", "Online", "6a586d89fa2b43a2c05e939e", "Online_TILI_Repeat_CX (SMS FB)"),
    (2335, "SMS", "Online", "6a586ddc32cbfe6f229e8d00", "Online_TILI_Event_CX (SMS FB)"),
    (2336, "SMS", "Online", "6a586f0206b3a3a36169e0b4", "Online_TILI_Non-Shoppers_CX (SMS FB)"),
    (2337, "SMS", "Online", "6a586f8a7b4904ad859ca7e7", "Online_TILI_VSL_Cross-Cat_CX (SMS FB)"),
    (2338, "SMS", "Online", "6a58700244a6626e51278e43", "Online_TILI_Non-Txn_CX (SMS FB)"),
]


def make_row(item: tuple[int, str, str, str, str]) -> CampaignRow:
    row_number, channel, campaign_type, campaign_id, campaign_name = item
    return CampaignRow(
        excel_row=row_number,
        campaign_date=date(2026, 7, 16),
        brand="VS",
        channel=channel,
        campaign_type=campaign_type,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        tracking_goal="16th - 19th July",
        start_date=date(2026, 7, 16),
        end_date=date(2026, 7, 19),
    )


def load_results() -> dict[str, dict]:
    if not CHECKPOINT.exists():
        return {}
    payload = json.loads(CHECKPOINT.read_text())
    return payload if isinstance(payload, dict) else {}


def save_results(results: dict[str, dict]) -> None:
    CHECKPOINT.write_text(json.dumps(results, indent=2, sort_keys=True))


async def main() -> None:
    results = load_results()
    requested_rows = {
        int(value) for value in os.getenv("ROWS", "").split(",") if value.strip()
    }
    recalculate_revenue = os.getenv("RECALCULATE_REVENUE") == "1"
    service = MoEngageService(settings)
    try:
        for item in CAMPAIGNS:
            row = make_row(item)
            if requested_rows and row.excel_row not in requested_rows:
                continue
            key = str(row.excel_row)
            saved = results.get(key, {})
            if saved.get("campaign_id") != row.campaign_id:
                saved = {
                    "excel_row": row.excel_row,
                    "campaign_id": row.campaign_id,
                    "campaign_name": row.campaign_name,
                    "channel": row.channel,
                    "campaign_type": row.campaign_type,
                }
            if "unique_users" not in saved:
                print(f"ROW {row.excel_row} START unique_users", flush=True)
                saved["unique_users"] = int(
                    await service.browser.query_metric(row, "unique_users")
                )
                results[key] = saved
                save_results(results)
                print(f"ROW {row.excel_row} DONE unique_users={saved['unique_users']}", flush=True)
            if recalculate_revenue or "total_revenue" not in saved:
                print(f"ROW {row.excel_row} START total_revenue", flush=True)
                saved["total_revenue"] = round(
                    await service.browser.query_metric(row, "total_revenue"), 2
                )
                results[key] = saved
                save_results(results)
                print(f"ROW {row.excel_row} DONE total_revenue={saved['total_revenue']}", flush=True)
            print(f"ROW {row.excel_row} COMPLETE", flush=True)
        print(json.dumps(results, indent=2, sort_keys=True), flush=True)
    finally:
        await service.browser.close()


if __name__ == "__main__":
    asyncio.run(main())
