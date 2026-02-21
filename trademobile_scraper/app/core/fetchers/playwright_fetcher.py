from __future__ import annotations

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .base import BaseFetcher

class PlaywrightFetcher(BaseFetcher):
    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._pw = None
        self._browser: Browser | None = None
        self._ctx: BrowserContext | None = None

    async def _ensure(self) -> None:
        if self._ctx:
            return
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        self._ctx = await self._browser.new_context()

    async def get_html(self, url: str) -> str:
        await self._ensure()
        assert self._ctx is not None

        page: Page = await self._ctx.new_page()
        try:
            await page.goto(url, wait_until="networkidle")
            return await page.content()
        finally:
            await page.close()

    async def aclose(self) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._ctx = None
        self._browser = None
        self._pw = None