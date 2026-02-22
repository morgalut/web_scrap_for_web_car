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
from app.core.scrapers.gear_scraper import GearSecondHandScraper
from app.core.scrapers.icar_news_scraper import IcarNewsScraper


@dataclass
class ScrapeRuntime:
    httpx: HttpxFetcher
    playwright: Optional[PlaywrightFetcher]
    hybrid_trademobile: Optional[HybridFetcher]

    async def aclose(self) -> None:
        """
        Close resources safely.

        NOTE:
        - HybridFetcher closes both http and pw internally.
        - If hybrid exists, close it and return (prevents double-close).
        """
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

        # Always available
        self._httpx = HttpxFetcher(config=settings.httpx)

        # Lazy-created (only if needed)
        self._pw: Optional[PlaywrightFetcher] = None

        # Lazy-created hybrid (TradeMobile articles)
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

    # -----------------------
    # Fetcher factories
    # -----------------------
    def _get_trademobile_article_fetcher(self) -> BaseFetcher:
        """
        TradeMobile:
        - Article pages sometimes need Playwright to wait for div.ProseMirror.
        - Discovery should stay HTTPX (fast, no ProseMirror requirement).
        """
        if self._hybrid_trademobile is None:
            self._hybrid_trademobile = HybridFetcher(
                http=self._httpx,
                pw=self._get_pw(),
                require_selector="div.ProseMirror",
            )
        return self._hybrid_trademobile

    def _get_autocoil_fetcher(self) -> BaseFetcher:
        """
        Auto.co.il:
        - HTTPX is enough (fast).
        """
        return self._httpx

    def _get_gear_fetcher(self) -> BaseFetcher:
        """
        Gear:
        - Discovery and most pages: HTTPX
        - Fallback: Playwright available for ads/popups or missing content
        """
        return self._httpx

    # -----------------------
    # Scraper factories
    # -----------------------
    def _create_trademobile(self, concurrency: int) -> BaseScraper:
        article_fetcher = self._get_trademobile_article_fetcher()
        discovery_fetcher = self._httpx
        return TradeMobileScraper(
            fetcher=article_fetcher,
            discovery_fetcher=discovery_fetcher,
            concurrency=concurrency,
        )

    def _create_autocoil(self, concurrency: int) -> BaseScraper:
        return AutoCoIlTestDrivesScraper(
            fetcher=self._get_autocoil_fetcher(),
            concurrency=concurrency,
        )

    def _create_gear(self, concurrency: int) -> BaseScraper:
        # Gear scraper needs both http + pw fallback
        return GearSecondHandScraper(
            http=self._httpx,
            pw=self._get_pw(),
            concurrency=concurrency,
        )

    def _create_icar_news(self, concurrency: int) -> BaseScraper:
        return IcarNewsScraper(
            fetcher=self._httpx,
            concurrency=concurrency,
        )

    # -----------------------
    # Public API
    # -----------------------
    def create(self, key: ScraperKey, concurrency: int) -> BaseScraper:
        if key == "trademobile_posts":
            return self._create_trademobile(concurrency=concurrency)

        if key == "autocoil_test_drives":
            return self._create_autocoil(concurrency=concurrency)

        # ✅ Support all Gear categories with the same scraper implementation
        if key in ("gear_second_hand", "gear_car_tests", "gear_car_insurance"):
            return self._create_gear(concurrency=concurrency)

        if key == "icar_news":
            return self._create_icar_news(concurrency=concurrency)

        raise ValueError(f"Unknown scraper key: {key}")