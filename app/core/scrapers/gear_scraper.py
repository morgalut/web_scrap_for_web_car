from __future__ import annotations

from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from app.core.models import Article
from app.core.fetchers.httpx_fetcher import HttpxFetcher
from app.core.fetchers.playwright_fetcher import PlaywrightFetcher
from app.core.scrapers.base import BaseScraper


class GearSecondHandScraper(BaseScraper):
    BASE = "https://www.gear.co.il"
    ARTICLE_SELECTOR = "div.single-article_content"
    DISMISS_SELECTORS = ["#dismiss-button", "[aria-label='סגור את המודעה']"]

    def __init__(
        self,
        http: HttpxFetcher,
        pw: PlaywrightFetcher,
        concurrency: int = 10,
    ) -> None:
        self.http = http
        self.pw = pw
        self.concurrency = max(1, concurrency)

    @staticmethod
    def _is_same_domain(url: str) -> bool:
        p = urlparse(url)
        return p.netloc.endswith("gear.co.il")

    def _abs(self, href: str) -> str:
        return urljoin(self.BASE, href)

    def _click_selectors(self) -> Optional[list[str]]:
        # controlled from router: scraper.close_ads = True/False
        return self.DISMISS_SELECTORS if bool(getattr(self, "close_ads", True)) else None

    def _extract_listing_items(self, html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "lxml")

        items: list[tuple[str, str]] = []

        for a in soup.select("a[href]"):
            href_raw = (a.get("href") or "").strip()
            if not href_raw:
                continue

            href_decoded = unquote(href_raw)

            # ✅ match after decoding (works for encoded + Hebrew)
            if "/כתבת-רכב/" not in href_decoded:
                continue

            url = self._abs(href_raw)
            if not self._is_same_domain(url):
                continue

            text = a.get_text(" ", strip=True)
            text = " ".join(text.split()) if text else ""  # ✅ allow empty text

            items.append((url, text))

        # De-dupe preserving order
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for u, t in items:
            if u not in seen:
                seen.add(u)
                out.append((u, t))

        return out

    def _extract_listing_links(self, html: str) -> list[str]:
        return [u for (u, _t) in self._extract_listing_items(html)]

    def _find_next_page(self, html: str) -> Optional[str]:
        soup = BeautifulSoup(html, "lxml")

        a = soup.select_one("a[rel='next'][href]")
        if a and a.get("href"):
            return self._abs(a["href"])

        for cand in soup.select("a[href]"):
            txt = (cand.get_text(strip=True) or "")
            if txt in {"הבא", "הבאה", "»", ">"}:
                href = cand.get("href") or ""
                if href:
                    return self._abs(href)

        return None

    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        urls: list[str] = []
        seen_pages: set[str] = set()

        page_url: Optional[str] = start_url
        while page_url:
            if page_url in seen_pages:
                break
            seen_pages.add(page_url)

            # ✅ HTTPX cannot click ads
            html_http = await self.http.get_html(page_url)
            items = self._extract_listing_items(html_http)
            found_urls = [u for (u, _t) in items]
            html_for_paging = html_http

            # ✅ Fallback to Playwright ONLY when HTTPX finds nothing
            if not found_urls:
                try:
                    html_pw = await self.pw.get_html(
                        page_url,
                        click_selectors=self._click_selectors(),
                    )
                    items = self._extract_listing_items(html_pw)
                    found_urls = [u for (u, _t) in items]
                    html_for_paging = html_pw
                except Exception as e:
                    print("Playwright discovery failed:", type(e).__name__, str(e))
                    found_urls = []

            for u in found_urls:
                if u not in urls:
                    urls.append(u)
                    if limit and len(urls) >= limit:
                        return urls[:limit]

            page_url = self._find_next_page(html_for_paging)

        return urls[:limit] if limit else urls

    def _extract_article_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        container = soup.select_one(self.ARTICLE_SELECTOR)
        if not container:
            return ""

        for tag in container.select("script, style, noscript"):
            tag.decompose()

        text = container.get_text("\n", strip=True)
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines)

    def _extract_title(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")

        h1 = soup.select_one("h1")
        if h1:
            t = h1.get_text(strip=True)
            if t:
                return t

        og = soup.select_one("meta[property='og:title']")
        if og and og.get("content"):
            return og["content"].strip()

        title = soup.select_one("title")
        return title.get_text(strip=True) if title else ""

    async def fetch_article(self, url: str) -> Article:
        # 1) Try HTTPX
        html = await self.http.get_html(url)
        text = self._extract_article_text(html)

        # 2) Fallback to Playwright if needed (click dismiss-button optionally)
        if not text:
            html = await self.pw.get_html(
                url,
                wait_for_selector=self.ARTICLE_SELECTOR,
                click_selectors=self._click_selectors(),
            )
            text = self._extract_article_text(html)

        title = self._extract_title(html)

        return Article(
            url=url,
            title=title,
            content=text,
            published=None,
            raw_html=html,
        )