from __future__ import annotations

import asyncio
from typing import Optional, Literal

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from .base import BaseFetcher


WaitState = Literal["attached", "visible", "hidden", "detached"]


class PlaywrightFetcher(BaseFetcher):
    """
    Improvements:
    - Wait state defaults to 'attached' (scraping-safe; avoids overlay/visibility issues)
    - Optional networkidle wait (helps JS rendering)
    - Scroll + retry loop for lazy-loaded listings
    - Best-effort click selectors support (cookie/close overlays)
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 60_000,
        wait_until: str = "domcontentloaded",
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.wait_until = wait_until

        self._pw = None
        self._browser: Browser | None = None
        self._ctx: BrowserContext | None = None

        self._lock = asyncio.Lock()  # ✅ IMPORTANT

    async def _ensure(self) -> None:
        async with self._lock:
            if self._ctx is not None:
                return

            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=self.headless)

            # ✅ You can optionally add locale/timezone/user_agent here if needed.
            self._ctx = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="he-IL",
                timezone_id="Asia/Jerusalem",
                viewport={"width": 1366, "height": 768},
            )
            self._ctx.set_default_navigation_timeout(self.timeout_ms)
            self._ctx.set_default_timeout(self.timeout_ms)

    async def get_html(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        click_selectors: Optional[list[str]] = None,
        wait_state: WaitState = "attached",
        extra_wait_ms: int = 0,
        wait_networkidle: bool = True,
        scroll_steps: int = 4,
        scroll_wait_ms: int = 700,
    ) -> str:
        await self._ensure()
        assert self._ctx is not None

        page: Page = await self._ctx.new_page()
        try:
            await page.goto(url, wait_until=self.wait_until, timeout=self.timeout_ms)

            if wait_networkidle:
                try:
                    await page.wait_for_load_state("networkidle", timeout=min(15_000, self.timeout_ms))
                except Exception:
                    pass

            if click_selectors:
                for sel in click_selectors:
                    try:
                        loc = page.locator(sel).first
                        if await loc.count() > 0:
                            await loc.click(timeout=1500)
                    except Exception:
                        pass

            if wait_for_selector:
                try:
                    # quick wait
                    await page.locator(wait_for_selector).first.wait_for(
                        state=wait_state,
                        timeout=min(12_000, self.timeout_ms),
                    )
                except Exception:
                    # scroll + retry
                    for _ in range(max(0, scroll_steps)):
                        try:
                            await page.evaluate("window.scrollBy(0, Math.max(700, window.innerHeight));")
                            await page.wait_for_timeout(scroll_wait_ms)
                            await page.locator(wait_for_selector).first.wait_for(
                                state=wait_state,
                                timeout=min(6_000, self.timeout_ms),
                            )
                            break
                        except Exception:
                            continue
                    # last chance (do not raise)
                    try:
                        await page.locator(wait_for_selector).first.wait_for(
                            state=wait_state,
                            timeout=min(10_000, self.timeout_ms),
                        )
                    except Exception:
                        pass

            if extra_wait_ms > 0:
                await page.wait_for_timeout(extra_wait_ms)

            html = await page.content()
            return html if html is not None else ""

        except Exception:
            # ✅ Never return None
            try:
                html = await page.content()
                return html if html is not None else ""
            except Exception:
                return ""
        finally:
            await page.close()

    async def aclose(self) -> None:
        if self._ctx is not None:
            await self._ctx.close()
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()

        self._ctx = None
        self._browser = None
        self._pw = None