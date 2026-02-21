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


ScraperKey = Literal["trademobile_posts", "autocoil_test_drives"]


@dataclass(frozen=True)
class SiteConfig:
    key: ScraperKey
    start_url: str


@dataclass(frozen=True)
class Settings:
    # Keep old behavior as default single-site (backwards compatible)
    base_url: str = "https://trademobile.co.il/posts/"

    # Multi-site registry (new)
    sites: Tuple[SiteConfig, ...] = (
        SiteConfig(key="trademobile_posts", start_url="https://trademobile.co.il/posts/"),
        SiteConfig(key="autocoil_test_drives", start_url="https://www.auto.co.il/articles/test-drives/"),
    )

    httpx: HttpxConfig = field(default_factory=HttpxConfig)