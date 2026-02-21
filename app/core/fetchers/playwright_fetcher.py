from __future__ import annotations

from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .base import BaseFetcher


class PlaywrightFetcher(BaseFetcher):
    """
    Playwright-based HTML fetcher.

    Key behavior:
    - Uses wait_until="domcontentloaded" (networkidle often never happens).
    - Can wait for a selector to be *visible* using locator(selector).wait_for(state="visible").
    - Reuses a single browser + context for performance.
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

    async def _ensure(self) -> None:
        if self._ctx is not None:
            return

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)

        self._ctx = await self._browser.new_context()
        self._ctx.set_default_navigation_timeout(self.timeout_ms)
        self._ctx.set_default_timeout(self.timeout_ms)

    async def get_html(self, url: str, wait_for_selector: Optional[str] = None) -> str:
        await self._ensure()
        assert self._ctx is not None

        page: Page = await self._ctx.new_page()
        try:
            await page.goto(url, wait_until=self.wait_until, timeout=self.timeout_ms)

            # ✅ Explicit “locator(...).wait_for(state='visible')”
            if wait_for_selector:
                await page.locator(wait_for_selector).first.wait_for(
                    state="visible",
                    timeout=self.timeout_ms,
                )

            return await page.content()
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