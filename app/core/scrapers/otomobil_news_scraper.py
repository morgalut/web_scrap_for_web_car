from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.core.fetchers.httpx_fetcher import HttpxFetcher
from app.core.fetchers.playwright_fetcher import PlaywrightFetcher
from app.core.models import Article
from app.core.scrapers.base import BaseScraper
from app.core.logging import get_logger

log = get_logger()


class OtomobilNewsScraper(BaseScraper):
    def __init__(self, http: HttpxFetcher, pw: PlaywrightFetcher, concurrency: int = 10) -> None:
        self.http = http
        self.pw = pw
        self.concurrency = concurrency

        # controlled by router: scraper.close_ads = True/False
        self.close_ads: bool = True

        self._click_selectors = [
            "#dismiss-button",
            "div#dismiss-button",
            "[aria-label='סגור את המודעה']",
            "button[aria-label='Close']",
            ".close-button",
        ]

    @staticmethod
    def _same_host(a: str, b: str) -> bool:
        return (urlparse(a).netloc or "").lower() == (urlparse(b).netloc or "").lower()

    @staticmethod
    def _clean_text(s: str) -> str:
        s = re.sub(r"[ \t]+", " ", s or "").strip()
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()

    @staticmethod
    def _extract_first_date_ddmmyyyy(soup: BeautifulSoup) -> Optional[str]:
        m = soup.find(string=re.compile(r"\b\d{2}/\d{2}/\d{4}\b"))
        if not m:
            return None
        mm = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", str(m))
        return mm.group(1) if mm else None

    def _parse_listing_links(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html or "", "lxml")
        urls: list[str] = []
        for a in soup.select("a.jet-engine-listing-overlay-link[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            abs_url = urljoin(base_url, href)
            urls.append(abs_url)
        return urls

    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()

        page_num = 1
        max_pages = 80  # safety cap

        while page_num <= max_pages:
            if limit is not None and len(found) >= limit:
                break

            page_url = (
                start_url.rstrip("/") + "/"
                if page_num == 1
                else start_url.rstrip("/") + f"/page/{page_num}/"
            )

            log.info("[otomobil_news] Discover page %d -> %s", page_num, page_url)

            # 1) Try HTTPX first (FAST)
            html = ""
            try:
                html = await self.http.get_html(page_url)
            except Exception as e:
                log.warning("[otomobil_news] HTTPX listing fetch failed page=%d err=%s", page_num, e)

            links = self._parse_listing_links(html, page_url)

            # 2) Fallback to Playwright only if HTTPX found nothing
            if not links:
                log.info("[otomobil_news] No links via HTTPX, fallback to Playwright (page %d)", page_num)
                html = await self.pw.get_html(
                    page_url,
                    wait_for_selector="a.jet-engine-listing-overlay-link[href]",
                    click_selectors=self._click_selectors if self.close_ads else None,
                    wait_state="attached",
                    wait_networkidle=False,  # important: ads keep network busy
                    extra_wait_ms=200,
                    scroll_steps=6,
                    scroll_wait_ms=700,
                )
                links = self._parse_listing_links(html, page_url)

            page_added = 0
            for u in links:
                if not self._same_host(u, start_url):
                    continue
                if u in seen:
                    continue
                seen.add(u)
                found.append(u)
                page_added += 1
                if limit is not None and len(found) >= limit:
                    break

            log.info("[otomobil_news] Page %d: +%d links (total=%d)", page_num, page_added, len(found))

            # Stop when pagination ends
            if page_added == 0:
                break

            page_num += 1

        return found

    async def fetch_article(self, url: str) -> Article:
        log.info("[otomobil_news] Fetch article -> %s", url)

        html = await self.pw.get_html(
            url,
            wait_for_selector="div.elementor-widget-theme-post-content",
            click_selectors=self._click_selectors if self.close_ads else None,
            wait_state="attached",
            wait_networkidle=False,  # important on ad-heavy pages
            extra_wait_ms=300,
            scroll_steps=3,
            scroll_wait_ms=600,
        )

        soup = BeautifulSoup(html or "", "lxml")

        for tag in soup.select("script, style, noscript, iframe"):
            tag.decompose()

        h2s = [self._clean_text(h.get_text(" ", strip=True)) for h in soup.select("h2.elementor-heading-title")]
        h2s = [t for t in h2s if t]
        title = h2s[0] if h2s else ""
        subtitle = h2s[1] if len(h2s) > 1 else ""

        published = self._extract_first_date_ddmmyyyy(soup)

        content_root = soup.select_one("div.elementor-widget-theme-post-content")
        parts: list[str] = []

        if content_root:
            for ad in content_root.select(
                ".google-auto-placed, ins.adsbygoogle, .adsbygoogle, [id^='aswift_'], .ap_container"
            ):
                ad.decompose()

            for node in content_root.select("h2, h3, h4, p, li"):
                txt = self._clean_text(node.get_text(" ", strip=True))
                if txt:
                    parts.append(txt)

        body = "\n".join(parts).strip()
        if subtitle and subtitle not in body:
            body = f"{subtitle}\n\n{body}".strip()

        return Article(
            url=url,
            title=title or subtitle or url,
            content=body,
            published=published,
            raw_html=html or "",
        )