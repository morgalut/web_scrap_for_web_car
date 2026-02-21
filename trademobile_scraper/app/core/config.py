from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(frozen=True)
class HttpxConfig:
    timeout_s: float = 20.0
    retries: int = 3
    backoff_s: float = 0.6
    max_connections: int = 40
    user_agent: str = "Mozilla/5.0 (compatible; TradeMobileHybridScraper/1.1)"


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://trademobile.co.il/posts/"
    httpx: HttpxConfig = field(default_factory=HttpxConfig)