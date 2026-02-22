from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Tuple


@dataclass(frozen=True)
class HttpxConfig:
    timeout_s: float = 20.0
    retries: int = 3
    backoff_s: float = 0.6
    max_connections: int = 40
    user_agent: str = "Mozilla/5.0 (compatible; TradeMobileHybridScraper/1.1)"


ScraperKey = Literal[
    "trademobile_posts",
    "autocoil_test_drives",
    "gear_second_hand",
    "gear_car_tests",
    "gear_car_insurance",  # ✅ NEW
    "icar_news",
]


@dataclass(frozen=True)
class SiteConfig:
    key: ScraperKey
    start_url: str


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://trademobile.co.il/posts/"

    sites: Tuple[SiteConfig, ...] = (
        SiteConfig(key="trademobile_posts", start_url="https://trademobile.co.il/posts/"),
        SiteConfig(key="autocoil_test_drives", start_url="https://www.auto.co.il/articles/test-drives/"),
        SiteConfig(
            key="gear_second_hand",
            start_url="https://www.gear.co.il/%D7%A8%D7%9B%D7%91-%D7%99%D7%93-%D7%A9%D7%A0%D7%99%D7%94",
        ),
        SiteConfig(
            key="gear_car_tests",
            start_url="https://www.gear.co.il/%D7%9E%D7%91%D7%97%D7%A0%D7%99-%D7%A8%D7%9B%D7%91",
        ),
        SiteConfig(
            key="gear_car_insurance",  # ✅ NEW
            start_url="https://www.gear.co.il/%D7%91%D7%99%D7%98%D7%95%D7%97-%D7%A8%D7%9B%D7%91",
        ),
        SiteConfig(
            key="icar_news",
            start_url="https://www.icar.co.il/%D7%97%D7%93%D7%A9%D7%95%D7%AA_%D7%A8%D7%9B%D7%91/",
        ),
    )

    httpx: HttpxConfig = field(default_factory=HttpxConfig)