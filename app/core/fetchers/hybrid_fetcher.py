from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .base import BaseFetcher
from .httpx_fetcher import HttpxFetcher
from .playwright_fetcher import PlaywrightFetcher


class HybridFetcher(BaseFetcher):
    def __init__(
        self,
        http: HttpxFetcher,
        pw: PlaywrightFetcher,
        require_selector: Optional[str] = "div.ProseMirror",
        click_selectors: Optional[list[str]] = None,  # ✅ NEW
    ) -> None:
        self.http = http
        self.pw = pw
        self.require_selector = require_selector
        self.click_selectors = click_selectors  # ✅ NEW

        
    @staticmethod
    def _is_trademobile_posts_listing(url: str) -> bool:
        """
        TradeMobile listing page looks like:
          https://trademobile.co.il/posts/   (or /posts)

        Article pages are usually:
          /posts/<something>
        """
        p = urlparse(url)
        path = (p.path or "").rstrip("/")
        return p.netloc == "trademobile.co.il" and path == "/posts"

    async def get_html(self, url: str) -> str:
        # 1) Try HTTPX first
        html = await self.http.get_html(url)

        # If no selector requirement, accept HTTPX
        if not self.require_selector:
            return html

        # ✅ If it's the TradeMobile LISTING page, do NOT require ProseMirror
        # (it often only exists on article pages)
        if self._is_trademobile_posts_listing(url):
            return html

        # For other pages, check if selector exists in HTTP HTML
        soup = BeautifulSoup(html, "lxml")
        if soup.select_one(self.require_selector):
            return html

        # 2) Fallback: Playwright
        # ✅ Wait for ProseMirror to be VISIBLE only on pages where it should exist
        return await self.pw.get_html(
                url,
                wait_for_selector=self.require_selector,
                wait_state="attached",
                extra_wait_ms=400,
                click_selectors=[
                    # common cookie/consent/close buttons (best-effort, harmless if missing)
                    "button:has-text('Accept')",
                    "button:has-text('I agree')",
                    "button:has-text('OK')",
                    "button:has-text('Agree')",
                    "button:has-text('מאשר')",
                    "button:has-text('אישור')",
                    "button:has-text('מסכים')",
                    "button:has-text('הבנתי')",
                    ".fc-button.fc-cta-consent",  # some cookie frameworks
                    "button[aria-label='Close']",
                    ".close",
                    ".popup-close",
                ],
            )

    async def aclose(self) -> None:
        await self.http.aclose()
        await self.pw.aclose()