from __future__ import annotations

from bs4 import BeautifulSoup

from .base import BaseFetcher
from .httpx_fetcher import HttpxFetcher
from .playwright_fetcher import PlaywrightFetcher

class HybridFetcher(BaseFetcher):
    """
    Fast path: httpx
    Fallback: Playwright
    Rule: if require_selector is missing in httpx HTML -> use Playwright HTML.
    """
    def __init__(
        self,
        http: HttpxFetcher,
        pw: PlaywrightFetcher,
        require_selector: str = "div.ProseMirror",
    ) -> None:
        self.http = http
        self.pw = pw
        self.require_selector = require_selector

    async def get_html(self, url: str) -> str:
        html = await self.http.get_html(url)
        soup = BeautifulSoup(html, "lxml")

        if self.require_selector and soup.select_one(self.require_selector):
            return html

        # fallback for JS rendered (or blocked) pages
        return await self.pw.get_html(url)

    async def aclose(self) -> None:
        await self.http.aclose()
        await self.pw.aclose()