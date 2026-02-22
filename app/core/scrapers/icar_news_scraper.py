from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import (
    urljoin,
    urlparse,
    urlunparse,
    urldefrag,
    parse_qsl,
    urlencode,
    quote,
    unquote,
)

from bs4 import BeautifulSoup

from app.core.fetchers.base import BaseFetcher
from app.core.scrapers.base import BaseScraper
from app.core.models import Article


@dataclass(frozen=True)
class IcarConfig:
    base_domain: str = "www.icar.co.il"

    # Listing pages (news section) use ?page=N
    page_param: str = "page"

    pw_click_selectors: tuple[str, ...] = (
        'button:has-text("אני מסכים")',
        'button:has-text("אישור")',
        '[aria-label="Close"]',
        ".close",
        ".modal-close",
    )


@dataclass
class PaginationTransitionStats:
    total_pages: int
    pages_with_both_prev_next: int
    pages_with_next_only: int
    pages_with_prev_only: int
    pages_with_none: int


class IcarNewsScraper(BaseScraper):
    """
    iCar news scraper:
    - Discover articles across ALL listing pages (?page=N)
    - Analyze pagination transitions (prev/next presence)
    - Fetch article and extract richer "all text" from the article container
    """

    def __init__(
        self,
        fetcher: BaseFetcher,
        concurrency: int = 10,
        config: Optional[IcarConfig] = None,
    ) -> None:
        self.fetcher = fetcher
        self.concurrency = concurrency
        self.config = config or IcarConfig()

        self.request_delay_s = 0.2
        self.request_delay_jitter_s = 0.2

    # -------------------------
    # URL normalization helpers
    # -------------------------
    def normalize_url(self, base_url: str, href: str) -> Optional[str]:
        if not href:
            return None

        href = href.strip()

        lowered = href.lower()
        if lowered.startswith(("mailto:", "tel:", "javascript:")):
            return None
        if "twitter.com/intent/" in lowered or "api.whatsapp.com" in lowered or "facebook.com/share" in lowered:
            return None

        abs_url = urljoin(base_url, href)
        abs_url, _frag = urldefrag(abs_url)

        p = urlparse(abs_url)
        if p.scheme not in ("http", "https"):
            return None

        netloc = (p.netloc or "").lower()
        if netloc and netloc != self.config.base_domain:
            return None

        q = []
        for k, v in parse_qsl(p.query, keep_blank_values=True):
            lk = k.lower()
            if lk.startswith("utm_") or lk in ("fbclid", "gclid", "yclid"):
                continue
            q.append((k, v))
        query = urlencode(q, doseq=True)

        raw_path = p.path or "/"
        norm_path = quote(unquote(raw_path), safe="/%:@")

        if norm_path.startswith("/news/") and not norm_path.endswith("/"):
            norm_path += "/"

        return urlunparse((p.scheme, netloc, norm_path, p.params, query, ""))

    def _set_query_param(self, url: str, key: str, value: str) -> str:
        p = urlparse(url)
        q = dict(parse_qsl(p.query, keep_blank_values=True))
        q[key] = value
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q, doseq=True), ""))

    # -------------------------
    # Pagination helpers
    # -------------------------
    def _extract_current_and_total_pages(self, soup: BeautifulSoup) -> Optional[tuple[int, int]]:
        """
        Looks for the Hebrew pattern: 'עמוד X מתוך Y'
        """
        text = soup.get_text(" ", strip=True)
        m = re.search(r"עמוד\s+(\d+)\s+מתוך\s+(\d+)", text)
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))

    def _detect_prev_next(self, soup: BeautifulSoup, base_url: str) -> tuple[bool, bool]:
        """
        Detects presence of 'הקודם' (prev) and 'הבא' (next) as clickable anchors.
        """
        prev_a = soup.find("a", string=lambda s: isinstance(s, str) and "הקודם" in s)
        next_a = soup.find("a", string=lambda s: isinstance(s, str) and "הבא" in s)

        has_prev = False
        has_next = False

        if prev_a and prev_a.get("href"):
            has_prev = self.normalize_url(base_url, prev_a["href"]) is not None
        if next_a and next_a.get("href"):
            has_next = self.normalize_url(base_url, next_a["href"]) is not None

        return has_prev, has_next

    async def discover_listing_page_urls(
        self,
        start_url: str,
        max_pages: Optional[int] = None,
    ) -> list[str]:
        """
        Returns all listing URLs for the section by using total-pages extracted from page text.
        """
        html = await self.fetcher.get_html(start_url)
        soup = BeautifulSoup(html, "lxml")

        pages_info = self._extract_current_and_total_pages(soup)
        if not pages_info:
            # Fallback: if pattern not found, just return the provided URL.
            return [start_url]

        _current, total = pages_info
        if max_pages is not None:
            total = min(total, max_pages)

        # Ensure we include page=1..total
        out = []
        for i in range(1, total + 1):
            out.append(self._set_query_param(start_url, self.config.page_param, str(i)))
        return out

    async def analyze_pagination_transitions(
        self,
        start_url: str,
        max_pages: Optional[int] = None,
    ) -> PaginationTransitionStats:
        """
        Fetches each listing page and counts where prev/next transitions exist.
        """
        listing_urls = await self.discover_listing_page_urls(start_url, max_pages=max_pages)

        both = next_only = prev_only = none = 0

        # Sequential here to keep load modest; if you want, you can parallelize with fetch_many.
        for url in listing_urls:
            html = await self.fetcher.get_html(url)
            soup = BeautifulSoup(html, "lxml")
            has_prev, has_next = self._detect_prev_next(soup, url)

            if has_prev and has_next:
                both += 1
            elif has_next and not has_prev:
                next_only += 1
            elif has_prev and not has_next:
                prev_only += 1
            else:
                none += 1

        return PaginationTransitionStats(
            total_pages=len(listing_urls),
            pages_with_both_prev_next=both,
            pages_with_next_only=next_only,
            pages_with_prev_only=prev_only,
            pages_with_none=none,
        )

    # -------------------------
    # Discovery (ALL pages)
    # -------------------------
    async def discover_article_urls(
        self,
        start_url: str,
        limit: Optional[int] = None,
        max_pages: Optional[int] = None,
    ) -> list[str]:
        """
        Discover /news/ article URLs across ALL listing pages.
        - limit applies to total unique articles returned (after dedupe).
        - max_pages optionally caps listing pages for faster runs/tests.
        """
        listing_urls = await self.discover_listing_page_urls(start_url, max_pages=max_pages)

        seen: set[str] = set()
        out: list[str] = []

        for page_url in listing_urls:
            html = await self.fetcher.get_html(page_url)
            soup = BeautifulSoup(html, "lxml")

            anchors = soup.select(
                'a[href^="/news/"], a[href^="https://www.icar.co.il/news/"], a[href^="http://www.icar.co.il/news/"]'
            )

            for a in anchors:
                href = a.get("href") or ""
                url = self.normalize_url(page_url, href)
                if not url:
                    continue
                if "/news/" not in url:
                    continue
                if url in seen:
                    continue

                seen.add(url)
                out.append(url)

                if limit is not None and len(out) >= limit:
                    return out

        return out

    # -------------------------
    # Article fetch + extraction
    # -------------------------
    async def fetch_article(self, url: str) -> Article:
        html = await self.fetcher.get_html(url)
        soup = BeautifulSoup(html, "lxml")

        # Prefer the main article container
        container = soup.select_one("div.article_text") or soup

        h1 = soup.select_one("h1")
        title = (h1.get_text(" ", strip=True) if h1 else "") or (
            soup.title.get_text(" ", strip=True) if soup.title else ""
        )

        # "All text" (within container) but still avoid obvious non-content:
        # - include more tags that commonly hold article body text
        # - skip scripts/styles/noscript/forms/buttons
        for bad in container.select("script, style, noscript, form, button, nav"):
            bad.decompose()

        texts: list[str] = []
        for el in container.select(
            "h1, h2, h3, h4, h5, h6, p, li, blockquote, figcaption, strong, em"
        ):
            t = el.get_text(" ", strip=True)
            if not t:
                continue
            texts.append(t)

        # De-duplicate adjacent repeats
        cleaned: list[str] = []
        last = None
        for t in texts:
            if t == last:
                continue
            cleaned.append(t)
            last = t

        body = "\n".join(cleaned).strip()

        return Article(
            url=url,
            title=title,
            content=body,
        )