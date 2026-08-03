"""Interactive one-time login for the persistent MoEngage automation profile."""

from __future__ import annotations

import asyncio
import getpass
import re
from pathlib import Path

from playwright.async_api import async_playwright


DASHBOARD_URL = "https://dashboard-03.moengage.com/v4/dashboards/68d26980ac6269ea10b52cf5"
PROFILE_DIR = Path(__file__).resolve().parents[1] / "storage" / "moengage-profile"


async def log_in(email: str, password: str) -> None:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR), channel="chrome", headless=False, viewport={"width": 1440, "height": 960}
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=30_000)
        last_urls: set[str] = set()
        google_opened = False
        email_submitted = False
        password_submitted = False
        account_selected = False
        consent_clicked = False
        for _ in range(300):
            open_pages = [candidate for candidate in context.pages if not candidate.is_closed()]
            for candidate in open_pages:
                if candidate.url not in last_urls:
                    print(f"Current page: {candidate.url}", flush=True)
                    last_urls.add(candidate.url)
                if "/auth/login" not in candidate.url and "dashboard-03.moengage.com" in candidate.url:
                    try:
                        await candidate.get_by_text("Create New", exact=True).first.wait_for(timeout=2_000)
                        print("LOGIN_SUCCESS", flush=True)
                        await context.close()
                        return
                    except Exception:
                        pass

                if "/auth/login" in candidate.url and not google_opened:
                    google = candidate.get_by_text(re.compile(r"^Google$", re.IGNORECASE)).last
                    try:
                        await google.wait_for(state="visible", timeout=2_000)
                        await google.click()
                        google_opened = True
                        print("Google sign-in opened.", flush=True)
                    except Exception:
                        pass

                if "accounts.google.com" in candidate.url:
                    email_input = candidate.locator(
                        'input[type="email"], input[name="identifier"], input#identifierId'
                    ).or_(candidate.get_by_label(re.compile(r"Email or phone", re.IGNORECASE)))
                    password_input = candidate.locator(
                        'input[type="password"], input[name="Passwd"]'
                    ).or_(candidate.get_by_label(re.compile(r"password", re.IGNORECASE)))
                    account = candidate.get_by_text(email, exact=False).first
                    consent = candidate.get_by_text(
                        re.compile(r"^(Continue|Allow)$", re.IGNORECASE)
                    ).last

                    if not account_selected and await account.count() and await account.is_visible():
                        await account.click()
                        account_selected = True
                        print("Google account selected.", flush=True)
                    elif not email_submitted and await email_input.count() and await email_input.first.is_visible():
                        await email_input.first.fill(email)
                        await email_input.first.press("Enter")
                        email_submitted = True
                        print("Google email submitted.", flush=True)
                    elif not password_submitted and await password_input.count() and await password_input.first.is_visible():
                        await password_input.first.fill(password)
                        await password_input.first.press("Enter")
                        password_submitted = True
                        print("Google password submitted. Complete the authenticator prompt if requested.", flush=True)
                    elif not consent_clicked and await consent.count() and await consent.is_visible():
                        await consent.click()
                        consent_clicked = True
                        print("Google access approved.", flush=True)
            if not open_pages:
                print("Browser window was closed.", flush=True)
                break
            await open_pages[-1].wait_for_timeout(2_000)
        await context.close()


if __name__ == "__main__":
    login_email = input("MoEngage email: ")
    login_password = getpass.getpass("MoEngage password: ")
    asyncio.run(log_in(login_email, login_password))
