from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.core.models import Article
from app.core.fetchers.base import BaseFetcher
from .base import BaseScraper

class TradeMobileScraper(BaseScraper):
    def __init__(
        self,
        fetcher: BaseFetcher,                 # for article pages
        concurrency: int = 12,
        discovery_fetcher: Optional[BaseFetcher] = None,  # for listing pages
    ) -> None:
        self.fetcher = fetcher
        self.discovery_fetcher = discovery_fetcher or fetcher
        self.concurrency = max(1, concurrency)

    @staticmethod
    def _is_article_href(href: str) -> bool:
        return href.startswith("/posts/") and href not in ("/posts", "/posts/")

    @staticmethod
    def _clean_text(s: str) -> str:
        s = re.sub(r"[ \t]+\n", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str:
        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            return og["content"].strip()
        h1 = soup.select_one("h1")
        if h1:
            return h1.get_text(" ", strip=True)
        if soup.title:
            return soup.title.get_text(" ", strip=True)
        return ""

    @staticmethod
    def _extract_published(soup: BeautifulSoup) -> Optional[str]:
        # Your posts index shows dd/mm/yyyy in Hebrew formatted date lines.
        text_all = soup.get_text("\n", strip=True)
        m = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", text_all)
        return m.group(1) if m else None

    @staticmethod
    def _extract_content(soup: BeautifulSoup) -> str:
        node = soup.select_one("div.ProseMirror")
        if node:
            return node.get_text("\n", strip=True)

        # fallback: sometimes sites wrap content in article
        art = soup.select_one("article")
        if art:
            return art.get_text("\n", strip=True)

        return ""

    async def discover_article_urls(self, start_url: str, limit: Optional[int] = None) -> list[str]:
        html = await self.discovery_fetcher.get_html(start_url)
        soup = BeautifulSoup(html, "lxml")

        urls: list[str] = []
        seen: set[str] = set()

        for a in soup.select("a[href]"):
            href = a.get("href") or ""
            if not self._is_article_href(href):
                continue

            full = urljoin(start_url, href)
            if urlparse(full).netloc != urlparse(start_url).netloc:
                continue

            if full not in seen:
                seen.add(full)
                urls.append(full)

            if limit and len(urls) >= limit:
                break

        return urls

    async def fetch_article(self, url: str) -> Article:
        html = await self.fetcher.get_html(url)
        soup = BeautifulSoup(html, "lxml")

        title = self._extract_title(soup)
        published = self._extract_published(soup)
        content = self._extract_content(soup)

        return Article(
            url=url,
            title=self._clean_text(title),
            content=self._clean_text(content),
            published=published,
        )

    async def fetch_many(self, urls):
        return await super().fetch_many(urls, concurrency=self.concurrency)