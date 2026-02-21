from __future__ import annotations

import asyncio
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

        async def _one(u: str) -> Article:
            async with sem:
                return await self.fetch_article(u)

        return await asyncio.gather(*[_one(u) for u in urls])