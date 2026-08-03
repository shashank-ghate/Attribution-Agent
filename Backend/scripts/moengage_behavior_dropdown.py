"""Inspect the Analysis type dropdown structure."""

from __future__ import annotations

import asyncio

from app.config.settings import settings
from app.services.moengage_service import MoEngageService


async def main() -> None:
    service = MoEngageService(settings)
    try:
        await service.browser._ensure_browser(headless=True)
        page = service.browser.page
        await page.goto(settings.moengage_ui_config["query_url"], wait_until="domcontentloaded")
        await page.wait_for_timeout(8_000)
        dropdowns = page.locator(".mds-dropdown").filter(has_text="Unique users")
        for index in range(await dropdowns.count()):
            candidate = dropdowns.nth(index)
            if await candidate.is_visible():
                print("current", index, await candidate.evaluate("el => el.outerHTML"), flush=True)
                trigger = candidate.locator(".mds-dropdown__trigger")
                await trigger.scroll_into_view_if_needed()
                await trigger.click(force=True)
                break
        await page.wait_for_timeout(700)
        nodes = await page.evaluate(
            """() => [...document.querySelectorAll('*')]
                .filter(el => el.children.length === 0 && (el.textContent || '').trim() === 'Aggregation')
                .map(el => {
                    const result = [];
                    let current = el;
                    while (current && result.length < 6) {
                        result.push({tag: current.tagName, cls: current.className, html: current.outerHTML.slice(0, 1200)});
                        current = current.parentElement;
                    }
                    return result;
                })"""
        )
        print("aggregation_nodes", nodes, flush=True)
        aggregation = page.locator(".mds-dropdown__popup__list__item[title='Aggregation']").last
        await aggregation.click()
        await page.wait_for_timeout(800)
        await page.screenshot(path="/tmp/moengage-analysis-dropdown.png", full_page=True)
        visible_dropdowns = []
        dropdowns = page.locator(".mds-dropdown:visible")
        for index in range(await dropdowns.count()):
            dropdown = dropdowns.nth(index)
            visible_dropdowns.append(
                {
                    "index": index,
                    "text": (await dropdown.inner_text()).replace("\n", " | "),
                    "parent": await dropdown.evaluate("el => el.parentElement?.className"),
                }
            )
        print("visible_dropdowns", visible_dropdowns, flush=True)
    finally:
        await service.browser.close()


if __name__ == "__main__":
    asyncio.run(main())
