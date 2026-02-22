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
            self._ctx = await self._browser.new_context()
            self._ctx.set_default_navigation_timeout(self.timeout_ms)
            self._ctx.set_default_timeout(self.timeout_ms)

    async def get_html(
        self,
        url: str,
        wait_for_selector: Optional[str] = None,
        click_selectors: Optional[list[str]] = None,
        wait_state: WaitState = "attached",   # ✅ CHANGED default from 'visible'
        extra_wait_ms: int = 0,               # ✅ optional small delay after selector appears
        wait_networkidle: bool = True,        # ✅ helps on JS-rendered pages
        scroll_steps: int = 4,                # ✅ for lazy-loaded listings
        scroll_wait_ms: int = 700,
    ) -> str:
        await self._ensure()
        assert self._ctx is not None

        page: Page = await self._ctx.new_page()
        try:
            await page.goto(url, wait_until=self.wait_until, timeout=self.timeout_ms)

            # ✅ often helps for JS-heavy pages
            if wait_networkidle:
                try:
                    await page.wait_for_load_state("networkidle", timeout=min(15_000, self.timeout_ms))
                except Exception:
                    pass

            # ✅ best-effort clicks (cookie banners, close buttons, etc.)
            if click_selectors:
                for sel in click_selectors:
                    try:
                        loc = page.locator(sel).first
                        if await loc.count() > 0:
                            await loc.click(timeout=1500)
                    except Exception:
                        pass

            # ✅ robust selector waiting (with scroll + retry)
            if wait_for_selector:
                # 1) quick wait
                try:
                    await page.locator(wait_for_selector).first.wait_for(
                        state=wait_state,
                        timeout=min(12_000, self.timeout_ms),
                    )
                except Exception:
                    # 2) scroll + retry (lazy-loading)
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
                    else:
                        # 3) last-chance wait (full timeout)
                        await page.locator(wait_for_selector).first.wait_for(
                            state=wait_state,
                            timeout=self.timeout_ms,
                        )

            if extra_wait_ms > 0:
                await page.wait_for_timeout(extra_wait_ms)

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