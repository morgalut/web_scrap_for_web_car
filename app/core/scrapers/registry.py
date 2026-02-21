from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.config import ScraperKey, Settings
from app.core.fetchers.base import BaseFetcher
from app.core.fetchers.httpx_fetcher import HttpxFetcher
from app.core.fetchers.playwright_fetcher import PlaywrightFetcher
from app.core.fetchers.hybrid_fetcher import HybridFetcher
from app.core.scrapers.base import BaseScraper
from app.core.scrapers.trademobile_scraper import TradeMobileScraper
from app.core.scrapers.autocoil_scraper import AutoCoIlTestDrivesScraper


@dataclass
class ScrapeRuntime:
    httpx: HttpxFetcher
    playwright: Optional[PlaywrightFetcher]
    hybrid_trademobile: Optional[HybridFetcher]

    async def aclose(self) -> None:
        # close hybrid if created, else close httpx/pw individually
        if self.hybrid_trademobile is not None:
            await self.hybrid_trademobile.aclose()
            return

        if self.httpx is not None:
            await self.httpx.aclose()
        if self.playwright is not None:
            await self.playwright.aclose()


class ScraperRegistry:
    def __init__(self, settings: Settings, headless: bool) -> None:
        self.settings = settings
        self.headless = headless

        self._httpx = HttpxFetcher(config=settings.httpx)
        self._pw: Optional[PlaywrightFetcher] = None
        self._hybrid_trademobile: Optional[HybridFetcher] = None

    def runtime(self) -> ScrapeRuntime:
        return ScrapeRuntime(
            httpx=self._httpx,
            playwright=self._pw,
            hybrid_trademobile=self._hybrid_trademobile,
        )

    def _get_pw(self) -> PlaywrightFetcher:
        if self._pw is None:
            self._pw = PlaywrightFetcher(headless=self.headless)
        return self._pw

    def _get_trademobile_article_fetcher(self) -> BaseFetcher:
        # Hybrid for article pages (wait for ProseMirror when needed)
        if self._hybrid_trademobile is None:
            self._hybrid_trademobile = HybridFetcher(
                http=self._httpx,
                pw=self._get_pw(),
                require_selector="div.ProseMirror",
            )
        return self._hybrid_trademobile

    def _get_autocoil_fetcher(self) -> BaseFetcher:
        return self._httpx

    def create(self, key: ScraperKey, concurrency: int) -> BaseScraper:
        if key == "trademobile_posts":
            article_fetcher = self._get_trademobile_article_fetcher()
            discovery_fetcher = self._httpx  # ✅ discovery should not require ProseMirror
            return TradeMobileScraper(
                fetcher=article_fetcher,
                discovery_fetcher=discovery_fetcher,
                concurrency=concurrency,
            )

        if key == "autocoil_test_drives":
            return AutoCoIlTestDrivesScraper(
                fetcher=self._get_autocoil_fetcher(),
                concurrency=concurrency,
            )

        # ✅ NEVER return None
        raise ValueError(f"Unknown scraper key: {key}")