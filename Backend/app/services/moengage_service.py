"""MoEngage query adapter.

The public Campaign Report API downloads preconfigured exports; it does not expose
the dashboard's per-event query builder. Production mode therefore targets the
customer-specific query endpoint supplied by MoEngage, while mock mode makes the
whole application testable before those credentials are provided.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx

from app.config.settings import Settings
from app.models.report import CampaignMetrics, CampaignRow
from app.services.moengage_browser_service import MoEngageBrowserService


class MoEngageError(RuntimeError):
    pass


class MoEngageService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.profiles_dir = settings.storage_dir / "moengage-profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.active_profile = "default"
        self.browser = self._new_browser(self._profile_path(self.active_profile))

    def _new_browser(self, profile_dir: Path) -> MoEngageBrowserService:
        return MoEngageBrowserService(
            profile_dir,
            self.settings.moengage_dashboard_url,
            self.settings.moengage_ui_config,
        )

    @staticmethod
    def normalize_profile_id(profile_id: str | None) -> str:
        value = (profile_id or "default").strip().casefold()
        value = re.sub(r"[^a-z0-9@._-]+", "-", value).strip("-.")
        if not value:
            value = "default"
        if len(value) > 80:
            digest = hashlib.sha256(value.encode()).hexdigest()[:10]
            value = f"{value[:69]}-{digest}"
        return value

    def _profile_path(self, profile_id: str) -> Path:
        profile_id = self.normalize_profile_id(profile_id)
        # Preserve the original installation's saved session as the default.
        if profile_id == "default":
            return self.settings.storage_dir / "moengage-profile"
        return self.profiles_dir / profile_id

    def available_profiles(self) -> list[str]:
        profiles = {"default"}
        if self.profiles_dir.exists():
            profiles.update(path.name for path in self.profiles_dir.iterdir() if path.is_dir())
        return sorted(profiles)

    async def select_profile(self, profile_id: str | None) -> str:
        normalized = self.normalize_profile_id(profile_id)
        if normalized == self.active_profile:
            return normalized
        await self.browser.close()
        self.active_profile = normalized
        self.browser = self._new_browser(self._profile_path(normalized))
        return normalized

    async def reset_profile(self, profile_id: str | None) -> str:
        import shutil

        normalized = await self.select_profile(profile_id)
        await self.browser.close()
        path = self._profile_path(normalized)
        if path.exists():
            await asyncio.to_thread(shutil.rmtree, path)
        self.browser = self._new_browser(path)
        return normalized

    def configured_brands(self) -> list[str]:
        if self.settings.moengage_mode == "browser":
            query_url_map = self.settings.moengage_ui_config.get("query_url_map") or {}
            if isinstance(query_url_map, dict):
                return sorted(query_url_map, key=str.casefold)
        return sorted(self.settings.moengage_brand_config)

    async def fetch_metrics(self, row: CampaignRow) -> CampaignMetrics:
        if self.settings.moengage_mode == "mock":
            if row.campaign_type == "Overall":
                online = await self._mock_metrics(replace(row, campaign_type="Online"))
                offline = await self._mock_metrics(replace(row, campaign_type="Offline"))
                return self._combine_metrics(online, offline)
            return await self._mock_metrics(row)
        if self.settings.moengage_mode == "browser":
            # A single dashboard page is intentionally used in sequence so filters
            # from two campaigns can never race with one another.
            if row.campaign_type == "Overall":
                online = replace(row, campaign_type="Online")
                offline = replace(row, campaign_type="Offline")
                online_users = await self.browser.query_metric(online, "unique_users")
                offline_users = await self.browser.query_metric(offline, "unique_users")
                online_revenue = await self.browser.query_metric(online, "total_revenue")
                offline_revenue = await self.browser.query_metric(offline, "total_revenue")
                return self._combine_metrics(
                    self._typed_metrics("Online", online_users, online_revenue),
                    self._typed_metrics("Offline", offline_users, offline_revenue),
                )
            unique_users = await self.browser.query_metric(row, "unique_users")
            total_revenue = await self.browser.query_metric(row, "total_revenue")
            return self._typed_metrics(row.campaign_type, unique_users, total_revenue)
        if self.settings.moengage_mode != "api":
            raise MoEngageError(f"Unsupported MOENGAGE_MODE: {self.settings.moengage_mode}")
        if row.campaign_type == "Overall":
            online = replace(row, campaign_type="Online")
            offline = replace(row, campaign_type="Offline")
            online_users, offline_users, online_revenue, offline_revenue = await asyncio.gather(
                self._query_metric(online, "unique_users"),
                self._query_metric(offline, "unique_users"),
                self._query_metric(online, "total_revenue"),
                self._query_metric(offline, "total_revenue"),
            )
            return self._combine_metrics(
                self._typed_metrics("Online", online_users, online_revenue),
                self._typed_metrics("Offline", offline_users, offline_revenue),
            )
        unique_users, total_revenue = await asyncio.gather(
            self._query_metric(row, "unique_users"),
            self._query_metric(row, "total_revenue"),
        )
        return self._typed_metrics(row.campaign_type, unique_users, total_revenue)

    @staticmethod
    def _typed_metrics(campaign_type: str, unique_users: float, revenue: float) -> CampaignMetrics:
        users = int(unique_users)
        total_revenue = round(float(revenue), 2)
        if (users == 0) != (total_revenue == 0):
            raise MoEngageError(
                "MoEngage returned inconsistent attribution metrics: "
                f"unique_users={users}, revenue={total_revenue}. "
                "The campaign was not written to Google Sheets; retry it after "
                "the MoEngage query finishes refreshing."
            )
        if campaign_type == "Online":
            return CampaignMetrics(
                users, total_revenue,
                online_unique_users=users, online_revenue=total_revenue,
            )
        if campaign_type == "Offline":
            return CampaignMetrics(
                users, total_revenue,
                offline_unique_users=users, offline_revenue=total_revenue,
            )
        raise MoEngageError(f"Unsupported campaign type {campaign_type!r}")

    @staticmethod
    def _combine_metrics(online: CampaignMetrics, offline: CampaignMetrics) -> CampaignMetrics:
        online_users = online.online_unique_users or 0
        offline_users = offline.offline_unique_users or 0
        online_revenue = online.online_revenue or 0.0
        offline_revenue = offline.offline_revenue or 0.0
        return CampaignMetrics(
            unique_users=online_users + offline_users,
            total_revenue=round(online_revenue + offline_revenue, 2),
            online_unique_users=online_users,
            offline_unique_users=offline_users,
            online_revenue=online_revenue,
            offline_revenue=offline_revenue,
        )

    async def _mock_metrics(self, row: CampaignRow) -> CampaignMetrics:
        await asyncio.sleep(0.012)
        digest = hashlib.sha256(
            f"{row.brand}|{row.channel}|{row.campaign_type}|{row.campaign_id}|{row.start_date}|{row.end_date}".encode()
        ).hexdigest()
        users = int(digest[:8], 16) % 1800
        revenue = round(users * (250 + (int(digest[8:12], 16) % 2400) / 10), 2)
        return self._typed_metrics(row.campaign_type, users, revenue)

    def _brand_config(self, brand: str) -> dict[str, Any]:
        for key, config in self.settings.moengage_brand_config.items():
            if key.casefold() == brand.casefold():
                return config
        raise MoEngageError(f"No MoEngage workspace configuration found for brand {brand!r}")

    async def _query_metric(self, row: CampaignRow, metric: str) -> float:
        config = self._brand_config(row.brand)
        endpoint = config.get("query_url")
        if not endpoint:
            raise MoEngageError(f"query_url is missing for brand {row.brand!r}")
        payload = {
            "workspace_id": config.get("workspace_id"),
            "metric": metric,
            "aggregation": "unique_users" if metric == "unique_users" else "sum",
            "date_range": {"from": row.start_date.isoformat(), "to": row.end_date.isoformat()},
            "filters": {
                "brand": row.brand,
                "campaign_channel_type": row.campaign_type.lower(),
                "channel": row.channel.lower(),
                "readable_campaign_id": row.campaign_id,
            },
        }
        headers = {"Accept": "application/json", **config.get("headers", {})}
        if config.get("api_key"):
            headers.setdefault("Authorization", f"Bearer {config['api_key']}")
        auth = None
        if config.get("username") and config.get("password"):
            auth = httpx.BasicAuth(config["username"], config["password"])

        last_error: Exception | None = None
        for attempt in range(self.settings.moengage_max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.settings.moengage_timeout_seconds) as client:
                    response = await client.post(endpoint, json=payload, headers=headers, auth=auth)
                response.raise_for_status()
                return self._extract_metric(response.json(), metric)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                last_error = exc
                if attempt < self.settings.moengage_max_retries:
                    await asyncio.sleep(0.4 * (2**attempt))
        raise MoEngageError(f"MoEngage {metric} query failed for row {row.excel_row}: {last_error}")

    @staticmethod
    def _extract_metric(data: Any, metric: str) -> float:
        candidates = [
            data.get(metric) if isinstance(data, dict) else None,
            data.get("value") if isinstance(data, dict) else None,
            data.get("data", {}).get(metric) if isinstance(data, dict) and isinstance(data.get("data"), dict) else None,
            data.get("data", {}).get("value") if isinstance(data, dict) and isinstance(data.get("data"), dict) else None,
            data.get("result", {}).get(metric) if isinstance(data, dict) and isinstance(data.get("result"), dict) else None,
        ]
        for value in candidates:
            if value is not None:
                return float(value)
        raise MoEngageError(f"Response did not contain metric {metric!r}")
