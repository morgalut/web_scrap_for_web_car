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
from app.core.scrapers.wheel_scraper import WheelTestDrivesScraper
from app.core.scrapers.queenoftheroad_scraper import QueenOfTheRoadTestDrivesScraper
from app.core.scrapers.carwiz_magazine_scraper import CarwizMagazineScraper

@dataclass
class ScrapeRuntime:
    httpx: HttpxFetcher
    playwright: Optional[PlaywrightFetcher]
    hybrid_trademobile: Optional[HybridFetcher]
    hybrid_wheel: Optional[HybridFetcher]
    hybrid_queenoftheroad: Optional[HybridFetcher]

    async def aclose(self) -> None:
        # Close hybrids first (they own both http+pw)
        if self.hybrid_trademobile is not None:
            await self.hybrid_trademobile.aclose()

        if self.hybrid_wheel is not None:
            await self.hybrid_wheel.aclose()

        if self.hybrid_queenoftheroad is not None:
            await self.hybrid_queenoftheroad.aclose()

        # Safe fallback close
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

        # Cached hybrids
        self._hybrid_trademobile: Optional[HybridFetcher] = None
        self._hybrid_wheel: Optional[HybridFetcher] = None
        self._hybrid_queenoftheroad: Optional[HybridFetcher] = None

    def runtime(self) -> ScrapeRuntime:
        return ScrapeRuntime(
            httpx=self._httpx,
            playwright=self._pw,
            hybrid_trademobile=self._hybrid_trademobile,
            hybrid_wheel=self._hybrid_wheel,
            hybrid_queenoftheroad=self._hybrid_queenoftheroad,
        )

    def _get_pw(self) -> PlaywrightFetcher:
        if self._pw is None:
            self._pw = PlaywrightFetcher(headless=self.headless)
        return self._pw

    # -----------------------
    # Fetcher factories
    # -----------------------
    def _get_trademobile_article_fetcher(self) -> BaseFetcher:
        if self._hybrid_trademobile is None:
            self._hybrid_trademobile = HybridFetcher(
                http=self._httpx,
                pw=self._get_pw(),
                require_selector="div.ProseMirror",
            )
        return self._hybrid_trademobile

    def _get_autocoil_fetcher(self) -> BaseFetcher:
        return self._httpx

    def _get_gear_fetcher(self) -> BaseFetcher:
        return self._httpx

    def _get_wheel_fetcher(self) -> BaseFetcher:
        if self._hybrid_wheel is None:
            self._hybrid_wheel = HybridFetcher(
                http=self._httpx,
                pw=self._get_pw(),
                require_selector="a.catArtiBox[href], h1.entry-title, div.entry-content",
            )
        return self._hybrid_wheel

    # ✅ QueenOfTheRoad HybridFetcher (no click_selectors here)
    def _get_queenoftheroad_fetcher(self) -> BaseFetcher:
        if self._hybrid_queenoftheroad is None:
            self._hybrid_queenoftheroad = HybridFetcher(
                http=self._httpx,
                pw=self._get_pw(),
                require_selector=(
                    "div.elementor-post__card a.elementor-post__thumbnail__link[href], "
                    "h1.elementor-heading-title, article p"
                ),
                # ✅ DO NOT pass click_selectors
                # HybridFetcher will use its own default close-ads selectors.
            )
        return self._hybrid_queenoftheroad

    # -----------------------
    # Scraper factories
    # -----------------------
    def _create_trademobile(self, concurrency: int) -> BaseScraper:
        return TradeMobileScraper(
            fetcher=self._get_trademobile_article_fetcher(),
            discovery_fetcher=self._httpx,
            concurrency=concurrency,
        )

    def _create_autocoil(self, concurrency: int) -> BaseScraper:
        return AutoCoIlTestDrivesScraper(
            fetcher=self._get_autocoil_fetcher(),
            concurrency=concurrency,
        )

    def _create_gear(self, concurrency: int) -> BaseScraper:
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

    def _create_wheel_test_drives(self, concurrency: int) -> BaseScraper:
        return WheelTestDrivesScraper(
            fetcher=self._get_wheel_fetcher(),
            concurrency=concurrency,
        )

    def _create_queenoftheroad_test_drives(self, concurrency: int) -> BaseScraper:
        return QueenOfTheRoadTestDrivesScraper(
            fetcher=self._get_queenoftheroad_fetcher(),
            concurrency=concurrency,
        )
    def _create_carwiz_magazine(self, concurrency: int) -> BaseScraper:
        # httpx is enough for the pages I checked; if it becomes JS-only later,
        # you can swap to a HybridFetcher (require_selector="main, h1, p").
        return CarwizMagazineScraper(
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

        if key in ("gear_second_hand", "gear_car_tests", "gear_car_insurance"):
            return self._create_gear(concurrency=concurrency)

        if key == "icar_news":
            return self._create_icar_news(concurrency=concurrency)

        if key == "wheel_test_drives":
            return self._create_wheel_test_drives(concurrency=concurrency)

        if key == "queenoftheroad_test_drives":
            return self._create_queenoftheroad_test_drives(concurrency=concurrency)
        
        if key == "carwiz_magazine":
            return self._create_carwiz_magazine(concurrency=concurrency)


        raise ValueError(f"Unknown scraper key: {key}")