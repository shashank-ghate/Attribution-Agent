from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import (
    BrowserContext,
    Browser,
    Error as PlaywrightError,
    Page,
    Playwright,
    async_playwright,
)

from app.models.report import CampaignRow


class BrowserAutomationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BehaviorQueryPlan:
    transaction_operator: str
    delivery_event: str
    analysis_type: str
    result_row_label: str
    aggregation: str | None = None
    aggregation_attribute: str | None = None


DELIVERY_EVENTS = {
    "WhatsApp": "WhatsApp Message Delivered",
    "SMS": "SMS Delivered",
    "RCS": "RCS Delivered",
}
DELIVERY_LOOKBACK_DAYS = 120
CIS_BRAND_OPERATOR = "(any of) contains"
CIS_BRAND_VALUE = "SP"

PURCHASED_CUSTOMERS_TITLE = re.compile(
    r"(?:Number\s+of|Campaign)\s+Purc(?:hased|ahsed)\s+Customers", re.I
)
CIS_EVENT_BRAND_PATTERN = re.compile(
    r"Brand_PM.*?contains.*?\bSP\b",
    re.I | re.S,
)


def build_behavior_query_plan(row: CampaignRow, metric: str) -> BehaviorQueryPlan:
    if row.campaign_type not in {"Online", "Offline"}:
        raise BrowserAutomationError("Overall rows must be split into Online and Offline queries")
    try:
        delivery_event = DELIVERY_EVENTS[row.channel]
    except KeyError as exc:
        raise BrowserAutomationError(f"No delivered-event mapping for channel {row.channel!r}") from exc
    operator = "exists" if row.campaign_type == "Online" else "does not exist"
    if metric == "unique_users":
        return BehaviorQueryPlan(operator, delivery_event, "Unique users", "Sale_Array")
    if metric == "total_revenue":
        return BehaviorQueryPlan(
            operator,
            delivery_event,
            "Aggregation",
            "Sum of Order_Net_Val in Sale_Array",
            aggregation="Sum",
            aggregation_attribute="Order_Net_Val",
        )
    raise BrowserAutomationError(f"Unsupported metric {metric!r}")


class MoEngageBrowserService:
    def __init__(
        self,
        profile_dir: Path,
        dashboard_url: str,
        ui_config: dict[str, Any],
        remote_cdp_url: str = "",
    ):
        self.profile_dir = profile_dir
        self.dashboard_url = dashboard_url
        self.ui = ui_config
        self.remote_cdp_url = remote_cdp_url
        self.playwright: Playwright | None = None
        self.remote_browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.lock = asyncio.Lock()

    async def start_login(self, login_hint: str | None = None, password: str | None = None) -> str:
        async with self.lock:
            await self._ensure_browser(headless=False)
            await self.page.goto(self.dashboard_url, wait_until="domcontentloaded")
            if self.page.url == "about:blank":
                raise BrowserAutomationError("Chrome opened but did not navigate to MoEngage")
            if self.context:
                for page in list(self.context.pages):
                    if page is not self.page and not page.is_closed() and page.url == "about:blank":
                        await page.close()
            await self.page.bring_to_front()
            state, _ = await self.status()
            if state == "connected":
                return (
                    f"The saved Google profile for {login_hint} is already connected to MoEngage. "
                    "No password was stored or reused by the application."
                )
            hinted, password_submitted = await self._open_google_login(login_hint, password)
            if password_submitted:
                return (
                    f"Google accepted the login details for {login_hint}. Complete MFA or any Google "
                    "security check, then click Verify login. The password was not saved."
                )
            if hinted:
                return (
                    f"Google login is open for {login_hint}, but the password step could not be completed "
                    "automatically. Enter it in the Google window, complete MFA, then click Verify login."
                )
            return "A MoEngage window is open. Choose Google, finish password/MFA, then click Verify login."

    async def _open_google_login(
        self,
        login_hint: str | None,
        password: str | None,
    ) -> tuple[bool, bool]:
        """Open Google SSO, enter request-scoped credentials, and leave MFA to the user."""
        if not login_hint or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", login_hint.strip()):
            return False, False
        hint = login_hint.strip()
        page = self.page
        try:
            if "accounts.google.com" not in page.url:
                candidates = [
                    page.get_by_role("button", name=re.compile(r"Google", re.I)).first,
                    page.get_by_text(re.compile(r"^Google$", re.I)).first,
                    page.locator("button").filter(has_text=re.compile(r"Google", re.I)).first,
                ]
                google = None
                for candidate in candidates:
                    try:
                        await candidate.wait_for(state="visible", timeout=12000)
                        google = candidate
                        break
                    except Exception:
                        continue
                if google is None:
                    return False, False
                await google.click()
                await page.wait_for_timeout(1200)

            if self.context:
                google_pages = [
                    candidate for candidate in self.context.pages
                    if not candidate.is_closed() and "accounts.google.com" in candidate.url
                ]
                if google_pages:
                    page = google_pages[-1]
                    self.page = page
                    await page.bring_to_front()

            try:
                await page.wait_for_url(re.compile(r"accounts\.google\.com"), timeout=10000)
            except Exception:
                return False, False

            existing_account = page.get_by_text(hint, exact=True)
            if await existing_account.count() and await existing_account.first.is_visible():
                await existing_account.first.click()
            else:
                identifier = page.locator('input[type="email"], input[name="identifier"]').first
                await identifier.wait_for(state="visible", timeout=10000)
                await identifier.fill(hint)
                next_button = page.get_by_role("button", name=re.compile(r"^Next$", re.I))
                if await next_button.count():
                    await next_button.first.click()

            if not password:
                return True, False
            password_input = page.locator('input[type="password"], input[name="Passwd"]').first
            try:
                await password_input.wait_for(state="visible", timeout=15000)
                await password_input.fill(password)
                password_next = page.locator("#passwordNext").first
                if await password_next.count():
                    await password_next.click()
                else:
                    next_button = page.get_by_role("button", name=re.compile(r"^Next$", re.I))
                    await next_button.first.click()
                return True, True
            except Exception:
                return True, False
        except Exception:
            # Login-page variations should never prevent the user from continuing manually.
            return False, False

    async def status(self) -> tuple[str, str]:
        if (not self.page or self.page.is_closed()) and self.context:
            open_pages = [page for page in self.context.pages if not page.is_closed()]
            if open_pages:
                self.page = open_pages[-1]
        if not self.page or self.page.is_closed():
            return "disconnected", "Open the MoEngage login window to connect."
        login_url = self.ui.get("login_url_contains", "login")
        logged_selector = self.ui.get("logged_in_selector")
        if login_url and login_url.lower() in self.page.url.lower():
            return "waiting_for_login", "Complete the login in the MoEngage window."
        if logged_selector:
            try:
                await self.page.locator(logged_selector).first.wait_for(timeout=3000)
            except Exception:
                return "waiting_for_login", "The configured logged-in marker is not visible yet."
        expected_host = urlparse(self.dashboard_url).netloc
        if expected_host and expected_host not in urlparse(self.page.url).netloc:
            return "waiting_for_login", "Complete the login in the MoEngage window."
        return "connected", "MoEngage session is connected and stored in the local browser profile."

    async def _ensure_browser(self, headless: bool = True):
        if self.page and not self.page.is_closed():
            return
        if self.context:
            try:
                open_pages = [page for page in self.context.pages if not page.is_closed()]
                self.page = open_pages[0] if open_pages else await self.context.new_page()
                return
            except Exception:
                self.context = None
                self.page = None
        if self.playwright is None:
            self.playwright = await async_playwright().start()
        if self.remote_cdp_url:
            try:
                self.remote_browser = await self.playwright.chromium.connect_over_cdp(
                    self.remote_cdp_url,
                    timeout=30000,
                )
            except PlaywrightError as exc:
                raise BrowserAutomationError(
                    "The Railway login browser is starting or unavailable. Wait a moment and try again."
                ) from exc
            self.context = (
                self.remote_browser.contexts[0]
                if self.remote_browser.contexts
                else await self.remote_browser.new_context(viewport={"width": 1440, "height": 960})
            )
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            return
        launch_options = {"headless": headless, "viewport": {"width": 1440, "height": 960}}
        if self.ui.get("browser_channel"):
            launch_options["channel"] = self.ui["browser_channel"]
        self.context = await self.playwright.chromium.launch_persistent_context(str(self.profile_dir), **launch_options)
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

    async def close(self):
        if self.context and not self.remote_cdp_url:
            try:
                await self.context.close()
            except Exception:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
        self.page = None
        self.context = None
        self.remote_browser = None
        self.playwright = None

    async def query_metric(self, row: CampaignRow, metric: str) -> float:
        async with self.lock:
            await self._ensure_browser(headless=True)
            expected_host = urlparse(self.dashboard_url).netloc
            current_host = urlparse(self.page.url).netloc if self.page else ""
            if self.page and (self.page.url == "about:blank" or current_host != expected_host):
                await self.page.goto(self.dashboard_url, wait_until="domcontentloaded")
            state, message = await self.status()
            if state != "connected":
                raise BrowserAutomationError(message)
            if self.ui.get("workflow") == "recorded_behavior":
                for attempt in range(2):
                    try:
                        return await self._query_recorded_behavior(row, metric)
                    except BrowserAutomationError as exc:
                        recoverable = any(
                            text in str(exc).casefold()
                            for text in (
                                "behavior query did not load",
                                "redirected away from the behavior report",
                            )
                        )
                        if attempt or not recoverable:
                            raise
                        # MoEngage occasionally leaves a stale/hidden SPA shell in
                        # the DOM. A fresh navigation on the next attempt is safe
                        # because the query builder is read-only until APPLY.
                        await self.page.wait_for_timeout(1500)
            required = ["query_url", "brand_switcher", "brand_option", "campaign_type", "channel", "campaign_id", "start_date", "end_date", "metric", "run_query", "result"]
            missing = [key for key in required if not self.ui.get(key)]
            if missing:
                raise BrowserAutomationError("MoEngage UI selectors are not configured: " + ", ".join(missing))
            page = self.page
            await page.goto(self.ui["query_url"], wait_until="domcontentloaded")
            await page.locator(self.ui["brand_switcher"]).click()
            await page.locator(self.ui["brand_option"].format(brand=row.brand)).click()
            await self._set_value(page, self.ui["campaign_type"], row.campaign_type)
            await self._set_value(page, self.ui["channel"], row.channel)
            await self._set_value(page, self.ui["campaign_id"], row.campaign_id)
            await self._set_value(page, self.ui["start_date"], row.start_date.isoformat())
            await self._set_value(page, self.ui["end_date"], row.end_date.isoformat())
            await self._set_value(page, self.ui["metric"], metric)
            await page.locator(self.ui["run_query"]).click()
            result = page.locator(self.ui["result"])
            await result.wait_for(timeout=int(self.ui.get("result_timeout_ms", 60000)))
            text = (await result.inner_text()).replace(",", "").replace("₹", "").strip()
            try:
                return float(text)
            except ValueError as exc:
                raise BrowserAutomationError(f"Could not read {metric} result from {text!r}") from exc

    async def _query_recorded_behavior(self, row: CampaignRow, metric: str) -> float:
        pending = {
            str(brand).casefold()
            for brand in self.ui.get("pending_special_workflows", [])
        }
        if row.brand.casefold() in pending and not (
            row.brand.casefold() == "agipl" and row.attribution_brand
        ):
            raise BrowserAutomationError(
                f"{row.brand} dashboard is configured, but its special query logic is still pending"
            )
        plan = build_behavior_query_plan(row, metric)
        page = self.page
        await self._switch_workspace(page, row.brand)
        query_url = self._query_url_for_brand(row.brand)
        await self._goto_behavior_report(page, query_url)
        try:
            await self._wait_for_behavior_report(page)
        except Exception as exc:
            screenshot_path = self.profile_dir.parent / "moengage-query-error.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            title = await page.title()
            body = (await page.locator("body").inner_text()).replace("\n", " | ")[:600]
            raise BrowserAutomationError(
                f"MoEngage behavior query did not load (url={page.url!r}, title={title!r}, "
                f"screenshot={str(screenshot_path)!r}, page={body!r})"
            ) from exc

        await self._ensure_section_open(page, "Events & filters", "Sale_Array")
        await self._choose_visible_value(page, ["exists", "does not exist"], plan.transaction_operator)
        if self._uses_event_transaction_brand(row.brand):
            await self._set_agipl_transaction_brand(page, row.attribution_brand)
        elif row.brand.casefold() == "cis":
            await self._ensure_cis_transaction_brand(page)

        await self._ensure_filter_editor_open(page)
        await self._set_delivery_event(page, plan.delivery_event)
        await self._set_delivery_lookback(page, DELIVERY_LOOKBACK_DAYS)
        await self._set_campaign_id(page, row.campaign_id)

        await self._ensure_section_open(page, "Behavior Options", "Analysis type")
        await self._set_behavior_options(page, row, plan)
        await self._set_daily_granularity(page)
        await page.get_by_role("button", name="APPLY", exact=True).click()
        return await self._read_behavior_total(page, plan.result_row_label)

    @staticmethod
    def _uses_event_transaction_brand(brand: str) -> bool:
        """Only AGIPL stores its target-brand condition on Sale_Array itself."""
        return brand.casefold() == "agipl"

    def _agipl_transaction_brand_value(self, attribution_brand: str | None) -> str:
        if not attribution_brand:
            raise BrowserAutomationError("Choose the attribution brand for AGIPL campaigns")
        if attribution_brand.casefold() == "agipl":
            raise BrowserAutomationError("AGIPL cannot attribute campaigns to itself")
        mapping = self.ui.get("agipl_attribution_brand_values") or {}
        return next(
            (
                str(value)
                for brand, value in mapping.items()
                if brand.casefold() == attribution_brand.casefold()
            ),
            attribution_brand,
        )

    async def _set_agipl_transaction_brand(
        self, page: Page, attribution_brand: str | None
    ):
        value = self._agipl_transaction_brand_value(attribution_brand)
        try:
            attribute = await self._reset_transaction_attribute(page, "Txn_Brand")
            dropdowns = attribute.locator(".mds-dropdown:visible")
            count = await dropdowns.count()
            if count < 3:
                raise BrowserAutomationError(
                    "AGIPL report must contain Txn_Brand contains <brand> in Events & filters"
                )
            operator = dropdowns.nth(count - 2)
            await self._set_titled_dropdown_control(page, operator, "contains")
            # Selecting the operator can rerender the entire attribute. Resolve
            # the fresh value control again before opening it.
            attribute = page.locator(".mds-attr:visible").filter(
                has_text=re.compile(r"Txn_Brand", re.I)
            ).first
            brand_value = attribute.locator(".mds-dropdown:visible").last
            await self._set_agipl_brand_value(page, brand_value, value)
            retained = (await brand_value.inner_text()).strip()
            if value.casefold() not in retained.casefold():
                raise BrowserAutomationError(
                    f"MoEngage retained Txn_Brand {retained!r} instead of {value!r}"
                )
        except BrowserAutomationError:
            raise
        except Exception as exc:
            screenshot_path = "/tmp/moengage-agipl-brand.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not set AGIPL Txn_Brand to {value!r} "
                f"(screenshot={screenshot_path!r})"
            ) from exc

    async def _ensure_cis_transaction_brand(self, page: Page):
        """Verify the saved CIS Brand_PM row without changing any of its controls."""
        txn_channel = page.locator(".mds-attr:visible").filter(
            has_text=re.compile(r"Txn_Channel", re.I)
        ).first
        try:
            await txn_channel.wait_for(state="visible", timeout=10000)
            event = txn_channel.locator(
                "xpath=ancestor::*[.//*[@data-test='attribute-add-btn']][1]"
            )
            await event.wait_for(state="visible", timeout=10000)
            brand_attribute = event.locator(".mds-attr:visible").filter(
                has_text=re.compile(r"Brand_PM", re.I)
            ).first
            await brand_attribute.wait_for(state="visible", timeout=10000)
            attribute_text = await brand_attribute.inner_text()
            inputs = brand_attribute.locator("input:visible")
            input_values = [
                await inputs.nth(index).input_value()
                for index in range(await inputs.count())
            ]
            operator_ok = (
                CIS_BRAND_OPERATOR.casefold() in attribute_text.casefold()
            )
            value_ok = any(
                value.strip() == CIS_BRAND_VALUE for value in input_values
            )
            if operator_ok and value_ok:
                return
        except PlaywrightError as exc:
            failure = str(exc)
        else:
            failure = (
                f"operator_text={attribute_text!r}, input_values={input_values!r}"
            )
        screenshot_path = "/tmp/moengage-cis-brand-readonly-check.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        raise BrowserAutomationError(
            "CIS Brand_PM row must already be configured as "
            f"{CIS_BRAND_OPERATOR!r} with uppercase {CIS_BRAND_VALUE!r}. "
            "The automation did not change the row "
            f"({failure}, screenshot={screenshot_path!r})"
        )

    @staticmethod
    async def _set_agipl_brand_value(page: Page, control, value: str):
        await control.wait_for(state="visible", timeout=10000)
        if value.casefold() in (await control.inner_text()).casefold():
            return
        await control.focus()
        await control.press("Enter")
        await page.wait_for_timeout(300)
        if not await page.locator(".mds-dropdown__popup:visible").count():
            await control.press("Space")
            await page.wait_for_timeout(300)
        if not await page.locator(".mds-dropdown__popup:visible").count():
            trigger = control.locator(".mds-dropdown__trigger").first
            await trigger.dispatch_event("mousedown")
            await trigger.dispatch_event("mouseup")
            await trigger.dispatch_event("click")
            await page.wait_for_timeout(300)
        await MoEngageBrowserService._select_open_option(page, value)

    @staticmethod
    async def _reset_transaction_attribute(page: Page, target_attribute: str):
        """Delete and recreate a Sale_Array transaction attribute.

        The value dropdown is single-select and can retain its prior React state.
        Recreating the attribute guarantees that a run cannot accidentally use
        the value retained by the preceding campaign.
        """
        txn_channel = page.locator(".mds-attr:visible").filter(
            has_text=re.compile(r"Txn_Channel", re.I)
        ).first
        try:
            await txn_channel.wait_for(state="visible", timeout=10000)
            event = txn_channel.locator(
                "xpath=ancestor::*[.//*[@data-test='attribute-add-btn']][1]"
            )
            await event.wait_for(state="visible", timeout=10000)

            target_pattern = re.compile(re.escape(target_attribute), re.I)
            attributes = event.locator(".mds-attr:visible").filter(
                has_text=target_pattern
            )
            removed = 0
            while await attributes.count():
                attribute = attributes.last
                delete_button = attribute.locator("[data-test='delete-button']").first
                await delete_button.wait_for(state="visible", timeout=5000)
                await delete_button.dispatch_event("mousedown")
                await delete_button.dispatch_event("mouseup")
                await delete_button.dispatch_event("click")
                await attribute.wait_for(state="detached", timeout=5000)
                removed += 1
                if removed > 10:
                    raise BrowserAutomationError(
                        f"MoEngage returned too many {target_attribute} attributes while clearing"
                    )
                attributes = event.locator(".mds-attr:visible").filter(
                    has_text=target_pattern
                )

            # A failed prior attempt can leave an incomplete "Select attribute"
            # row. Remove it before adding the target so retries always begin
            # from the same state.
            empty_attributes = event.locator(".mds-attr:visible").filter(
                has_text=re.compile(r"Select attribute", re.I)
            )
            while await empty_attributes.count():
                empty_attribute = empty_attributes.last
                delete_button = empty_attribute.locator(
                    "[data-test='delete-button']"
                ).first
                await delete_button.wait_for(state="visible", timeout=5000)
                await delete_button.click(force=True)
                await empty_attribute.wait_for(state="detached", timeout=5000)
                removed += 1
                if removed > 10:
                    raise BrowserAutomationError(
                        "MoEngage returned too many incomplete attributes while clearing"
                    )
                empty_attributes = event.locator(".mds-attr:visible").filter(
                    has_text=re.compile(r"Select attribute", re.I)
                )

            add_attribute = event.locator("[data-test='attribute-add-btn']").first
            await add_attribute.wait_for(state="visible", timeout=10000)
            await add_attribute.click(force=True)
            await page.wait_for_timeout(400)

            attribute_control = event.locator(
                ".mds-attr__name .mds-dropdown:visible"
            ).last
            await attribute_control.wait_for(state="visible", timeout=10000)
            if not await page.locator(".mds-dropdown__popup:visible").count():
                trigger = attribute_control.locator(".mds-dropdown__trigger").first
                await trigger.dispatch_event("mousedown")
                await trigger.dispatch_event("mouseup")
                await trigger.dispatch_event("click")
            await MoEngageBrowserService._select_open_option(
                page, target_attribute
            )

            fresh_attribute = event.locator(".mds-attr:visible").filter(
                has_text=target_pattern
            ).last
            await fresh_attribute.wait_for(state="visible", timeout=10000)
            return fresh_attribute
        except BrowserAutomationError:
            raise
        except Exception as exc:
            screenshot_path = "/tmp/moengage-agipl-brand-reset.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not clear and recreate the {target_attribute} attribute "
                f"(screenshot={screenshot_path!r})"
            ) from exc

    @staticmethod
    async def _wait_for_behavior_report(page: Page):
        """Wait for report content without selecting a hidden duplicate title."""
        for _ in range(60):
            try:
                body_text = await page.locator("body").inner_text(timeout=2000)
                if PURCHASED_CUSTOMERS_TITLE.search(body_text):
                    return
            except PlaywrightError:
                pass
            await page.wait_for_timeout(500)
        raise BrowserAutomationError(
            "The purchased-customers report title did not appear in the visible page content"
        )

    @staticmethod
    async def _goto_behavior_report(page: Page, query_url: str):
        """Open a report after workspace redirects have fully settled."""
        last_error = None
        for attempt in range(3):
            try:
                await page.goto(query_url, wait_until="domcontentloaded")
            except PlaywrightError as exc:
                last_error = exc
                if "interrupted by another navigation" not in str(exc).lower():
                    raise
            await page.wait_for_timeout(1200)
            current_url = page.url
            if (
                "/analytics/v2/behavior" in current_url
                and "did=" in current_url
                and "chartId=" in current_url
            ):
                return
            if attempt < 2:
                await page.wait_for_timeout(1200)
        raise BrowserAutomationError(
            "MoEngage redirected away from the Behavior report while changing workspaces"
        ) from last_error

    def _query_url_for_brand(self, brand: str) -> str:
        mapping = self.ui.get("query_url_map") or {}
        if mapping:
            query_url = next(
                (value for key, value in mapping.items() if key.casefold() == brand.casefold()),
                None,
            )
            if not query_url:
                raise BrowserAutomationError(
                    f"No MoEngage Behavior query URL is configured for brand {brand!r}. "
                    "Add that brand's full behavior URL containing did and chartId."
                )
            return query_url
        query_url = self.ui.get("query_url")
        if not query_url:
            raise BrowserAutomationError("MOENGAGE_UI_CONFIG_JSON.query_url is required")
        return query_url

    async def _switch_workspace(self, page: Page, brand: str):
        mapping = self.ui.get("workspace_map", {})
        target = next((value for key, value in mapping.items() if key.casefold() == brand.casefold()), None)
        if not target:
            raise BrowserAutomationError(f"No MoEngage workspace mapping configured for brand {brand!r}")
        current = page.get_by_text(target, exact=True)
        for index in range(await current.count()):
            if await current.nth(index).is_visible():
                return
        known = sorted(set(mapping.values()), key=len, reverse=True)
        switcher = None
        selector = self.ui.get("workspace_switcher")
        if selector:
            switcher = page.locator(selector).first
        else:
            for name in known:
                candidate = page.get_by_text(name, exact=True)
                if await candidate.count() and await candidate.first.is_visible():
                    switcher = candidate.first
                    break
        if switcher is None:
            raise BrowserAutomationError("Could not find the MoEngage workspace switcher")
        await switcher.click()
        await self._select_open_option(page, target)
        confirmation = page.get_by_role("button", name=re.compile("Change Workspace", re.I))
        if await confirmation.count() and await confirmation.first.is_visible():
            await confirmation.first.click()
        # Workspace changes trigger a delayed SPA redirect. Wait until the URL
        # has remained unchanged before opening the brand's Behavior report.
        await page.wait_for_timeout(1500)
        previous_url = page.url
        stable_checks = 0
        for _ in range(20):
            await page.wait_for_timeout(400)
            current_url = page.url
            if current_url == previous_url:
                stable_checks += 1
                if stable_checks >= 5:
                    break
            else:
                previous_url = current_url
                stable_checks = 0

    @staticmethod
    async def _ensure_section_open(page: Page, heading: str, marker: str):
        title = page.get_by_text(heading, exact=True).first
        header = title.locator("xpath=ancestor::header[1]")
        icon = header.locator(".material-icons").last
        if await icon.count() and "keyboard_arrow_up" in (await icon.inner_text()).strip():
            return
        await title.scroll_into_view_if_needed()
        toggle = header.locator("[role='button']").last
        if await toggle.count():
            await toggle.evaluate("element => element.click()")
        else:
            await title.evaluate("element => element.click()")
        await page.wait_for_timeout(500)
        if heading == "Filter Users":
            nested_filter = page.locator(".mds-segmentation__nested-filter").filter(has_text=marker).first
            if await nested_filter.count():
                await nested_filter.locator(".mds-segmentation__arrow-wrapper").click(force=True)
        await page.get_by_text(re.compile(re.escape(marker), re.I)).first.wait_for(timeout=10000)

    @staticmethod
    async def _ensure_filter_editor_open(page: Page):
        heading = page.get_by_text("Filter Users", exact=True).first
        header = heading.locator("xpath=ancestor::header[1]")
        section_icon = header.locator(".material-icons").last
        delivery_pattern = re.compile(
            "|".join(re.escape(value) for value in DELIVERY_EVENTS.values()), re.I
        )
        nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
            has_text=delivery_pattern
        ).first
        event_control = nested_filter.locator(".mds-event__event-name .mds-dropdown").first

        # Visibility of the actual editor is more reliable than the animated
        # arrow glyph, whose text can lag behind the section state.
        if not await event_control.count() or not await event_control.is_visible():
            toggle = header.locator("[role='button']").last
            if await toggle.count():
                await toggle.click(force=True)
            else:
                await heading.click(force=True)
            await page.wait_for_timeout(600)

            nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
                has_text=delivery_pattern
            ).first
            event_control = nested_filter.locator(".mds-event__event-name .mds-dropdown").first
        try:
            await nested_filter.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = "/tmp/moengage-filter-nested-missing.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not find the MoEngage delivered-event filter "
                f"(screenshot={screenshot_path!r})"
            ) from exc
        if not await event_control.is_visible():
            arrow_wrapper = nested_filter.locator(".mds-segmentation__arrow-wrapper").first
            await arrow_wrapper.dispatch_event("mousedown")
            await arrow_wrapper.dispatch_event("mouseup")
            await arrow_wrapper.dispatch_event("click")
            await page.wait_for_timeout(400)

        try:
            await event_control.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = Path("/tmp/moengage-filter-editor-error.png")
            await page.screenshot(path=str(screenshot_path), full_page=True)
            raise BrowserAutomationError(
                "Could not open the MoEngage filter editor "
                f"(section_icon={(await section_icon.inner_text()).strip()!r}, "
                f"screenshot={str(screenshot_path)!r})"
            ) from exc

    async def _choose_visible_value(self, page: Page, possible_values: list[str], target: str):
        visible_current = None
        # Saved reports hydrate their event attributes asynchronously. BBW in
        # particular renders Sale_Array first and adds Txn_Channel a few seconds
        # later, so retry before treating the control as absent.
        for attempt in range(30):
            for value in possible_values:
                candidates = page.get_by_text(value, exact=True)
                for index in range(await candidates.count()):
                    candidate = candidates.nth(index)
                    dropdown = candidate.locator(
                        "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' mds-dropdown ')][1]"
                    )
                    if await candidate.is_visible() and await dropdown.count():
                        visible_current = candidate
                        if value == target:
                            return
                        break
                if visible_current is not None:
                    break
            if visible_current is not None:
                break
            if attempt < 29:
                await page.wait_for_timeout(400)
        if visible_current is None:
            await page.screenshot(path=f"/tmp/moengage-control-{target.replace(' ', '-')}.png", full_page=True)
            raise BrowserAutomationError(f"Could not find the control for {target!r}")
        dropdown = visible_current.locator(
            "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' mds-dropdown ')][1]"
        )
        if await dropdown.count():
            trigger = dropdown.locator(".mds-dropdown__trigger").first
            await trigger.scroll_into_view_if_needed()
            await trigger.click(force=True)
        else:
            await visible_current.click(force=True)
        await self._select_open_option(page, target)
        await page.wait_for_timeout(400)
        selected = False
        target_candidates = page.get_by_text(target, exact=True)
        for index in range(await target_candidates.count()):
            candidate = target_candidates.nth(index)
            candidate_dropdown = candidate.locator(
                "xpath=ancestor::*[contains(concat(' ', normalize-space(@class), ' '), ' mds-dropdown ')][1]"
            )
            if await candidate.is_visible() and await candidate_dropdown.count():
                selected = True
                break
        if not selected:
            screenshot_path = f"/tmp/moengage-selection-{target.replace(' ', '-')}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage did not retain selection {target!r} "
                f"(screenshot={screenshot_path!r})"
            )

    @staticmethod
    async def _select_open_option(page: Page, value: str):
        async def click_option() -> bool:
            titled_option = page.locator(
                f'.mds-dropdown__popup__list__item[title="{value}"]:visible'
            )
            if await titled_option.count():
                await titled_option.last.dispatch_event("click")
                return True
            popup_option = page.locator(".mds-dropdown__popup__list__item:visible").filter(
                has_text=re.compile(rf"^\s*{re.escape(value)}\s*$", re.I)
            )
            if await popup_option.count():
                await popup_option.last.dispatch_event("click")
                return True
            option = page.get_by_role("option", name=value, exact=True)
            if await option.count() and await option.last.is_visible():
                await option.last.click()
                return True
            text_option = page.get_by_text(value, exact=True)
            for index in range(await text_option.count() - 1, -1, -1):
                candidate = text_option.nth(index)
                popup_item = candidate.locator("xpath=ancestor::*[contains(@class, 'mds-dropdown__popup__list__item')][1]")
                if await candidate.is_visible() and await popup_item.count():
                    await popup_item.click()
                    return True
            return False

        if await click_option():
            return
        search = page.locator(
            ".mds-dropdown__popup:visible input[placeholder*='Search' i], "
            ".mds-dropdown__menu:visible input[placeholder*='Search' i], "
            "[role='listbox']:visible input[placeholder*='Search' i]"
        ).last
        if await search.count() and await search.is_editable():
            await search.fill(value)
            await page.wait_for_timeout(1200)
            if await click_option():
                return
            await search.press("Enter")
            return
        popup_count = await page.locator(".mds-dropdown__popup:visible").count()
        visible_inputs = page.locator("input:visible")
        placeholders = []
        for index in range(await visible_inputs.count()):
            placeholders.append(await visible_inputs.nth(index).get_attribute("placeholder"))
        raise BrowserAutomationError(
            f"Could not select MoEngage option {value!r} "
            f"(visible_popups={popup_count}, input_placeholders={placeholders!r})"
        )

    async def _set_delivery_event(self, page: Page, event_name: str):
        delivery_pattern = re.compile(
            "|".join(re.escape(value) for value in DELIVERY_EVENTS.values()), re.I
        )
        nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
            has_text=delivery_pattern
        ).first
        event_control = nested_filter.locator(".mds-event__event-name .mds-dropdown").first
        try:
            await event_control.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = "/tmp/moengage-delivery-event-control.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not open the MoEngage delivered-event control "
                f"(screenshot={screenshot_path!r})"
            ) from exc

        current = (await event_control.inner_text()).strip()
        if event_name.casefold() in current.casefold():
            return
        trigger = event_control.locator(".mds-dropdown__trigger").first
        await trigger.dispatch_event("mousedown")
        await trigger.dispatch_event("mouseup")
        await trigger.dispatch_event("click")
        await self._select_open_option(page, event_name)
        await page.wait_for_timeout(500)
        current_control = page.locator(".mds-event__event-name .mds-dropdown:visible").filter(
            has_text=re.compile(r"(WhatsApp Message Delivered|SMS Delivered|RCS Delivered)", re.I)
        ).last
        try:
            await current_control.wait_for(state="visible", timeout=5000)
            current = (await current_control.inner_text()).strip()
        except Exception:
            current = ""
        if event_name.casefold() not in current.casefold():
            screenshot_path = "/tmp/moengage-delivery-event-selection.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage did not retain delivered event {event_name!r}; current control is "
                f"{current!r} (screenshot={screenshot_path!r})"
            )

    @staticmethod
    async def _set_delivery_lookback(page: Page, days: int):
        delivery_pattern = re.compile(
            "|".join(re.escape(value) for value in DELIVERY_EVENTS.values()), re.I
        )
        nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
            has_text=delivery_pattern
        ).first
        numeric_inputs = nested_filter.locator("input[type='number']")
        try:
            # The first number is the execution count (at least 1); the second
            # is the relative lookback window (formerly 30 days).
            lookback = numeric_inputs.nth(1)
            await lookback.wait_for(state="visible", timeout=10000)
            if "days" not in (await nested_filter.inner_text()).casefold():
                raise BrowserAutomationError(
                    "The delivered-event lookback unit is not set to days"
                )
            if await lookback.input_value() != str(days):
                await lookback.fill(str(days))
                await lookback.press("Tab")
                await page.wait_for_timeout(500)
            # Re-resolve after React updates the nested filter.
            nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
                has_text=delivery_pattern
            ).first
            retained = await nested_filter.locator("input[type='number']").nth(1).input_value()
            if retained != str(days):
                raise BrowserAutomationError(
                    f"MoEngage retained a {retained}-day delivery window instead of {days} days"
                )
        except BrowserAutomationError:
            raise
        except Exception as exc:
            screenshot_path = "/tmp/moengage-delivery-lookback.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not set the delivered-event lookback to {days} days "
                f"(screenshot={screenshot_path!r})"
            ) from exc

    async def _set_campaign_id(self, page: Page, campaign_id: str):
        # The recorded workflow opens the editor immediately before setting the
        # delivered event and campaign id. Calling the toggle helper a second
        # time here can race the header animation and collapse the section.
        value_control = await self._reset_campaign_attribute(page)
        # _ensure_filter_editor_open above is the single source of truth for the
        # section state. Re-reading the animated header icon here can briefly
        # report its previous value and toggle the section closed again.
        trigger = value_control.locator(".mds-dropdown__trigger").first
        is_open = await page.locator(".mds-dropdown__popup:visible").count() > 0
        if await trigger.count() and not is_open:
            # The parent dropdown is keyboard-focusable. Opening it with Enter
            # avoids the nested-filter overlay that captures coordinate clicks.
            await value_control.focus()
            await value_control.press("Enter")
            await page.wait_for_timeout(300)
            if not await page.locator(".mds-dropdown__popup:visible").count():
                await value_control.press("Space")
                await page.wait_for_timeout(300)
            if not await page.locator(".mds-dropdown__popup:visible").count():
                await value_control.press("ArrowDown")
                await page.wait_for_timeout(300)
        elif not await trigger.count():
            await value_control.click(force=True)
        try:
            await self._select_open_option(page, campaign_id)
        except Exception as exc:
            screenshot_path = "/tmp/moengage-campaign-id-option.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not select campaign id {campaign_id!r} "
                f"(screenshot={screenshot_path!r})"
            ) from exc
        await page.wait_for_timeout(400)
        selected_text = (await value_control.inner_text()).strip()
        if campaign_id.casefold() not in selected_text.casefold():
            screenshot_path = "/tmp/moengage-campaign-id-selection.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage did not retain campaign id {campaign_id!r}; current control is "
                f"{selected_text!r} (screenshot={screenshot_path!r})"
            )

    async def _reset_campaign_attribute(self, page: Page):
        """Remove every existing campaign-id filter and add one empty filter.

        MoEngage renders Readable Campaign Id as a single-select dropdown with
        no clear button. Selecting another option can leave the previous value
        in React state, so deleting and recreating the attribute is the only
        deterministic reset before each campaign query.
        """
        attributes = page.locator(".mds-attr:visible").filter(
            has_text="Readable Campaign Id"
        )
        removed = 0
        while await attributes.count():
            attribute = attributes.last
            delete_button = attribute.locator("[data-test='delete-button']").first
            if not await delete_button.count() or not await delete_button.is_visible():
                screenshot_path = "/tmp/moengage-campaign-id-clear.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                raise BrowserAutomationError(
                    "Could not clear the existing Readable Campaign Id filter "
                    f"(screenshot={screenshot_path!r})"
                )
            await delete_button.dispatch_event("mousedown")
            await delete_button.dispatch_event("mouseup")
            await delete_button.dispatch_event("click")
            try:
                await attribute.wait_for(state="detached", timeout=5000)
            except Exception as exc:
                screenshot_path = "/tmp/moengage-campaign-id-clear.png"
                await page.screenshot(path=screenshot_path, full_page=True)
                raise BrowserAutomationError(
                    "MoEngage did not clear the existing Readable Campaign Id filter "
                    f"(screenshot={screenshot_path!r})"
                ) from exc
            removed += 1
            if removed > 10:
                raise BrowserAutomationError(
                    "MoEngage returned too many Readable Campaign Id filters while clearing"
                )
            attributes = page.locator(".mds-attr:visible").filter(
                has_text="Readable Campaign Id"
            )

        await self._ensure_campaign_attribute(page)
        fresh_attribute = page.locator(".mds-attr:visible").filter(
            has_text="Readable Campaign Id"
        ).last
        value_control = fresh_attribute.locator(
            ".mds-attr__value .mds-dropdown"
        ).first
        try:
            await value_control.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = "/tmp/moengage-campaign-id-control.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                "Could not create a fresh Readable Campaign Id value control "
                f"(screenshot={screenshot_path!r})"
            ) from exc
        return value_control

    async def _ensure_campaign_attribute(self, page: Page):
        visible_attribute = page.locator(".mds-attr:visible").filter(
            has_text="Readable Campaign Id"
        ).first
        if await visible_attribute.count():
            return

        delivery_pattern = re.compile(
            "|".join(re.escape(value) for value in DELIVERY_EVENTS.values()), re.I
        )
        nested_filter = page.locator(".mds-segmentation__nested-filter").filter(
            has_text=delivery_pattern
        ).first
        add_attribute = nested_filter.locator("[data-test='attribute-add-btn']").first
        try:
            await add_attribute.wait_for(state="visible", timeout=10000)
            await add_attribute.dispatch_event("mousedown")
            await add_attribute.dispatch_event("mouseup")
            await add_attribute.dispatch_event("click")
            await page.wait_for_timeout(400)
            await self._ensure_filter_editor_open(page)
            attribute_name = page.locator(".mds-attr__name .mds-dropdown:visible").last
            await attribute_name.wait_for(state="visible", timeout=10000)
            if not await page.locator(".mds-dropdown__popup:visible").count():
                attribute_trigger = attribute_name.locator(".mds-dropdown__trigger").first
                await attribute_trigger.dispatch_event("mousedown")
                await attribute_trigger.dispatch_event("mouseup")
                await attribute_trigger.dispatch_event("click")
            await self._select_open_option(page, "Readable Campaign Id")
            await visible_attribute.wait_for(state="visible", timeout=10000)
            try:
                await page.locator(".mds-dropdown__popup:visible").wait_for(
                    state="visible", timeout=3000
                )
            except Exception:
                pass
        except Exception as exc:
            screenshot_path = "/tmp/moengage-readable-campaign-attribute.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not add the Readable Campaign Id attribute "
                f"(screenshot={screenshot_path!r})"
            ) from exc

    async def _set_behavior_options(self, page: Page, row: CampaignRow, plan: BehaviorQueryPlan):
        analysis = page.locator(".mds-dropdown:visible").filter(
            has_text=re.compile(r"^(Unique users|Aggregation)", re.I)
        ).first
        await self._set_analysis_type(page, analysis, plan.analysis_type)
        if plan.aggregation:
            await page.wait_for_timeout(500)
            operator = page.locator(".operators-wrapper .mds-dropdown:visible").first
            attribute = page.locator(".attribute-wrapper .mds-dropdown:visible").first
            await self._set_titled_dropdown_control(page, operator, plan.aggregation)
            await self._set_dropdown_control(page, attribute, plan.aggregation_attribute)
        await self._set_duration(page, row.start_date.isoformat(), row.end_date.isoformat())

    @staticmethod
    async def _set_daily_granularity(page: Page):
        candidates = page.get_by_text("Daily", exact=True)
        for index in range(await candidates.count()):
            candidate = candidates.nth(index)
            if await candidate.is_visible():
                await candidate.click()
                await page.wait_for_timeout(400)
                return
        screenshot_path = "/tmp/moengage-daily-granularity.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        raise BrowserAutomationError(
            "Could not select Daily granularity in the MoEngage behavior chart "
            f"(screenshot={screenshot_path!r})"
        )

    async def _set_analysis_type(self, page: Page, dropdown, value: str):
        await self._set_titled_dropdown_control(page, dropdown, value)
        selected = page.get_by_text(
            re.compile(rf"Analysis for\s+{re.escape(value)}\s+between", re.I)
        ).first
        try:
            await selected.wait_for(state="visible", timeout=5000)
        except Exception as exc:
            screenshot_path = "/tmp/moengage-analysis-selection.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage analysis type did not change to {value!r} "
                f"(screenshot={screenshot_path!r})"
            ) from exc

    async def _set_titled_dropdown_control(self, page: Page, dropdown, value: str):
        """Set a MoEngage dropdown through its exact, stable option title."""
        try:
            await dropdown.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = f"/tmp/moengage-dropdown-{value.replace(' ', '-')}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not find the MoEngage dropdown for {value!r} (screenshot={screenshot_path!r})"
            ) from exc
        if value.casefold() in (await dropdown.inner_text()).casefold():
            return
        trigger = dropdown.locator(".mds-dropdown__trigger").first
        await trigger.scroll_into_view_if_needed()
        await trigger.click(force=True)
        option = page.locator(
            f'.mds-dropdown__popup__list__item[title="{value}"]:visible'
        ).last
        try:
            await option.wait_for(state="visible", timeout=5000)
            await option.click()
        except Exception as exc:
            screenshot_path = f"/tmp/moengage-option-{value.replace(' ', '-')}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not select MoEngage option {value!r} (screenshot={screenshot_path!r})"
            ) from exc
        await page.wait_for_timeout(500)

    async def _set_dropdown_control(self, page: Page, dropdown, value: str):
        try:
            await dropdown.wait_for(state="visible", timeout=10000)
        except Exception as exc:
            screenshot_path = f"/tmp/moengage-dropdown-{value.replace(' ', '-')}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"Could not find the MoEngage dropdown for {value!r} (screenshot={screenshot_path!r})"
            ) from exc
        if value in (await dropdown.inner_text()):
            return
        trigger = dropdown.locator(".mds-dropdown__trigger").first
        await trigger.scroll_into_view_if_needed()
        await trigger.click(force=True)
        await self._select_open_option(page, value)
        await page.wait_for_timeout(400)

        current = page.locator(".attribute-wrapper .mds-dropdown:visible").first if value == "Order_Net_Val" else dropdown
        selected_text = (await current.inner_text()).strip()
        if value.casefold() not in selected_text.casefold():
            screenshot_path = f"/tmp/moengage-selection-{value.replace(' ', '-')}.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage did not retain selection {value!r}; current control is "
                f"{selected_text!r} (screenshot={screenshot_path!r})"
            )

    @staticmethod
    async def _set_duration(page: Page, start_iso: str, end_iso: str):
        label = page.get_by_text("Duration", exact=True).last
        duration = label.locator("xpath=following::input[1]").first
        changed = await duration.evaluate(
            """(el, dates) => {
                const key = Object.keys(el).find(k => k.startsWith('__reactInternalInstance'));
                let fiber = key && el[key];
                while (fiber) {
                    const instance = fiber.stateNode;
                    if (instance?.props?.onChange && Array.isArray(instance.props.value)) {
                        const make = (iso, source) => {
                            const [year, month, day] = iso.split('-').map(Number);
                            return source.clone().year(year).month(month - 1).date(day)
                                .hour(0).minute(0).second(0).millisecond(0);
                        };
                        instance.props.onChange(
                            [make(dates.start, instance.props.value[0]),
                             make(dates.end, instance.props.value[1])],
                            {
                                selectedOption: 'CUSTOM_RANGE',
                                lastNSelectedValues: instance.props.lastNConfig?.lastNSelectedValues
                            }
                        );
                        return true;
                    }
                    fiber = fiber.return;
                }
                return false;
            }""",
            {"start": start_iso, "end": end_iso},
        )
        await page.wait_for_timeout(600)
        actual = await duration.input_value()
        expected_start = date.fromisoformat(start_iso).strftime("%d %b %Y")
        expected_end = date.fromisoformat(end_iso).strftime("%d %b %Y")
        if not changed or expected_start not in actual or expected_end not in actual:
            screenshot_path = "/tmp/moengage-duration-selection.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            raise BrowserAutomationError(
                f"MoEngage did not retain duration {expected_start!r} - {expected_end!r}; "
                f"current value is {actual!r} (screenshot={screenshot_path!r})"
            )

    @staticmethod
    async def _read_behavior_total(page: Page, row_label: str) -> float:
        loading = page.get_by_text(re.compile("Please wait while the data loads", re.I))
        if await loading.count():
            try:
                await loading.first.wait_for(state="hidden", timeout=90000)
            except Exception:
                pass
        # AG Grid renders the pinned label and numeric cells in peer rows with
        # the same row-index. Cell zero is the selectable summary (Average by
        # default); all remaining cells are the Daily values. Both unique users
        # and revenue must use the Sum of those daily values to match the manual
        # MoEngage workflow.
        pinned_row = page.locator("[role='row']").filter(
            has_text=re.compile(re.escape(row_label), re.I)
        ).first
        try:
            await pinned_row.wait_for(state="visible", timeout=90000)
            row_index = await pinned_row.get_attribute("row-index")
            peer_rows = page.locator(f"[role='row'][row-index='{row_index}']")
            for index in range(await peer_rows.count()):
                peer_cells = peer_rows.nth(index).locator("[role='gridcell']")
                if await peer_cells.count() >= 2:
                    daily_text = [
                        await peer_cells.nth(cell_index).inner_text()
                        for cell_index in range(1, await peer_cells.count())
                    ]
                    return MoEngageBrowserService._sum_daily_values(daily_text)
        except Exception:
            # Retain the older single-summary fallback for unusual grid layouts.
            pass
        label = page.get_by_text(re.compile(re.escape(row_label), re.I)).last
        await label.wait_for(timeout=90000)
        row = label.locator("xpath=ancestor::*[@role='row'][1]")
        if await row.count():
            cells = row.locator("[role='gridcell']")
            if await cells.count() >= 2:
                return MoEngageBrowserService._parse_number(await cells.nth(1).inner_text())
        value = label.locator("xpath=following::*[@role='gridcell'][1]")
        if await value.count():
            return MoEngageBrowserService._parse_number(await value.first.inner_text())
        raise BrowserAutomationError(f"Could not read the behavior-table total for {row_label!r}")

    @staticmethod
    def _sum_daily_values(values: list[str]) -> float:
        return sum(MoEngageBrowserService._parse_number(value) for value in values)

    @staticmethod
    def _parse_number(value: str) -> float:
        cleaned = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
        if not cleaned:
            raise BrowserAutomationError(f"MoEngage returned a non-numeric result: {value!r}")
        return float(cleaned)

    @staticmethod
    async def _set_value(page: Page, selector: str, value: str):
        locator = page.locator(selector)
        tag = await locator.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            await locator.select_option(label=value)
        else:
            await locator.fill(value)
