from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from typing import Iterable, Optional

from app.core.models import Article


class BaseScraper(ABC):
    @abstractmethod
    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_article(self, url: str) -> Article:
        raise NotImplementedError

    async def fetch_many(self, urls: Iterable[str], concurrency: int = 10) -> list[Article]:
        sem = asyncio.Semaphore(max(1, concurrency))

        # ✅ Global per-request delay (seconds)
        # You can set this per scraper instance: scraper.request_delay_s = 0.5
        base_delay = float(getattr(self, "request_delay_s", 0.0) or 0.0)

        # ✅ Add jitter so requests don’t look “robotic”
        jitter = float(getattr(self, "request_delay_jitter_s", 0.15) or 0.0)

        async def _one(u: str) -> Article:
            async with sem:
                if base_delay > 0:
                    await asyncio.sleep(base_delay + (random.random() * jitter))
                return await self.fetch_article(u)

        return await asyncio.gather(*[_one(u) for u in urls])