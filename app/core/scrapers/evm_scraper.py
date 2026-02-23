from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.core.fetchers.httpx_fetcher import HttpxFetcher
from app.core.fetchers.playwright_fetcher import PlaywrightFetcher
from app.core.models import Article
from app.core.scrapers.base import BaseScraper


class EvmNewsScraper(BaseScraper):
    """
    https://www.evm.co.il/
    Discovery requires Playwright because the homepage uses "טען עוד" (load more).
    Article pages are usually server-rendered (Httpx is enough for fetch_article).
    """

    # Listing selectors (based on your HTML snippet)
    _CARD_LINK_SEL = "div.post-details h2.post-title a[href]"
    _DATE_IN_CARD_SEL = "div.post-details .post-meta span.date"

    # "Load more" button selectors
    _LOAD_MORE_SEL = "a.load-more-button, a.block-pagination.next-posts.show-more-button.load-more-button"

    # Article page selectors (WP themes vary a bit)
    _TITLE_SEL = "h1.entry-title, h1.post-title, header h1"
    _CONTENT_SEL = "div.entry-content, article .entry-content, article div[itemprop='articleBody'], article"
    _DATE_SEL = "div.post-meta span.date, span.date.meta-item"

    def __init__(self, http: HttpxFetcher, pw: PlaywrightFetcher , concurrency : int = 12) -> None:
        self.http = http
        self.pw = pw
        self.concurrency = concurrency

        # set by router per run:
        # self.request_delay_s
        # self.request_delay_jitter_s
        # self.close_ads

    # -------------------------
    # Helpers
    # -------------------------
    @staticmethod
    def _abs(base: str, href: str) -> str:
        return urljoin(base, href.strip())

    @staticmethod
    def _is_article_url(u: str) -> bool:
        """
        Keep normal article permalinks, reject obvious non-article paths.
        """
        try:
            p = urlparse(u)
            if p.scheme not in ("http", "https"):
                return False
            if p.netloc not in ("www.evm.co.il", "evm.co.il"):
                return False

            path = (p.path or "/").strip("/")
            if not path:
                return False

            bad_prefixes = ("category/", "tag/", "author/", "wp-json/", "page/")
            if any(path.startswith(bp) for bp in bad_prefixes):
                return False

            return True
        except Exception:
            return False

    @staticmethod
    def _clean_text(el) -> str:
        if not el:
            return ""
        return el.get_text(" ", strip=True)

    # -------------------------
    # BaseScraper API
    # -------------------------
    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        """
        Clicks "טען עוד" until:
        - button disappears OR
        - no new links are added after clicking OR
        - limit reached
        """
        seen: set[str] = set()
        last_count = -1
        stable_rounds = 0

        # initial load
        html = await self.pw.get_html(
            start_url,
            wait_for_selector=self._CARD_LINK_SEL,
            wait_state="attached",
            extra_wait_ms=350,
            wait_networkidle=True,
            click_selectors=[
                # consent / close popups (best-effort)
                "button:has-text('Accept')",
                "button:has-text('OK')",
                "button:has-text('I agree')",
                "button:has-text('מאשר')",
                "button:has-text('אישור')",
                "button:has-text('מסכים')",
                "button:has-text('הבנתי')",
                ".fc-button.fc-cta-consent",
                "button[aria-label='Close']",
                ".close",
                ".popup-close",
            ]
            if bool(getattr(self, "close_ads", True))
            else None,
        )

        for _ in range(80):  # safety cap
            soup = BeautifulSoup(html, "lxml")

            for a in soup.select(self._CARD_LINK_SEL):
                href = a.get("href")
                if not href:
                    continue
                u = self._abs(start_url, href)
                if self._is_article_url(u):
                    seen.add(u)
                    if limit is not None and len(seen) >= limit:
                        return sorted(seen)[:limit]

            # no-growth tracking
            if len(seen) == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = len(seen)

            if stable_rounds >= 2:
                break

            # no "load more" -> done
            if not soup.select_one(self._LOAD_MORE_SEL):
                break

            # click "load more" (PlaywrightFetcher click_selectors)
            html = await self.pw.get_html(
                start_url,
                wait_for_selector=self._CARD_LINK_SEL,
                wait_state="attached",
                extra_wait_ms=700,
                wait_networkidle=True,
                click_selectors=[self._LOAD_MORE_SEL],
            )

        urls = sorted(seen)
        return urls[:limit] if limit is not None else urls

    async def fetch_article(self, url: str) -> Article:
        html = await self.http.get_html(url)
        soup = BeautifulSoup(html, "lxml")

        title = self._clean_text(soup.select_one(self._TITLE_SEL))
        published = self._clean_text(soup.select_one(self._DATE_SEL)) or None

        content_el = soup.select_one(self._CONTENT_SEL)
        if content_el:
            for x in content_el.select("script, style, noscript"):
                x.decompose()
            content = content_el.get_text("\n", strip=True)
        else:
            content = ""

        return Article(
            url=url,
            title=title,
            content=content,
            published=published,
            raw_html=html,
        )