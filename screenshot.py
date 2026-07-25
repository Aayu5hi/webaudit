# =============================================================================
# screenshot.py — Capture homepage hero (top 800px) for AI visual analysis
# =============================================================================
"""
Takes a screenshot of just the hero fold (top 800px) of the homepage,
compresses it to JPEG, and returns base64-encoded bytes ready to send to
the OpenAI vision API.

Requires: playwright  (pip install playwright && playwright install chromium)
Falls back gracefully if playwright is not installed — visual checks are then
skipped and marked as "could not assess".
"""

from __future__ import annotations

import base64
from typing import Optional

from config import SCREENSHOT_HERO_HEIGHT, SCREENSHOT_JPEG_QUALITY, SCREENSHOT_WIDTH


async def capture_hero(url: str) -> Optional[str]:
    """
    Launch a headless Chromium browser, navigate to `url`, wait for the page
    to settle, and capture a JPEG screenshot of the top SCREENSHOT_HERO_HEIGHT
    pixels.

    Returns
    -------
    str | None
        Base64-encoded JPEG string, or None if capture failed.
    """
    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("  [screenshot] playwright not installed — skipping visual analysis.")
        print("               Run: pip install playwright && playwright install chromium")
        return None

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )

            page = await browser.new_page(
                viewport={"width": SCREENSHOT_WIDTH, "height": SCREENSHOT_HERO_HEIGHT},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )

            print(f"  [screenshot] Loading {url} …")
            try:
                await page.goto(url, wait_until="networkidle", timeout=20_000)
            except PWTimeout:
                pass  # page might still be usable

            # Dismiss cookie banners if possible (common selectors)
            for selector in [
                "[id*='cookie'] button",
                "[class*='cookie'] button",
                "[id*='consent'] button",
                "[class*='consent'] button",
                "button[data-accept]",
                "#cookie-accept",
                ".cookie-accept",
                "[aria-label='Accept cookies']",
            ]:
                try:
                    await page.click(selector, timeout=500)
                    break
                except Exception:
                    pass

            # Ensure we're at top
            await page.evaluate("window.scrollTo(0, 0)")

            # Capture hero fold only
            screenshot_bytes = await page.screenshot(
                clip={
                    "x": 0,
                    "y": 0,
                    "width": SCREENSHOT_WIDTH,
                    "height": SCREENSHOT_HERO_HEIGHT,
                },
                type="jpeg",
                quality=SCREENSHOT_JPEG_QUALITY,
            )

            await browser.close()

        # Encode as base64 string
        b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        print(f"  [screenshot] Hero captured ({len(screenshot_bytes) // 1024} KB).")
        return b64

    except Exception as exc:
        print(f"  [screenshot] Failed to capture hero: {exc}")
        return None