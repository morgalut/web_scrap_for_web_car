from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Tuple


@dataclass(frozen=True)
class HttpxConfig:
    timeout_s: float = 20.0
    retries: int = 3
    backoff_s: float = 0.6
    max_connections: int = 40
    user_agent: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


ScraperKey = Literal[
    "trademobile_posts",
    "autocoil_test_drives",
    "gear_second_hand",
    "gear_car_tests",
    "gear_car_insurance",
    "icar_news",
    "wheel_test_drives",
    "queenoftheroad_test_drives",
    "carwiz_magazine",
    "freesbe_blog",
    "autocenter_articles",  # ✅ NEW
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
        SiteConfig(
            key="wheel_test_drives",
            start_url="https://wheel.co.il/category/%D7%9E%D7%91%D7%97%D7%A0%D7%99-%D7%93%D7%A8%D7%9B%D7%99%D7%9D/",
        ),
        SiteConfig(
            key="queenoftheroad_test_drives",
            start_url="https://www.queenoftheroad.co.il/category/%d7%9e%d7%91%d7%97%d7%a0%d7%99-%d7%93%d7%a8%d7%9b%d7%99%d7%9d/",
        ),
        SiteConfig(
            key="carwiz_magazine",
            start_url="https://carwiz.co.il/magazine",
        ),
        SiteConfig(
            key="freesbe_blog",
            start_url="https://freesbe.com/blog",
        ),
        SiteConfig(
            key="autocenter_articles",
            start_url="https://www.autocenter.co.il/articles",
    ),
    )

    httpx: HttpxConfig = field(default_factory=HttpxConfig)