"""Print frame diagnostics for the recorded MoEngage behavior report."""

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
        print("page", page.url, await page.title(), flush=True)
        html = await page.content()
        marker = html.find("Number of Purchased Customers")
        print("html_length", len(html), "marker", marker, html[marker - 200:marker + 300] if marker >= 0 else "", flush=True)
        for point in ((220, 90), (250, 170), (330, 230), (1200, 680)):
            hit = await page.evaluate(
                """([x, y]) => {
                    let el = document.elementFromPoint(x, y);
                    const parts = [];
                    while (el && parts.length < 5) {
                        parts.push(el.outerHTML.slice(0, 500));
                        el = el.parentElement;
                    }
                    return parts;
                }""",
                point,
            )
            print("point", point, hit, flush=True)
        filter_users = page.get_by_text("Filter Users", exact=True)
        print("filter_users_count", await filter_users.count(), flush=True)
        for index in range(await filter_users.count()):
            print("filter", index, await filter_users.nth(index).is_visible(), await filter_users.nth(index).evaluate("el => el.parentElement.outerHTML"), flush=True)
        await filter_users.first.click(force=True)
        await page.wait_for_timeout(1_000)
        html = await page.content()
        print("readable_occurrences", html.count("Readable Campaign Id"), flush=True)
        readable_nodes = await page.evaluate(
            """() => [...document.querySelectorAll('*')]
                .filter(el => el.children.length === 0 && (el.textContent || '').includes('Readable Campaign Id'))
                .map(el => ({tag: el.tagName, text: el.textContent, parent: el.parentElement?.parentElement?.outerHTML.slice(0, 3000)}))"""
        )
        print("readable_nodes", readable_nodes, flush=True)
        nested = page.locator(".mds-segmentation__nested-filter").filter(has_text="Readable Campaign Id").first
        await nested.locator(".mds-segmentation__arrow-wrapper").click(force=True)
        await page.wait_for_timeout(700)
        expanded = await page.evaluate(
            """() => [...document.querySelectorAll('*')]
                .filter(el => el.children.length === 0 && (el.textContent || '').trim() === 'Readable Campaign Id')
                .map(el => el.parentElement?.parentElement?.parentElement?.outerHTML.slice(0, 5000))"""
        )
        print("expanded_readable", expanded, flush=True)
        ancestors = await page.evaluate(
            """() => {
                let el = [...document.querySelectorAll('*')].find(
                    node => node.children.length === 0 && (node.textContent || '').trim() === 'Readable Campaign Id'
                );
                const result = [];
                while (el && result.length < 10) {
                    result.push({tag: el.tagName, cls: el.className, text: (el.textContent || '').trim().slice(0, 300), html: el.outerHTML.slice(0, 800)});
                    el = el.parentElement;
                }
                return result;
            }"""
        )
        print("readable_ancestors", ancestors, flush=True)
        attr_children = await page.evaluate(
            """() => {
                const label = [...document.querySelectorAll('*')].find(
                    node => node.children.length === 0 && (node.textContent || '').trim() === 'Readable Campaign Id'
                );
                const attr = label?.closest('.mds-attr');
                return [...(attr?.children || [])].map(el => ({cls: el.className, text: el.textContent, html: el.outerHTML.slice(0, 1600)}));
            }"""
        )
        print("attr_children", attr_children, flush=True)
        await page.screenshot(path=str(settings.storage_dir / "moengage-filter-expanded.png"), full_page=True)
        await page.screenshot(path=str(settings.storage_dir / "moengage-filter-open.png"), full_page=True)
        for index, frame in enumerate(page.frames):
            body = (await frame.locator("body").inner_text()).replace("\n", " | ")[:500]
            count = await frame.get_by_text("Number of Purchased Customers", exact=False).count()
            print(index, frame.url, "title_matches", count, "body", body, flush=True)
    finally:
        await service.browser.close()


if __name__ == "__main__":
    asyncio.run(main())
