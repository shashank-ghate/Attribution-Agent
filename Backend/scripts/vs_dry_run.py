"""Run one VS campaign through MoEngage without writing to Google Sheets."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.config.settings import settings
from app.services.excel_service import ExcelService
from app.services.moengage_service import MoEngageService


WORKBOOK = Path(__file__).resolve().parents[1] / "data" / "Apparel Master Sheet_2026.xlsx"


async def main() -> None:
    _, rows, _ = ExcelService().read_campaigns(WORKBOOK)
    campaign = next(
        row
        for row in rows
        if row.brand.casefold() == "vs"
        and (row.existing_unique_users is None or row.existing_revenue is None)
    )
    service = MoEngageService(settings)
    try:
        result = {
            "excel_row": campaign.excel_row,
            "brand": campaign.brand,
            "channel": campaign.channel,
            "campaign_type": campaign.campaign_type,
            "campaign_id": campaign.campaign_id,
            "campaign_name": campaign.campaign_name,
            "start_date": campaign.start_date.isoformat(),
            "end_date": campaign.end_date.isoformat(),
        }
        checkpoint = settings.storage_dir / "vs-dry-run.json"
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text())
            if saved.get("campaign_id") == campaign.campaign_id and "unique_users" in saved:
                result["unique_users"] = int(saved["unique_users"])
                print(f"RESUME unique_users={result['unique_users']}", flush=True)
        if "unique_users" not in result:
            print("START unique_users", flush=True)
            result["unique_users"] = int(await service.browser.query_metric(campaign, "unique_users"))
            checkpoint.write_text(json.dumps(result, indent=2))
            print(f"DONE unique_users={result['unique_users']}", flush=True)
        print("START total_revenue", flush=True)
        result["total_revenue"] = round(
            await service.browser.query_metric(campaign, "total_revenue"), 2
        )
        checkpoint.write_text(json.dumps(result, indent=2))
        print(f"DONE total_revenue={result['total_revenue']}", flush=True)
        print(json.dumps(result, indent=2), flush=True)
    finally:
        await service.browser.close()


if __name__ == "__main__":
    asyncio.run(main())
