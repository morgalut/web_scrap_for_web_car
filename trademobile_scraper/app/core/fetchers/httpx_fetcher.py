from __future__ import annotations

import asyncio
import httpx

from app.core.config import HttpxConfig
from .base import BaseFetcher

class HttpxFetcher(BaseFetcher):
    def __init__(self, config: HttpxConfig) -> None:
        self.config = config
        limits = httpx.Limits(
            max_connections=self.config.max_connections,
            max_keepalive_connections=self.config.max_connections,
        )
        self.client = httpx.AsyncClient(
            timeout=self.config.timeout_s,
            follow_redirects=True,
            limits=limits,
            headers={"User-Agent": self.config.user_agent},
        )

    async def get_html(self, url: str) -> str:
        last_err: Exception | None = None
        for attempt in range(1, self.config.retries + 1):
            try:
                r = await self.client.get(url)
                r.raise_for_status()
                return r.text
            except Exception as e:
                last_err = e
                if attempt < self.config.retries:
                    await asyncio.sleep(self.config.backoff_s * attempt)
        raise last_err or RuntimeError("httpx failed")

    async def aclose(self) -> None:
        await self.client.aclose()